# WordPress Docker Template

[![CI](https://github.com/jackwjensen/wp_image/actions/workflows/ci.yml/badge.svg)](https://github.com/jackwjensen/wp_image/actions/workflows/ci.yml)
[![Release](https://github.com/jackwjensen/wp_image/actions/workflows/release.yml/badge.svg)](https://github.com/jackwjensen/wp_image/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![WordPress 7.0](https://img.shields.io/badge/WordPress-7.0-21759B?logo=wordpress&logoColor=white)
![PHP 8.4](https://img.shields.io/badge/PHP-8.4-777BB4?logo=php&logoColor=white)
![MySQL 8.4 LTS](https://img.shields.io/badge/MySQL-8.4_LTS-4479A1?logo=mysql&logoColor=white)
[![GHCR](https://img.shields.io/badge/ghcr.io-wp__image-2496ED?logo=docker&logoColor=white)](https://github.com/jackwjensen/wp_image/pkgs/container/wp_image)

A production-ready, batteries-included template for running self-hosted Docker
WordPress sites — **WordPress 7.0 + PHP 8.4 + MySQL 8.4 LTS** — with GitHub
Actions CI, a published GHCR image on every release, automatic-rollback
deployment to a VPS, and Nginx Proxy Manager routing.

> Built and maintained by [**Allegro IT ApS**](https://allegroit.dk/) ·
> *International project management with team spirit* ·
> [kontakt@allegroit.dk](mailto:kontakt@allegroit.dk)

## Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick start (local development)](#quick-start-local-development)
- [Architecture](#architecture)
- [The image](#the-image)
- [Development commands](#development-commands)
- [Running the tests](#running-the-tests)
- [Deploy to production](#deploy-to-production)
- [Releasing](#releasing)
- [Migrating an existing site](#migrating-an-existing-site)
- [Database strategy](#database-strategy)
- [Contributing & security](#contributing--security)
- [License](#license)

## Features

- **WordPress 7.0 + PHP 8.4 + Apache** on a thin image built from the official
  upstream, with tuned PHP upload limits baked in.
- **MySQL 8.4 LTS** with a real authenticated health check.
- **CI on every push/PR** — ShellCheck, Hadolint, Compose validation,
  actionlint, plus a build + smoke test (see the badge above).
- **Release automation** — push a `v*` tag to build and publish the image to
  **GHCR** (keyless, via the built-in `GITHUB_TOKEN`) with build provenance.
- **Auto-deploy on push to `master`** with **automatic rollback** if WordPress
  fails to serve after deploy.
- **Nginx Proxy Manager** integration via an external Docker network.
- **WP-CLI** available locally for command-line management.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker
  Engine + the Compose v2 plugin)
- Bash (Git Bash on Windows) to run the helper and test scripts
- For deployment: a VPS with Docker, Nginx Proxy Manager, and an
  `nginx-proxy-network` Docker network

## Quick start (local development)

1. Copy this template to a new folder for your site.
2. Create `.env` from `.env.example`:
   ```env
   COMPOSE_FILE=docker-compose.yml
   COMPOSE_PROJECT_NAME=my-site
   ```
3. Start the stack (builds the image on first run):
   ```bash
   ./dev.sh up        # Linux/macOS/Git Bash
   dev.bat up         # Windows
   ```
4. Open <http://localhost:8080> and complete the WordPress setup.

## Architecture

The same two services run locally and in production; a Compose override file
swaps the environment-specific bits.

| | Local development (`docker-compose.yml`) | Production (`+ docker-compose.production.yml`) |
| --- | --- | --- |
| WordPress | Built from `Dockerfile`, port `8080:80` published, debug **on** | Same image, **no published port**, debug off, `DISALLOW_FILE_EDIT` |
| MySQL | Port `3306` published, dev password | No published port, password from `.env` |
| Networking | Default bridge only | Also joins the external `nginx-proxy-network` |
| Routing | Direct to `localhost:8080` | Nginx Proxy Manager → `<project>-wordpress:80` |

Production merges both files via `COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml`
in the server's `.env`. Each site sets a unique `COMPOSE_PROJECT_NAME`, which
names the containers (`<project>-wordpress`, `<project>-mysql`) so NPM can route
to the right one.

```
GitHub push ──▶ Actions ──SSH──▶ VPS: git pull + docker compose up --build
                                   │
                          nginx-proxy-network
                                   │
   Internet ──▶ Nginx Proxy Manager ──▶ <project>-wordpress:80 ──▶ MySQL (internal)
```

## The image

WordPress is built from a small [`Dockerfile`](Dockerfile) that extends the
official image and bakes in [`config/uploads.ini`](config/uploads.ini), so the
PHP limits travel with the image instead of relying on a host bind-mount. Local
dev and production both build it; tagged releases publish it to GHCR:

```bash
docker pull ghcr.io/jackwjensen/wp_image:latest
# or pin a version
docker pull ghcr.io/jackwjensen/wp_image:1.0.0
```

## Development commands

| Command | Description |
|---------|-------------|
| `dev.sh up` | Build and start containers |
| `dev.sh down` | Stop containers |
| `dev.sh reset` | Destroy volumes and restart fresh |
| `dev.sh logs` | Follow WordPress logs |
| `dev.sh cli wp plugin list` | Run WP-CLI commands |
| `dev.sh backup` | Dump the database to `backups/` |
| `dev.sh restore backups/file.sql` | Restore the database from a dump |

(`dev.bat` provides the same commands on Windows.)

## Running the tests

The same checks CI runs, locally:

```bash
shellcheck scripts/*.sh dev.sh tests/*.sh   # shell lint
hadolint Dockerfile                          # Dockerfile lint
docker compose config -q                     # Compose validation
bash tests/healthcheck.test.sh               # fast: no Docker stack needed
bash tests/smoke.sh                          # builds the image + brings up the stack
```

`tests/smoke.sh` asserts that WordPress serves HTTP, that the baked-in
`upload_max_filesize` is active, and that WordPress can reach MySQL.

## Deploy to production

1. Create a **private** GitHub repo and push.
2. Add repository secrets: `HETZNER_HOST` and `HETZNER_SSH_KEY` (a per-repo
   deploy key).
3. On the server, run:
   ```bash
   ./scripts/setup-server.sh <site-name> <repo-url>
   ```
4. Add a proxy host in Nginx Proxy Manager: `example.com` →
   `<site-name>-wordpress:80` (port **80**, not 8080). Do **not** enable
   "Force SSL" — the image already honours `X-Forwarded-Proto`.
5. Push to `master` — [`deploy.yml`](.github/workflows/deploy.yml) SSHes in,
   rebuilds, and health-checks. If WordPress doesn't serve HTTP afterwards, it
   rolls back automatically.

## Releasing

Push a SemVer tag to build and publish the image and create a GitHub Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

[`release.yml`](.github/workflows/release.yml) authenticates to GHCR with the
built-in `GITHUB_TOKEN` (no stored secret), publishes
`ghcr.io/jackwjensen/wp_image` tagged `1.0.0`, `1.0`, `1`, and `latest`, attaches
a build-provenance attestation, and drafts release notes.

## Migrating an existing site

1. Install the [Duplicator](https://wordpress.org/plugins/duplicator/) plugin on
   the existing site and create a package (`installer.php` + archive zip).
2. Set up production with `scripts/setup-server.sh`.
3. Complete the WordPress install wizard (throwaway values — Duplicator
   overwrites everything).
4. Copy the Duplicator files to the server and run
   `scripts/import-duplicator.sh installer.php <archive.zip>`.
5. Open `https://example.com/installer.php` and complete the wizard:
   - **DB Host**: `mysql` (NOT `localhost` — containers use Docker DNS)
   - **DB Name**: `wordpress`
   - **DB User**: `root`
   - **DB Password**: from `MYSQL_ROOT_PASSWORD` in the server's `.env`
6. Commit the `wp-content/themes/` and `wp-content/plugins/` changes and push.
7. Sync the production DB to local: `./scripts/sync-db-from-prod.sh <site-name> example.com`.

## Database strategy

WordPress plugins manage their own schema via `dbDelta()` — there are no
migration files. Instead:

- **Install/uninstall plugins locally**, commit the files, push. WordPress
  converges the schema on activation.
- **Pull prod DB to local** with `scripts/sync-db-from-prod.sh` (includes a URL
  search-replace; see the script's note about serialized data).
- **Never push the local DB to production** — let WordPress/plugins handle their
  own upgrades. User content lives in production.

## Contributing & security

- Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md) and our
  [Code of Conduct](CODE_OF_CONDUCT.md).
- Security: please report vulnerabilities privately — see
  [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © [Allegro IT ApS](https://allegroit.dk/)
