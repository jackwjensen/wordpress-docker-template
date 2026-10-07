#!/usr/bin/env python3
"""Which files the scanner reads, and which it refuses to.

Split out of standards_core.py when the workflow and .env.example predicates pushed it
past the pack's own 500-line limit. The seam is the subject that grew: "which files are
in scope" changes when a new file type enters scope or a new generated directory needs
excluding, while the rest of core changes when the domain vocabulary does.

Two decisions here are load-bearing and easy to get wrong:

* Compose files, workflows, .env.example and Dockerfiles are matched by FILENAME, never by
  adding ".yml" to SOURCE_SUFFIXES. The suffix route would silently pull in every Kubernetes
  manifest and OpenAPI spec in the tree, and would apply the file-length rule to stack
  definitions where it means nothing.
* Exclusions are matched against the REPO-RELATIVE path, never the absolute one. A repo
  that happens to live under a directory called "build" or "dist" would otherwise have
  every one of its files silently skipped.

Source of truth: engineering-standards/engineering_standards/standards_scope.py
"""

from __future__ import annotations

import re
from pathlib import Path

from standards_core import CheckConfig
from standards_pack_identity import is_foreign_pack_file

SOURCE_SUFFIXES = (
    ".cs",
    ".razor",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".php",
)

# Which files are in scope is this module's job, so the predicates stay here even though
# the RULES live in standards_compose.py -- that module imports them, and moving them
# there instead would make should_check depend on the rules it is supposed to gate.
#
# Matched by filename rather than by suffix so that putting ".yml" in scope does not
# silently drag in every Kubernetes manifest and OpenAPI spec in the tree.
COMPOSE_FILENAME = re.compile(r"^docker-compose[.\w-]*\.ya?ml$", re.IGNORECASE)

# A GitHub Actions workflow, in scope only for the deploy-gate rule. Matched on the
# containing directory as well as the suffix, since ".github/workflows" is the only place
# these live and a stray root-level "deploy.yml" is not one.
WORKFLOW_DIRECTORY = "/.github/workflows/"

# The committed env template. Never `.env` itself -- that holds real secrets and is never
# read by anything here.
ENV_EXAMPLE_FILENAME = re.compile(r"^\.env\.example$", re.IGNORECASE)

# A .NET project file, in scope only for the runtime-support rule. Matched by filename for
# the same reason the compose and workflow predicates are: it keeps `.csproj` out of
# SOURCE_SUFFIXES, where the file-length and naming rules would start judging XML they have
# no opinion about. `.fsproj`/`.vbproj` are here because the rule reads a TFM, which is the
# one thing all three spell identically -- not because the estate has any F# in it today.
PROJECT_FILENAME = re.compile(r"^[\w.-]+\.(?:cs|fs|vb)proj$", re.IGNORECASE)

# A Dockerfile, in scope only for the container-root-user rule. By filename for the same
# reason as everything above it: a Dockerfile has no suffix to add to SOURCE_SUFFIXES, and
# even if it had, the file-length and naming rules have no opinion about one. `Dockerfile.x`
# is included because that is how repos spell a second target (Dockerfile.dev, .worker), and
# a dev-only image that genuinely wants root can say so with a line-scoped exemption.
DOCKERFILE_FILENAME = re.compile(r"^Dockerfile(?:\.[\w.-]+)?$", re.IGNORECASE)

# `.nvmrc`, in scope only for the node-support floor. It is one line holding one version, and
# it OUTRANKS everything else that names a Node version in the repo -- CI_DEFAULTS defers to
# it by design -- so a floor that could not read it would be enforcing the toolchain everywhere
# except the file that actually decides it.
NVMRC_FILENAME = re.compile(r"^\.nvmrc$", re.IGNORECASE)

# The three files that declare a Python version, in scope only for the python-support floor.
# By filename for the same reason as everything above: putting ".toml" or ".cfg" in
# SOURCE_SUFFIXES would drag every tool config in the tree under the length and naming rules,
# which have no opinion about TOML.
#
# `.python-version` is Python's `.nvmrc` -- pyenv and uv both read it, and it is what decides
# which interpreter a developer's shell picks up. `pyproject.toml` holds `requires-python` plus
# the ruff/black/mypy targets, which is four declarations in one file. `setup.cfg` is the
# legacy home of `python_requires`; it is here because allegro-it-services still ships one, and
# a declaration site the floor cannot see is a declaration site the floor can be moved into.
#
# setup.py is deliberately NOT added: it is a `.py` file and therefore already in scope, and
# putting a version rule on the source suffixes would mean scanning application code for a
# keyword. PEP 621 put this in pyproject.toml; nothing in the estate declares it in setup.py.
PYPROJECT_FILENAME = re.compile(r"^pyproject\.toml$", re.IGNORECASE)
PYTHON_VERSION_FILENAME = re.compile(r"^\.python-version$", re.IGNORECASE)
SETUP_CFG_FILENAME = re.compile(r"^setup\.cfg$", re.IGNORECASE)

# composer.json, in scope for the PHP floor and its consistency sibling. By filename like every
# predicate above: adding ".json" to SOURCE_SUFFIXES would pull in every package-lock, tsconfig
# and appsettings in the tree, none of which these rules have an opinion about.
COMPOSER_FILENAME = re.compile(r"^composer\.json$", re.IGNORECASE)
# Dependabot's config, which lives in .github/ but NOT in .github/workflows/ -- so `is_workflow`
# does not reach it and nothing scanned it before 2026-08-27. It is in scope because its `ignore`
# list is where "we are deliberately behind on this package" is recorded, and an undated entry
# there is how that becomes permanent (see dependency-holdback in standards_packages.py).
DEPENDABOT_FILENAME = re.compile(r"^dependabot\.ya?ml$", re.IGNORECASE)

# package.json, in scope for the package-wildcard rule. Not for the Node FLOOR: `engines.node`
# is a range this pack deliberately does not judge (see standards_node_support.py). What is
# judged here is the opposite of a range -- a dependency with no version at all.
PACKAGE_JSON_FILENAME = re.compile(r"^package\.json$", re.IGNORECASE)

# requirements.txt (and its -dev / -base variants), in scope for the package-wildcard rule --
# the Python sibling of package.json. A bare `Django` line with no specifier at all resolves to
# whatever is newest at install time, which is the same unreproducible-build defect the .NET
# and npm halves catch. By filename because ".txt" in SOURCE_SUFFIXES would drag in every
# README and licence in the tree.
REQUIREMENTS_FILENAME = re.compile(r"^requirements[\w.-]*\.txt$", re.IGNORECASE)

# Config files, in scope for the committed-credential rule. THIS IS THE GAP THAT LET THE REAL
# ONE THROUGH: `appsettings.Development.json` was in scope for nothing at all, because ".json"
# is not a source suffix and no filename predicate named it -- so a committed demo password in
# ligelon-compliance passed every gate the pack had. `.env.example` is here for the same reason
# in reverse: it is SUPPOSED to be committed, carrying key names with empty values, so it is
# exactly where a real value hides in plain sight.
#
# `.env` itself is matched so the rule can report it BY NAME. It is never opened -- see
# standards_secrets.py.
CONFIG_FILENAME = re.compile(
    r"^(?:appsettings[\w.-]*\.json|web\.config|app\.config|settings[\w.-]*\.(?:json|ini|cfg)"
    r"|\.env(?:\.[\w.-]+)?)$",
    re.IGNORECASE,
)


def is_workflow(path: Path, repo_root: Path) -> bool:
    """True for a GitHub Actions workflow file."""
    if path.suffix.casefold() not in (".yml", ".yaml"):
        return False
    return WORKFLOW_DIRECTORY in "/" + path.relative_to(repo_root).as_posix()


def looks_like_workflow(path: Path) -> bool:
    """`is_workflow` for callers that have no repo root -- the toolchain version readers.

    WHY THIS EXISTS, and it is not a convenience. Those readers used to end in a fall-through
    that treated ANY file as a workflow and searched it for `node-version:`. That was harmless
    while the only caller was the dispatcher, which hands them nothing else -- and became a bug
    the moment the consistency engine started walking every in-scope path, because a `.py` file
    holding `"node-version: '22'"` as a TEST FIXTURE was read as a real declaration. The pack
    failed its own gate on its own test suite, which is the cheap version of what would
    otherwise have fired in every adopted repo with a fixture or a code sample in its docs.

    Decided on the path's own parents rather than a repo-relative path, because a reader is
    given a file and no tree.
    """
    if path.suffix.casefold() not in (".yml", ".yaml"):
        return False
    parent = path.parent
    return parent.name.casefold() == "workflows" and parent.parent.name.casefold() == ".github"


# The JavaScript family, where one set of regexes serves every member. TypeScript is in
# here too: the sentinel traps are runtime behaviour, identical with or without types.
SCRIPT_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

# Paths never checked: machine-generated, vendored, or build output.
EXCLUDED_PATH_FRAGMENTS = (
    "/obj/",
    "/bin/",
    "/node_modules/",
    "/vendor/",
    "/migrations/",
    "/.git/",
    "/dist/",
    "/build/",
    "/__pycache__/",
    "/.venv/",
    "/venv/",
    "/staticfiles/",
    "/wwwroot/lib/",
    "/.next/",
    "/coverage/",
)
EXCLUDED_NAME_FRAGMENTS = (".min.", ".g.", ".designer.", ".generated.")


def should_check(path: Path, repo_root: Path, config: CheckConfig) -> bool:
    """Decide whether a file is in scope.

    Exclusions are matched against the REPO-RELATIVE path, never the absolute one: a repo
    that happens to live under a directory called "build" or "dist" would otherwise have
    every one of its files silently skipped.

    THE PACK'S OWN FILES ARE NOT THE CONSUMING REPO'S SOURCE. A repo that adopted the pack
    holds ~100 files it did not write and must not edit, so measuring them here reported
    findings and exemption markers nobody in that repo could act on -- see
    standards_pack_identity. In the PACK's own repository they are the source, and are
    checked exactly as before.
    """
    in_scope = (
        path.suffix in SOURCE_SUFFIXES
        or COMPOSE_FILENAME.match(path.name)
        or ENV_EXAMPLE_FILENAME.match(path.name)
        or PROJECT_FILENAME.match(path.name)
        or DOCKERFILE_FILENAME.match(path.name)
        or NVMRC_FILENAME.match(path.name)
        or PYPROJECT_FILENAME.match(path.name)
        or PYTHON_VERSION_FILENAME.match(path.name)
        or SETUP_CFG_FILENAME.match(path.name)
        or COMPOSER_FILENAME.match(path.name)
        or PACKAGE_JSON_FILENAME.match(path.name)
        or REQUIREMENTS_FILENAME.match(path.name)
        or CONFIG_FILENAME.match(path.name)
        or DEPENDABOT_FILENAME.match(path.name)
        or is_workflow(path, repo_root)
    )
    if not in_scope:
        return False

    relative = path.relative_to(repo_root)
    if is_foreign_pack_file(relative, repo_root):
        return False

    lowered = "/" + relative.as_posix().casefold() + "/"

    excluded = EXCLUDED_PATH_FRAGMENTS + config.extra_excluded_fragments
    if any(fragment.casefold() in lowered for fragment in excluded):
        return False

    return not any(fragment in path.name.casefold() for fragment in EXCLUDED_NAME_FRAGMENTS)
