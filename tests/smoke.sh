#!/usr/bin/env bash
#
# End-to-end smoke test: build the image, bring up the stack, and assert the
# real artifact works. Runs in CI (build-and-smoke job) and locally.
#
#   1. OpenLiteSpeed serves HTTP on :8080 and :80   (via the shared healthcheck)
#   2. Baked-in PHP upload limit active, in lsphp   (proves the Dockerfile COPY shipped)
#   3. LiteSpeed's page cache works                 (X-LSCACHE set, a cacheable response hits)
#   4. WordPress installs and reaches MySQL         (WP-CLI in the image)
#   5. Permalinks via .htaccess                     (wp rewrite flush --hard, pretty URL serves)
#   6. A restart keeps the secret keys and an imported table prefix; WORDPRESS_DEBUG=false is off
#   7. Core follows the image: an older core is upgraded, a newer one never downgraded
#   8. Hardening: the server, lsphp and WP-CLI run as www-data, the root filesystem is read-only,
#      and `wp` is the image's pinned WP-CLI, not the base image's own copy
#
# Runs as its own Compose project (`wordpress-smoke`) with no published ports
# (tests/docker-compose.smoke.yml), probing from inside the container — so it never touches the
# dev stack's volumes and never needs host port 8080.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Windows/Git Bash: don't mangle compose volume paths

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

URL="http://localhost:8080"
# Exported rather than passed as -p/-f, so scripts/healthcheck.sh's own `docker compose exec`
# reaches the same project. They override a COMPOSE_* in .env.
export COMPOSE_PROJECT_NAME=wordpress-smoke
export COMPOSE_PATH_SEPARATOR=:
export COMPOSE_FILE=docker-compose.yml:tests/docker-compose.smoke.yml
# A fresh password per run, for a database that lives only as long as the test.
MYSQL_ROOT_PASSWORD="smoke-$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
export MYSQL_ROOT_PASSWORD
COMPOSE=(docker compose)

cleanup() { "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
in_wp() { "${COMPOSE[@]}" exec -T wordpress "$@"; }
wp() { "${COMPOSE[@]}" exec -T wordpress wp "$@"; }
# shellcheck disable=SC2016  # PHP's $wp_version, single-quoted on purpose
installed_version() { in_wp php -r 'include "/var/www/html/wp-includes/version.php"; echo $wp_version;'; }
restart_wp() {
  "${COMPOSE[@]}" restart wordpress >/dev/null
  bash scripts/healthcheck.sh "$URL/" 45 2 wordpress >/dev/null
}

echo "==> Building image and starting the stack"
"${COMPOSE[@]}" up -d --build

echo "==> Waiting for WordPress to serve HTTP (:8080 local, :80 production)"
bash scripts/healthcheck.sh "$URL/" 45 2 wordpress
bash scripts/healthcheck.sh "http://localhost/" 5 2 wordpress

echo "==> Asserting the web server is LiteSpeed"
in_wp curl -sI "$URL/" | grep -qi '^server: litespeed' || fail "no 'Server: LiteSpeed' header"

echo "==> Asserting nothing runs as root, the root filesystem is read-only, and wp is pinned"
root_processes="$(in_wp ps -eo user=,args= | grep -E 'openlitespeed|lsphp' | grep -v '^www-data' || true)"
[ -z "$root_processes" ] || fail "OpenLiteSpeed or lsphp running as another user than www-data: $root_processes"
in_wp sh -c 'touch /usr/local/lsws/smoke-write 2>/dev/null' && fail "the container's root filesystem is writable"
[ "$(in_wp sh -c 'command -v wp')" = "/usr/local/bin/wp" ] || fail "wp is not the image's pinned /usr/local/bin/wp"

echo "==> Asserting baked-in PHP upload_max_filesize is 256M (CLI and lsphp)"
limit="$(in_wp php -r 'echo ini_get("upload_max_filesize");' | tr -d '[:space:]')"
[ "$limit" = "256M" ] || fail "CLI upload_max_filesize is '$limit', expected '256M'"

# A throwaway PHP page that asks LiteSpeed to cache it, as the LiteSpeed Cache plugin does.
in_wp sh -c 'cat > /var/www/html/smoke-probe.php' <<'PHP'
<?php
header( 'X-LiteSpeed-Cache-Control: public,max-age=60' );
echo ini_get( 'upload_max_filesize' ), '|', $_SERVER['X-LSCACHE'] ?? '', '|', microtime( true );
PHP
probe="$(in_wp curl -fsS "$URL/smoke-probe.php")"
[ "${probe%%|*}" = "256M" ] || fail "lsphp upload_max_filesize is '${probe%%|*}', expected '256M'"

echo "==> Asserting LiteSpeed's page cache is available and serves hits"
lscache="$(printf '%s' "$probe" | cut -d'|' -f2)"
case "$lscache" in on*) ;; *) fail "X-LSCACHE is '$lscache' — LiteSpeed Cache would not cache" ;; esac
in_wp curl -fsS -D - -o /dev/null "$URL/smoke-probe.php" | grep -qi '^x-litespeed-cache: hit' \
  || fail "the second request for a cacheable page was not a cache hit"
in_wp rm -f /var/www/html/smoke-probe.php

echo "==> Asserting WordPress can reach the database (install page, then a WP-CLI install)"
install_html="$(in_wp curl -fsSL "$URL/wp-admin/install.php" || true)"
printf '%s' "$install_html" | grep -qi "Error establishing a database connection" \
  && fail "WordPress cannot reach the database"
printf '%s' "$install_html" | grep -qi "wordpress" || fail "install page did not render as expected"
wp core install --url="$URL" --title=Smoke --admin_user=smoke \
  --admin_password="$(head -c 18 /dev/urandom | base64)" --admin_email=smoke@example.com --skip-email --quiet

echo "==> Asserting permalinks work through .htaccess, and a changed .htaccess is applied"
# OpenLiteSpeed keeps the .htaccess it loaded until it restarts; the entrypoint's watcher
# restarts it gracefully within ~5 s of a change. Wait for that, never for a fixed sleep.
status_within() { # <path> <expected status> -> succeeds once the path answers that status
  local tries=0 status=""
  while [ "$tries" -lt 20 ]; do
    status="$(in_wp curl -s -o /dev/null -w '%{http_code}' "$URL$1")"
    [ "$status" = "$2" ] && return 0
    tries=$((tries + 1)); sleep 1
  done
  echo "$1 answered HTTP $status, expected $2" >&2; return 1
}
# The docroot has been served without an .htaccess by now (health checks, the install), so
# this also proves a NEW .htaccess is picked up, not only one present at start.
wp rewrite structure '/%postname%/' --hard --quiet
in_wp grep -q 'BEGIN WordPress' /var/www/html/.htaccess || fail "wp rewrite flush --hard wrote no .htaccess rules"
status_within /hello-world/ 200 || fail "pretty permalink /hello-world/ never served (new .htaccess not applied)"
# An edit to the now-loaded file, ahead of WordPress's catch-all rule.
in_wp sh -c '{ printf "RewriteEngine On\nRewriteRule ^smoke-redirect$ / [R=302,L]\n"; cat /var/www/html/.htaccess; } > /tmp/smoke.htaccess && cat /tmp/smoke.htaccess > /var/www/html/.htaccess'
status_within /smoke-redirect 302 || fail "an edited .htaccess was never applied"

echo "==> Asserting a restart keeps the secret keys and an imported table prefix"
keys_before="$(in_wp grep "'AUTH_KEY'" /var/www/html/wp-config.php)"
# As if Duplicator had imported a site with its own prefix.
in_wp sed -i "s/^\$table_prefix = 'wp_';/\$table_prefix = 'dup_';/" /var/www/html/wp-config.php
restart_wp
[ "$(in_wp grep "'AUTH_KEY'" /var/www/html/wp-config.php)" = "$keys_before" ] || fail "restart changed the secret keys"
in_wp grep -q "^\$table_prefix = 'dup_';" /var/www/html/wp-config.php || fail "restart reset the imported table prefix"
in_wp sed -i "s/^\$table_prefix = 'dup_';/\$table_prefix = 'wp_';/" /var/www/html/wp-config.php
in_wp grep -q "define( 'WP_DEBUG', true );" /var/www/html/wp-config.php || fail "WORDPRESS_DEBUG=true did not switch WP_DEBUG on"
"${COMPOSE[@]}" exec -T -e WORDPRESS_DEBUG=false wordpress php /usr/local/lib/wordpress-docker/make-wp-config.php >/dev/null
in_wp grep -q "define( 'WP_DEBUG', false );" /var/www/html/wp-config.php || fail "WORDPRESS_DEBUG=false left WP_DEBUG on"

echo "==> Asserting core follows the image (upgrade, never downgrade)"
image_version="$(installed_version)"
in_wp sed -i "s/^\$wp_version = .*/\$wp_version = '1.0';/" /var/www/html/wp-includes/version.php
restart_wp
[ "$(installed_version)" = "$image_version" ] || fail "an older core was not upgraded to the image's $image_version"
in_wp sed -i "s/^\$wp_version = .*/\$wp_version = '99.0';/" /var/www/html/wp-includes/version.php
restart_wp
[ "$(installed_version)" = "99.0" ] || fail "a newer core was downgraded to the image's"
in_wp grep -q 'BEGIN WordPress' /var/www/html/.htaccess || fail "a restart lost .htaccess"

echo "PASS: smoke test succeeded (LiteSpeed + page cache, upload limit, WordPress + DB, permalinks, restart, core sync)"
