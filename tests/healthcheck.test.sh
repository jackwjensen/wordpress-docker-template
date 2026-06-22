#!/usr/bin/env bash
#
# Regression test for the deploy health-check bug.
#
# The old deploy logic counted "running" containers and never checked HTTP, so a
# WordPress that booted but returned 500 (or nothing) was reported "healthy".
# scripts/healthcheck.sh fixes this by probing HTTP and requiring a 2xx/3xx.
#
# This test pins the fix: the health check MUST fail against an endpoint where
# nothing is serving. Proven to fail without the fix — the old container-count
# logic ignores the URL entirely and would exit 0 here, turning this assertion
# red. It needs no Docker, so it runs fast in the CI lint job.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HEALTHCHECK="$ROOT_DIR/scripts/healthcheck.sh"

# Port 9 (discard) — nothing serves HTTP here. 1 attempt, 1s delay = fast.
DEAD_URL="http://127.0.0.1:9"

echo "==> Expecting healthcheck.sh to FAIL against a non-serving endpoint ($DEAD_URL)"
if bash "$HEALTHCHECK" "$DEAD_URL" 1 1; then
  echo "FAIL: healthcheck.sh reported healthy against a dead endpoint" >&2
  echo "      (this is exactly the silent-failure the fix prevents)" >&2
  exit 1
fi

echo "PASS: healthcheck.sh correctly fails when nothing is serving HTTP"
