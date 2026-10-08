"""verify.py's CLI contract, driven through the real entry point.

The gate engine's units are tested in test_standards_gate.py; what had NO coverage was the
seam every hook and CI job actually touches -- the CLI. That is the layer where the estate's
silent failures lived (a skip indistinguishable from a pass, an escape hatch that did not
disengage), so these tests assert exit codes and printed outcomes, not internals.

Run: python test_verify_cli.py   (or pytest)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

PACK_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(PACK_DIRECTORY))

from standards_selftest import run_module_tests  # noqa: E402  (path set above)


def make_repo(root: Path) -> Path:
    (root / "engineering_standards").mkdir(parents=True)
    for source in PACK_DIRECTORY.glob("*.py"):
        shutil.copy2(source, root / "engineering_standards" / source.name)
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    # A clean fixture must satisfy every repo-level rule, so these tests exercise only the
    # CLI: gitignore above, and the documentation dimension's index here.
    (root / "docs").mkdir()
    (root / "docs" / "index.md").write_text("---\naudience: dev\ntype: reference\n---\n# Map\n", encoding="utf-8")
    return root


def run_verify(root: Path, *arguments: str, skip_variable: str | None = None, extra: dict[str, str] | None = None):
    environment = {key: value for key, value in os.environ.items() if key != "SKIP_STANDARDS_GATE"}
    environment.update(extra or {})
    if skip_variable is not None:
        environment["SKIP_STANDARDS_GATE"] = skip_variable
    return subprocess.run(
        [sys.executable, str(root / "engineering_standards" / "verify.py"), "--root", str(root), *arguments],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


def test_escape_hatch_short_circuits_everything() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = run_verify(make_repo(Path(tmp)), skip_variable="1")
        assert result.returncode == 0, result.stderr
        assert "skipped entirely" in result.stdout, "the skip must be SAID, not silent"


def test_list_names_the_gates_and_runs_nothing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = run_verify(make_repo(Path(tmp)), "--list")
        assert result.returncode == 0, result.stderr
        assert "source limits" in result.stdout, "the scanner gate must be discovered and named"


def test_clean_repo_passes_and_names_what_ran() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        (repo / "Ok.cs").write_text("public class Fine { public bool IsActive { get; set; } }\n", encoding="utf-8")
        result = run_verify(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok      source limits" in result.stdout, "a pass must name the gate that ran"


def _adopted_repo_with_a_newer_ruff(root: Path, decisions: list[dict]) -> dict[str, str]:
    """A repo pinned to ruff 0.16.5 whose registry says 0.16.10 -- answered from a FRESH cache,
    so the real `deps.py check` runs end to end through verify without touching the network."""
    make_repo(root)
    (root / ".gitignore").write_text(
        ".env\n__pycache__/\n.venv/\n", encoding="utf-8"
    )  # a requirements file makes it Python
    (root / "requirements.txt").write_text("ruff==0.16.5\n", encoding="utf-8")
    record = {"format": 1, "dependencies": {"pypi:ruff": decisions}}
    (root / ".standards-dependencies.json").write_text(json.dumps(record), encoding="utf-8")
    cache = root.parent / "dependency-cache.json"
    releases = [["0.16.5", "2026-08-01", None], ["0.16.10", "2026-09-20", None]]
    lookups = {"releases:pypi:ruff": {"releases": releases, "preferred": None, "fetched": time.time()}}
    cache.write_text(json.dumps({"lookups": lookups, "notes": {}}), encoding="utf-8")
    return {"STANDARDS_DEPS_CACHE": str(cache), "CI": ""}


def test_a_release_nobody_looked_at_blocks_the_push_and_says_what_to_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        result = run_verify(repo, extra=_adopted_repo_with_a_newer_ruff(repo, []))
        assert result.returncode == 1, result.stdout + result.stderr
        assert "[dependency-newer]" in result.stderr and "deps.py investigate pypi:ruff" in result.stderr


def test_a_dated_deferral_lets_the_push_through_and_is_printed() -> None:
    until = (datetime.now(UTC).date() + timedelta(days=7)).isoformat()
    deferral = {
        "version": "0.16.10",
        "decision": "deferred",
        "date": "2026-10-02",
        "by": "Jack",
        "reason": "0.16.10 reformats every file; take it with the formatting commit",
        "until": until,
    }
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        result = run_verify(repo, extra=_adopted_repo_with_a_newer_ruff(repo, [deferral]))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok      dependencies" in result.stdout
        assert f"deferred until {until}" in result.stdout, "a deferral that lets a push through must be SEEN"


def test_violation_fails_with_the_rule_named() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        (repo / "Bad.cs").write_text("public class Thing { public bool Active { get; set; } }\n", encoding="utf-8")
        result = run_verify(repo)
        combined = result.stdout + result.stderr
        assert result.returncode == 1, combined
        assert "bool-prefix" in combined, "the failing rule must be named in the output"


if __name__ == "__main__":
    sys.exit(run_module_tests(globals(), "verify.py CLI"))


def test_exemption_notes_never_crowd_out_the_findings() -> None:
    """A failed gate must show what to FIX, not the list of things already decided.

    `failure_detail` keeps the first MAX_DETAIL_LINES "interesting" lines, and the rule-tag
    pattern it selects on matches an `exempt: path [rule] -- reason` note exactly as it
    matches a finding. The exemption report prints FIRST, so in a repo carrying more than
    MAX_DETAIL_LINES exemptions every real finding was pushed off the end: the gate said it
    failed and then listed only decisions somebody had already made.

    Found on 2026-09-01 in this repo, which carries fourteen -- adding one more exemption
    silently hid `docs-frontmatter` from a run that was reporting it the day before.
    """
    from standards_gate_outcomes import (  # noqa: PLC0415  (local by design: imported after this test builds its tree)
        MAX_DETAIL_LINES,
        failure_detail,
    )

    noise = [
        f"exempt: scripts/module_{index}.py [some-rule] -- a decision already taken here"
        for index in range(MAX_DETAIL_LINES + 5)
    ]
    finding = "docs/setup.md:1: [docs-frontmatter] 'audience' is undeclared"
    detail = failure_detail("\n".join(noise + [finding]))

    assert finding in detail, f"the finding was crowded out by exemption notes:\n{detail}"
    assert "exempt:" not in detail, "exemption notes are decisions, not things to fix"


def test_a_tuned_setting_note_is_also_not_a_finding() -> None:
    """`tuned:` is the same shape of note -- a stated decision, printed on every run."""
    from standards_gate_outcomes import (  # noqa: PLC0415  (local by design: imported after this test builds its tree)
        failure_detail,  # noqa: PLC0415  (local by design: imported after this test builds its tree)
    )

    detail = failure_detail(
        "tuned: maxFileLines = 800 [file-too-long] -- vendored parser, split upstream\n"
        "lib/request.php:1: [client-address-untested] no test names it"
    )
    assert "client-address-untested" in detail
    assert "tuned:" not in detail
