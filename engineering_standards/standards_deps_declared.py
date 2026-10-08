#!/usr/bin/env python3
"""Every dependency a repository declares, and the version it is pinned at.

Read-only: no rule lives here. The dependency gate (`deps.py check`) asks this module what the
repository depends on, asks `standards_deps_registry` what is newest, and judges the pair with
`standards_deps_verdict`. Splitting the reading out keeps each module answerable to one
question, and lets every reader be tested without a network.

WHAT COUNTS AS DECLARED: a version written in a file the repository owns -- project files,
lockless manifests, Dockerfiles, compose files, workflows, `global.json`. Lockfiles are NOT read:
they record what was resolved, and the decision this gate polices is the one a person wrote.

PACK-OWNED FILES ARE SKIPPED IN A CONSUMER. `engineering_standards/requirements.txt` and the
analyzer list in `Directory.Build.props` belong to the pack: a consumer cannot change them
(the next sync overwrites the edit), so judging them there would block a push on a decision the
repo is not allowed to make. The pack judges them in its own checkout, and the sync carries the
result out. A root-level pack copy is recognised by the footer every pack file carries.

Source of truth: engineering-standards/engineering_standards/standards_deps_declared.py
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from standards_core import warn_unreadable
from standards_pack_identity import is_foreign_pack_file, is_the_pack_itself
from standards_packages import PACKAGE_REFERENCE
from standards_projects import VENDOR_DIRECTORIES
from standards_versions import USES

PACK_FOOTER = "Source of truth: engineering-standards/"

# Ecosystem names, as they appear in the record's keys (`pypi:ruff`).
NUGET = "nuget"
PYPI = "pypi"
NPM = "npm"
COMPOSER = "composer"
DOCKER = "docker"
ACTION = "github-action"
DOTNET_SDK = "dotnet-sdk"

# Directories under a dot that DO hold declarations; every other dot-directory is tooling.
DECLARING_DOT_DIRECTORIES = frozenset({".github", ".config"})

PACKAGE_VERSION_ITEM = re.compile(
    r"""<PackageVersion\s+(?=[^>]*Include\s*=\s*["'](?P<name>[^"']+)["'])"""
    r"""[^>]*Version\s*=\s*["'](?P<version>[^"']+)["']""",
    re.IGNORECASE,
)
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?\s*(?P<spec>[=<>!~].*)?$")
DOCKER_FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(?P<image>\S+)(?:\s+AS\s+(?P<alias>\S+))?", re.IGNORECASE)
COMPOSE_IMAGE = re.compile(r"""^\s*image:\s*["']?(?P<image>[^"'\s#]+)""")
SHA = re.compile(r"^[0-9a-f]{40}$")
ACTION_TAG_COMMENT = re.compile(r"\s*(v?\d+(?:\.\d+)*)\b")

# A full release number, then any variant suffixes: `24.1.0-alpine`, `7.1.3-php8.5-fpm`. The
# number decides exactness; a suffix only picks a flavour of that one release.
EXACT_NUMERIC = re.compile(r"^v?\d+(?:\.\d+){2,3}(?:[-+][\w.]+)*$")


@dataclass(frozen=True)
class Dependency:
    """One declared dependency at one site. The same package at two sites is two of these."""

    ecosystem: str
    name: str
    version: str
    path: Path  # repo-relative
    line: int  # 1-based
    # The release a SHA pin names, from its trailing comment (`@<sha>  # v7.0.1`). A commit carries
    # no version, so this is what puts a pinned Action in a line; absent, its line is unknown.
    label: str | None = None

    @property
    def key(self) -> str:
        return f"{self.ecosystem}:{self.name}"

    @property
    def is_pinned(self) -> bool:
        """Whether the version names exactly one release (decision 1 of the 2026-10-02 plan)."""
        return is_exact(self.ecosystem, self.version)

    @property
    def release(self) -> str:
        """The release the pin names, spelled the way its registry spells it (`==9.1.1` -> `9.1.1`)."""
        version = self.version.removeprefix("==")
        if self.ecosystem in {COMPOSER, NPM, NUGET}:
            version = version.removeprefix("v")
        return version


def is_exact(ecosystem: str, version: str) -> bool:
    """Whether a version as WRITTEN names exactly one release in its ecosystem."""
    if ecosystem == PYPI:
        return version.startswith("==") and "*" not in version
    if ecosystem == ACTION:
        return bool(SHA.match(version))
    if ecosystem == DOCKER:
        return version.startswith("sha256:") or bool(EXACT_NUMERIC.match(version))
    # NuGet: a plain `Version="x"` resolves to exactly x for a direct reference (it is the
    # LOWEST version satisfying the floor), so a literal three-or-four part version is a pin.
    return bool(EXACT_NUMERIC.match(version))


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _table(value: object, where: str) -> dict:
    """A JSON/TOML object where one is required; anything else is a malformed manifest, said as
    a ValueError so the caller names the file rather than an AttributeError escaping it."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{where} is not an object")
    return value


def _from_project_file(path: Path, text: str) -> Iterable[Dependency]:
    for pattern in (PACKAGE_REFERENCE, PACKAGE_VERSION_ITEM):
        for found in pattern.finditer(text):
            yield Dependency(NUGET, found["name"], found["version"], path, _line_number(text, found.start()))


def _from_dotnet_tools(path: Path, text: str) -> Iterable[Dependency]:
    tools = _table(_table(json.loads(text), "the file").get("tools"), "`tools`")
    for name, entry in tools.items():
        offset = text.find(f'"{name}"')
        version = str(_table(entry, f"`{name}`").get("version", ""))
        yield Dependency(NUGET, name, version, path, _line_number(text, max(offset, 0)))


def _from_requirements(path: Path, text: str) -> Iterable[Dependency]:
    for index, raw in enumerate(text.splitlines()):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-") or ";" in line or "@" in line:
            continue
        found = REQUIREMENT.match(line)
        if found:
            spec = (found["spec"] or "").replace(" ", "")
            yield Dependency(PYPI, found["name"].lower(), spec, path, index + 1)


def _from_pyproject(path: Path, text: str) -> Iterable[Dependency]:
    data = tomllib.loads(text)
    project = _table(data.get("project"), "[project]")
    entries: list[str] = [entry for entry in project.get("dependencies", []) if isinstance(entry, str)]
    for group in _table(project.get("optional-dependencies"), "[project.optional-dependencies]").values():
        entries.extend(entry for entry in group if isinstance(entry, str))
    for group in _table(data.get("dependency-groups"), "[dependency-groups]").values():
        entries.extend(entry for entry in group if isinstance(entry, str))
    for entry in entries:
        offset = text.find(entry)
        for dependency in _from_requirements(path, entry):
            yield Dependency(PYPI, dependency.name, dependency.version, path, _line_number(text, max(offset, 0)))


def _from_json_blocks(path: Path, text: str, ecosystem: str, blocks: tuple[str, ...]) -> Iterable[Dependency]:
    data = _table(json.loads(text), "the file")
    for block in blocks:
        for name, version in _table(data.get(block), f"`{block}`").items():
            if ecosystem == COMPOSER and "/" not in name:
                continue  # `php` and `ext-*` are the runtime, judged by the PHP floor rules
            if ecosystem == NPM and not isinstance(version, str):
                continue
            offset = text.find(f'"{name}"')
            yield Dependency(ecosystem, name, str(version), path, _line_number(text, max(offset, 0)))


def _from_package_json(path: Path, text: str) -> Iterable[Dependency]:
    return _from_json_blocks(path, text, NPM, ("dependencies", "devDependencies", "optionalDependencies"))


def _from_composer(path: Path, text: str) -> Iterable[Dependency]:
    return _from_json_blocks(path, text, COMPOSER, ("require", "require-dev"))


def split_image(reference: str) -> tuple[str, str] | None:
    """`registry/repo:tag` or `repo@sha256:...` -> (image, version); None when unreadable."""
    if "$" in reference or reference == "scratch":
        return None
    if "@" in reference:
        image, digest = reference.split("@", 1)
        return image, digest
    slash = reference.rfind("/")
    colon = reference.rfind(":")
    if colon > slash:
        return reference[:colon], reference[colon + 1 :]
    return reference, "latest"


def _from_dockerfile(path: Path, text: str) -> Iterable[Dependency]:
    stages: set[str] = set()
    for index, line in enumerate(text.splitlines()):
        found = DOCKER_FROM.match(line)
        if not found:
            continue
        reference = found["image"]
        if found["alias"]:
            stages.add(found["alias"].lower())
        if reference.lower() in stages:
            continue  # `FROM build AS publish` names an earlier stage, not an image
        parts = split_image(reference)
        if parts:
            yield Dependency(DOCKER, parts[0], parts[1], path, index + 1)


def _images_and_actions(path: Path, text: str) -> Iterable[Dependency]:
    """Compose files and workflows: `image:` lines; workflows also `uses:` lines."""
    for index, line in enumerate(text.splitlines()):
        image = COMPOSE_IMAGE.match(line)
        if image:
            parts = split_image(image["image"])
            if parts:
                yield Dependency(DOCKER, parts[0], parts[1], path, index + 1)
            continue
        code, _, comment = line.partition("#")
        action = USES.search(code)
        if action and not action[1].startswith(("./", "docker://")):
            owner_repo = "/".join(action[1].split("/")[:2])
            tag = ACTION_TAG_COMMENT.match(comment)
            yield Dependency(ACTION, owner_repo, action[2], path, index + 1, tag[1] if tag else None)


def _from_global_json(path: Path, text: str) -> Iterable[Dependency]:
    version = _table(_table(json.loads(text), "the file").get("sdk"), "`sdk`").get("version")
    if isinstance(version, str) and version:
        yield Dependency(DOTNET_SDK, "dotnet-sdk", version, path, _line_number(text, text.find(version)))


Reader = Callable[[Path, str], Iterable[Dependency]]


def reader_for(name: str, relative: Path, pack_itself: bool = False) -> Reader | None:
    """The reader for one file, by name and place, or None when it declares nothing we read.

    In the pack's own checkout, `ci/*.yml` are read as workflows: they are the templates every
    consumer's check job is merged from, so the Actions they name are the pack's to keep current.
    """
    lowered = name.lower()
    in_workflows = relative.parts[:2] == (".github", "workflows") or (pack_itself and relative.parts[:1] == ("ci",))
    readers: tuple[tuple[bool, Reader], ...] = (
        (lowered.endswith((".csproj", ".fsproj", ".vbproj")), _from_project_file),
        (lowered in {"directory.build.props", "directory.packages.props"}, _from_project_file),
        (lowered == "dotnet-tools.json", _from_dotnet_tools),
        (lowered.startswith("requirements") and lowered.endswith(".txt"), _from_requirements),
        (lowered == "pyproject.toml", _from_pyproject),
        (lowered == "package.json", _from_package_json),
        (lowered == "composer.json", _from_composer),
        (lowered.startswith("dockerfile"), _from_dockerfile),
        (
            lowered.startswith(("docker-compose", "compose")) and lowered.endswith((".yml", ".yaml")),
            _images_and_actions,
        ),
        (in_workflows and lowered.endswith((".yml", ".yaml")), _images_and_actions),
        (lowered in {"action.yml", "action.yaml"}, _images_and_actions),
        (lowered == "global.json", _from_global_json),
    )
    return next((reader for applies, reader in readers if applies), None)


def _candidate_files(repo_root: Path) -> Iterable[Path]:
    for directory, subdirectories, files in os.walk(repo_root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in VENDOR_DIRECTORIES and (not name.startswith(".") or name in DECLARING_DOT_DIRECTORIES)
        ]
        for name in files:
            yield Path(directory) / name


def _is_pack_owned(relative: Path, text: str, repo_root: Path, pack_itself: bool) -> bool:
    if pack_itself:
        return False
    return is_foreign_pack_file(relative, repo_root) or PACK_FOOTER in text


def declared_dependencies(repo_root: Path) -> list[Dependency]:
    """Every dependency the repository itself declares, in path then line order."""
    pack_itself = is_the_pack_itself(repo_root)
    found: list[Dependency] = []
    for path in _candidate_files(repo_root):
        relative = path.relative_to(repo_root)
        reader = reader_for(path.name, relative, pack_itself)
        if reader is None:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if _is_pack_owned(relative, text, repo_root, pack_itself):
                continue
            found.extend(reader(relative, text))
        except (OSError, ValueError) as error:
            # Said out loud, never skipped quietly: a manifest the gate cannot read is a set of
            # dependencies it is not checking, and a quiet skip would look exactly like "current".
            warn_unreadable(relative, error, "its dependencies are NOT checked by the dependency gate")
    return sorted(found, key=lambda dependency: (dependency.path.as_posix(), dependency.line))
