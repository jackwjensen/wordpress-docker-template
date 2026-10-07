---
description: What may be committed, and what may not — the one rule with no exceptions
alwaysLoad: any file in any language can carry a credential into git, and the ones that do are config, fixtures and seeders rather than a scopeable file type
---

# Credentials: what may be committed, and what may not

One rule, and it has no exceptions worth the words: **a credential that works anywhere must
never reach git.** Not in production config, not in a fixture, not in a seeder, and not in a
development-only settings file. "Development-only" describes where it is *used*; it says
nothing about where it is *stored*, and git is forever in a way a dev environment is not.

## The argument that always gets made, and why it loses

*"It's only a dev password."* It is a **working credential** — and the estate reuses one local
login everywhere, so one commit publishes every project's local superadmin at once. A repo's
**audience changes** (a contractor, an agency, a customer handover, a mirror) without the file
changing. And **git keeps it after you delete it**: cleaning it out properly means rewriting
history and rotating the credential — days of work for a line that took seconds. The measured
case: `ligelon-compliance` carried its demo password in the committed
`appsettings.Development.json`, and the estate's seeded admin password nearly followed it in
because the file already looked like the place such things went. A committed dev password is
not a bug; it is a shape that invites the next one.

## Where they may live instead

In rough order of preference. Pick the first that fits the stack.

1. **The framework's own secret store.** `dotnet user-secrets` (a `UserSecretsId` in the csproj,
   values under the user profile), Django's environment-backed settings, Laravel's `.env`. The
   value sits outside the repo while staying tied to the project, and no `.gitignore` line has
   to be right for it to stay out.
2. **A gitignored `.env`.** Fine, and the estate already relies on it — but it depends on the
   ignore rule remaining correct, so check `git check-ignore .env` rather than assuming.
   `.env.example` is committed and carries the **key names with empty values**.
3. **Generated at first run and printed once.** The strongest option where it fits: nothing to
   leak because nothing was written down. Good for a first-admin bootstrap, awkward for a demo
   cast that documentation names.

## What may be committed

- **Key names**, in `.env.example`, with empty values and a comment saying what each is for.
- **A pointer** to where the value lives — "see the identity notes", not the value.
- **A deliberately fake value that cannot work anywhere**, and only where a placeholder is
  structurally required. The design-time connection string in `migrations.md` is the worked
  example, and its lesson applies here: make it *obviously* fake, because a realistic-looking
  one invites somebody to "fix" it into a real credential.

## Seeders read credentials; they never contain them

A seeder needs a password to hash, so it takes one — from configuration, never a literal — and
it **refuses rather than defaulting**: a fallback to a built-in value is the committed value
that then gets used wherever nobody set the variable. Throw and name the missing key
(`configuration["Demo:Password"] ?? throw ...`). Two more: **hash it, never store it**, even for
demo data; and **gate it on the environment**, with the guard in the seeder rather than the
caller's good intentions.

**And it validates what it was given.** Writing a hash directly skips the framework's password
validators, so a placeholder value yields an account holding a password the application would
refuse — measured: a demo admin whose password was its own e-mail address, three database wipes
before anyone found out. Check configured credentials against the *real* validators at startup;
refuse to start otherwise, naming the failing rule and never the value.

## The estate's standard local accounts

`localadmin@allegroit.dk` and `localuser@allegroit.dk` are seeded in every repo that needs a
local superadmin or a plain test user, so that one set of credentials works everywhere. **The
addresses may be committed; the passwords may not.** Their values live in the identity notes
under `~/.claude/memory/` — which is exactly the split this file describes, and the reason the
values are in memory rather than in any repo.

## A secret must never reach the client, git or no git

The rule above is about *history*; this is about *distribution*. A frontend build inlines its
`environment` / config object into the bundle it ships, so a secret placed there is served to
every visitor — moving it to a different frontend file changes nothing, the whole object is
compiled in. Keep server-side the keys a call *uses* (payment capture, mail send, OAuth
exchange); the browser holds only the deliberately-public half. An external audit found live
Paystack and Brevo *secret* keys in a production Angular bundle; rotating them without moving
the calls server-side just republished the new ones next deploy. `committed-credential` catches
a known secret *format* even in a `.ts`, but "this ships to the browser" it cannot judge.

## Checking

Before a commit that touches config, a seeder, a fixture or a compose file:

```bash
git diff --cached | grep -iE 'password|secret|api[_-]?key|token' 
```

A hit is not automatically wrong — a key *name* is fine — but every hit deserves the question.
And when a credential has already been committed, rotating it is part of the fix, not an
optional follow-up: history keeps the old one whatever the working tree says.

Source of truth: engineering-standards/claude/rules/secrets.md
