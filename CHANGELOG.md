# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Upgrading a site already deployed from the Apache template

The first deploy with OpenLiteSpeed starts on an empty `wp-html` volume: the old
container's `wp-config.php` and `.htaccess` are gone (they lived in the container,
not a volume). Before that deploy:

1. If the site's table prefix is not `wp_` (common after a Duplicator import —
   check `$table_prefix` in the running container's `wp-config.php`), add
   `WORDPRESS_TABLE_PREFIX: <prefix>` to the `wordpress` environment in
   `docker-compose.production.yml`. Without it WordPress sees an empty database and
   shows the install wizard — and the deploy health check counts that as healthy.
2. After the deploy, write the permalink rules again:
   `docker compose exec -u www-data wordpress wp rewrite flush --hard`.
3. Expect everyone to be logged out once (new secret keys); after that they are
   kept across deploys.

### Changed

- **Web server: OpenLiteSpeed instead of Apache** — one container built on
  `litespeedtech/openlitespeed:1.9.2-lsphp85` (PHP 8.5, from 8.4), with WordPress
  core from the official `wordpress:7.1-php8.5-fpm` image. The LiteSpeed Cache
  plugin's page cache only works on a LiteSpeed server; README, "Page cache:
  LiteSpeed Cache", covers setup, WooCommerce's REST API cache, and moving off
  W3 Total Cache / WP Rocket. Carried over from the Ellengaard site's move.
- `wp-config.php` is written at every container start from the `WORDPRESS_*`
  variables (lsphp cannot read the environment), keeping the secret keys and the
  table prefix.
- WordPress core, `wp-config.php` and `.htaccess` live in a new `wp-html` volume;
  the entrypoint upgrades core from a newer image and never downgrades it.
- Local dev publishes `8080:8080` (OpenLiteSpeed listens on 8080 as well as 80),
  so WordPress's loopback requests reach the container.
- WP-CLI is built into the image (`dev.sh cli <command>`, also in production);
  the separate `wpcli` service is gone.
- `dev.sh logs` follows OpenLiteSpeed's log files.
- Local MySQL is published on `127.0.0.1:3307` (was `3306` on every interface),
  and the local stack has no restart policy any more — Allegro IT's dev port
  registry. Production is unchanged: no published ports, `restart: unless-stopped`.
- `tests/smoke.sh` runs as its own Compose project with no published ports, and
  also checks the page cache, permalinks via `.htaccess`, restarts and core sync.
- Upgraded the base image to **WordPress 7.1** (from 7.0); MySQL 8.4 LTS is
  unchanged.
- The image `HEALTHCHECK` now uses exec (JSON) form, as Hadolint DL3025 requires
  (flagged once the Hadolint action was bumped to 3.5.0); behaviour is unchanged.

### Fixed

- `WORDPRESS_DEBUG: "false"` in production turned `WP_DEBUG` **on** (the official
  image treats any non-empty value as true); it is now parsed as a boolean.
- A deploy (`--force-recreate`) no longer logs everyone out: the secret keys used
  to be regenerated with every new container.
- `tests/smoke.sh` ran under the dev stack's project name, so its closing
  `down -v` deleted the local development database.
- `dev.bat cli` passed the word `cli` on to WP-CLI.

## [1.0.0] - 2026-06-22

First public release: a polished, clone-and-own WordPress Docker template. (The
project was renamed from `wp_image` to `wordpress-docker-template` for this
release.)

### Added
- Thin `Dockerfile` (`FROM wordpress:7.0-php8.4-apache`) that bakes in the PHP
  upload limits and adds a container `HEALTHCHECK`.
- CI workflow (`ci.yml`): ShellCheck, Hadolint, Compose validation, actionlint,
  a build + smoke test, and a health-check regression test — on every push/PR.
- Release workflow (`release.yml`): on a `v*` tag, build and publish the image to
  GHCR using the built-in `GITHUB_TOKEN` (keyless — no stored secret), with a
  build-provenance attestation and an auto-generated GitHub Release.
- Shared `scripts/healthcheck.sh`, plus `tests/smoke.sh` and
  `tests/healthcheck.test.sh`.
- Dependabot (grouped, monthly) for the `docker` and `github-actions` ecosystems.
- Community-health files: SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, issue/PR
  templates, CODEOWNERS, and `.editorconfig`.
- "Make it your own" guide: detach onto your own account, and/or track this repo
  as an `upstream` remote to pull future template improvements.
- Tasteful Allegro IT attribution and a soft "Need a hand?" CTA in the README.

### Changed
- Upgraded the stack to **WordPress 7.0 + PHP 8.4** (from 6.7 + PHP 8.3); MySQL
  stays on **8.4 LTS**.
- Production deploy now verifies WordPress **serves HTTP** instead of counting
  "running" containers, and rebuilds the image (`docker compose up --build`).
- Generalised the docs for public clone-and-own use: a vendor-neutral "deploy to
  any Docker VPS behind a reverse proxy" guide (Allegro IT's Hetzner + Nginx Proxy
  Manager setup kept as a labelled example), with vendor-neutral deploy secrets
  `DEPLOY_HOST` / `DEPLOY_SSH_KEY` (optional `DEPLOY_USER` / `DEPLOY_PATH`).
- Deploy runs only when `DEPLOY_HOST` is configured, so a fresh clone never
  produces a failing deploy; configuring the secret activates it.
- Hardened the shell scripts (`set -euo pipefail`, quoting, `MYSQL_PWD` instead
  of passwords on the command line, `MSYS_NO_PATHCONV` in `dev.sh`).
- CI and release smoke-test jobs retry to ride out transient Docker Hub pull
  rate-limits on shared runners.
- Pinned all GitHub Actions to current released versions.

### Fixed
- Deploy health check no longer reports success when WordPress is up but
  returning HTTP 500 (e.g. the database is unreachable).
