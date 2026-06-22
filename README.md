# WordPress Docker Template

[![CI](https://github.com/jackwjensen/wp_image/actions/workflows/ci.yml/badge.svg)](https://github.com/jackwjensen/wp_image/actions/workflows/ci.yml)
[![Release](https://github.com/jackwjensen/wp_image/actions/workflows/release.yml/badge.svg)](https://github.com/jackwjensen/wp_image/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![WordPress 7.0](https://img.shields.io/badge/WordPress-7.0-21759B?logo=wordpress&logoColor=white)
![PHP 8.4](https://img.shields.io/badge/PHP-8.4-777BB4?logo=php&logoColor=white)
![MySQL 8.4 LTS](https://img.shields.io/badge/MySQL-8.4_LTS-4479A1?logo=mysql&logoColor=white)
[![GHCR](https://img.shields.io/badge/ghcr.io-wp__image-2496ED?logo=docker&logoColor=white)](https://github.com/jackwjensen/wp_image/pkgs/container/wp_image)

**Clone it, run one command, and you have a full WordPress + MySQL development
environment in Docker — ready to build a site on.** When you're ready, deploy it
to any Docker host, take it onto your own account, and (if you like) keep pulling
improvements from upstream.

Modern stack — **WordPress 7.0 · PHP 8.4 · MySQL 8.4 LTS** — with GitHub Actions
CI, a published image on GHCR, and an optional one-push deploy with automatic
rollback.

## Contents

- [Quick start](#quick-start)
- [Features](#features)
- [Architecture](#architecture)
- [The image](#the-image)
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
git clone https://github.com/jackwjensen/wp_image.git my-site
cd my-site
cp .env.example .env          # set COMPOSE_PROJECT_NAME=my-site
./dev.sh up                   # Windows: dev.bat up
```

Open <http://localhost:8080> and finish the WordPress install wizard. That's it —
you're developing.

## Features

- **WordPress 7.0 + PHP 8.4 + Apache** on a thin image built from the official
  upstream, with tuned PHP upload limits baked in.
- **MySQL 8.4 LTS** with a real authenticated health check.
- **CI on every push/PR** — ShellCheck, Hadolint, Compose validation, actionlint,
  plus a build + smoke test (see the badge above).
- **Published image** on GHCR, built and released from a version tag (keyless).
- **Optional one-push deploy** over SSH with **automatic rollback** if WordPress
  fails to serve afterwards — dormant until you configure a target.
- **WP-CLI** available locally for command-line management.

## Architecture

The same two services run locally and in production; a Compose override file swaps
the environment-specific bits.

| | Local (`docker-compose.yml`) | Production (`+ docker-compose.production.yml`) |
| --- | --- | --- |
| WordPress | Built from `Dockerfile`, port `8080:80`, debug on | Same image, no published port, debug off, `DISALLOW_FILE_EDIT` |
| MySQL | Port `3306` published, dev password | No published port, password from `.env` |
| Networking | Default bridge only | Also joins an external reverse-proxy network |
| Routing | Direct to `localhost:8080` | Reverse proxy → `<project>-wordpress:80` |

Production merges both files via
`COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml` in the server's
`.env`. Each site sets a unique `COMPOSE_PROJECT_NAME`, which names the containers
(`<project>-wordpress`, `<project>-mysql`) so a reverse proxy can route to the
right one.

## The image

WordPress is built from a small [`Dockerfile`](Dockerfile) that extends the
official image and bakes in [`config/uploads.ini`](config/uploads.ini), so the PHP
limits travel with the image. Local dev and production both build it; tagged
releases publish it to GHCR:

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

## Deploy to your server

Deployment is **optional and dormant until you configure it** — a fresh clone runs
locally and passes CI with no deploy setup at all.

The included workflow ([`deploy.yml`](.github/workflows/deploy.yml)) deploys over
SSH to any Docker host on push to `master`. To activate it:

1. Add two repository **secrets**:
   - `DEPLOY_HOST` — your server's host or IP
   - `DEPLOY_SSH_KEY` — a private SSH key the server accepts

   (Optional **variables** `DEPLOY_USER` and `DEPLOY_PATH` default to `root` and
   `/opt/apps/<repo>`.)
2. On the server, run `./scripts/setup-server.sh <site-name> <repo-url>` once — it
   clones the repo, generates the DB password, builds the image, and starts the
   stack.
3. Put a reverse proxy in front for TLS and routing, pointing your domain at the
   `wordpress` container on port **80**.
4. Push to `master`. The workflow rebuilds, health-checks that WordPress actually
   serves HTTP, and rolls back automatically if it doesn't.

> **Example setup (what Allegro IT runs in production):** a VPS with
> [Nginx Proxy Manager](https://nginxproxymanager.com/) terminating TLS and routing
> each site's domain to its `<project>-wordpress:80` container. Any Docker host plus
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
5. Commit the `wp-content/themes/` and `wp-content/plugins/` changes and push.
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
3. Add your own `DEPLOY_HOST` / `DEPLOY_SSH_KEY` secrets to deploy to your server.
4. Optionally remove the [Need a hand?](#need-a-hand) section.

**Stay connected — pull future improvements**

Keep this repo as an `upstream` remote and merge template updates when you want
them (CI, Docker, and tooling improvements — never your site content):

```bash
git remote add upstream https://github.com/jackwjensen/wp_image.git
git fetch upstream
git merge upstream/master        # or: git rebase upstream/master
```

Your themes, plugins, uploads, and database stay yours; upstream changes touch only
the scaffolding (Dockerfile, Compose, CI, scripts, docs).

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
