---
audience: dev
type: reference
---

# CI, tests, releases and repository contents

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

- **lint**: ShellCheck (scripts, `dev.sh`, tests, `docker/openlitespeed/*.sh`), Hadolint
  (`Dockerfile`), `docker compose config` validation (base + production merge), actionlint, the
  health-check regression test, then the engineering-standards steps: PHP syntax check, the
  pack's scanner tests and `engineering_standards/verify.py --strict`.
- **build-and-smoke**: builds the image and runs `tests/smoke.sh`.
- **deploy** (push to `master` or a manual run, after both jobs above pass): SSH as `deploy`,
  host key pinned, `git pull`, rebuild, health check, roll back on failure. Dormant without the
  `DEPLOY_HOST` secret. A newer push cancels an older run's checks on a pull request, never on
  `master`, so a deploy is never cut off halfway.

## Tests

- `tests/smoke.sh` — end-to-end: build + up, then assert `Server: LiteSpeed` on :8080 and :80;
  OpenLiteSpeed and lsphp running as `www-data`, the root filesystem read-only, `wp` the pinned
  WP-CLI; the upload limit (CLI and lsphp); `X-LSCACHE` + a real `X-LiteSpeed-Cache: hit`; a
  WP-CLI install against MySQL; a pretty permalink through a NEW `.htaccess`, and an EDITED one
  applied (the restart watcher); salts + an imported table prefix surviving a restart;
  `WORDPRESS_DEBUG=false` → off; and core upgraded from the image but never downgraded. It
  generates a throwaway `MYSQL_ROOT_PASSWORD` per run. Runs as Compose project `wordpress-smoke` with no published ports (probes inside
  the container via `COMPOSE_PROJECT_NAME`/`COMPOSE_FILE`), so it never deletes the dev stack's
  volumes and never needs host port 8080 — safe to run locally while another project holds 8080.
- `tests/healthcheck.test.sh` — proves `scripts/healthcheck.sh` fails when WordPress is not
  serving (the old "count running containers" check did not). Fast; no Docker needed.
- `scripts/healthcheck.sh <url> [retries] [delay] [compose-service]` — the single health probe
  shared by the smoke test, the regression test, the deploy workflow and `setup-server.sh`. The
  4th argument curls *inside* a compose service (production publishes no host port).

## Releasing

Push a SemVer tag (`git tag v1.2.0 && git push origin v1.2.0`). `.github/workflows/release.yml`
smoke-tests, then builds and publishes the image to **GHCR**
(`ghcr.io/jackwjensen/wordpress-docker-template`, tags `1.2.0`/`1.2`/`1`/`latest`) using the
built-in `GITHUB_TOKEN` — keyless, no stored secret — attaches a build-provenance attestation,
and drafts a GitHub Release. The GHCR package must be made public once (Packages →
wordpress-docker-template → Package settings) for anonymous pulls.

## Dependency and community hygiene

- **Dependabot** (`.github/dependabot.yml`): grouped, monthly updates for the `docker` (base
  images + compose tags) and `github-actions` ecosystems.
- **Community health**: `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue/PR
  templates, `CODEOWNERS`, `.editorconfig`.

## What is version-controlled

| Path | Tracked | Notes |
|------|---------|-------|
| `wp-content/themes/`, `wp-content/plugins/` | Yes | The site's own code |
| `wp-content/uploads/` | No | Docker volume, synced separately |
| `config/` | Yes | PHP config (upload limits) |
| `Dockerfile`, `docker/openlitespeed/` | Yes | The image: server + vhost config, entrypoint, wp-config.php generator, WP-CLI config |
| `tests/`, `.github/` | Yes | Smoke + regression tests; CI/deploy/release workflows, Dependabot, templates |
| `engineering_standards/`, `.claude/rules/` | Yes | The engineering-standards pack (synced by `/apply-standards`, never edited here) |
<!-- standards: docs-stale-symbol exempt -- backups/ is the gitignored output directory dev.sh backup creates, so git never lists it -->
| `.env`, `backups/` | No | Passwords per environment; local DB dumps |

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Builds the image (OpenLiteSpeed + lsphp 8.5, core from the official image, WP-CLI, uploads.ini, HEALTHCHECK) |
| `docker/openlitespeed/httpd_config.conf` | OpenLiteSpeed server config (www-data, no web admin, :8080 + :80, cache module) |
| `docker/openlitespeed/vhconf.conf` | The virtual host (`.htaccess` rewrites, dotfiles hidden) |
| `docker/openlitespeed/entrypoint.sh` | Container start: core install/upgrade, wp-config.php, then OpenLiteSpeed |
| `docker/openlitespeed/make-wp-config.php` | Writes wp-config.php from `WORDPRESS_*` (keeps salts + table prefix) |
| `docker/openlitespeed/wp-cli.yml`, `wp.sh` | WP-CLI config (`mod_rewrite` → `.htaccess`) and the `wp` wrapper |
| `docker-compose.yml`, `docker-compose.production.yml` | Base + local dev; production overrides |
| `tests/docker-compose.smoke.yml` | Smoke-test overrides (no volumes, no published ports) |
| `.env.example` | Template for `.env` |
| `.github/workflows/ci.yml` | Checks on every push/PR, then the deploy on `master` |
| `.github/workflows/release.yml` | Tag `v*` → GHCR + GitHub Release |
| `config/uploads.ini` | PHP upload limits (256M) |
| `scripts/setup-server.sh` | One-time server setup (clones, creates .env, builds + starts containers, fixes permissions) |
| `scripts/import-duplicator.sh` | Copies Duplicator files into the container |
| `scripts/sync-db-from-prod.sh`, `.bat` | Pull the production DB to local (bash / Windows cmd) |
| `scripts/healthcheck.sh` | Shared HTTP health probe (CI, deploy, setup) |
| `tests/smoke.sh`, `tests/healthcheck.test.sh` | End-to-end smoke test; health-check regression test |
| `dev.bat` / `dev.sh` | Local development helpers |
| `PUBLISH_NOTES.md` | Deploy-time hazards for the next push |
