#!/usr/bin/env bash
#
# `wp` in the image: WP-CLI on lsphp's own PHP, the same build and ini files the site runs on.
# WP-CLI 2.12 predates PHP 8.5; its deprecation notices are hidden, real errors are not.
# Run it as the web server user: docker compose exec -u www-data wordpress wp <command>
exec php -d 'error_reporting=E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED' /usr/local/lib/wp-cli/wp-cli.phar "$@"
