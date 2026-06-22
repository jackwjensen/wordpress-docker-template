#!/usr/bin/env bash
#
# Probe WordPress for a healthy HTTP status, retrying until it responds or we
# give up. This is the single source of truth for "is WordPress actually
# serving?" — used by tests/smoke.sh, tests/healthcheck.test.sh, and the
# production deploy workflow.
#
# Why not count "running" containers? A container can be up while WordPress
# returns HTTP 500 (database down, PHP fatal). We require a real 2xx/3xx
# response (a fresh install legitimately 302-redirects to the install wizard).
#
# Usage: healthcheck.sh <URL> [RETRIES] [DELAY] [COMPOSE_SERVICE]
#   URL              URL to probe. On the host use http://localhost:8080;
#                    inside a container use http://localhost/.
#   RETRIES          number of attempts            (default: 30)
#   DELAY            seconds between attempts       (default: 2)
#   COMPOSE_SERVICE  if set, curl runs *inside* this compose service via
#                    `docker compose exec` — for production, where no host port
#                    is published. If empty, curl runs on the host.
set -euo pipefail

URL="${1:?Usage: healthcheck.sh <URL> [retries] [delay] [compose-service]}"
RETRIES="${2:-30}"
DELAY="${3:-2}"
SERVICE="${4:-}"

probe() {
  if [ -n "$SERVICE" ]; then
    docker compose exec -T "$SERVICE" curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL"
  else
    curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL"
  fi
}

attempt=1
while [ "$attempt" -le "$RETRIES" ]; do
  status="$(probe 2>/dev/null || true)"
  case "$status" in
    2[0-9][0-9] | 3[0-9][0-9])
      echo "Healthy: $URL returned HTTP $status (attempt $attempt/$RETRIES)"
      exit 0
      ;;
  esac
  echo "Waiting for WordPress at $URL — got '${status:-no response}' (attempt $attempt/$RETRIES)"
  attempt=$((attempt + 1))
  sleep "$DELAY"
done

echo "Health check FAILED: $URL never returned a healthy HTTP status" >&2
exit 1
