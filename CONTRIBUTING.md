# Contributing

Thanks for your interest in improving this WordPress Docker template!

## Development setup

Requirements: Docker Desktop (or Docker Engine + Compose v2) and Bash.

```bash
cp .env.example .env       # set COMPOSE_PROJECT_NAME
./dev.sh up                # build + start, then open http://localhost:8080
```

Helper commands live in `dev.sh` / `dev.bat`: `up`, `down`, `reset`, `logs`,
`cli`, `backup`, `restore`.

## Running the checks locally

CI runs these on every push and pull request — run them before opening a PR:

```bash
shellcheck scripts/*.sh dev.sh tests/*.sh
hadolint Dockerfile
docker compose config -q
bash tests/healthcheck.test.sh   # fast: no Docker stack needed
bash tests/smoke.sh              # builds the image + brings up the full stack
```

## Pull requests

- Keep changes focused, and update docs (`README.md`, `CLAUDE.md`) in the **same**
  PR as the code they describe.
- Add or update a test when you fix a bug or change behaviour.
- Never commit secrets — `.env` is git-ignored and must stay that way.
- Present-tense, descriptive commit subjects are appreciated (e.g.
  "Fix deploy health check").

## Releases

Maintainers cut a release by pushing a SemVer tag:

```bash
git tag v1.2.0
git push origin v1.2.0
```

That builds and publishes the image to GHCR and creates a GitHub Release
automatically (see [`.github/workflows/release.yml`](.github/workflows/release.yml)).
