#!/usr/bin/env bash
# Import a Duplicator package into a running WordPress container.
# Run this on the server after setup-server.sh and completing the initial WP install.
#
# Usage: ./scripts/import-duplicator.sh <installer.php> <archive.zip>
# Example: ./scripts/import-duplicator.sh installer.php 20260320_site_archive.zip
#
# IMPORTANT NOTES:
# - Complete the WordPress install wizard FIRST (use throwaway values - Duplicator overwrites everything)
# - Duplicator files must be on the server filesystem (scp them from your local machine)
# - In the Duplicator wizard, use these DB settings:
#     Host: mysql        (NOT localhost — containers use Docker DNS)
#     Name: wordpress
#     User: root
#     Password: (from .env → MYSQL_ROOT_PASSWORD)
# - Duplicator writes its own wp-config.php. The container rewrites it from the compose
#   files at every start, keeping the secret keys and the imported site's table prefix
#   (docker/openlitespeed/make-wp-config.php) — anything else Duplicator put there is
#   dropped. Put lasting settings in WORDPRESS_CONFIG_EXTRA.
# - After the import, re-save Settings → Permalinks (or run
#   `docker compose exec -u www-data wordpress wp rewrite flush --hard`) so .htaccess
#   gets the permalink rules OpenLiteSpeed reads.

set -euo pipefail

INSTALLER="${1:?Usage: import-duplicator.sh <installer.php> <archive.zip>}"
ARCHIVE="${2:?Usage: import-duplicator.sh <installer.php> <archive.zip>}"

if [ ! -f "$INSTALLER" ]; then
  echo "Error: $INSTALLER not found" >&2
  exit 1
fi

if [ ! -f "$ARCHIVE" ]; then
  echo "Error: $ARCHIVE not found" >&2
  exit 1
fi

echo "Fixing wp-content permissions..."
docker compose exec -T wordpress chown -R www-data:www-data /var/www/html/wp-content

echo "Copying Duplicator files into WordPress container..."
docker compose cp "$INSTALLER" wordpress:/var/www/html/
docker compose cp "$ARCHIVE" wordpress:/var/www/html/

echo ""
echo "=== Files copied ==="
echo "Now open the Duplicator installer in your browser:"
echo "  https://<your-domain>/installer.php"
echo ""
echo "Database settings for Duplicator:"
echo "  Host:     mysql    (NOT localhost)"
echo "  Name:     wordpress"
echo "  User:     root"
echo "  Password: see MYSQL_ROOT_PASSWORD in $(pwd)/.env"
echo "            (e.g. grep MYSQL_ROOT_PASSWORD .env)"
echo ""
