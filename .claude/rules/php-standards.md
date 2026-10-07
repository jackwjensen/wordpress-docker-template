---
paths:
  - "**/*.php"
description: PHP standards that php -l and the source scanner cannot check
---

# PHP standards (judgment rules)

The mechanical half is enforced by `php -l` in CI (parse errors) and
`check-source-limits.py` (file length, `unset-not-zero`, `date-out-of-range`,
`php-strict-types`). Don't re-check those by eye.

PHP is the least defended stack here: no analyzer, no type checker, and a runtime that
prefers to coerce rather than complain. Almost everything below exists because the language
will silently accept the wrong thing.

## The runtime floor is enforced, and every declaration moves together

**`php-support` in `check-source-limits.py` enforces `PHP_FLOOR`** — the number and the support
dates behind it live in `engineering_standards/standards_versions.py` and `engineering_standards/standards_php_support.py`,
never here, so there is one place to change it.

It reads three sites — any `FROM php:` base image, every `php-version:` in CI, and
composer.json's `require.php` — and `php-consistency` enforces that they name the **same**
version. Clearing the floor on every line is not enough: a repo whose CI lints on one minor and
whose container runs another is green right up until production.

**`require.php` is a minimum, never a pin.** Composer reads a bare `8.5.0` as *exactly* that —
unlike NuGet, where the same string is a floor — so `"php": "8.5.0"` genuinely pins the
platform, and that is reported even when the number is current. Write `^8.5` or `>=8.5`. This is
the estate policy in its clearest form: *we only define minimum*, because pinning is how a new
app inherits an old platform.

Where an extension genuinely has no build for the floor, exempt the line and name both the
blocker and what would unblock it:

```json
"require": {
    "//": "standards: php-support exempt -- ext-foo has no build for this floor yet; revisit when upstream ships one, tracked in PUBLISH_NOTES.md.",
    "php": "^8.4"
}
```

## Types are declared everywhere the language allows

`declare(strict_types=1)` at the top of every file that can carry it — enforced by the
scanner, exempt only for template partials that open with HTML, since PHP demands the declare
be the *first* statement. Without it a `"abc"` argument arrives at an `int` parameter as `0`,
which is exactly the sentinel bug below, manufactured by the runtime.

Then declare the types the language will accept: parameters, return types, properties.

```php
function load_post(string $slug, string $lang): ?array   // right
function load_post($slug, $lang)                          // says nothing, checks nothing
```

A `?array` return is the honest signature for "found or not found" — see the null rule below.
Locals cannot be typed in PHP, so the **name** carries the whole load there; see
`naming.md`.

## Exception handling: the same three layers as C# and Python

1. **Entry points** — the front controller, every router action, every form POST handler,
   webhook receiver and cron entry wraps its body in `try/catch` and renders a human-readable
   error page. Never let a raw PHP error or stack trace reach the browser; that is an
   information disclosure as well as a bad experience.
2. **External resource access** — every PDO call, `file_get_contents`, `curl`, `mail`, and
   third-party SDK call gets its own `try/catch`. Rethrow or handle deliberately.
3. **Business logic in between** — none at all. Let it propagate.

PHP-specific traps, all of which produce silent failure:

- **Set `PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION`.** The default is to return `false` and
  say nothing, so an un-checked query looks like an empty result set.
- **`@` suppression is banned.** It hides the error and leaves the wrong value in flight.
- **Check `false` returns.** `file_get_contents`, `fopen`, `json_decode`, `strtotime`,
  `preg_match` all report failure by return value, not by throwing. An unchecked
  `strtotime()` returning `false` becomes `1970-01-01` the moment it is formatted.
- **Never use exceptions for flow control** — check state first (`if ($items === [])`).

## Unset is `null`, never a zero-like sentinel

**This rule is about the value, not the type: is there a value, or is there not?** If "no
value" is a legitimate state, the type is nullable (`?int`, `?string`) and unset is `null` —
never `0`, `-1`, `''`, or `'0000-00-00'`. Each of those is a real value too, so once stored,
"nobody chose" and "somebody chose this" cannot be told apart.

Two kinds of value can never be zero-like, and the scanner enforces exactly these: an
**identity** (`$project_id`) may be neither `0` nor `''`, and an **external reference**
(`$stripe_reference`, an idempotency key) may not be `''`. A display name, a subject or a
description legitimately may — there "absent" and "empty" render the same and the distinction
buys nothing.

**Money is deliberately not one of them.** An amount can legitimately *be* zero — a zero-amount
verification charge, an empty wallet, `array_sum([])` — so for money `null` is usually the wrong
model and `0` is the genuine domain default. What is wrong is inventing an amount for data that
never arrived; see the payload rule below.

PHP is the *worst* language for this rule because it gives you two coalescing operators and
only one of them is safe:

```php
$job->project_id = $selected['id'] ?? 0;   // WRONG - dangling FK; there is no project 0
$pageSize        = $prefs['size'] ?: 50;   // WRONG - `?:` also eats a deliberate 0
$pageSize        = $prefs['size'] ?? 50;   // right - only null coalesces
```

- **`??` coalesces only `null`** (and an unset key, without a notice). This is the one to use.
- **`?:` coalesces every falsy value** — `0`, `''`, `'0'`, `[]`, `false`. It cannot express
  "unset" because it cannot distinguish it from "zero".
- **`empty()` has the same defect** and is the most common way this bug is written.
  `!isset($x)` or `$x === null` say what they mean; `empty($x)` is true for `'0'`.
- **`==` coerces.** `0 == 'abc'` was true before PHP 8, and `'1' == '01'` still is. Use
  `===` everywhere, and `strcasecmp()`/`mb_strtolower()` deliberately for case-insensitive
  comparison rather than `==`.

**The one exception — a genuine default.** Where the domain really has a default for "nothing
chosen", assign it by **name**, never as a bare literal:
`$job->status_id = $chosen ?? JobStatus::PLANNED;`

**Not covered: an aggregate over a possibly-empty set.** `array_sum([])` is genuinely `0` — the
additive identity, not a stand-in for "unknown". Same for `count()`.

**Not covered: normalise-then-guard.** Coalescing an *optional* value to `''` and then
branching on it immediately is correct, because the branch restores the distinction before
anything is stored:

```php
$series_id = (string) ($post['meta']['series'] ?? '');
$is_hub    = $series_id !== '' && $series_part === null;   // right - it branches on absence
```

The harm this rule prevents is "nobody chose" and "somebody chose this" becoming
indistinguishable. A guard on the same name against the same zero-like value makes them
distinguishable again, so the scanner stays silent when one appears within a few lines.
**This exemption does not extend to the payload rule below** — there the value can genuinely
*be* zero, so a guard cannot tell a missing key from a real `0`.

## Never default a field you read out of an external payload

PHP does this more than any other stack here, because everything arrives as an array —
`$_POST`, a `json_decode` body, a PDO row, markdown frontmatter. Reading **by literal key** and
defaulting turns "the key was absent" into a confident value:

```php
$amount_minor = $payload['amount_subtotal'] ?? 0;   // WRONG - a missing key becomes a free charge
```

A missing key is a contract surprise, not an amount — and because a real amount *can* be `0`,
the invented value and the true one are indistinguishable afterwards. Check for the key, or let
it fail:

```php
if (!array_key_exists('amount_subtotal', $payload)) {
    throw new RuntimeException('checkout payload has no amount_subtotal');
}
```

Reported as `payload-default` for money-named fields. Note this is the one place where `??` is
*not* the safe choice — for a required key, no coalesce at all is.

## Persisted dates declare a sensible range

Every stored date has a plausible window: business dates roughly
`2000-01-01 … today + 1 year`, system timestamps `2020-01-01 … now + 1 day`. Name the window,
reuse it, and widen it only for a field that genuinely holds historic or BC dates — saying so
in a comment where it is declared, so the width reads as a decision.

**Enforce at two layers, because the app is not the only writer.** A PHP guard cannot see a
raw-SQL import, a restored backup, or a hand-run `UPDATE`, which is exactly how the bad rows
arrive:

1. **App guard** — validate on the way in. `DateTimeImmutable::createFromFormat()` plus
   `getLastErrors()`, not `strtotime()`, which returns `false` for garbage and is happy to
   parse `'0000-00-00'`.
2. **DB `CHECK` constraint** on the column, in the migration. The only layer that survives an
   import.

MySQL makes this worse than it needs to be: `'0000-00-00'` is a *legal* value in a
non-strict-mode `DATE` column, and it is what a failed insert leaves behind. It then aborts
the statement the moment it reaches a typed intermediate — the failure surfaces nowhere near
the code that wrote it. Never write it, and never use `'1970-01-01'` or a far-future date to
mean "not set"; use `null`.

## Money is integer minor units or `DECIMAL`, never a float

PHP has no decimal type, so pick one and stay with it: integer *øre*/cents in the application
and `DECIMAL(18,2)` in the database, or `bcmath` for arithmetic. `0.1 + 0.2 !== 0.3` in PHP
exactly as everywhere else, and `round()` after the fact does not undo accumulated error.
Never `float` for a money column, a money property, or a running total.

## N+1: enforce it at boot, not with a scanner

`data-access.md` writes its N+1 warning for EF Core, where relation lazy loading is off by
default. **Laravel is the opposite case and the hazard is real here** — Eloquent lazy-loads
relations by default, so one touched inside a loop silently issues a query per row.

Do not try to catch that with a source scan; Laravel ships a stronger guard. In
`AppServiceProvider::boot()`:

```php
Model::preventLazyLoading(! app()->isProduction());
```

**This does not remove the ability to fetch a relation on demand — it removes the ability to
do it by accident.** The deliberate version is one call, and it works on a single model or a
whole collection with one query either way:

```php
$order->load('invoice');          // I need it now, and I am saying so
$orders->loadMissing('items');    // one query for the whole collection, not one per row
```

That is the genuine benefit of lazy loading — don't fetch what you don't need — kept, while
the failure mode is removed. What you lose is the *silence*.

The `! app()->isProduction()` argument is deliberate: a violation throws
`LazyLoadingViolationException` in development and test, where a missing `with([...])`
surfaces the first time the code runs, and stays disabled in production, where degrading a
live request to punish a developer mistake helps nobody.

**This is required in any Laravel app added to the estate**, and it is config rather than a
scanner rule for the same reason the `var` ban lives in `.editorconfig`: the strongest layer
that can hold a rule should hold it. Consider `preventSilentlyDiscardingAttributes()` and
`preventAccessingMissingAttributes()` alongside it — same call site, same class of silent bug.

## SQL is parameterised; output is escaped

- **Every query is a prepared statement with bound parameters.** No string interpolation into
  SQL, not even for an integer you "know" is safe, and not even in an admin-only path.
- **Escape at the point of output, by context.** `htmlspecialchars($x, ENT_QUOTES, 'UTF-8')`
  for HTML text, `urlencode()` in a URL, `json_encode()` for JSON. Escaping on the way *in*
  corrupts the stored data and still leaves the other contexts wrong.
- **Treat every superglobal as hostile** — `$_GET`, `$_POST`, `$_COOKIE`, `$_SERVER` and
  `$_FILES` alike. Validate the shape and the range, don't just check it is present.

## DRY: one canonical implementation, and every entry point converges on it

When two code paths solve the same problem, extract one named function both call. This
matters most where a piece of state can be reached several ways — the router, a form handler,
and a cron job all writing the same record. Every path calls the same helper, or you get
partial-update bugs where one stamps three columns and another stamps one.

Acceptable duplication: trivial one-liners, and structurally similar code solving genuinely
*different* problems.

## Guard clauses, not nested ifs

Validate preconditions at the top and `return`/`throw` early; the happy path runs at the
lowest indentation. A third level of nesting means restructure.

## Named constants over magic values

Every business-meaningful literal gets a name — a `const`, a class constant, or an enum
(PHP 8.1+ enums are preferred over string constants, and give you the compile-time check the
language otherwise lacks). Exempt: `0`, `1`, `true`, `''`.

## Danish bookkeeping retention (5 years)

Financial records under 5 years old cannot be deleted while the organisation is active. Check
record age before any destructive operation; offer archival instead.
