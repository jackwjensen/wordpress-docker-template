#!/usr/bin/env bash
#
# End-to-end smoke test: build the image, bring up the stack, and assert the
# real artifact works. Runs in CI (build-and-smoke job) and locally.
#
#   1. WordPress serves HTTP            (via the shared healthcheck)
#   2. Baked-in PHP upload limit active (proves the Dockerfile COPY shipped)
#   3. WordPress can reach MySQL        (install page renders, no DB error)
#
# Uses tests/docker-compose.smoke.yml to drop the host wp-content bind-mounts, so
# running the test never writes WordPress's default themes/plugins into the tree.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Windows/Git Bash: don't mangle compose volume paths

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${BASE_URL:-http://localhost:8080}"
COMPOSE=(docker compose -f docker-compose.yml -f tests/docker-compose.smoke.yml)

cleanup() { "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> Building image and starting the stack"
"${COMPOSE[@]}" up -d --build

echo "==> Waiting for WordPress to serve HTTP"
bash scripts/healthcheck.sh "$BASE_URL" 45 2

echo "==> Asserting baked-in PHP upload_max_filesize is 256M"
limit="$("${COMPOSE[@]}" exec -T wordpress php -r 'echo ini_get("upload_max_filesize");' | tr -d '[:space:]')"
if [ "$limit" != "256M" ]; then
  echo "FAIL: upload_max_filesize is '$limit', expected '256M'" >&2
  exit 1
fi

echo "==> Asserting WordPress can reach the database"
install_html="$(curl -fsSL "$BASE_URL/wp-admin/install.php" || true)"
if printf '%s' "$install_html" | grep -qi "Error establishing a database connection"; then
  echo "FAIL: WordPress cannot reach the database" >&2
  exit 1
fi
if ! printf '%s' "$install_html" | grep -qi "wordpress"; then
  echo "FAIL: install page did not render as expected" >&2
  exit 1
fi

echo "PASS: smoke test succeeded (HTTP up, upload limit baked in, DB reachable)"
