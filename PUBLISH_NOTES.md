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

### The deploy now pulls images; MySQL moves to 26.7.0 (Innovation)
**Applies to:** any deployed site that takes this version, and any local dev stack with an
existing `mysql-data` volume. Informational for the template itself, which deploys nowhere;
a fresh clone starts on an empty volume and is unaffected.
**Why it matters:** until now no deploy pulled, so the server kept whichever `mysql:8.4` it
first downloaded. The first deploy with this change pulls `mysql:26.7.0`, and **MySQL refuses
an in-place upgrade from 8.4 straight to 26.7**: the only supported route is 8.4 LTS → 9.7.x
LTS → 26.7 ([upgrade paths](https://dev.mysql.com/doc/refman/26.7/en/upgrade-paths.html)).
Deployed as-is on 8.4 data, the database container does not start and the site is down
until the deploy rolls back. 26.7 is an Innovation release: it is supported only until the
next Innovation release (26.10), so keep taking Dependabot's MySQL bumps. The deploy also
needs Docker Hub reachable from the server (the rollback does not).
**Before deploying:** take a database dump (`docker compose exec mysql mysqldump …`, or the
server's backup routine) and keep it. Then either step the volume through 9.7 first
(set `image: mysql:9.7.2` on the server, `docker compose up -d mysql`, wait for healthy,
check `docker logs <site>-db`), or load the dump into a fresh 26.7 volume after the deploy.
**After:** `docker compose exec mysql mysql --version` reports 26.7.0; check
`docker logs <site>-db` for upgrade errors; load the public URL and confirm 200.
**Rollback:** data that 26.7 (or 9.7) has opened cannot go back to 8.4 in place. Restore the
dump into a fresh volume on `mysql:8.4.11` and revert the commit.

## Deployed

_Nothing yet._
