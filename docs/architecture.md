---
audience: dev
type: explanation
---

# How the stack is built, and why

## One OpenLiteSpeed container

**OpenLiteSpeed + lsphp 8.5, one container** (Jack, 2026-10-07: the WordPress sites Allegro IT
hosts run OpenLiteSpeed + the LiteSpeed Cache plugin; he has bad experiences with W3 Total Cache
and WP Rocket). Carried over from Ellengaard (`ellengaard-dk` commit `20b8a09`), which moved from
nginx + PHP-FPM the same day; this template moved from Apache.

- `Dockerfile` = `litespeedtech/openlitespeed:1.9.2-lsphp85` (Ubuntu 26.04, PHP 8.5.9;
  extensions a superset of the official image's except `pdo_sqlite`/`sqlite3`) + curl + pinned
  WP-CLI + `config/uploads.ini` (as `mods-available/zz-uploads.ini`, lsphp's ini scan dir).
- WordPress core comes from the official `wordpress:7.1-php8.5-fpm` image (multi-stage `core`,
  with `wp-config-docker.php` removed).
- `docker/openlitespeed/` = server config (`httpd_config.conf`: `www-data`, `disableWebAdmin 1`,
  :8080 + :80 plain HTTP, the cache module), the vhost (`vhconf.conf`: `.htaccess` rewrites),
  `entrypoint.sh` (core install/upgrade → `make-wp-config.php` → the base image's
  `/entrypoint.sh`, which starts `lswsctrl`, runs `"$@"`, then loops), `wp-cli.yml`, `wp.sh`.
- `php` on the PATH is lsphp's CLI; WP-CLI runs on it through the `wp` wrapper.
- MySQL 8.4 LTS is the database.

## Why LiteSpeed, not Apache or nginx

LiteSpeed Cache's **page cache** only works on a LiteSpeed web server. The plugin does not cache
pages itself: it sends `X-LiteSpeed-Cache-Control` headers, and the server's cache module
(`module cache` in `httpd_config.conf`) stores and serves the page. nginx and Apache ignore the
headers, so there the plugin offers only its optimisation features. The server tells the plugin
it may cache by setting `X-LSCACHE` (`on,crawler`) in `$_SERVER`; a cached response carries
`X-LiteSpeed-Cache: hit`. Jack's well-performing sites all answer `Server: LiteSpeed`.

## Why wp-config.php is generated at every start

lsphp cannot see the container's environment — `getenv()` returns false under LSAPI (tested on
Ellengaard, 2026-10-07) — so the official image's `wp-config.php`, which reads the environment on
every request, cannot work. `make-wp-config.php` runs with the CLI PHP (which *can* see the
environment) at every container start and writes literal values. It keeps the existing secret
keys and table prefix, so restarts never log anyone out and an imported site keeps its prefix.
A failure to read or write stops the container start, so the deploy health check catches it.

## Why core lives in a volume, and still follows the image

Core, `wp-config.php` and `.htaccess` live in the `wp-html` volume, so a deploy
(`--force-recreate`) keeps logins, permalinks and LiteSpeed Cache's rules. The entrypoint copies
core into an empty volume, and replaces core's own files — never `wp-content`, `wp-config.php` or
`.htaccess` — when the image's WordPress is newer than the volume's. It never downgrades. So a
Dependabot base-image bump still updates core on the next deploy, as it did when core lived in
the container layer.

## Compose files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base config + local dev (ports 8080:8080 and `127.0.0.1:3307` for MySQL, debug on, `wp-html` volume, **no `restart:`**) |
| `docker-compose.production.yml` | Production overrides (no ports, joins `nginx-proxy-network`, debug off, `DISALLOW_FILE_EDIT`, `restart: unless-stopped` on every service) |

Merged in production via `COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml` in the
server's `.env`. The `wordpress` service is built from the repo `Dockerfile` (locally and on the
server via `docker compose up --build`); only `mysql` uses an upstream image directly. Both files
set `WP_CACHE` true (for LiteSpeed Cache; harmless without it).

**Local ports follow the Allegro IT dev port registry** (`.claude/rules/infrastructure.md`): 8080
the site, `127.0.0.1:3307` the database — never 3306, never the short `"3307:3306"` form (that
binds every interface). All local projects share these numbers and only one runs at a time, so
the base file has no restart policy: a self-restarting stack would come back after a Docker
Desktop restart and hold the ports against the next project. OpenLiteSpeed listens on 8080 inside
the container too, so WordPress's loopback to `http://localhost:8080` (WP-Cron, Site Health)
reaches the same container.

## Containers, network and server layout

Production containers are named `${COMPOSE_PROJECT_NAME}-wordpress` and
`${COMPOSE_PROJECT_NAME}-mysql`; the reverse proxy routes each domain to
`<project>-wordpress:80`. Production joins the proxy's external network (default
`nginx-proxy-network`); MySQL stays on the project's internal network only.

One directory per site under a common root (default `/opt/apps/<repo>`), each its own Compose
project. Allegro IT runs this with Nginx Proxy Manager on a Hetzner VPS; any Docker host plus a
reverse proxy works the same way.

## Deployment

Push to `master` (or a manual dispatch) → GitHub Actions SSHes into the host at `DEPLOY_PATH`
(default `/opt/apps/<repo-name>`) → `git pull` → `docker compose up --build --force-recreate -d`
→ HTTP health check (`scripts/healthcheck.sh`, probed inside the container). On failure it
reverts to the previous commit and rebuilds. It stays dormant until the `DEPLOY_HOST` and
`DEPLOY_SSH_KEY` secrets are set (optional variables `DEPLOY_USER` / `DEPLOY_PATH`, default
`root` / `/opt/apps/<repo>`), so a fresh clone never produces a red deploy.
