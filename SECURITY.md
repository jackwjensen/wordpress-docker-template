# Security Policy

## Supported versions

This is a template repository. Security fixes land on the default branch
(`master`) and in the most recent tagged release — always base new sites on the
latest release.

| Version                            | Supported |
| ---------------------------------- | --------- |
| latest `master` / newest release   | ✅        |
| older tags                         | ❌        |

The shipped stack tracks current, supported upstream versions (WordPress 7.1,
OpenLiteSpeed 1.9, PHP 8.5, MySQL 8.4 LTS), and Dependabot proposes updates monthly.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

- Preferred: GitHub's **private vulnerability reporting** ("Report a
  vulnerability" under the repository's **Security** tab).
- Or email **kontakt@allegroit.dk** with details and reproduction steps.

We aim to acknowledge reports within 5 business days and will agree a disclosure
timeline with you. Please allow a reasonable window to ship a fix before any
public disclosure.

## Scope

This repository provides Docker and CI scaffolding around the official WordPress
image. Vulnerabilities in WordPress core, PHP, or MySQL themselves should be
reported to their respective projects; we track and pull in fixed upstream
images as they are released.
