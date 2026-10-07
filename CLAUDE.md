# WordPress Docker Template

Claude context for this repo. It's a clone-and-own template for Dockerised WordPress sites: one OpenLiteSpeed container (WordPress 7.1 + lsphp 8.5, ready for LiteSpeed Cache), MySQL 8.4 LTS, local dev via Docker Compose, CI + GHCR releases, and an optional SSH deploy to any Docker host. The user-facing guide is `README.md`; the knowledge behind it is in `docs/` (index below); this file holds what must be known before touching anything.

## Using this template

This repo is the template itself. To start a site from it:

1. Clone it, set `COMPOSE_PROJECT_NAME` in `.env` (copied from `.env.example`), and run `./dev.sh up` — see `README.md` ("Quick start").
2. Build the site locally; commit theme/plugin changes under `wp-content/`.
3. Deploy to your own server when ready — see `README.md` ("Deploy to your server"). Deployment stays dormant until the `DEPLOY_HOST` / `DEPLOY_SSH_KEY` secrets are set, so a fresh clone never produces a failing deploy.
4. To move it onto another account and/or track this repo for updates, see `README.md` ("Make it your own").

Conventions worth knowing:
- **One site per repo**; each sets a unique `COMPOSE_PROJECT_NAME`, which names the production containers `<project>-wordpress` / `<project>-mysql` so a reverse proxy can route to the right one.
- **Migrating an existing site?** Use Duplicator — see the gotchas below and `README.md` ("Migrating an existing site").
- **Per-repo deploy key**: GitHub rejects reusing one SSH deploy key across repos; give each its own (and, if several share a host, an SSH config alias so git picks the right one).
- **Web server is OpenLiteSpeed, page cache is LiteSpeed Cache** (Jack, 2026-10-07) — never Apache/nginx, never W3 Total Cache or WP Rocket. Why: `docs/architecture.md`.

## Important Gotchas

- **DB host is `mysql`, not `localhost`** — inside Docker, each container has its own network. `localhost` inside the WordPress container refers to itself. The MySQL container is reachable via Docker DNS as `mysql` (the service name from docker-compose.yml).
- **Reverse-proxy target is port 80, not 8080** — OpenLiteSpeed's production listener is :80. It also listens on :8080, which local dev publishes as `8080:8080` so WordPress's loopback to `http://localhost:8080` (WP-Cron, Site Health) reaches the same container.
- **Never edit `wp-config.php` in the container** — lsphp cannot see the environment, so `docker/openlitespeed/make-wp-config.php` rewrites it from the `WORDPRESS_*` variables at **every start** (keeping salts and table prefix). Change the compose files and restart. `WORDPRESS_DEBUG` is a boolean (`"false"` is off).
- **Permalinks live in `.htaccess`** — OpenLiteSpeed reads it (`autoLoadHtaccess`). `wp rewrite flush --hard` writes the rules from the CLI thanks to `/etc/wp-cli/config.yml` (`apache_modules: [mod_rewrite]`).
- **Core, `wp-config.php` and `.htaccess` live in the `wp-html` volume** — the entrypoint upgrades core from a newer image and never downgrades. `docker compose down -v` wipes them (and an imported table prefix).
- **OpenLiteSpeed logs are files, not `docker compose logs`** — `/usr/local/lsws/logs/` (`error.log`, `access.log`, `stderr.log` = PHP's errors). `dev.sh logs` tails them.
- **WooCommerce: LiteSpeed Cache's "Cache REST API" must be off** (`wp litespeed-option set cache-rest 0`) — on by default, it served the Store API cart from the cache (Ellengaard, 2026-10-07).
- **No HTTPS listener and no http→https redirect locally, ever** — port 8080 is shared by every local project, and a redirect on it is remembered by the browser for all of them.
- **Local ports follow the dev port registry** — 8080 site, `127.0.0.1:3307` MySQL; no `restart:` in `docker-compose.yml` (production overlay only, on every service). Never remap to dodge a collision. See `.claude/rules/infrastructure.md`.
- **WP-CLI is in the image** — `docker compose exec -u www-data wordpress wp <command>` (locally `dev.sh cli <command>`), in production too. There is no `wpcli` service.
- **Duplicator files go INSIDE the container** — files placed on the server filesystem aren't served by OpenLiteSpeed. Use `docker compose cp` or the `import-duplicator.sh` script.
- **WordPress install wizard must be completed first** — on a fresh container, WordPress shows its install wizard before any other URL works. Complete it with throwaway values before running Duplicator.
- **Table prefix** — the generator keeps an imported site's prefix at every restart; `WORDPRESS_TABLE_PREFIX` overrides it. Only wiping the `wp-html` volume loses it — avoid resetting volumes after an import.
- **wp-content permissions** — the container runs OpenLiteSpeed and lsphp as `www-data`. After any file operations, fix ownership: `docker compose exec wordpress chown -R www-data:www-data /var/www/html/wp-content`
- **Uploads subdirectories** — after a fresh DB import, plugins may expect subdirectories under `wp-content/uploads/` that don't exist in the volume. Fix with: `docker compose exec wordpress chown -R www-data:www-data /var/www/html/wp-content/uploads` (the plugin will create its subdirectory on next request once permissions are correct).
- **GitHub deploy keys are unique per repo** — the same SSH public key cannot be added to multiple repos. Use SSH config host aliases to map each repo to its own key.
- **Production .env is critical** — without it, containers start in dev mode (ports exposed, not on the proxy network). The `setup-server.sh` script creates this automatically.
- **Windows has no `export` or Git Bash by default** — `sync-db-from-prod.sh` needs bash. Use `sync-db-from-prod.bat`, or the manual steps in `docs/database-changes.md`.
- **Reverse-proxy "Force SSL" can cause redirect loops** — the generated `wp-config.php` already turns `X-Forwarded-Proto: https` into `$_SERVER['HTTPS']`. Don't enable "Force SSL" (e.g. in Nginx Proxy Manager) for the upstream.
- **Never run `tests/smoke.sh` under another project name** — it runs as Compose project `wordpress-smoke` with no published ports, precisely so its closing `down -v` cannot touch the dev stack.

## Development Commands

| Command | Description |
|---------|-------------|
| `dev.bat up` | Start containers |
| `dev.bat down` | Stop containers |
| `dev.bat reset` | Destroy volumes and restart fresh |
| `dev.bat logs` | Follow OpenLiteSpeed's error log and PHP's errors |
| `dev.bat cli plugin list` | Run WP-CLI commands (in the container, as `www-data`) |
| `dev.bat cli litespeed-purge all` | Purge LiteSpeed Cache's page cache |
| `dev.bat backup` | Dump DB to `backups/` |
| `dev.bat restore backups/file.sql` | Restore DB from dump |

(`dev.sh` has the same commands.)

## Engineering standards

This repo runs the Allegro IT engineering-standards pack: judgment rules in `.claude/rules/`, the scanner and gates in `engineering_standards/` — both synced by `/apply-standards`, never edited here. Verification is `python engineering_standards/verify.py`; the git hooks (`core.hooksPath engineering_standards/hooks`) run it at commit (`--staged`) and push, and CI runs it with `--strict`. Do not run it by hand.

- **`php-standards.md` is copied by hand**: the pack's `has_php` looks only two directory levels deep and misses `docker/openlitespeed/make-wp-config.php`, so a re-sync does not refresh it. Copy it again from the pack after each `/apply-standards` until the pack's check is fixed.
- **Settled, do not re-open**: the template ships no in-product user documentation (`userDocs` undeclared) and enumerates no public routes (`docsRouteInventories` undeclared). It has no database access code, UI, forms, login, payments, expiring credentials or background jobs of its own — the WordPress site built on it does — so `data-access`, `data-integrity`, `ui-standards`, `bot-defence`, `session-authority`, `payments`, `certificate-expiry` and `background-jobs` are not adopted.
- Deploy-time hazards go in `PUBLISH_NOTES.md` in the same commit (`.claude/rules/publishing.md`).

## Docs

| Page | For |
|---|---|
| `docs/index.md` | The map |
| `docs/architecture.md` | Why OpenLiteSpeed; generated wp-config.php; the wp-html volume and core sync; compose files, ports, containers, deploy |
| `docs/ci-tests-and-releases.md` | What CI runs, what the tests assert, releasing, what each file is |
| `docs/database-changes.md` | Deploy-time PHP migrations; copying production's DB to local (also by hand on Windows) |
| `docs/elementor.md` | Custom themes alongside Elementor (Theme Builder conditions, `template_include`, CSS, `_elementor_data`) |
| `docs/polylang.md` | Polylang navigation, permalinks, front pages, scripts |
