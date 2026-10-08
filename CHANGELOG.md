# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Upgrading a site already deployed from the 1.0.0 (Apache) template

The first deploy of this version changes who deploys, what the container is called, and
who owns its files. Do these in order; root stays a working fallback until the end.

**Before the deploy** (on the server, as root, in `/opt/apps/<site>`):

1. **Table prefix.** The first OpenLiteSpeed start is on an empty `wp-html` volume — the
   old container's `wp-config.php` and `.htaccess` lived in the container. If the site's
   prefix is not `wp_` (common after a Duplicator import — check `$table_prefix` in the
   running container's `wp-config.php`), add `WORDPRESS_TABLE_PREFIX: <prefix>` to the
   `wordpress` environment in `docker-compose.production.yml`. Without it WordPress sees
   an empty database and shows the install wizard — which the health check counts as
   healthy.
2. **The `deploy` user.** `useradd --create-home --shell /bin/bash deploy`,
   `usermod -aG docker deploy`, `chown -R deploy:deploy /opt/apps/<site>`. Give it read
   access to the repo (the GitHub deploy key and its `~/.ssh/config` alias, moved to
   `/home/deploy/.ssh/`), and the CI key:
   `grep github-actions /root/.ssh/authorized_keys >> /home/deploy/.ssh/authorized_keys`.
   Verify as that user: `su - deploy -c 'cd /opt/apps/<site> && git pull && docker compose ps'`.
   Leave root's `authorized_keys` alone until every site deploys green.
3. **Host-key pin.** Add the `DEPLOY_HOST_FINGERPRINT` secret — the server's **ECDSA**
   fingerprint: `ssh-keygen -lf /etc/ssh/ssh_host_ecdsa_key.pub` (the deploy action is a
   Go SSH client, which negotiates ECDSA). Without it the deploy job now fails on
   purpose.
4. **Volume ownership** — chown first, deploy second. The container now runs as
   `www-data` (uid 33) and cannot write a root-owned volume; the running old container is
   unaffected by the chown:
   `docker run --rm -v <site>_wp-uploads:/u alpine chown -R 33:33 /u`.

**The deploy** — push. The containers are recreated as `<site>-web` / `<site>-db`
(service names are unchanged, so no orphan clean-up is needed).

**Right after the deploy:**

5. **Reverse proxy:** point the site's proxy host at `<site>-web` port 80 (it targeted
   `<site>-wordpress`). The public site answers 502 until this is done.
6. Write the permalink rules: `docker compose exec wordpress wp rewrite flush --hard`
   (applied within ~5 s), then load the public URL and confirm 200.
7. Expect everyone to be logged out once (new secret keys); after that they are kept.

**Rollback:** set the repository variable `DEPLOY_USER=root`, revert the commit and push
(or on the server: `git checkout <previous> && docker compose up -d --build
--force-recreate`), and point the proxy back at `<site>-wordpress`.

**Local development stacks** from 1.0.0: the database volume was created with the old
fixed local password. Before the first `./dev.sh up`, put `MYSQL_ROOT_PASSWORD=` with that
old value (from the 1.0.0 `docker-compose.yml`) in `.env` to keep the volume — or let
`dev.sh up` generate a new one and run `./dev.sh reset` (which deletes the local
database).

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
  also checks the page cache, permalinks via `.htaccess`, restarts, core sync, and
  the hardening below.
- **Nothing runs as root**: OpenLiteSpeed, lsphp, the entrypoint and WP-CLI run as
  `www-data` (`USER` in the image; Docker lets it bind :80). The image no longer uses
  the base image's root-only `/entrypoint.sh`.
- **Read-only container**: `read_only: true`, with every measured write path a volume
  (`wp-html`, `wp-uploads`, `ols-logs`, `ols-cache`) or a sized tmpfs. OpenLiteSpeed's
  configuration is copied from the image into a tmpfs at every start.
- **A changed `.htaccess` is applied automatically**: OpenLiteSpeed only reads it at
  start, so the entrypoint restarts it gracefully within ~5 s of a change (permalink
  saves, LiteSpeed Cache's rules). `docker stop` now stops it cleanly instead of being
  killed after 10 s.
- **Containers are named in the base file**, `<project>-web` and `<project>-db` (were
  `<project>-wordpress` / `<project>-mysql`, production only). The proxy targets
  `<project>-web:80`.
- **No committed database password**: `MYSQL_ROOT_PASSWORD` comes from `.env`;
  `dev.sh`/`dev.bat` generate it locally, `setup-server.sh` on a server. Scripts run
  the mysql client inside the mysql container, which already holds it.
- **Deploy gated, non-root, host key pinned**: the deploy job moved into `ci.yml` and
  runs only after the check jobs pass (`deploy.yml` is gone); it logs in as `deploy`
  (created by `setup-server.sh`) and requires `DEPLOY_HOST_FINGERPRINT`. CI no longer
  cancels a run on `master` when a newer push arrives.
- Production sets `DISALLOW_FILE_MODS`: themes and plugins come from git and are not
  writable by WordPress there.
- `wp` is now the image's pinned, checksum-verified WP-CLI: the base image's `PATH`
  put its own `/usr/bin/wp` first.
- Upgraded the base image to **WordPress 7.1** (from 7.0); MySQL 8.4 LTS is
  unchanged.
- The image `HEALTHCHECK` now uses exec (JSON) form, as Hadolint DL3025 requires
  (flagged once the Hadolint action was bumped to 3.5.0); behaviour is unchanged.
- **Every dependency is pinned to one exact release** (engineering-standards pack
  2026.10.08-2): images to exact tags (`wordpress:7.1.3-php8.5-fpm`, `mysql:8.4.11`,
  `rhysd/actionlint:1.7.12`), actions to commit SHAs with the version beside them — the
  same releases they resolved to, nothing upgraded. Dependabot now also watches the
  compose files (`docker-compose` ecosystem).
- **The deploy pulls before it builds** (`docker compose pull --ignore-buildable`, then
  `build --pull`), so a server fetches a newly pinned tag and same-tag security rebuilds;
  the rollback stays unpulled. See PUBLISH_NOTES.md.
- CI installs its test tools from `engineering_standards/requirements.txt` (ruff 0.16.10,
  pytest 9.1.1) instead of versions typed into the workflow.

### Fixed

- `WORDPRESS_DEBUG: "false"` in production turned `WP_DEBUG` **on** (the official
  image treats any non-empty value as true); it is now parsed as a boolean.
- A deploy (`--force-recreate`) no longer logs everyone out: the secret keys used
  to be regenerated with every new container.
- `tests/smoke.sh` ran under the dev stack's project name, so its closing
  `down -v` deleted the local development database.
- `dev.bat cli` passed the word `cli` on to WP-CLI.
- Line endings are pinned in `.gitattributes`: a clone without `core.autocrlf=true`
  checked the batch files out LF-only, where cmd can miss their labels.

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
