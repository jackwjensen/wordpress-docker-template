# WordPress Docker Template

[![CI](https://github.com/jackwjensen/wordpress-docker-template/actions/workflows/ci.yml/badge.svg)](https://github.com/jackwjensen/wordpress-docker-template/actions/workflows/ci.yml)
[![Release](https://github.com/jackwjensen/wordpress-docker-template/actions/workflows/release.yml/badge.svg)](https://github.com/jackwjensen/wordpress-docker-template/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![WordPress 7.1](https://img.shields.io/badge/WordPress-7.1-21759B?logo=wordpress&logoColor=white)
![OpenLiteSpeed](https://img.shields.io/badge/OpenLiteSpeed-1.9-0E7DC2)
![PHP 8.5](https://img.shields.io/badge/PHP-8.5-777BB4?logo=php&logoColor=white)
![MySQL 8.4 LTS](https://img.shields.io/badge/MySQL-8.4_LTS-4479A1?logo=mysql&logoColor=white)
[![GHCR](https://img.shields.io/badge/ghcr.io-container-2496ED?logo=docker&logoColor=white)](https://github.com/jackwjensen/wordpress-docker-template/pkgs/container/wordpress-docker-template)

**Clone it, run one command, and you have a full WordPress + MySQL development
environment in Docker — ready to build a site on.** When you're ready, deploy it
to any Docker host, take it onto your own account, and (if you like) keep pulling
improvements from upstream.

Modern stack — **WordPress 7.1 · OpenLiteSpeed · PHP 8.5 · MySQL 8.4 LTS** —
ready for the LiteSpeed Cache plugin's server-side page cache, with GitHub Actions
CI, a published image on GHCR, and an optional one-push deploy with automatic
rollback.

## Contents

- [Quick start](#quick-start)
- [Features](#features)
- [Architecture](#architecture)
- [The image](#the-image)
- [Page cache: LiteSpeed Cache](#page-cache-litespeed-cache)
- [Development commands](#development-commands)
- [Running the tests](#running-the-tests)
- [Deploy to your server](#deploy-to-your-server)
- [Releasing](#releasing)
- [Migrating an existing site](#migrating-an-existing-site)
- [Database strategy](#database-strategy)
- [Make it your own](#make-it-your-own)
- [Need a hand?](#need-a-hand)
- [Contributing & security](#contributing--security)
- [License](#license)

## Quick start

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(or Docker Engine + the Compose v2 plugin) and Bash (Git Bash on Windows).

```bash
git clone https://github.com/jackwjensen/wordpress-docker-template.git my-site
cd my-site
cp .env.example .env          # set COMPOSE_PROJECT_NAME=my-site
./dev.sh up                   # Windows: dev.bat up
```

Open <http://localhost:8080> and finish the WordPress install wizard. That's it —
you're developing. (`dev.sh up` generates a local database password into `.env` on
its first run; no password is ever committed.)

## Features

- **WordPress 7.1 + OpenLiteSpeed + PHP 8.5 (lsphp)** in one container: the
  official LiteSpeed image with WordPress core from the official WordPress image,
  tuned PHP upload limits baked in, and the server-side page cache that the
  [LiteSpeed Cache](https://wordpress.org/plugins/litespeed-cache/) plugin needs.
- **MySQL 8.4 LTS** with a real authenticated health check.
- **CI on every push/PR** — ShellCheck, Hadolint, Compose validation, actionlint,
  plus a build + smoke test (see the badge above).
- **Published image** on GHCR, built and released from a version tag (keyless).
- **Optional one-push deploy** over SSH with **automatic rollback** if WordPress
  fails to serve afterwards — only after CI passes, as a non-root user, with the
  server's host key pinned; dormant until you configure a target.
- **Hardened container**: nothing runs as root, and the root filesystem is
  read-only — WordPress writes only to its volumes.
- **WP-CLI** in the image — locally and on the server.

## Architecture

The same two services run locally and in production; a Compose override file swaps
the environment-specific bits.

| | Local (`docker-compose.yml`) | Production (`+ docker-compose.production.yml`) |
| --- | --- | --- |
| WordPress | Built from `Dockerfile`, OpenLiteSpeed on port `8080:8080`, debug on | Same image, OpenLiteSpeed on `:80`, no published port, debug off, `DISALLOW_FILE_EDIT` + `DISALLOW_FILE_MODS` |
| MySQL | `127.0.0.1:3307` (this machine only) | No published port |
| Database password | Generated into `.env` by `dev.sh up` | Generated into `.env` by `setup-server.sh` |
| Container | `www-data`, read-only root filesystem | Same |
| Restart policy | None — the stack runs only when you start it | `unless-stopped` on every service |
| Networking | Default bridge only | Also joins an external reverse-proxy network |
| Routing | Direct to `localhost:8080` | Reverse proxy → `<project>-web:80` |

Production merges both files via
`COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml` in the server's
`.env`. Each site sets a unique `COMPOSE_PROJECT_NAME`, which names the containers
(`<project>-web`, `<project>-db`) so a reverse proxy can route to the right one.

Production's themes and plugins come from git: WordPress cannot install or update
them there (`DISALLOW_FILE_MODS`). Install and update plugins locally, commit, push.

## The image

The [`Dockerfile`](Dockerfile) builds one container that serves HTTP itself:
the official [`litespeedtech/openlitespeed`](https://hub.docker.com/r/litespeedtech/openlitespeed)
image (OpenLiteSpeed + lsphp 8.5), WordPress core copied from the official
`wordpress` image, pinned WP-CLI, and [`config/uploads.ini`](config/uploads.ini),
so the PHP limits travel with the image. The server configuration lives in
[`docker/openlitespeed/`](docker/openlitespeed/): one virtual host, PHP and the
files run as `www-data`, no web admin console, plain HTTP on `8080` (local) and
`80` (production, behind your reverse proxy).

Two things work differently from the official WordPress image:

- **`wp-config.php` is written at every container start** from the `WORDPRESS_*`
  variables in the compose files. lsphp cannot see the container's environment
  (`getenv()` returns false under LSAPI), so the official image's `wp-config.php`,
  which reads the environment on every request, cannot work. The generated file
  keeps the existing secret keys and table prefix. Change settings in the compose
  files (`WORDPRESS_CONFIG_EXTRA` for extra `define()`s) and restart — never edit
  `wp-config.php` itself.
- **Core lives in the `wp-html` volume**, together with `wp-config.php` and
  `.htaccess`, so a deploy keeps permalinks, cache rules and logins. Core still
  follows the image: when the image carries a newer WordPress than the volume, the
  entrypoint replaces core's files (never `wp-content`, `wp-config.php` or
  `.htaccess`, and never a downgrade). After a major upgrade, WordPress asks for
  its database update on the next admin visit.

Local dev and production both build the image; tagged releases publish it to GHCR:

```bash
docker pull ghcr.io/jackwjensen/wordpress-docker-template:latest
# or pin a version
docker pull ghcr.io/jackwjensen/wordpress-docker-template:1.0.0
```

## Page cache: LiteSpeed Cache

Allegro IT's WordPress sites run the
[LiteSpeed Cache](https://wordpress.org/plugins/litespeed-cache/) plugin, which is
why the image runs OpenLiteSpeed rather than Apache or nginx:

- **Its page cache only works on a LiteSpeed web server** (OpenLiteSpeed or
  LiteSpeed Enterprise). The plugin does not cache pages itself; it sends
  `X-LiteSpeed-Cache-Control` headers, and the server's cache module stores and
  serves the page. nginx and Apache ignore those headers, so there you get only
  the plugin's optimisation features (CSS/JS, images), not the page cache.
- The server tells the plugin it can cache by setting `X-LSCACHE` (`on,crawler`)
  in `$_SERVER`. A response served from the cache carries `X-LiteSpeed-Cache: hit`.
- Permalinks and the plugin's own rules live in **`.htaccess`**. WordPress writes it
  when Permalinks are saved; from the command line, `dev.sh cli rewrite flush --hard`
  does the same. OpenLiteSpeed only re-reads a changed `.htaccess` after a restart,
  so the container watches it and restarts OpenLiteSpeed gracefully within about
  five seconds of a change.

Set it up on a site — locally, then commit `wp-content/plugins/litespeed-cache`
(production does not install plugins itself):

```bash
./dev.sh cli plugin install litespeed-cache --activate
```

`WP_CACHE` is already `true` in both compose files. Purge with
`./dev.sh cli litespeed-purge all` (= the admin bar's "Purge All"). The container
empties the cache when it starts, so a restart or deploy never serves pages cached
from the previous version.

> **WooCommerce shops: turn "Cache REST API" off** —
> `./dev.sh cli litespeed-option set cache-rest 0`. It is on by default, and it
> served WooCommerce's Store API cart from the cache, so shoppers would see each
> other's carts. Cart, checkout and My Account pages are never cached.

**Coming from W3 Total Cache or WP Rocket?** Uninstall it the WordPress way, so its
drop-in `advanced-cache.php` goes too, then install LiteSpeed Cache:

```bash
./dev.sh cli plugin uninstall --deactivate w3-total-cache
./dev.sh cli plugin install litespeed-cache --activate
```

W3 Total Cache leaves `wp-content/w3tc-config/`, `wp-content/cache/`, an
`nginx.conf` in the site root and `w3tc_*` options behind; remove them by hand.
Keep `WP_CACHE` true.

## Development commands

| Command | Description |
|---------|-------------|
| `dev.sh up` | Build and start containers |
| `dev.sh down` | Stop containers |
| `dev.sh reset` | Destroy volumes and restart fresh |
| `dev.sh logs` | Follow OpenLiteSpeed's error log and PHP's errors (files in the container, `/usr/local/lsws/logs/`) |
| `dev.sh cli plugin list` | Run WP-CLI commands (inside the WordPress container, which runs as `www-data`) |
| `dev.sh backup` | Dump the database to `backups/` |
| `dev.sh restore backups/file.sql` | Restore the database from a dump |

(`dev.bat` provides the same commands on Windows.)

Local ports: <http://localhost:8080> for the site and `127.0.0.1:3307` for MySQL
(user `root`, password: `MYSQL_ROOT_PASSWORD` in your `.env`). The stack has no
restart policy, so it stays down after a Docker Desktop restart until you run
`dev.sh up`.

## Running the tests

The repo carries Allegro IT's engineering-standards checks (`engineering_standards/`,
rules in `.claude/rules/`). Turn on their git hooks once per clone — commit then runs the
quick checks on what you stage, and push runs them all:

```bash
git config core.hooksPath engineering_standards/hooks
```

The same checks CI runs, locally:

```bash
shellcheck scripts/*.sh dev.sh tests/*.sh docker/openlitespeed/*.sh   # shell lint
hadolint Dockerfile                          # Dockerfile lint
docker compose config -q                     # Compose validation
bash tests/healthcheck.test.sh               # fast: no Docker stack needed
bash tests/smoke.sh                          # builds the image + brings up the stack
```

`tests/smoke.sh` asserts that OpenLiteSpeed serves HTTP, that nothing runs as root
and the root filesystem is read-only, that the baked-in `upload_max_filesize` is
active, that LiteSpeed's page cache answers a cacheable page with a hit, that
WordPress installs against MySQL, that permalinks work through `.htaccess` and an
edited `.htaccess` is applied, that a restart keeps the secret keys and table
prefix, and that core is upgraded from a newer image but never downgraded. It runs as its own
Compose project (`wordpress-smoke`) with no published ports, so it never touches
your dev stack's data and never needs port 8080.

## Deploy to your server

Deployment is **optional and dormant until you configure it** — a fresh clone runs
locally and passes CI with no deploy setup at all.

The `deploy` job in [`ci.yml`](.github/workflows/ci.yml) deploys over SSH to any
Docker host on push to `master` — only after the lint and smoke-test jobs pass. It
logs in as a named non-root user (`deploy`, in the docker group) and verifies the
server's host key. To activate it:

1. On the server, as root, run `./scripts/setup-server.sh <site-name> <repo-url>`
   once (read its header first: the `deploy` user needs read access to the repo). It
   creates the `deploy` user, clones the repo as that user, generates the DB
   password, builds the image, starts the stack, and prints the values for step 2.
2. Add three repository **secrets**:
   - `DEPLOY_HOST` — your server's host or IP
   - `DEPLOY_SSH_KEY` — a private SSH key whose public half is in
     `/home/deploy/.ssh/authorized_keys`
   - `DEPLOY_HOST_FINGERPRINT` — the server's **ECDSA** host-key fingerprint
     (`SHA256:…`), as printed by the setup script. ECDSA, not ed25519: the deploy
     action is a Go SSH client, which negotiates ECDSA, and a wrong pin fails with
     a mismatch that names no algorithm.

   (Optional **variables** `DEPLOY_USER` and `DEPLOY_PATH` default to `deploy` and
   `/opt/apps/<repo>`.)
3. Put a reverse proxy in front for TLS and routing, pointing your domain at the
   `<project>-web` container on port **80**. Leave the proxy's "force HTTPS" off for
   the upstream: OpenLiteSpeed speaks plain HTTP, and `wp-config.php` turns the
   proxy's `X-Forwarded-Proto` header into HTTPS for WordPress.
4. Push to `master`. The workflow rebuilds, health-checks that WordPress actually
   serves HTTP, and rolls back automatically if it doesn't.

> **Example setup (what Allegro IT runs in production):** a VPS with
> [Nginx Proxy Manager](https://nginxproxymanager.com/) terminating TLS and routing
> each site's domain to its `<project>-web:80` container. Any Docker host plus
> a reverse proxy works the same way.

## Releasing

Push a SemVer tag to build and publish the image and create a GitHub Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

[`release.yml`](.github/workflows/release.yml) authenticates to GHCR with the
built-in `GITHUB_TOKEN` (no stored secret), publishes
`ghcr.io/<owner>/<repo>` tagged `1.0.0`, `1.0`, `1`, and `latest`, attaches a
build-provenance attestation, and drafts release notes.

## Migrating an existing site

1. Install the [Duplicator](https://wordpress.org/plugins/duplicator/) plugin on
   the existing site and create a package (`installer.php` + archive zip).
2. Set up the server with `scripts/setup-server.sh` and finish the WordPress
   install wizard (throwaway values — Duplicator overwrites everything).
3. Copy the Duplicator files to the server and run
   `scripts/import-duplicator.sh installer.php <archive.zip>`.
4. Open `https://example.com/installer.php` and complete the wizard:
   - **DB Host**: `mysql` (NOT `localhost` — containers use Docker DNS)
   - **DB Name**: `wordpress` · **DB User**: `root`
   - **DB Password**: from `MYSQL_ROOT_PASSWORD` in the server's `.env`

   Duplicator writes its own `wp-config.php`; the container rewrites it at the
   next start, keeping the secret keys and the imported table prefix. Then save
   Settings → Permalinks once, so `.htaccess` gets the rewrite rules.
5. Commit the `wp-content/themes/` and `wp-content/plugins/` changes and push, then
   hand those folders back to the `deploy` user as the import script prints, so
   the next deploy's `git pull` can write them.
6. Sync the production DB to local: `./scripts/sync-db-from-prod.sh <site-name> example.com`
   (requires the `DEPLOY_HOST` env var; see the script's note about serialized data).

## Database strategy

WordPress plugins manage their own schema via `dbDelta()` — there are no migration
files. Instead:

- **Install/uninstall plugins locally**, commit the files, push. WordPress
  converges the schema on activation.
- **Pull prod DB to local** with `scripts/sync-db-from-prod.sh`.
- **Never push the local DB to production** — let WordPress/plugins upgrade their
  own schema. User content lives in production.

## Make it your own

This template is yours to adopt. Two common paths — and they combine well:

**Take it onto your own account**

1. Create your own repo and re-point `origin`:
   ```bash
   git remote set-url origin git@github.com:you/your-site.git
   git push -u origin master
   ```
2. Update the bits that name the upstream project: [`CODEOWNERS`](CODEOWNERS), the
   badges/links at the top of this README, and the OCI labels in the
   [`Dockerfile`](Dockerfile). The release workflow already publishes to
   `ghcr.io/<your-account>/<repo>` automatically — no edit needed.
3. Add your own `DEPLOY_HOST` / `DEPLOY_SSH_KEY` / `DEPLOY_HOST_FINGERPRINT`
   secrets to deploy to your server.
4. Optionally remove the [Need a hand?](#need-a-hand) section.

**Stay connected — pull future improvements**

Keep this repo as an `upstream` remote and merge template updates when you want
them (CI, Docker, and tooling improvements — never your site content):

```bash
git remote add upstream https://github.com/jackwjensen/wordpress-docker-template.git
git fetch upstream
git merge upstream/master        # or: git rebase upstream/master
```

Your themes, plugins, uploads, and database stay yours; upstream changes touch only
the scaffolding (Dockerfile, Compose, CI, scripts, docs). Read
[CHANGELOG.md](CHANGELOG.md) before you deploy a merge — a site deployed from the
Apache version of this template needs the steps under "Upgrading a site already
deployed from the Apache template" on its first OpenLiteSpeed deploy.

## Need a hand?

This template is built and maintained by **[Allegro IT ApS](https://allegroit.dk/)**,
a Danish software studio. If you'd rather have us **build, migrate, or host** your
WordPress site — on EU-based, GDPR-friendly infrastructure — we're happy to help:
[kontakt@allegroit.dk](mailto:kontakt@allegroit.dk).

## Contributing & security

- Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md) and our
  [Code of Conduct](CODE_OF_CONDUCT.md).
- Security: please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © [Allegro IT ApS](https://allegroit.dk/) — fork it, ship it, make
it yours.
