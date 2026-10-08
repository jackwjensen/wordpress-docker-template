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
- WordPress core comes from the official `wordpress:7.1.3-php8.5-fpm` image (multi-stage `core`,
  with `wp-config-docker.php` removed). Every image and action is pinned to one exact release
  (`mysql:8.4.11`, actions by commit SHA); Dependabot proposes the moves.
- `docker/openlitespeed/` = server config (`httpd_config.conf`: `www-data`, `disableWebAdmin 1`,
  :8080 + :80 plain HTTP, the cache module), the vhost (`vhconf.conf`: `.htaccess` rewrites),
  `entrypoint.sh` (core install/upgrade → `make-wp-config.php` → configuration into the tmpfs →
  `lswsctrl start` → wait, restarting on `.htaccess` changes, stopping cleanly on `SIGTERM`),
  `wp-cli.yml`, `wp.sh`.
- `php` on the PATH is lsphp's CLI; WP-CLI runs on it through the `wp` wrapper. The image puts
  `/usr/local/bin` first on the `PATH`: the base image lists it last and ships its own
  unwrapped `/usr/bin/wp`, which would otherwise shadow the pinned one.
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
| `docker-compose.yml` | Base config + local dev: container names, read-only + mounts, password from `.env`, ports 8080:8080 and `127.0.0.1:3307`, debug on, **no `restart:`** |
| `docker-compose.production.yml` | Production overrides: no ports, joins `nginx-proxy-network`, debug off, `DISALLOW_FILE_EDIT` + `DISALLOW_FILE_MODS`, `restart: unless-stopped` on every service |

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

## Why it runs as www-data, read-only

Nothing in the container runs as root — OpenLiteSpeed, lsphp, the entrypoint and WP-CLI are all
`www-data` (the image's `USER`). Root bought nothing: Docker sets
`net.ipv4.ip_unprivileged_port_start=0` inside containers, so an unprivileged process binds :80.
The base image's own `/entrypoint.sh` is not used, because it `chown`s the configuration to
`lsadm`, which needs root; the Dockerfile gives OpenLiteSpeed's directories to `www-data`
instead.

The root filesystem is read-only (`read_only: true`). What the container writes was measured
with `docker diff` on a running site (2026-10-08), and each path is a mount:

| Path | Mount | Why |
|---|---|---|
| `/var/www/html` | volume `wp-html` | core, `wp-config.php`, `.htaccess` (`uploads` is its own volume) |
| `/usr/local/lsws/logs` | volume `ols-logs` | `error.log`, `access.log`, `stderr.log` |
| `/usr/local/lsws/cachedata` | volume `ols-cache` | the page cache; emptied at every start |
| `/tmp` | tmpfs, 512 MB | OpenLiteSpeed's sockets and swap, PHP uploads (256 MB max), WP-CLI's cache |
| `/usr/local/lsws/conf`, `/usr/local/lsws/admin/conf` | tmpfs | OpenLiteSpeed writes parsed copies of its config beside it at start |
| `/usr/local/lsws/tmp`, `/usr/local/lsws/cgid` | tmpfs | a download and a socket |

The configuration directory cannot be a volume: Docker seeds a volume from the image only
once, so every later image's configuration would be ignored. The image keeps it in
`/usr/local/lsws/conf.image` and the entrypoint copies it into the tmpfs at every start — the
image stays the single source.

## Why .htaccess changes restart the server

OpenLiteSpeed reads a directory's `.htaccess` the first time it rewrites a request through that
directory and keeps it until it restarts — a new file, or an edit, is ignored (measured
2026-10-08, as root and as `www-data` alike; LiteSpeed Enterprise re-reads, OpenLiteSpeed does
not). Requests for real files (`/wp-login.php`, the health check) do not load it, which is why
a new file can *seem* to apply: only after a pretty URL has been served is "no `.htaccess`"
held. The smoke test reproduces that state before it checks the watcher. WordPress writes
`.htaccess` when permalinks are saved, and LiteSpeed Cache writes its rules there, so the
entrypoint polls the `.htaccess` files every 5 s and restarts OpenLiteSpeed gracefully
(`lswsctrl restart`) when one changes. It watches the docroot two levels down plus the top of
`uploads`: a set bounded by core's own tree, never by the number of uploads. An `.htaccess`
deeper than that needs `docker compose exec wordpress lswsctrl restart`.

## Containers, network and server layout

Containers are named in the base file, so development and production agree:
`<project>-web` (the reverse proxy forwards to `<project>-web:80`) and `<project>-db`, from
`COMPOSE_PROJECT_NAME` (default `wordpress`). The name is interpolated rather than literal
because every site built from the template is its own instance (`.claude/rules/infrastructure.md`).
Production joins the proxy's external network (default `nginx-proxy-network`); MySQL stays on
the project's internal network only.

One directory per site under a common root (default `/opt/apps/<repo>`), each its own Compose
project. Allegro IT runs this with Nginx Proxy Manager on a Hetzner VPS; any Docker host plus a
reverse proxy works the same way.

## Deployment

Push to `master` (or a manual run) → CI's two check jobs → the `deploy` job in `ci.yml`, which
runs only after both pass → SSH into the host as the `deploy` user, host key pinned → `git pull`
in `DEPLOY_PATH` (default `/opt/apps/<repo-name>`) → `docker compose up --build --force-recreate
-d` → HTTP health check (`scripts/healthcheck.sh`, probed inside the container). On failure it
reverts to the previous commit and rebuilds. It stays dormant until the `DEPLOY_HOST` secret is
set, so a fresh clone never produces a red deploy; once it is, `DEPLOY_SSH_KEY` and
`DEPLOY_HOST_FINGERPRINT` are required (optional variables `DEPLOY_USER` / `DEPLOY_PATH`,
default `deploy` / `/opt/apps/<repo>`).

**Why `deploy`, not root:** a CI key with a root shell makes any compromise of the workflow, the
key or the third-party SSH action a full host takeover. `deploy` is in the docker group, which
is still root-*adjacent* (it can bind-mount `/`), so this is one rung down from root, not least
privilege. **Why the fingerprint is ECDSA:** `appleboy/ssh-action` runs a Go SSH client, which
negotiates ECDSA where OpenSSH prefers ed25519; pinning the ed25519 value fails with a
mismatch that names no algorithm. Both rules: `.claude/rules/publishing.md`.

**The database password** lives only in `.env`: `scripts/setup-server.sh` writes it on a server,
`dev.sh`/`dev.bat` generate it locally. The compose files refuse to start without it, and scripts
run the mysql client inside the mysql container, which already holds it.
