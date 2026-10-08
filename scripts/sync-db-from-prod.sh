#!/usr/bin/env bash
# Pull production database to local development.
# Usage: ./scripts/sync-db-from-prod.sh <site-name> [prod-domain] [local-url]
# Example: ./scripts/sync-db-from-prod.sh my-wp-site example.com http://localhost:8080
#
# NOTE: This script requires the DEPLOY_HOST env var and SSH access to the server.
# On Windows, use sync-db-from-prod.bat instead, or run the manual steps from CLAUDE.md.
#
# CAVEAT: the URL search-replace below uses raw MySQL REPLACE(), which is NOT
# serialization-aware. If a plugin stores serialized data that embeds the domain
# and the replacement changes the string length, that row can be corrupted. For
# sites with heavy serialized option/meta data, skip the prod-domain argument and
# use WP-CLI in the image instead:
#   ./dev.sh cli search-replace 'https://example.com' 'http://localhost:8080' --all-tables

set -euo pipefail

# Runs a client inside the LOCAL mysql container, which already holds the password in its own
# environment (from .env) — so it never passes through this script or the process argv.
in_local_mysql() { docker compose exec -T mysql sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" exec mysql -uroot wordpress"; }

SITE_NAME="${1:?Usage: sync-db-from-prod.sh <site-name> [prod-domain] [local-url]}"
PROD_DOMAIN="${2:-}"
LOCAL_URL="${3:-http://localhost:8080}"
SERVER="${DEPLOY_HOST:?Set DEPLOY_HOST env var}"
REMOTE_DIR="/opt/apps/${SITE_NAME}"

# Guard: a domain must look like a domain. The value is interpolated into SQL
# below, so reject anything with quotes/metacharacters up front.
if [ -n "$PROD_DOMAIN" ] && ! printf '%s' "$PROD_DOMAIN" | grep -Eq '^[A-Za-z0-9.-]+$'; then
  echo "Error: prod-domain '$PROD_DOMAIN' contains unexpected characters" >&2
  exit 1
fi

mkdir -p backups

echo "Dumping production database..."
# REMOTE_DIR expands locally (intended); the password lookup runs on the server.
# shellcheck disable=SC2029
ssh "root@${SERVER}" "cd ${REMOTE_DIR} && MYSQL_PWD=\$(grep MYSQL_ROOT_PASSWORD .env | cut -d= -f2) docker compose exec -T -e MYSQL_PWD mysql mysqldump -uroot wordpress" > backups/prod_sync.sql

echo "Importing into local database..."
in_local_mysql < backups/prod_sync.sql

if [ -n "$PROD_DOMAIN" ]; then
  echo "Replacing URLs: ${PROD_DOMAIN} -> ${LOCAL_URL}"
  in_local_mysql <<SQL
UPDATE wp_options  SET option_value = REPLACE(option_value, 'https://${PROD_DOMAIN}', '${LOCAL_URL}') WHERE option_value LIKE '%${PROD_DOMAIN}%';
UPDATE wp_options  SET option_value = REPLACE(option_value, 'http://${PROD_DOMAIN}',  '${LOCAL_URL}') WHERE option_value LIKE '%${PROD_DOMAIN}%';
UPDATE wp_posts    SET post_content = REPLACE(post_content, 'https://${PROD_DOMAIN}', '${LOCAL_URL}') WHERE post_content LIKE '%${PROD_DOMAIN}%';
UPDATE wp_posts    SET guid         = REPLACE(guid,         'https://${PROD_DOMAIN}', '${LOCAL_URL}') WHERE guid LIKE '%${PROD_DOMAIN}%';
UPDATE wp_postmeta SET meta_value   = REPLACE(meta_value,   'https://${PROD_DOMAIN}', '${LOCAL_URL}') WHERE meta_value LIKE '%${PROD_DOMAIN}%';
SQL
fi

# The container runs as www-data; -u root, because uploads from an older stack may still be
# root-owned.
echo "Fixing uploads permissions..."
docker compose exec -T -u root wordpress chown -R www-data:www-data /var/www/html/wp-content/uploads

echo "Done! Local DB is now a copy of production."
