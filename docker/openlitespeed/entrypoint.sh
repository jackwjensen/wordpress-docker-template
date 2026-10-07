#!/usr/bin/env bash
#
# Container start for the OpenLiteSpeed WordPress image:
#   1. WordPress core in the wp-html volume is installed, or upgraded when the image is newer
#   2. wp-config.php is (re)written from the WORDPRESS_* environment
#   3. the base image's entrypoint starts OpenLiteSpeed and keeps the container alive
set -euo pipefail

WP_ROOT=/var/www/html
WP_SRC=/usr/src/wordpress

# $wp_version from a core tree's wp-includes/version.php. (The PHP code is single-quoted on
# purpose: $argv and $wp_version are PHP's, not the shell's.)
wp_version() {
  # shellcheck disable=SC2016
  php -r 'include $argv[1]; echo $wp_version;' "$1/wp-includes/version.php"
}

# 1. The volume keeps core, wp-config.php (its secret keys) and .htaccess (permalinks and
#    LiteSpeed Cache's rules) across deploys. Core still follows the image: a newer image
#    replaces core's own files; wp-content, wp-config.php and .htaccess are never touched, and
#    a volume that is newer than the image (WordPress updated itself) is never downgraded.
#    cp -a keeps www-data as owner (set in the Dockerfile).
if [ ! -e "$WP_ROOT/wp-includes/version.php" ]; then
  echo "WordPress core not found in $WP_ROOT — copying it from the image"
  cp -a "$WP_SRC/." "$WP_ROOT/"
else
  image_version="$(wp_version "$WP_SRC")"
  installed_version="$(wp_version "$WP_ROOT")"
  # shellcheck disable=SC2016  # PHP's $argv, single-quoted on purpose
  if php -r 'exit(version_compare($argv[1], $argv[2], ">") ? 0 : 1);' "$image_version" "$installed_version"; then
    echo "Upgrading WordPress core $installed_version → $image_version from the image"
    for entry in "$WP_SRC"/*; do
      name="$(basename "$entry")"
      [ "$name" = wp-content ] && continue
      rm -rf "${WP_ROOT:?}/$name"
      cp -a "$entry" "$WP_ROOT/"
    done
  fi
fi

# 2. lsphp cannot read the environment, so the configuration is written into the file.
php /usr/local/lib/wordpress-docker/make-wp-config.php

# 3. Starts lswsctrl, runs "$@" (nothing), then waits while the server runs.
exec /entrypoint.sh "$@"
