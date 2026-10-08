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

## Deployed

_Nothing yet._
