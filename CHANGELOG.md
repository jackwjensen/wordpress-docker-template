# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
