#!/usr/bin/env python3
"""Enforce the coding standards that language analyzers cannot express.

Roslyn naming rules can filter by symbol kind and modifier but not by *type*, so
"bool properties start with Is/Has/Can/Should" and "money is never float/double"
have no analyzer equivalent. Ruff has no file-length rule at all. This script
covers exactly that residue -- nothing here duplicates a rule an analyzer already
enforces.

The checks themselves live in standards_checks.py, which must sit beside this file.
This half is the driver: walking the tree, ratcheting the baseline, reporting, CLI.

Checks: file-too-long, baseline-grew, bool-prefix, money-not-decimal,
unset-not-zero, payload-default, date-sentinel, date-out-of-range, razor-var,
php-strict-types, query-shape, paged-without-order (a paginated query with no total order --
see standards_paging.py), client-address (the client's address read from the peer socket or
the front of the forwarded chain -- see standards_client_address.py), technical-error-shown
(an exception's own text or a bare status code reaching the user -- see
standards_user_errors.py), the constants family
(config-default-in-code, const-environment-literal, plus const-duplicated-literal on
whole-tree scans -- see standards_constants.py), the deployment-contract family (compose-port,
compose-container-name, compose-overlay-name, deploy-gate, env-example-compose),
plus the documentation family on whole-tree scans (docs-missing, docs-frontmatter,
docs-broken-link, docs-orphan-page, docs-stale-symbol, claude-md-length -- see
standards_docs.py), its coverage half (docs-uncovered-command, docs-uncovered-env,
docs-uncovered-route -- see standards_coverage.py), and the shipped user-docs contract
(userdocs-missing, userdocs-dangling-slug, userdocs-unlinked-page, userdocs-orphan-topic,
plus a non-blocking doc-sync note at the commit stage -- see standards_userdocs.py), the
judgment layer's own budget (rules-scope-declared, rules-file-length, rules-context-budget --
see standards_rules.py; prose is the one layer whose growth has a running cost, because it is
enforced by being read), the
toolchain floors (python-support, php-support, node-support, runtime-support), and the
*-consistency family (python-, node-, php-, dotnet-), which COMPARE files rather than read
the repository's shape -- whether CI and the Dockerfile agree on a version is invisible from
either one, so they are repo-level for a different reason than the rest of that list.
unset-not-zero and the date rules are the mechanical half of "unset is null" and
"dates declare a sensible range"; payload-default is a separate rule about missing
external data rather than about null-versus-zero; query-shape is a smoke alarm for
an ORM query that has taken on a shape a database view should own.
The judgment halves stay prose in claude/rules/*.md.

Usage:
    python check-source-limits.py [--root DIR] [--config FILE] [--format github]
    python check-source-limits.py --staged          # only what this commit changes
    python check-source-limits.py --files a.cs b.py # only these

Scope defaults to the whole tree, which is what CI and `--write-baseline` need. `--staged`
is for the pre-commit hook: see standards_git.py for why a commit gate checks the commit
rather than the repository, and for the one caveat that comes with it.

Exit codes: 0 = clean, 1 = violations found, 2 = bad invocation.

Source of truth: engineering-standards/engineering_standards/check-source-limits.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import the sibling module by path rather than relying on the caller's cwd: the commit
# hook and the CI job both invoke this script from the repo root, not from engineering_standards/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# BEFORE EVERY OTHER PACK IMPORT, and that order is the whole point: the modules below are
# written for the floor this repo declares, so an interpreter beneath it cannot even parse
# them. Checked here the answer is a sentence; checked one line later it is a SyntaxError
# traceback from a hook that was supposed to be reporting on somebody's commit.
from standards_runtime import require_supported_python  # noqa: E402  (must precede the rest)

require_supported_python(Path(__file__).resolve().parent)

from standards_baseline import (  # noqa: E402  (same reason)
    load_baseline,
    report_eslint_suppressions,
    violation_key,
    write_baseline_file,
)
from standards_checks import (  # noqa: E402  (path must be set before the import)
    CheckConfig,
    Violation,
)
from standards_coverage import check_coverage  # noqa: E402  (same reason)
from standards_dispatch import check_source_file  # noqa: E402  (same reason)
from standards_docs import check_documentation  # noqa: E402  (same reason)
from standards_exemption_report import (  # noqa: E402  (same reason)
    collect_exemptions,
    read_source_lines,
)
from standards_exemptions import file_length_exemption  # noqa: E402
from standards_git import (  # noqa: E402  (same reason)
    ignored_files,
    partially_staged_files,
    staged_files,
)
from standards_paydown import check_paydown  # noqa: E402  (same reason)

# Re-exported: `driver.NEVER_BASELINED` and `driver.TOOLCHAINS` are the names the baseline and
# package tests reach for. TOOLCHAINS has no caller left here since the repo-level rules moved
# to standards_repository.py; it stays because removing it would break those tests' import.
from standards_registry import NEVER_BASELINED, TOOLCHAINS  # noqa: E402,F401  (same reason)
from standards_repository import repository_violations  # noqa: E402  (same reason)
from standards_rules import check_rules  # noqa: E402  (same reason)
from standards_scope import should_check  # noqa: E402  (same reason)
from standards_tests import check_tests_cover_modules  # noqa: E402  (same reason)
from standards_userdocs import check_userdocs, unsynced_change_notes  # noqa: E402  (same reason)


def candidate_files(root: Path, config: CheckConfig, only: list[Path] | None = None) -> list[Path]:
    """Every in-scope file, or the in-scope subset of `only`.

    One resolver for all three collectors, so a scoped run cannot accidentally walk the
    tree for exemptions while checking a subset for violations -- the two would then
    disagree about what was examined, and the summary would describe a run that never
    happened.

    `only` is filtered through the same `should_check` predicate rather than trusted: a
    staged path may be a deleted file, a submodule, or something the scanner is not
    supposed to read (a migration, vendored code), and naming it explicitly does not make
    it in scope.

    FILES GIT IGNORES ARE NOT SCANNED. The walk reads the filesystem, but every rule here
    is about what a repository CONTAINS -- so a path git is told to ignore, and does not
    track, is not this scanner's business. Applied to both branches rather than only to the
    tree walk: an ignored path can never be staged, so the filter is a no-op for `only` and
    keeping one predicate is worth more than skipping a call.

    Computed ONCE per resolution and never inside `should_check`, which runs per path: the
    answer costs a subprocess, and asking it per file would turn a scan into thousands of
    them.
    """
    if only is None:
        paths = sorted(root.rglob("*"))
    else:
        # Resolved because `--files` is written by a human relative to their cwd, and
        # filtered to the tree because should_check computes a repo-relative path and
        # raises on anything outside it.
        paths = sorted({path.resolve() for path in only})
        paths = [path for path in paths if path.is_relative_to(root)]

    ignored = ignored_files(root)

    return [path for path in paths if path.is_file() and path not in ignored and should_check(path, root, config)]


def collect_oversized_files(root: Path, config: CheckConfig, paths: list[Path]) -> dict[str, int]:
    """Current line counts of every file already over the limit, for --write-baseline.

    2026-08-15: a --write-baseline run in DonorLink grandfathered its seven exempt
    files as debt, because this walked the tree without asking about exemptions. An
    exempt file is a decision, not debt, and must never reach the ledger.
    """
    oversized: dict[str, int] = {}
    for path in paths:
        lines = read_source_lines(path)
        if lines is None:
            continue
        if len(lines) > config.max_file_lines and not file_length_exemption(lines):
            oversized[path.relative_to(root).as_posix()] = len(lines)
    return oversized


def write_baseline(
    root: Path,
    baseline_path: Path,
    config: CheckConfig,
    consent_flag: bool = False,
) -> int:
    """Scan the whole tree and hand its findings to the ledger writer.

    The split is deliberate: walking is this file's job, the ledger's format and the consent
    that gates a write are standards_baseline.py's. Scope narrowing is ignored on purpose --
    see write_baseline_file for what a partial baseline silently destroys.
    """
    paths = candidate_files(root, config)
    oversized = collect_oversized_files(root, config, paths)
    member_violations = sorted(
        violation_key(violation, root)
        for violation in (
            *collect_violations(root, config, oversized, paths),
            *check_documentation(root, config),
            *check_coverage(root, config),
            *check_userdocs(root, config),
            # Baselineable adoption debt; a repository-level check, missing here until 2026-09-03.
            *check_tests_cover_modules(root, config),
            # rules-scope-declared and rules-file-length are ordinary debt and grandfather
            # like anything else. rules-context-budget does NOT -- it is in NEVER_BASELINED,
            # because a baselined context budget is the silent growth the rule exists to
            # stop, recorded as accepted.
            *check_rules(root, config),
        )
        if violation.rule != "file-too-long" and violation.rule not in NEVER_BASELINED
    )
    return write_baseline_file(baseline_path, config, oversized, member_violations, consent_flag)


def collect_violations(root: Path, config: CheckConfig, baseline: dict[str, int], paths: list[Path]) -> list[Violation]:
    violations: list[Violation] = []

    for path in paths:
        lines = read_source_lines(path)
        if lines is None:
            continue

        violations.extend(check_source_file(path, lines, config, baseline, root))

    return violations


def report(violations: list[Violation], root: Path, output_format: str) -> None:
    for violation in violations:
        relative = violation.path.relative_to(root).as_posix()
        if output_format == "github":
            print(f"::error file={relative},line={violation.line}::[{violation.rule}] {violation.message}")
        else:
            print(f"{relative}:{violation.line}: [{violation.rule}] {violation.message}")


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Directory to scan (default: cwd)")
    parser.add_argument(
        "--config",
        default=".standards.json",
        help="Optional JSON config for per-repo tuning (default: .standards.json)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "github"),
        default="text",
        help="Output format; 'github' emits workflow error annotations",
    )
    parser.add_argument(
        "--baseline",
        default=".standards-baseline.json",
        help="Grandfathered oversized files (default: .standards-baseline.json)",
    )
    parser.add_argument(
        "--paydown",
        metavar="BASE_REF",
        help=(
            "Also require that every baselined file this branch touches has paid debt down "
            "against BASE_REF (e.g. origin/master). For push and CI, not for commit."
        ),
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Record current oversized files as the baseline instead of failing on them",
    )
    parser.add_argument(
        "--baseline-consent",
        action="store_true",
        help=(
            "Confirm, non-interactively, that a human has agreed to grandfather the findings "
            "--write-baseline would absorb. Required when stdin is not a terminal."
        ),
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help=(
            "Ignore the baseline file entirely: every finding must be fixed or exempted. "
            "Refuses to write a baseline as well."
        ),
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--staged",
        action="store_true",
        help="Check only the files staged for commit (for the pre-commit hook)",
    )
    scope.add_argument(
        "--files",
        nargs="+",
        metavar="PATH",
        type=Path,
        help="Check only these files",
    )
    return parser.parse_args(argv)


def resolve_scope(root: Path, arguments: argparse.Namespace) -> tuple[list[Path] | None, int]:
    """The explicit file list for this run, or None to walk the whole tree.

    The int is an exit code, non-zero only when the invocation cannot be honoured. A
    scoped run that finds nothing to check is a normal, successful outcome -- committing
    only a README must not be reported as a failure.
    """
    if arguments.files:
        return list(arguments.files), 0

    if not arguments.staged:
        return None, 0

    staged = staged_files(root)
    if staged is None:
        print(
            "error: --staged needs a git repository, and git could not be asked here",
            file=sys.stderr,
        )
        return None, 2

    return staged, 0


def baseline_argument_error(arguments: argparse.Namespace) -> int | None:
    """The two --write-baseline combinations that ask for contradictory things.

    Split out of `main` so the CLI's validation is one thing and its work is another;
    these were two of the seven early returns that put `main` over the return limit.
    """
    if arguments.staged or arguments.files:
        print(
            "error: --write-baseline always scans the whole tree; combining it with "
            "--staged/--files would drop every baselined file outside that scope",
            file=sys.stderr,
        )
        return 2
    if arguments.no_baseline:
        print(
            "error: --no-baseline and --write-baseline ask for opposite things",
            file=sys.stderr,
        )
        return 2
    return None


def print_summary(
    root: Path,
    config: CheckConfig,
    paths: list[Path],
    only: list[Path] | None,
    remaining: list[Violation],
    grandfathered: list[Violation],
    output_format: str,
) -> int:
    """Everything the run PRINTS, and the exit code that goes with it.

    Split out of `main` on 2026-09-02, the last of four concerns sharing one function at
    cyclomatic complexity 19. What it prints is not incidental: a `clean` line that did not
    name its relief -- grandfathered, exempt, tuned, ESLint's own -- is a claim nobody can check.
    """
    for setting, value, reason in config.tuning:
        print(f"tuned: {setting} = {value} -- {reason}")

    exemptions = collect_exemptions(root, config, paths)
    for relative, rule, reason in exemptions:
        print(f"exempt: {relative} [{rule}] -- {reason}")

    report_eslint_suppressions(root)  # the OTHER baseline, if the repo carries one
    if remaining:
        report(remaining, root, output_format)
        print(f"\ncheck-source-limits: {len(remaining)} violation(s)", file=sys.stderr)
        return 1

    notes = [f"{len(paths)} file(s)" if only is not None else "whole tree"]
    if grandfathered:
        notes.append(f"{len(grandfathered)} grandfathered")
    if exemptions:
        notes.append(f"{len(exemptions)} exempt")
    if config.tuning:
        notes.append(f"{len(config.tuning)} tuned")
    print(f"check-source-limits: clean ({', '.join(notes)})")
    return 0


def print_staged_notes(root: Path, config: CheckConfig, only: list[Path] | None) -> None:
    """The two notes only a --staged run can owe, neither of them a violation."""
    for path in partially_staged_files(root):
        print(
            f"note: {path.relative_to(root).as_posix()} has unstaged edits; checked "
            f"the working-tree version, which is not exactly what is being committed"
        )
    # The doc-sync nudge: a note, not a violation, because whether a staged edit changed
    # behaviour or merely refactored is judgment a scanner cannot make (standards_userdocs).
    for note in unsynced_change_notes(root, config, only or []):
        print(f"note: {note}")


def main(argv: list[str]) -> int:
    arguments = parse_arguments(argv)

    root = Path(arguments.root).resolve()
    if not root.is_dir():
        print(f"error: --root '{root}' is not a directory", file=sys.stderr)
        return 2

    config = CheckConfig.load(root / arguments.config)
    baseline_path = root / arguments.baseline

    if arguments.write_baseline:
        error = baseline_argument_error(arguments)
        if error is not None:
            return error
        return write_baseline(root, baseline_path, config, arguments.baseline_consent)

    only, scope_error = resolve_scope(root, arguments)
    if scope_error:
        return scope_error

    paths = candidate_files(root, config, only)

    # Named rather than silently tolerated: these are the only files where reading the
    # working tree can disagree with what is actually being committed.
    if arguments.staged:
        print_staged_notes(root, config, only)

    # --no-baseline reads the tree as though no ledger existed: every finding must be fixed or
    # exempted. This is the mode an adoption takes when it refuses to grandfather anything, and
    # the mode a repo can use to see what its baseline is actually hiding.
    if arguments.no_baseline:
        oversized_baseline, known_violations = {}, set()
    else:
        oversized_baseline, known_violations = load_baseline(baseline_path)
    violations = collect_violations(root, config, oversized_baseline, paths)

    # The one check about the REPOSITORY rather than about a file, so it runs only on a
    # whole-tree scan. Running it at commit would block every commit in a repo whose
    # .gitignore is short -- including the commit that fixes it -- which is the same
    # failure the staged scope exists to prevent (see standards_git.py). Push and CI both
    # scan the whole tree, so nothing reaches a remote unchecked.
    if only is None:
        violations += repository_violations(root, config, paths)

    grandfathered = [v for v in violations if violation_key(v, root) in known_violations]
    remaining = [v for v in violations if violation_key(v, root) not in known_violations]

    # Not baselineable and not grandfatherable by construction: this asks whether the debt
    # MOVED, so measuring it against the ledger it is meant to shrink would be circular.
    if arguments.paydown:
        remaining += check_paydown(
            root,
            arguments.paydown,
            arguments.baseline,
            oversized_baseline,
            config.max_file_lines,
        )

    # Printed with the exemptions and for the same reason: a relaxation that appears in no
    # output is indistinguishable from a repo that never needed one, so `clean` stops being
    # a claim anybody can check. `.standards.json` was the one relaxation this summary could
    # not see.
    return print_summary(
        root,
        config,
        paths,
        only,
        remaining,
        grandfathered,
        arguments.format,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
