#!/usr/bin/env bash
#
# Container start for the OpenLiteSpeed WordPress image. Runs as www-data (the image's USER):
#   1. WordPress core in the wp-html volume is installed, or upgraded when the image is newer
#   2. wp-config.php is (re)written from the WORDPRESS_* environment
#   3. OpenLiteSpeed starts, and this script waits while it runs
#
# Not the base image's /entrypoint.sh: that one chowns OpenLiteSpeed's config to lsadm, which
# needs root. The Dockerfile already gives those directories to www-data.
set -euo pipefail

WP_ROOT=/var/www/html
WP_SRC=/usr/src/wordpress
LSWSCTRL=/usr/local/lsws/bin/lswsctrl

# $wp_version from a core tree's wp-includes/version.php. (The PHP code is single-quoted on
# purpose: $argv and $wp_version are PHP's, not the shell's.)
wp_version() {
  # shellcheck disable=SC2016
  php -r 'include $argv[1]; echo $wp_version;' "$1/wp-includes/version.php"
}

# Core's own files from the image: everything except wp-content. wp-config.php and .htaccess
# are not in the image's tree, so they are never touched.
install_core_files() {
  local entry name
  for entry in "$WP_SRC"/*; do
    name="$(basename "$entry")"
    [ "$name" = wp-content ] && continue
    rm -rf "${WP_ROOT:?}/$name"
    cp -a "$entry" "$WP_ROOT/"
  done
}

# WordPress's default wp-content (index.php, the default theme and plugins), never overwriting
# anything. A directory this user cannot write -- a bind mount of a git checkout owned by the
# deploy user -- is skipped and said so: there the site's own committed themes and plugins
# are the content.
seed_wp_content() {
  local entry name target
  mkdir -p "$WP_ROOT/wp-content"
  for entry in "$WP_SRC"/wp-content/*; do
    name="$(basename "$entry")"
    target="$WP_ROOT/wp-content/$name"
    if [ ! -d "$entry" ]; then
      [ -e "$target" ] || cp -a "$entry" "$target"
    elif [ -w "$target" ] || { [ ! -e "$target" ] && mkdir -p "$target"; }; then
      cp -a --update=none "$entry/." "$target/"
    else
      echo "Not seeding WordPress's default wp-content/$name: $target is not writable by $(id -un)"
    fi
  done
}

# 1. The volume keeps core, wp-config.php (its secret keys) and .htaccess (permalinks and
#    LiteSpeed Cache's rules) across deploys. Core still follows the image: a newer image
#    replaces core's own files, and a volume that is newer than the image (WordPress updated
#    itself) is never downgraded.
if [ ! -e "$WP_ROOT/wp-includes/version.php" ]; then
  echo "WordPress core not found in $WP_ROOT — installing it from the image"
  install_core_files
  seed_wp_content
else
  image_version="$(wp_version "$WP_SRC")"
  installed_version="$(wp_version "$WP_ROOT")"
  # shellcheck disable=SC2016  # PHP's $argv, single-quoted on purpose
  if php -r 'exit(version_compare($argv[1], $argv[2], ">") ? 0 : 1);' "$image_version" "$installed_version"; then
    echo "Upgrading WordPress core $installed_version → $image_version from the image"
    install_core_files
  fi
fi

# 2. lsphp cannot read the environment, so the configuration is written into the file.
php /usr/local/lib/wordpress-docker/make-wp-config.php

# 3. OpenLiteSpeed's configuration from the image (conf/ and admin/conf/ are tmpfs in the
#    read-only container; see the Dockerfile). The page cache starts empty, as it did when it
#    lived in the container layer: cached pages from the previous deploy could point at assets
#    that deploy replaced.
cp -a /usr/local/lsws/conf.image/. /usr/local/lsws/conf/
cp -a /usr/local/lsws/admin/conf.image/. /usr/local/lsws/admin/conf/
find /usr/local/lsws/cachedata -mindepth 1 -delete

"$LSWSCTRL" start
# docker stop sends SIGTERM to this script (PID 1), which bash otherwise ignores until Docker
# kills the container 10 s later. Stop the server cleanly instead. `sleep & wait` lets the
# trap run at once rather than after the current sleep.
trap '"$LSWSCTRL" stop; exit 0' TERM INT

# 4. OpenLiteSpeed reads a directory's .htaccess once and keeps it until it restarts — a new or
#    edited file is ignored (measured 2026-10-08; LiteSpeed Enterprise re-reads, OpenLiteSpeed
#    does not). WordPress (Settings → Permalinks) and LiteSpeed Cache write .htaccess at
#    runtime, so this loop restarts the server gracefully whenever one changes. Watched: the
#    docroot two levels down plus the top of uploads — a set bounded by WordPress core's own
#    tree, never by the number of uploads. A missing directory (no uploads volume, no uploads
#    yet) is an empty set, not an error that set -e would turn into the container's exit.
htaccess_state() {
  {
    find "$WP_ROOT" -maxdepth 2 -name .htaccess -printf '%p %T@ %s\n' 2>/dev/null || true
    find "$WP_ROOT/wp-content/uploads" -maxdepth 1 -name .htaccess -printf '%p %T@ %s\n' 2>/dev/null || true
  } | sort
}
is_running() { "$LSWSCTRL" status | grep -q 'litespeed is running with PID'; }

htaccess_seen="$(htaccess_state)"
# lswsctrl daemonises; keep the container alive while the server runs, and end it (so Docker
# restarts it) if the server dies. A graceful restart briefly swaps the main process, so a
# failed status is re-checked once before giving up.
while is_running || { sleep 2; is_running; }; do
  sleep 5 &
  wait $!
  htaccess_now="$(htaccess_state)"
  if [ "$htaccess_now" != "$htaccess_seen" ]; then
    echo ".htaccess changed — restarting OpenLiteSpeed gracefully so it applies"
    "$LSWSCTRL" restart
    htaccess_seen="$htaccess_now"
  fi
done
echo "OpenLiteSpeed is no longer running" >&2
exit 1
