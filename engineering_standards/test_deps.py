"""Cases for deps.py: the manual path, end to end, exactly as a person types it.

Decision 9 of the 2026-10-02 plan: everything works by hand, and Claude's skill uses the same
commands. So the workflow is driven here through `main()` with real argv -- adopt, be blocked,
investigate, pin, record, pass -- against a temporary repository and a canned registry. No case
touches the network or the developer's real cache.

`CI` is cleared around every case: GitHub's runners set it, and it makes `check` strict, so a
case about a developer machine would otherwise assert the wrong behaviour in CI.

Run: python test_deps.py   (or pytest)
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deps  # noqa: E402
from standards_deps_cache import CACHE_ENVIRONMENT  # noqa: E402
from standards_deps_registry import NotFound  # noqa: E402
from standards_selftest import run_module_tests  # noqa: E402

PYPI_RUFF = "https://pypi.org/pypi/ruff/json"
REASON = "0.16.10 reformats every file; take it with the formatting commit"


class Registry:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses

    def __call__(self, url: str, _headers: dict[str, str]) -> bytes:
        body = self.responses.get(url)
        if body is None:
            raise NotFound(url)
        if isinstance(body, Exception):
            raise body
        return json.dumps(body).encode()


RUFF_IS_NEWER = Registry(
    {
        PYPI_RUFF: {
            "info": {},
            "releases": {
                "0.16.5": [{"upload_time_iso_8601": "2026-08-01T00:00:00Z"}],
                "0.16.10": [{"upload_time_iso_8601": "2026-09-20T00:00:00Z"}],
            },
        }
    }
)


@contextmanager
def repository(pin: str = "ruff==0.16.5") -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tree:
        root = Path(tree)
        (root / "requirements.txt").write_text(pin + "\n", encoding="utf-8")
        saved = {name: os.environ.get(name) for name in (CACHE_ENVIRONMENT, "CI")}
        os.environ[CACHE_ENVIRONMENT] = str(root / "cache.json")
        os.environ.pop("CI", None)
        try:
            yield root
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def run(root: Path, *argv: str, registry: Registry = RUFF_IS_NEWER) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = deps.main(["--root", str(root), *argv], fetch=registry)
    return code, out.getvalue() + err.getvalue()


def in_days(days: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


def test_a_repository_that_has_not_adopted_the_gate_passes_and_says_how() -> None:
    with repository() as root:
        code, output = run(root, "check")
        assert code == 0
        assert "init" in output


def test_the_whole_manual_path() -> None:
    """Adopt, be blocked, look, pin, record, pass -- the loop a person runs at a terminal."""
    with repository() as root:
        assert run(root, "init")[0] == 0
        code, output = run(root, "check")
        assert code == 1
        assert "requirements.txt:1: [dependency-newer] pypi:ruff" in output, "the shape verify keeps as a finding"
        assert "next: python engineering_standards/deps.py investigate pypi:ruff" in output

        code, output = run(root, "investigate", "ruff")
        assert code == 0 and "0.16.10" in output

        code, output = run(root, "record", "ruff", "0.16.10", "updated", "--by", "Jack")
        assert code == 1 and "still pinned at ==0.16.5" in output, "an update the manifest never made"

        (root / "requirements.txt").write_text("ruff==0.16.10\n", encoding="utf-8")
        assert run(root, "record", "ruff", "0.16.10", "updated", "--by", "Jack")[0] == 0
        assert run(root, "check")[0] == 0


def test_a_dated_deferral_lets_the_push_through_and_is_printed() -> None:
    with repository() as root:
        run(root, "init")
        code, _ = run(
            root, "record", "ruff", "0.16.10", "defer", "--until", in_days(7), "--reason", REASON, "--by", "Jack"
        )
        assert code == 0
        code, output = run(root, "check")
        assert code == 0
        assert "notice: pypi:ruff covered" in output and REASON in output, "verify prints notices under `ok`"


def test_the_escape_hatch_refuses_an_open_ended_deferral() -> None:
    with repository() as root:
        run(root, "init")
        code, output = run(
            root, "record", "ruff", "0.16.10", "defer", "--until", in_days(60), "--reason", REASON, "--by", "Jack"
        )
        assert code == 1 and "at most" in output
        assert run(root, "check")[0] == 1


def test_an_unreachable_registry_warns_locally_and_fails_in_ci() -> None:
    offline = Registry({PYPI_RUFF: OSError("connection refused")})
    with repository() as root:
        run(root, "init")
        assert run(root, "check", registry=offline)[0] == 0
        assert run(root, "check", "--ci", registry=offline)[0] == 1


def test_a_floating_version_blocks() -> None:
    with repository(pin="ruff>=0.16") as root:
        run(root, "init")
        code, output = run(root, "check")
        assert code == 1 and "not a pin" in output


def test_an_ambiguous_or_unknown_name_is_refused() -> None:
    with repository() as root:
        run(root, "init")
        assert run(root, "record", "nothing-here", "1.0.0", "updated", "--by", "Jack")[0] == 2
        assert run(root, "investigate", "nothing-here")[0] == 2


if __name__ == "__main__":
    sys.exit(run_module_tests(globals(), "deps.py"))
