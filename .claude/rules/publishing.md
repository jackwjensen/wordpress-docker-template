---
paths:
  - '**/PUBLISH_NOTES.md'
  - '**/docker-compose*.yml'
  - '**/Migrations/**'
  - '**/migrations/**'
  - '**/.env.example'
  - '**/.github/workflows/*.yml'
description: PUBLISH_NOTES.md — carrying deploy-time knowledge from the commit that created it to the person deploying
---

# Publish notes: what the deployer needs that the diff cannot tell them

Every repo here auto-deploys on push to `master`. The person pushing is therefore the person
deploying, often days after the change was written and with no memory of it — and some changes
carry a hazard that is invisible in the diff. A data migration that reads a date column. A
published port that moves. A container that gets renamed while a reverse proxy points at the old
name. An env var that must exist on the server *before* the container starts.

`PUBLISH_NOTES.md` in the repo root is where that knowledge waits.

## The rule

**A commit that carries a deploy-time hazard adds an entry in the same commit.** Not afterwards,
not in the PR description — in the file, beside the code, where the person deploying will look.

A change needs an entry when it touches any of:

- **Migrations** — especially data migrations, anything reading an existing column into a typed
  intermediate, or an index/FK reordering. Migrations auto-apply at startup, so a statement the
  database rejects does not fail cleanly; it crash-loops the container behind a 502.
- **Published ports or container names** — anything a reverse proxy, a firewall rule, a cron
  entry, or a saved database connection points at.
- **Environment variables** — a new required var must be in the server's `.env` *before* the
  deploy, or the container starts and immediately dies.
- **Volumes** — a renamed or removed volume silently orphans data.
- **Anything needing a step outside the repo** — a DNS record, an NPM proxy host, a Stripe
  webhook endpoint, a cron line, a firewall rule.
- **Anything that cannot be verified locally** — a paid API path, a multi-user flow, visual
  polish. Say so, so the deployer knows to look.

Ordinary code changes need no entry. If everything needed one, nobody would read it.

## The shape

Two sections. Entries accumulate under **Pending** and move to **Deployed** once shipped —
the history is worth keeping, because "when did this port change?" is a question that gets
asked.

```markdown
# Publish notes

Deploy-time hazards, newest first. Everything under **Pending** applies to the next push;
move it to **Deployed** with the date once it has shipped and been verified.

## Pending — next deploy

### Container renamed `foo-1` → `foo-web`
**Why it matters:** NPM's proxy host for `foo.dk` targets the old name.
**Before deploying:** point the proxy host at `foo-web` (or confirm it targets the service
name, which does not change).
**After:** load `https://foo.dk` and confirm 200, not 502.
**Rollback:** revert the commit and `docker compose up -d --force-recreate`.

## Deployed

### 2026-08-01 — Added `STRIPE_WEBHOOK_SECRET`
Needed in the server `.env` before the deploy. Done.
```

**Write the entry for someone who has forgotten the change.** "Watch the migration" is useless;
"this migration reads `t_time_log.Date` into a UNION subquery, and two legacy rows held
`0000-00-00` until they were repaired — take a backup first" is what saves the evening.

**Always include the rollback.** The deployer is reading this because something looks wrong.

**Record when a "before deploying" step has been DONE.** These entries are instructions, and an
instruction with no state is one somebody re-runs, or skips because they assume a colleague
already did. Add a status line to the entry the moment you perform it — it stays under Pending
until the deploy that needed it actually succeeds, so the two facts ("done on the box" and
"shipped") are tracked separately. That matters most when a deploy fails for an unrelated
reason: the server change is already applied, the code that needs it is not, and the next
person needs both halves of that.

## Renaming a file the server's `.env` points at

A specific hazard worth its own note, because the obvious ordering is the wrong one and it
nearly cost an outage in `allegro-it-services` on 2026-08-10.

`COMPOSE_FILE` (and anything like it) names a file **literally**. Rename that file in git and
there is no ordering that keeps the server consistent throughout:

- Change `.env` **first** and the box points at a file it has not pulled yet — every
  `docker compose` command there fails until the deploy pulls.
- Change it **after** and the deploy itself fails, because the pull has already removed the old
  filename.

So the window is unavoidable. What you control is its length and what happens inside it:

1. **Push immediately after editing `.env`** — the deploy's `git pull` closes the window, and it
   is the first thing the job does. Do not edit `.env` "sometime before" the push; the gap is
   the whole risk.
2. **Know that auto-rollback is broken inside the window.** A rollback checks out the previous
   commit — which has the *old* filename — while `.env` names the new one, so the rollback's own
   `docker compose up` fails. If the deploy stops containers before the step that failed, they
   stay stopped. Recovery is `git checkout master && docker compose up -d`, and it belongs in
   the entry.
3. **Expect the first push to fail for an unrelated reason.** If the repo has unpushed commits
   that CI has never seen, the pre-deploy gate is meeting them for the first time. Get the
   checks green *before* touching `.env`, so the window opens once.

**Verify the checks the entry tells the deployer to run can actually pass at the time they run
them.** The entry here said to confirm with `docker compose config`, which cannot succeed until
the new overlay exists on the box — so the instruction failed for a correct reason and looked
like a problem.

## A recreated container can leave the proxy pointing at a dead IP

The second hazard worth its own section, because it makes a **green deploy and a 502 site at
the same time** — and every deploy in this estate ends with `docker compose up
--force-recreate`.

`--force-recreate` can hand the new container a different IP on the shared proxy network, and
Nginx Proxy Manager's openresty keeps routing to the old one until it is reloaded. The app is
healthy, `docker compose ps` says running, a container-count health check passes — and the
public hostname serves 502 from openresty. Measured on InvoTrack, 2026-08-15: ~8 minutes of
502 after a fully green run, with `curl` from *inside* the NPM container to the upstream
returning 200 the whole time.

Two consequences for a deploy script:

1. **Reload NPM after the recreate** — `docker exec nginx-proxy-app-1 sh -c 'nginx -t &&
   nginx -s reload'`, non-fatally (the probe below is the verdict; a failed reload must not
   roll back a deploy the proxy might yet serve). The rollback path recreates the container
   too, so it needs the same reload or the *restored* version 502s.
2. **A container count is not a health check.** The only proof a deploy succeeded is the
   public URL answering 200 — probe it in a retry loop and fail the deploy (triggering the
   rollback) if it never does. InvoTrack's deploy.yml is the reference implementation.

Not a changelog — a changelog says what changed, these notes say what to *do* about it. Not a
runbook: standing operational procedure belongs in the repo's `CLAUDE.md` or a runbook, while
these notes are the changes in flight. An entry that is still true after ten deploys was
documentation in the wrong place; move it.

## Clearing it

Move entries to **Deployed** as part of the push, not before it — an entry sitting under
Pending after a successful deploy is how the next deployer learns to ignore the file.

---

# Who the deploy is, and who the container is

The sections above are about *what the deployer needs to know*. These are about *what the
pipeline is allowed to be* — the identity CI assumes when it reaches the machine, and the
identity the process keeps once it is there. Both are enforced mechanically
(`engineering_standards/standards_deploy.py`); this is the judgment half.

All three rules below were universal across the estate on 2026-08-18: ten deploy workflows in
nine repos, every one logging in as `root`, none verifying the host key, and app containers
running as root because `USER` was never set. None had ever failed. That is the point — they
are not bug reports, they are the properties that decide how bad an unrelated bug is allowed
to get.

## Deploys run as a named non-root user (`deploy-root-ssh`)

A CI key with a root shell means any compromise of the workflow, the key secret, or the
third-party SSH action is a full host takeover — and the action is the part nobody here
controls. Create a `deploy` account, put it in the `docker` group, give it ownership of the
stack directory, and name it in the workflow.

**Say what this buys, honestly, because overselling it is how the next person skips the step
that actually matters.** Anyone in the `docker` group can bind-mount `/` into a container and
read or write anything on the host. So `deploy` is root-**adjacent**; it is not least
privilege and must never be described as such. What it genuinely buys:

- no direct root shell over SSH, so `PermitRootLogin` can eventually go;
- a smaller sshd surface and one fewer account that accepts remote keys;
- per-user attribution in `auth.log` — with everything as root, "who deployed that?" has no
  answer;
- the option to constrain the key later with `command=` / `from=` in `authorized_keys`, which
  is the step that *would* make it least privilege.

**Migrating is ordered so root stays a working fallback throughout.** Create the user and give
it the CI public keys, chown the stack directories, verify by SSH-ing as `deploy` and running
the deploy's own first commands, and only then change the workflow — one repo at a time, each
push its own test. Leave root's `authorized_keys` alone until every repo is green; removing it
is the last step, not the first. Done that way, a failed migration rolls back with one revert
and no server change.

**Read the deploy script for root-isms before switching it.** A `chown`, a path under `/root/`,
a write outside the stack directory, or a `systemctl` call will fail as `deploy` and take the
deploy with it. A `docker exec` into another stack is fine — docker-group membership covers it.

## SSH steps verify the host key (`deploy-no-hostkey`)

Without `fingerprint:`, the action trusts whatever answers at that address, so anything able to
answer for the host — a hijacked DNS record, a BGP detour — collects a credential with write
access to every stack on the box.

**Get the value by testing, never by reading it off `ssh -v`.** This is the trap, and it is the
reason this section exists: a server usually offers several host keys and *the client chooses*.
OpenSSH's preference list leads with ed25519; Go's `crypto/ssh` leads with ECDSA.
`appleboy/ssh-action` is a composite action that downloads `drone-ssh` — a Go binary — so the
key CI negotiates is usually **not** the one a developer is shown. The check is then a bare
string compare against `ssh.FingerprintSHA256` of whatever was negotiated, and the failure is:

```
ssh: handshake failed: ssh: host key fingerprint mismatch
```

which names no algorithm and offers no hint. Pinning the obvious ed25519 value would have
broken all ten deploys in the estate at once.

The reliable way to establish it costs two minutes, needs no production credential, and works
for any Go-based SSH action:

```bash
# Host-key verification happens BEFORE authentication, so a throwaway key separates the two
# failure modes: "fingerprint mismatch" = wrong pin, "unable to authenticate" = right pin.
ssh-keygen -t ed25519 -N '' -f /tmp/throwaway -q
drone-ssh --host <host> --username deploy --key-path /tmp/throwaway \
          --fingerprint "SHA256:<candidate>" --script "echo hi"
```

Try the ECDSA candidate first (`ssh-keyscan -t ecdsa <host> | ssh-keygen -lf -`). Record which
algorithm won in a comment beside the value, or the next person will "fix" it back.

A rebuilt server changes the key and breaks every repo's deploy at once. That is the intended
failure mode of a pin — but it means the new fingerprint has to be distributed deliberately,
so put it in the publish notes.

## App containers set `USER` (`container-root-user`)

A container listening on an unprivileged port needs no capability at all, so root buys nothing
and costs a container escape that starts as root. The runtime images ship a ready non-root
user for exactly this — `USER $APP_UID` (uid 1654) on `mcr.microsoft.com/dotnet/aspnet`,
`USER node` on `node` — so the fix is one line and the omission is pure inheritance from the
base image. Judged on the **final stage only**: build stages need root to install packages and
never ship.

### The migration: chown first, deploy second

Docker seeds a volume's ownership from the image only when it **creates** the volume. An
existing named volume keeps whatever it already had, so a container that was root yesterday
leaves root-owned volumes that a non-root container tomorrow cannot write.

The ordering makes this a zero-downtime change, and it is worth understanding rather than
copying: **root can write to a directory owned by the new uid, but the new uid cannot write to
a root-owned one.** So chown *first* — the currently running root container is unaffected —
and deploy second.

```bash
docker run --rm -v <vol-a>:/a -v <vol-b>:/b alpine chown -R 1654:1654 /a /b
docker run --rm -v <vol-a>:/a -v <vol-b>:/b alpine ls -ldn /a /b   # must print 1654 1654
```

**Volumes are the half everyone remembers. The half that gets forgotten is inside the image.**
Anything the app writes *under the content root* — generated PDFs, exports, a cache directory
— is published output that `COPY` leaves root-owned, and no volume chown touches it. In
InvoTrack that was `wwwroot/documents/{invoices,payslips}`, and missing it produced an app that
started, served, logged a user in, and failed only when somebody created an invoice. Create and
chown those paths in the Dockerfile:

```dockerfile
RUN mkdir -p /app/keys /app/uploads /app/wwwroot/documents \
    && chown -R $APP_UID:$APP_UID /app/keys /app/uploads /app/wwwroot/documents
USER $APP_UID
```

**Grep for write paths before switching, rather than discovering them one support ticket at a
time**: `CreateDirectory`, `WriteAll`, `open(..., "w")`, `fopen`, anything joining a path onto
the content root.

### Verify by exercising a write, not by loading the home page

The failure mode is a container that starts and serves. In InvoTrack, a missing keys chown gave
Data Protection `Permission denied` and then HTTP 500 on every page — which the deploy's URL
probe catches — while `docker compose ps` still reported `running`, which a container-count
health check would have called healthy. A different missing chown broke only invoice creation,
which no automated probe touches at all.

So after the first non-root deploy: confirm `docker exec <container> id` reports the new uid,
grep the log for `permission denied`, and **perform one real write through the UI** — the thing
the app does that touches disk.

### `read_only: true` is a separate decision, and often not available

Worth wanting, but it is incompatible with an app that writes into its own image — which the
`wwwroot/documents` case above is exactly. It becomes available only once every write path is a
volume or a tmpfs. If you drop it, record *why* in the compose file, so the next reader knows it
was considered rather than missed.

# Naming the credentials a server holds

A shared server's `/root/.ssh` accumulates keys for years, added one at a time by whoever
needed the next one. There is no compiler to keep them consistent and nothing in any repo to
scan, so this is prose with **no rule id and no scanner** — deliberately. A rule id here would
imply `standards_deploy.py` enforces it; nothing does, because the subject lives on the box
rather than in a checkout. It is a convention to follow when creating a key, not a gate.

**Three namespaces, three jobs, one convention each:**

| Namespace | Convention | Example |
|---|---|---|
| `Host` aliases in `~/.ssh/config` | kebab-case, `<service>-<target>` | `github-invotrack`, `storagebox-db` |
| Key files on disk | snake_case, `<target>_<role>_key` | `invotrack_deploy_key`, `storagebox_db_backup_key` |
| `authorized_keys` comments | kebab-case, `<consumer>-<app>-<role>-key` | `github-actions-invotrack-deploy-key` |

**The separators differ per namespace on purpose, and the reason is which ones get typed.**
Aliases are typed — into `git remote` URLs, into `sftp <alias>` — so they sit beside hostnames
and URLs, where kebab-case is the surrounding grammar and a wrong one fails immediately and
loudly. Key filenames appear only inside `IdentityFile` lines and are read by almost nobody, so
they drift for free; they take the shell-variable shape instead. If that distinction feels
arbitrary, the alternative is worse: one convention across all three means renaming ten working
deploy keys to fix a cosmetic problem, and the estate has already voted — aliases were 12/12
kebab and key files 10/12 snake when this was measured (2026-08-21), without anyone deciding it.

**The `github-actions-` prefix in `authorized_keys` is load-bearing, not decoration.** It is
the only place in the whole SSH surface that string appears, and it is what the deploy-user
migration selects on:

```bash
grep 'github-actions' /root/.ssh/authorized_keys > /home/deploy/.ssh/authorized_keys
```

A CI key added as `deploy_key_serverops` or `gh-actions-foo` is silently omitted from that
copy, and the failure surfaces later as one repo's deploy failing to authenticate while the
others work — the asymmetry that makes a migration look finished when it is not. **Keep the
prefix exactly; the rest of the name is style.**

**What the drift actually costs, stated honestly.** Measured on the Allegro IT server
2026-08-21: five comments were pure kebab (`github-actions-donorlink-deploy-key`) and five were
hybrids (`github-actions-prototypes_deploy_key`), with one — `github-actions-sourcetext-ai_deploy_key`
— mixing both separators inside a single name. All ten still matched the `grep`, so **nothing
was broken**. That is the point worth internalising: this is cosmetic *today*, and it stays
cosmetic only because every name happens to retain the prefix. A convention nobody wrote down
survives on luck, and the next person copies whichever neighbour they happen to look at.

**When you add a key, name all three at once** — alias, file, and comment — rather than
creating the file now and letting the comment default to whatever `ssh-keygen -C` last had.
`ssh-keygen`'s default comment is `user@host`, which says nothing about what the key is for.
