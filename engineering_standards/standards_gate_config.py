"""How a repo declares the way one of its gates is actually run.

Everything in `standards_gates` assumes a project's tools are runnable on this machine:
it finds a virtualenv, or falls back to the interpreter that started the hook. That
assumption is simply false for a project whose environment lives in a container, and the
failure it produces is the worst kind — allegro-it-services keeps its Django dependencies
in `__pypackages__` INSIDE the backend image, so the discovered interpreter was a host
Python that happened to have pytest and none of the application's dependencies. The gate
failed on `ImproperlyConfigured` on every push, for everyone, about nothing anybody had
written. ruff kept passing there, which is what hid it: ruff needs no application
environment.

Reaching for `SKIP_STANDARDS_GATE=1` is not the answer to that, and this module exists so
nobody has to. The hatch disables EVERY gate, so routing around one broken one silently
stops enforcing all the rest — on precisely the push where verification mattered.

Shape, in `.standards.json`, keyed by the project's repo-relative path (`.` for the root):

    "gateCommands": {
      "packages/backend": {
        "pytest": {
          "command": ["docker", "compose", "exec", "-T", "backend",
                      "python", "-m", "pytest", "-q", "-x"],
          "runFrom": "."
        }
      }
    }

`runFrom` is repo-relative and defaults to the project. It exists because a container
command usually has to run where the compose file is, not where the code is.
"""

from __future__ import annotations

import json
from pathlib import Path

GATE_OVERRIDES_KEY = "gateCommands"


def gate_overrides(repo_root: Path) -> dict:
    """The declarations for this repo, or an empty mapping when there are none."""
    try:
        with (repo_root / ".standards.json").open(encoding="utf-8") as handle:
            return json.load(handle).get(GATE_OVERRIDES_KEY, {}) or {}
    except OSError, json.JSONDecodeError:
        # Absent or unreadable config means "no overrides", which is the normal case for
        # every repo. A malformed file is already reported loudly by check-source-limits.
        return {}


def project_overrides(repo_root: Path, project: Path, overrides: dict) -> dict:
    """The declarations for one project, keyed by its repo-relative path."""
    key = "." if project == repo_root else project.relative_to(repo_root).as_posix()
    return overrides.get(key, {})
