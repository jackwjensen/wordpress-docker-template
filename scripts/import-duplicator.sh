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
#   `docker compose exec wordpress wp rewrite flush --hard`) so .htaccess gets the permalink
#   rules; the container restarts OpenLiteSpeed gracefully to apply them.

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

# Duplicator extracts the site's themes and plugins into wp-content, which on a server is
# bind-mounted from the deploy user's checkout. The container runs as www-data, so hand
# wp-content to it for the import (-u root: www-data cannot chown files it does not own).
echo "Giving wp-content to www-data for the import..."
docker compose exec -T -u root wordpress chown -R www-data:www-data /var/www/html/wp-content

# Streamed in through exec rather than `docker compose cp`: the container's root filesystem is
# read-only, and this writes into the wp-html volume as www-data.
# The target path goes in as an argument ($1), never spliced into the shell string, so a
# filename with spaces or quotes cannot change the command.
copy_into_docroot() {
  local source_file="$1" target_path
  target_path="/var/www/html/$(basename "$source_file")"
  docker compose exec -T wordpress sh -c 'cat > "$1"' sh "$target_path" < "$source_file"
}
echo "Copying Duplicator files into WordPress container..."
copy_into_docroot "$INSTALLER"
copy_into_docroot "$ARCHIVE"

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
echo "After the import:"
echo "  1. Write the permalink rules (the container applies them within seconds):"
echo "       docker compose exec wordpress wp rewrite flush --hard"
echo "  2. Commit wp-content/themes and wp-content/plugins, then give them back to this"
echo "     checkout's owner so the deploy's git pull can write them again:"
echo "       docker compose exec -T -u root wordpress chown -R $(id -u):$(id -g) \\"
echo "         /var/www/html/wp-content/themes /var/www/html/wp-content/plugins"
echo ""
