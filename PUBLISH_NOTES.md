# Publish notes

Deploy-time hazards that the diff cannot show: migrations that need watching, ports and
container names something outside the repo points at, environment variables that must exist on
the server *before* the container starts, and steps that happen outside git.

Everything under **Pending** applies to the next push. Move an entry to **Deployed** with the
date once it has shipped *and been verified* — not before, because a stale Pending entry is how
the next person learns to ignore this file.

The rule, and when an entry is required, is in `.claude/rules/publishing.md`.

## Pending — next deploy

### OpenLiteSpeed, non-root deploy, renamed containers (first deploy after 1.0.0)
**Applies to:** any site deployed from the 1.0.0 template that takes this version. This repo
itself deploys nowhere (no `DEPLOY_HOST`), so for the template it is informational.
**Why it matters:** the deploy now logs in as `deploy` (not root) and refuses to run without
`DEPLOY_HOST_FINGERPRINT`; the web container becomes `<site>-web`, which the reverse proxy
must target; the container runs as uid 33, so a root-owned uploads volume becomes
unwritable; and a non-`wp_` table prefix must be declared or WordPress shows its install
wizard (which the health check counts as healthy).
**Before deploying:** steps 1–4 in CHANGELOG.md, "Upgrading a site already deployed from the
1.0.0 (Apache) template" — prefix, `deploy` user, fingerprint secret, uploads chown.
**After:** point the proxy host at `<site>-web:80` (502 until then), run
`docker compose exec wordpress wp rewrite flush --hard`, load the public URL and confirm 200.
**Rollback:** repository variable `DEPLOY_USER=root`, revert the commit and push, and point
the proxy back at `<site>-wordpress`.

### The deploy now pulls images; MySQL is pinned to 8.4.11
**Applies to:** any deployed site that takes this version. Informational for the template
itself, which deploys nowhere.
**Why it matters:** until now no deploy pulled, so the server kept whichever `mysql:8.4` it
first downloaded — possibly months old. The first deploy with this change pulls
`mysql:8.4.11` and recreates the database container on it: a MySQL patch upgrade within the
8.4 LTS line, applied to the live data at that restart. It also needs Docker Hub reachable
from the server at deploy time (the rollback does not).
**Before deploying:** take a database dump (`docker compose exec mysql mysqldump …`, or the
server's backup routine) and note the running version:
`docker compose exec mysql mysql --version`.
**After:** `docker compose exec mysql mysql --version` reports 8.4.11; check
`docker logs <site>-db` for upgrade errors; load the public URL and confirm 200.
**Rollback:** the deploy's automatic rollback recreates the containers from the previous
commit, whose `mysql:8.4` is still the server's older cached copy — so the database steps
back to that patch release on data 8.4.11 has opened. MySQL supports in-place downgrades
within the 8.4 LTS series; if it will not start anyway, restore the dump into a fresh
volume.

## Deployed

_Nothing yet._
