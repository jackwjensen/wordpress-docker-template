#!/usr/bin/env python3
"""Which verification commands a repo has, and when each one runs.

This is the half that knows what "verify this repo" MEANS -- it detects the stack, finds
the right interpreter and package manager, and returns the commands. `verify.py` is the
CLI around it, the git hooks call that, and CI calls it too. One definition, three callers.

Before this module existed the same knowledge lived in three places that could disagree:
this discovery logic (reachable only by the commit hook), a hardcoded step list per stack
in `ci/check-*.yml`, and a verify command written out in prose in each repo's CLAUDE.md.
The pack's own rule says a standard restated in two layers will drift; this was the pack
breaking that rule about the one command that checks the rules.

WHY TWO STAGES. A commit gate and a push gate answer different questions:

* COMMIT is about the change in front of you, and must be fast enough that nobody reaches
  for the escape hatch. Sub-second checks only, scoped to what is staged.
* PUSH is about the repository, and push in this estate IS the production deploy -- every
  repo auto-deploys on push to master. That is the moment worth minutes.

The expensive checks (`dotnet build`, `dotnet test`, `tsc`, `pytest`) cannot be scoped to a
file list anyway: a compiler needs the whole project. Putting them at commit bought nothing
except a slow commit, and a slow commit is how a gate gets bypassed.

Analyzer findings are deliberately NOT at the commit stage. `Directory.Build.props` sets
TreatWarningsAsErrors, so an analyzer violation is already a red squiggle in the IDE and a
failed local build -- the developer cannot miss it without trying. Gating it twice would
cost minutes per commit to re-report something they have already been told.

Source of truth: engineering-standards/engineering_standards/standards_gates.py
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from standards_gate_config import gate_overrides, project_overrides
from standards_gate_outcomes import absent_toolchain_reason, failure_detail
from standards_git import trunk_ref
from standards_pack_identity import PACK_DIRECTORY, is_the_pack_itself

# Re-exported: migrate.py and the gate tests import these names from here.
from standards_projects import (  # noqa: F401
    PROJECT_SEARCH_DEPTH,
    VENDOR_DIRECTORIES,
    declared_tools,
    entity_framework_projects,
    js_runner,
    python_interpreter,
    python_projects,
)

GATE_TIMEOUT_SECONDS = 900


class Stage(str, Enum):
    """When a gate runs. COMMIT is a subset of PUSH, never the other way round."""

    COMMIT = "commit"
    PUSH = "push"


class Outcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Gate:
    """One check: its name, the command, and the directory to run it in.

    The directory matters for a monorepo, where a nested Python project's config only
    applies from its own root.
    """

    name: str
    command: list[str]
    working_directory: Path
    # Whether the repo DECLARED this command in `.standards.json` (see standards_gate_config).
    # Carried on the gate because exactly one classifier depends on it: only a declared
    # command can be a container command, and only a container command may be excused as
    # "environment not reachable". See standards_gate_outcomes.UNREACHABLE_TOOLCHAIN_PATTERN.
    declared: bool = False


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    outcome: Outcome
    detail: str = ""

    @property
    def is_failure(self) -> bool:
        return self.outcome is Outcome.FAILED


def build_gates(repo_root: Path, stage: Stage, scanner_format: str = "text") -> list[Gate]:
    """The verification commands that apply to this repo at this stage, cheapest first."""
    gates: list[Gate] = [*source_limit_gates(repo_root, stage, scanner_format)]

    if stage is Stage.COMMIT:
        # Ruff is the one linter fast enough to belong here -- it is a Rust binary that
        # clears a few thousand files in well under a second, so scoping it to the staged
        # set would add more complexity than it saves time.
        gates += python_gates(repo_root, ruff_only=True)
        return gates

    if any(repo_root.glob("*.sln")):
        gates.append(Gate("dotnet build", ["dotnet", "build", "--nologo", "-warnaserror"], repo_root))
        if any(repo_root.rglob("*Tests*.csproj")):
            gates.append(Gate("dotnet test", ["dotnet", "test", "--nologo", "--no-build"], repo_root))
        # The model snapshot is committed source that only `dotnet ef` ever reads, so a stale
        # one passes build and test and first fails at container startup, when the next
        # migration is scaffolded against the wrong baseline. Measured in InvoTrack on
        # 2026-08-15: a snapshot recording CURRENT_TIMESTAMP where the model said
        # CURRENT_TIMESTAMP(6) survived an entire branch and surfaced as a startup ERR in a
        # deploy simulation. `has-pending-model-changes` diffs the model against the snapshot
        # at design time -- the connection string is never opened, so no database is needed.
        # --no-build reuses the `dotnet build` output above, same as `dotnet test`.
        for project in entity_framework_projects(repo_root):
            where = "" if project == repo_root else f" ({project.relative_to(repo_root).as_posix()})"
            gates.append(
                Gate(
                    f"ef model sync{where}",
                    ["dotnet", "ef", "migrations", "has-pending-model-changes", "--no-build"],
                    project,
                )
            )

    package_json = repo_root / "package.json"
    if package_json.is_file():
        scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        runner = js_runner(repo_root)
        if "type-check" in scripts:
            gates.append(Gate("type-check", [runner, "run", "type-check"], repo_root))
        if "lint" in scripts:
            gates.append(Gate("lint", [runner, "run", "lint"], repo_root))
        # The old hand-written CI job ran this and the gate discovery did not, so folding CI
        # onto build_gates would have silently dropped a whole frontend suite -- the precise
        # drift this consolidation exists to end, introduced by the consolidation itself.
        # Relies on the runner's `test` script being one-shot; a watch-mode script would sit
        # here until GATE_TIMEOUT_SECONDS.
        if "test" in scripts:
            gates.append(Gate("js tests", [runner, "run", "test"], repo_root))

    gates += python_gates(repo_root)

    return gates


def source_limit_gates(repo_root: Path, stage: Stage, scanner_format: str = "text") -> list[Gate]:
    """The pack's own scanner, scoped to the staged set at commit and the tree at push."""
    # STILL ASKED OF repo_root -- "does THIS repo carry the pack?" -- because a repo outside
    # the pack must be a silent no-op rather than an error. But the DIRECTORY NAME comes from
    # where this module actually sits, never from a literal, because a literal is what broke
    # this silently in the 2026-09-02 move: the path said `scripts/`, the package had moved
    # to `engineering_standards/`, and a missing scanner yields NO GATE rather than a failure
    # -- so `verify` reported "no gates apply to this repository" and exited 0. A gate that
    # cannot find itself must never be indistinguishable from a repo with nothing to check,
    # and now it cannot be: the name is read off the installation doing the asking.
    limits_script = repo_root / PACK_DIRECTORY / "check-source-limits.py"
    if not limits_script.is_file():
        return []

    scope = ["--staged"] if stage is Stage.COMMIT else []
    reporting = ["--format", scanner_format] if scanner_format != "text" else []
    name = "source limits (staged)" if stage is Stage.COMMIT else "source limits"

    # Pay-down runs at push and in CI, never at commit. Being refused on the first commit
    # into a baselined file would only teach --no-verify, and the unit of work this judges
    # is the branch, not the commit. An unresolvable trunk yields NO pay-down argument
    # rather than a failing gate: a repo with no trunk yet has no recorded debt to move.
    paydown: list[str] = []
    if stage is not Stage.COMMIT:
        base_ref = trunk_ref(repo_root)
        if base_ref is not None:
            paydown = ["--paydown", base_ref]

    # THE SAME INTERPRETER AS EVERY OTHER PYTHON GATE, not `sys.executable`. The one that
    # started the hook is whatever happened to be first on PATH, which on 2026-09-03 was
    # Python 3.13 on a machine whose repo declares a 3.14 floor -- so ruff and pytest ran on
    # the venv's 3.14 while the scanner ran on 3.13, and nothing said the two disagreed.
    return [
        Gate(
            name,
            [
                python_interpreter(repo_root, repo_root),
                str(limits_script),
                "--root",
                str(repo_root),
                *scope,
                *reporting,
                *paydown,
            ],
            repo_root,
        )
    ]


def build_gate(
    name: str,
    label: str,
    default_command: list[str],
    project: Path,
    repo_root: Path,
    overrides: dict,
) -> Gate:
    """One gate, using the repo's declared command for it where there is one."""
    declared = overrides.get(name)
    if not declared:
        return Gate(f"{name}{label}", default_command, project)
    run_from = declared.get("runFrom")
    return Gate(
        f"{name}{label}",
        list(declared["command"]),
        repo_root / run_from if run_from else project,
        declared=True,
    )


def python_gates(repo_root: Path, ruff_only: bool = False) -> list[Gate]:
    """ruff and pytest, for every Python project in the repo that has declared them.

    Gated on the project *declaring* the tool rather than on the tool being importable: a
    declaration is the repo saying it wants this enforced, and it cannot be satisfied by
    an incomplete local environment. A missing interpreter or module is handled by
    `run_gate`, which skips rather than blocks -- see the note there on why that direction
    is the safe one for a hook.

    **Per project, not per repo.** allegro-it-services keeps its Django half in
    `packages/backend/`, so a root-only check would have gated the TypeScript and left the
    Python ungated -- exactly the asymmetry this function exists to remove, in the one repo
    where it is least visible.
    """
    overrides = gate_overrides(repo_root)
    gates: list[Gate] = []
    for project in python_projects(repo_root):
        declared = declared_tools(project)
        interpreter = python_interpreter(project, repo_root)
        where = "" if project == repo_root else f" ({project.relative_to(repo_root)})"

        declared_commands = project_overrides(repo_root, project, overrides)
        skip_pack = _foreign_pack_arguments(project, repo_root)

        if "ruff" in declared:
            gates.append(
                build_gate(
                    "ruff",
                    where,
                    [interpreter, "-m", "ruff", "check", "."] + skip_pack.get("ruff", []),
                    project,
                    repo_root,
                    declared_commands,
                )
            )

        # FORMATTING IS THE FORMATTER'S JOB, and this is what makes that true rather than
        # aspirational. ruff implements the blank-line family (E301/E302/E303/E305) in
        # PREVIEW only, precisely because it considers whitespace a formatter concern -- so a
        # repo that lints but never formats has a whole class of findings nothing can see.
        # Fourteen of them had accumulated here, invisible to a green gate.
        #
        # `--check` never writes: it reports and fails, so the gate cannot rewrite a file
        # under someone mid-edit. Runs at COMMIT beside ruff check, being equally sub-second.
        if "ruff" in declared:
            gates.append(
                build_gate(
                    "ruff format",
                    where,
                    [interpreter, "-m", "ruff", "format", "--check", "."] + skip_pack.get("ruff", []),
                    project,
                    repo_root,
                    declared_commands,
                )
            )

        if ruff_only:
            continue

        # Last, and deliberately: it is the only gate that costs real seconds, so
        # everything cheap has already had its say by the time a push waits on a suite.
        if "pytest" in declared or (project / "tests").is_dir():
            gates.append(
                build_gate(
                    "pytest",
                    where,
                    [interpreter, "-m", "pytest", "-q", "-x"] + skip_pack.get("pytest", []),
                    project,
                    repo_root,
                    declared_commands,
                )
            )

    return gates


def _foreign_pack_arguments(project: Path, repo_root: Path) -> dict[str, list[str]]:
    """Arguments that keep a CONSUMING repo's Python gates off the pack's own files.

    The pack lands at the repo ROOT, so only a project rooted there can reach it -- a Django
    half in `packages/backend/` never could, and must not be handed flags naming a directory
    it cannot see.

    WITHOUT THIS, A CONSUMER'S GATES RUN ON CODE THAT IS NOT ITS OWN. pytest collected the
    pack's ~900 cases beside the repo's under `-x`, so a pack test could fail a push in a
    repo whose own code was fine, and ruff linted ~100 modules the repo must not edit --
    every finding unfixable there, because the next sync overwrites the file. The pack's own
    repository is excluded from this exclusion: there they ARE the source.

    RUFF TAKES `--extend-exclude`, NEVER `--exclude`, and the difference is the whole
    behaviour of the gate. `--exclude` REPLACES the configured exclude list rather than
    adding to it, so passing it here silently un-excluded everything `ruff-standards.toml`
    excludes -- `**/migrations/**`, `.venv`, `venv`, `node_modules`, `staticfiles` -- for the
    duration of every gate run in every consuming repo. Found in sourcetext.ai on 2026-09-09
    as three S608 findings inside `migrations/versions/` that appeared ONLY under
    `verify.py` and not under a direct `ruff check .`. A finding that exists in one
    invocation and not the other is the worst shape a finding can take: it makes the gate
    the suspect rather than the code, which is the failure class this pack exists to prevent.
    pytest's `--ignore` adds rather than replaces, so it needs no equivalent.
    """
    if project != repo_root or is_the_pack_itself(repo_root):
        return {}
    if not (repo_root / PACK_DIRECTORY).is_dir():
        return {}
    return {
        "pytest": [f"--ignore={PACK_DIRECTORY}"],
        "ruff": ["--extend-exclude", PACK_DIRECTORY],
    }


def run_gate(gate: Gate) -> GateResult:
    """Run one gate.

    A missing toolchain SKIPS rather than fails. That direction is deliberate: a developer
    whose machine has no dotnet SDK should still be able to commit a README, and CI is the
    authoritative backstop for anything that reaches the remote. What was wrong before is
    that a skip was indistinguishable from a pass -- so the outcome is now named, and
    `verify.py` prints it. What a non-zero exit MEANS is decided in standards_gate_outcomes.
    """
    try:
        completed = subprocess.run(  # noqa: S603  (gate commands come from .standards.json / discovery, never from a scanned file)
            gate.command,
            cwd=gate.working_directory,
            capture_output=True,
            text=True,
            # UTF-8, never the locale codec: bare `text=True` decodes cp1252 here, and one
            # undefined byte kills subprocess's reader thread, so `stdout` returns None and
            # the gate reports FAILED with no detail. Only reachable on failure, so it hides
            # until the run that mattered -- docs/verification.md, "the reporting path".
            encoding="utf-8",
            errors="replace",
            timeout=GATE_TIMEOUT_SECONDS,
            shell=False,
            # The return code IS the gate's verdict, read below -- never an exception.
            check=False,
        )
    except FileNotFoundError:
        return GateResult(gate, Outcome.SKIPPED, f"{gate.command[0]} is not installed here")
    except subprocess.TimeoutExpired:
        return GateResult(gate, Outcome.FAILED, f"timed out after {GATE_TIMEOUT_SECONDS}s")

    if completed.returncode == 0:
        return GateResult(gate, Outcome.PASSED)

    output = (completed.stdout or "") + (completed.stderr or "")

    absent = absent_toolchain_reason(gate.command, output, gate.declared)
    if absent is not None:
        return GateResult(gate, Outcome.SKIPPED, absent)

    return GateResult(gate, Outcome.FAILED, failure_detail(output))


def run_gates(gates: list[Gate]) -> list[GateResult]:
    return [run_gate(gate) for gate in gates]
