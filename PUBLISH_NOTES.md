# Publish notes

Deploy-time hazards that the diff cannot show: migrations that need watching, ports and
container names something outside the repo points at, environment variables that must exist on
the server *before* the container starts, and steps that happen outside git.

Everything under **Pending** applies to the next push. Move an entry to **Deployed** with the
date once it has shipped *and been verified* — not before, because a stale Pending entry is how
the next person learns to ignore this file.

The rule, and when an entry is required, is in `.claude/rules/publishing.md`.

## Pending — next deploy

_Nothing pending._

## Deployed

_Nothing yet._
