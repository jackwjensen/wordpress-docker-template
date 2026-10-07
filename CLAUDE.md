# WordPress Docker Template

Claude context for this repo. It's a clone-and-own template for Dockerised WordPress sites: one OpenLiteSpeed container (WordPress 7.1 + lsphp 8.5, ready for LiteSpeed Cache), MySQL 8.4 LTS, local dev via Docker Compose, CI + GHCR releases, and an optional SSH deploy to any Docker host. The user-facing guide is in `README.md`; this file is the working context for Claude.

## Using this template

This repo is the template itself. To start a site from it:

1. Clone it, set `COMPOSE_PROJECT_NAME` in `.env` (copied from `.env.example`), and run `./dev.sh up` — see `README.md` ("Quick start").
2. Build the site locally; commit theme/plugin changes under `wp-content/`.
3. Deploy to your own server when ready — see `README.md` ("Deploy to your server"). Deployment stays dormant until the `DEPLOY_HOST` / `DEPLOY_SSH_KEY` secrets are set, so a fresh clone never produces a failing deploy.
4. To move it onto another account and/or track this repo for updates, see `README.md` ("Make it your own").

Conventions worth knowing:
- **One site per repo**; each sets a unique `COMPOSE_PROJECT_NAME`, which names the production containers `<project>-wordpress` / `<project>-mysql` so a reverse proxy can route to the right one.
- **Migrating an existing site?** Use Duplicator — see the gotchas below and `README.md` ("Migrating an existing site").
- **Per-repo deploy key**: GitHub rejects reusing one SSH deploy key across repos; give each its own (and, if several share a host, an SSH config alias so git picks the right one).

## Important Gotchas

- **DB host is `mysql`, not `localhost`** — inside Docker, each container has its own network. `localhost` inside the WordPress container refers to itself. The MySQL container is reachable via Docker DNS as `mysql` (the service name from docker-compose.yml).
- **Reverse-proxy target is port 80, not 8080** — OpenLiteSpeed's production listener is :80. It also listens on :8080, which local dev publishes as `8080:8080` so WordPress's loopback to `http://localhost:8080` (WP-Cron, Site Health) reaches the same container.
- **lsphp cannot see the container's environment** — `getenv()` returns false under LSAPI (tested on Ellengaard, 2026-10-07), so the official image's runtime-`getenv` `wp-config.php` cannot work. `docker/openlitespeed/make-wp-config.php` writes `wp-config.php` with literal values from the `WORDPRESS_*` variables at **every container start**, keeping the existing secret keys and table prefix. Never edit `wp-config.php` in the container — change the compose files and restart. `WORDPRESS_DEBUG` is parsed as a boolean (`"false"` is off — the official image treated any non-empty value as on).
- **Permalinks live in `.htaccess`** — OpenLiteSpeed reads it (`rewrite { enable 1; autoLoadHtaccess 1 }` in `vhconf.conf`). WP-CLI runs outside a web request, so WordPress can't tell the server reads `.htaccess`; `/etc/wp-cli/config.yml` (`apache_modules: [mod_rewrite]`, via `WP_CLI_CONFIG_PATH`) makes `wp rewrite flush --hard` write the rules.
- **Core, `wp-config.php` and `.htaccess` live in the `wp-html` volume** — so a deploy keeps logins, permalinks and LiteSpeed Cache's rules. The entrypoint copies core from the image into an empty volume, and replaces core's files (never `wp-content`, `wp-config.php`, `.htaccess`) when the image's WordPress is newer than the volume's; it never downgrades. So a Dependabot base-image bump still updates core on deploy.
- **OpenLiteSpeed logs are files, not `docker compose logs`** — `/usr/local/lsws/logs/` (`error.log`, `access.log`, `stderr.log` = PHP's errors). `dev.sh logs` tails them.
- **LiteSpeed Cache's page cache needs a LiteSpeed server** — the plugin only sends `X-LiteSpeed-Cache-Control` headers; the server's cache module (`module cache` in `httpd_config.conf`) does the caching and sets `X-LSCACHE` (`on,crawler`) in `$_SERVER`, which tells the plugin it may cache. nginx and Apache ignore the headers. On WooCommerce shops, **"Cache REST API" must be off** (`wp litespeed-option set cache-rest 0`) — on by default, it served the Store API cart from the cache (Ellengaard, 2026-10-07).
- **No HTTPS listener and no http→https redirect locally, ever** — port 8080 is shared by every local project, and a redirect on it is remembered by the browser for all of them.
- **Duplicator files go INSIDE the container** — files placed on the server filesystem aren't served by OpenLiteSpeed. Use `docker compose cp` or the `import-duplicator.sh` script.
- **wp-content permissions** — the container runs OpenLiteSpeed and lsphp as `www-data`. After any file operations, fix ownership: `docker compose exec wordpress chown -R www-data:www-data /var/www/html/wp-content`
- **Uploads subdirectories** — after a fresh DB import, plugins may expect subdirectories under `wp-content/uploads/` that don't exist in the volume. Fix with: `docker compose exec wordpress chown -R www-data:www-data /var/www/html/wp-content/uploads` (the plugin will create its subdirectory on next request once permissions are correct).
- **WordPress install wizard must be completed first** — on a fresh container, WordPress shows its install wizard before any other URL works. Complete it with throwaway values before running Duplicator.
- **GitHub deploy keys are unique per repo** — the same SSH public key cannot be added to multiple repos. Use SSH config host aliases to map each repo to its own key.
- **Production .env is critical** — without it, containers start in dev mode (ports exposed, not on the proxy network). The `setup-server.sh` script creates this automatically.
- **WP-CLI IS in the WordPress image** (since the OpenLiteSpeed switch) — pinned and checksum-verified, behind a `wp` wrapper that runs it on lsphp's CLI with PHP 8.5 deprecation notices hidden. Run it as the web server user: `docker compose exec -u www-data wordpress wp <command>` (locally `dev.sh cli <command>`), in production too. There is no separate `wpcli` service any more.
- **Table prefix** — Duplicator writes its own `wp-config.php` with the imported site's prefix; the generator keeps that prefix at every restart. `WORDPRESS_TABLE_PREFIX` overrides it. Only `docker compose down -v` (which wipes the `wp-html` volume) loses it — avoid resetting volumes after an import.
- **Windows has no `export` or Git Bash by default** — the sync-db-from-prod.sh script requires bash with `export`. Use `sync-db-from-prod.bat` on Windows, or do the steps manually (see "Manual DB Sync on Windows" below).
- **Reverse-proxy "Force SSL" can cause redirect loops** — when the proxy terminates SSL and forwards HTTP to the container, the generated `wp-config.php` already turns `X-Forwarded-Proto: https` into `$_SERVER['HTTPS']`. Don't enable "Force SSL" (e.g. in Nginx Proxy Manager) for the upstream.

## Manual DB Sync on Windows

If the sync scripts don't work (SSH passphrase prompts, no bash), do it step by step:

1. **On the server** (SSH session):
   ```bash
   cd /opt/apps/<site-name>
   docker compose exec -T mysql mysqldump -uroot -p$(grep MYSQL_ROOT_PASSWORD .env | cut -d= -f2) wordpress > /tmp/<site-name>-dump.sql
   ```

2. **On Windows** (cmd):
   ```cmd
   scp root@<server-ip>:/tmp/<site-name>-dump.sql backups\prod_sync.sql
   docker compose exec -T mysql mysql -uroot -pWordPress_Dev123! wordpress < backups\prod_sync.sql
   docker compose exec mysql mysql -uroot -pWordPress_Dev123! wordpress -e "UPDATE wp_options SET option_value='http://localhost:8080' WHERE option_name IN ('siteurl','home');"
   docker compose exec wordpress chown -R www-data:www-data /var/www/html/wp-content/uploads
   ```

## Architecture

- **OpenLiteSpeed + lsphp 8.5, one container** (Jack, 2026-10-07: the WordPress sites Allegro IT hosts run OpenLiteSpeed + the LiteSpeed Cache plugin; he has bad experiences with W3 Total Cache and WP Rocket). Carried over from Ellengaard (`ellengaard-dk` commit `20b8a09`), which moved from nginx + PHP-FPM the same day; this template moved from Apache. `Dockerfile` = `litespeedtech/openlitespeed:1.9.2-lsphp85` (Ubuntu 26.04, PHP 8.5.9; extensions a superset of the official image's except `pdo_sqlite`/`sqlite3`) + curl + pinned WP-CLI + `config/uploads.ini` (as `mods-available/zz-uploads.ini`, lsphp's ini scan dir); WordPress core comes from the official `wordpress:7.1-php8.5-fpm` image (multi-stage `core`, with `wp-config-docker.php` removed). `docker/openlitespeed/` = server config (`httpd_config.conf`: `www-data`, `disableWebAdmin 1`, :8080 + :80 plain HTTP, the cache module), the vhost (`vhconf.conf`: `.htaccess` rewrites), `entrypoint.sh` (core install/upgrade → `make-wp-config.php` → the base image's `/entrypoint.sh`, which starts `lswsctrl`, runs `"$@"`, then loops), `wp-cli.yml`, `wp.sh`. `php` on the PATH is lsphp's CLI. Tagged releases publish the image to GHCR (`ghcr.io/jackwjensen/wordpress-docker-template`).
- MySQL 8.4 LTS database
- WP-CLI in the image: `dev.sh cli <command>` locally, `docker compose exec -u www-data wordpress wp <command>` anywhere
- CI builds + smoke-tests the image on every push/PR; a `v*` tag publishes it to GHCR (keyless, built-in `GITHUB_TOKEN`)

## Docker Compose Structure

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base config + local dev (ports 8080:8080 and `127.0.0.1:3307` for MySQL, debug on, `wp-html` volume, **no `restart:`**) |
| `docker-compose.production.yml` | Production overrides (no ports, joins `nginx-proxy-network`, debug off, `DISALLOW_FILE_EDIT`, `restart: unless-stopped` on every service) |

Local ports follow the Allegro IT dev port registry (engineering-standards pack, `claude\rules\infrastructure.md`): 8080 the site, `127.0.0.1:3307` the database — never 3306, never the short `"3307:3306"` form (that binds every interface). All local projects share these numbers and only one runs at a time, so the base file has **no restart policy**: a self-restarting stack would come back after a Docker Desktop restart and hold the ports against the next project. `restart:` belongs in the production overlay only, on every service; both overlays' services also need `ports: !override []` (Compose merges `ports`).

Merged in production via `COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml` in the server's `.env`.

The `wordpress` service is built from the repo `Dockerfile` (locally and on the server via `docker compose up --build`); only `mysql` uses an upstream image directly. `config/uploads.ini` is baked into the image, not bind-mounted. Both files set `WP_CACHE` true (for LiteSpeed Cache; harmless without it).

### Container naming
Production containers are named `${COMPOSE_PROJECT_NAME}-wordpress` and `${COMPOSE_PROJECT_NAME}-mysql`. This is how the reverse proxy routes to the correct site — each site has a unique `COMPOSE_PROJECT_NAME`.

### Network
- Production joins the reverse proxy's external network (default `nginx-proxy-network`)
- MySQL stays on the default internal network only (not exposed to the proxy)

## Deployment

- **Trigger**: Push to `master` (or manual workflow dispatch)
- **Method**: GitHub Actions SSHes into any Docker host
- **Server path**: `DEPLOY_PATH` variable, default `/opt/apps/<repo-name>`
- **Process**: git pull → docker compose up --build --force-recreate -d → HTTP health check (`scripts/healthcheck.sh`, probed inside the container)
- **Rollback**: Automatic on failure (reverts to previous commit, rebuilds + recreates containers)
- **Secrets to activate**: `DEPLOY_HOST`, `DEPLOY_SSH_KEY` (a per-repo deploy key); optional `DEPLOY_USER` / `DEPLOY_PATH` variables (default `root` / `/opt/apps/<repo>`)
- **Dormant until configured**: the deploy step runs only when `DEPLOY_HOST` is set, so a fresh clone (no secret) skips deploy and the job still succeeds — cloning never produces a red deploy.
- **Reference setup**: Allegro IT runs these behind Nginx Proxy Manager on a Hetzner VPS; any Docker host + reverse proxy works the same way.

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request:
- **lint**: ShellCheck (scripts, `dev.sh`, tests, `docker/openlitespeed/*.sh`), Hadolint (`Dockerfile`), `docker compose config` validation (base + production merge), actionlint, and the health-check regression test.
- **build-and-smoke**: builds the image and runs `tests/smoke.sh` (see Testing).

## Releasing

Push a SemVer tag (`git tag v1.2.0 && git push origin v1.2.0`). `.github/workflows/release.yml` smoke-tests, then builds and publishes the image to **GHCR** (`ghcr.io/jackwjensen/wordpress-docker-template`, tags `1.2.0`/`1.2`/`1`/`latest`) using the built-in `GITHUB_TOKEN` — **keyless, no stored secret** — attaches a build-provenance attestation, and drafts a GitHub Release. The GHCR package must be made public once (Packages → wordpress-docker-template → Package settings) for anonymous pulls.

## Testing

- `tests/smoke.sh` — end-to-end: build + up, then assert `Server: LiteSpeed` on :8080 and :80, the upload limit (CLI and lsphp), `X-LSCACHE` + a real `X-LiteSpeed-Cache: hit`, a WP-CLI install against MySQL, a pretty permalink through `.htaccess`, salts + an imported table prefix surviving a restart, `WORDPRESS_DEBUG=false` → off, and core upgraded from the image but never downgraded. Runs as Compose project `wordpress-smoke` with no published ports (probes inside the container via `COMPOSE_PROJECT_NAME`/`COMPOSE_FILE`), so it never deletes the dev stack's volumes and never needs host port 8080 — safe to run locally while another project holds 8080.
- `tests/healthcheck.test.sh` — regression test proving `scripts/healthcheck.sh` fails when WordPress is not serving (the old "count running containers" check did not). Fast; no Docker needed.
- `scripts/healthcheck.sh <url> [retries] [delay] [compose-service]` — the single health probe shared by the smoke test, the regression test, the deploy workflow, and `setup-server.sh`. The 4th arg curls *inside* a compose service (used in production, which publishes no host port).

## Dependency & Community Hygiene

- **Dependabot** (`.github/dependabot.yml`): grouped, monthly updates for the `docker` (base image + compose tags) and `github-actions` ecosystems.
- **Community health**: `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue/PR templates, `CODEOWNERS`, `.editorconfig`.
- All GitHub Actions are pinned to released versions and kept current by Dependabot.

## Server Layout (reference)

A simple, scalable layout: one directory per site under a common root (default `/opt/apps/<repo>`), each its own Compose project:
```
/opt/apps/
├── <wp-site-1>/
├── <wp-site-2>/
└── <wp-site-3>/
```

A reverse proxy handles TLS and routing:
- Each WordPress container joins the proxy's external network (default `nginx-proxy-network`)
- The proxy maps each domain → `<compose-project-name>-wordpress:80`

(Allegro IT runs this with Nginx Proxy Manager on a Hetzner VPS.)

## What's Version Controlled

| Path | Tracked | Notes |
|------|---------|-------|
| `wp-content/themes/` | Yes | Theme files |
| `wp-content/plugins/` | Yes | Plugin files |
| `config/` | Yes | PHP config (upload limits etc.) |
| `wp-content/uploads/` | No | Docker volume, sync separately |
| `.env` | No | Contains passwords, created per environment |
| `backups/` | No | Local DB dumps |
| `Dockerfile` | Yes | Builds the WordPress image |
| `docker/openlitespeed/` | Yes | OpenLiteSpeed server + vhost config, entrypoint, wp-config.php generator, WP-CLI config |
| `tests/` | Yes | Smoke + regression tests |
| `.github/` | Yes | CI/deploy/release workflows, Dependabot, templates |

## DB Migration Strategy

WordPress doesn't have a migration framework like Laravel/Django. The approach:
- **Initial setup**: Use Duplicator on production, then sync DB to local.
- **Plugin install/uninstall**: Do locally, commit plugin files. WordPress auto-runs `dbDelta()` on activation — schema converges.
- **Pull prod DB to local**: Use `./scripts/sync-db-from-prod.sh` (dumps, imports, URL search-replace).
- **Never push local DB to prod** — let WordPress/plugins handle their own schema upgrades.
- **User content** (posts, comments) lives only in production. Sync prod → local when you need fresh data.

### Deploy-time PHP Migrations

For one-time or idempotent database changes that can't be done through the WordPress admin, add a `migrate.php` script to the theme and run it from the deploy workflow:

```yaml
# In deploy.yml, after health check:
docker compose exec -T wordpress php wp-content/themes/<theme>/migrate.php || echo "Migration skipped"
```

The script bootstraps WordPress and runs DB operations:
```php
<?php
if ( ! defined( 'ABSPATH' ) ) {
    $_SERVER['HTTP_HOST']   = $_SERVER['HTTP_HOST'] ?? 'localhost';
    $_SERVER['REQUEST_URI'] = $_SERVER['REQUEST_URI'] ?? '/';
    require dirname( __DIR__, 3 ) . '/wp-load.php';
}
global $wpdb;
// ... your migration logic here ...
```

Key rules for deploy migrations:
- **Must be idempotent** — safe to re-run on every deploy (use conditional checks or DELETE+INSERT patterns).
- **Polylang requires `$_SERVER['HTTP_HOST']`** — without it, Polylang throws a fatal error. Always set it before `require wp-load.php`.
- **WP-CLI is in the image now** — a deploy step can also run `docker compose exec -T -u www-data wordpress wp eval-file wp-content/themes/<theme>/migrate.php`, which bootstraps WordPress for you.

## Working with Elementor

When building a custom child theme alongside Elementor, several non-obvious conflicts arise:

### Elementor Theme Builder vs Custom Templates

Elementor Pro's Theme Builder stores header, footer, single post, and archive templates as `elementor_library` posts with `_elementor_conditions` postmeta. The condition `include/general` (header/footer) or `include/singular` (single post) makes Elementor inject its template on ALL matching pages — **independently of the WordPress template hierarchy**. This means your custom `header.php`, `single.php`, and `page.php` files will be overridden or doubled.

**Fix**: Remove conflicting Elementor template conditions from the database:
```php
// In migrate.php — remove Elementor conditions for templates that conflict with theme files
$templates_to_disable = [ /* post IDs of Header, Footer, Single Post, Single Page templates */ ];
$ids = implode( ',', array_map( 'intval', $templates_to_disable ) );
$wpdb->query( "DELETE FROM {$wpdb->postmeta} WHERE post_id IN ($ids) AND meta_key = '_elementor_conditions'" );
$wpdb->query( "DELETE FROM {$wpdb->options} WHERE option_name LIKE '%elementor%conditions%'" );
```

To find the template IDs:
```sql
SELECT p.ID, p.post_title, pm.meta_value
FROM wp_posts p JOIN wp_postmeta pm ON p.ID = pm.post_id
WHERE p.post_type = 'elementor_library' AND pm.meta_key = '_elementor_conditions';
```

### Overriding Elementor's Template Include

Elementor hooks into `template_include` at a high priority. To reclaim control, register your own filter at priority **999**:
```php
add_filter( 'template_include', function( $template ) {
    if ( is_home() )             return locate_template( 'home.php' ) ?: $template;
    if ( is_category() )         return locate_template( 'category.php' ) ?: $template;
    if ( is_singular( 'post' ) ) return locate_template( 'single.php' ) ?: $template;
    // For pages: only override non-Elementor pages (let Elementor render its own pages like the front page)
    if ( is_page() && ! is_front_page() ) {
        $is_elementor = get_post_meta( get_queried_object_id(), '_elementor_edit_mode', true ) === 'builder';
        if ( ! $is_elementor ) return locate_template( 'page.php' ) ?: $template;
    }
    return $template;
}, 999 );
```

### Elementor CSS Specificity

Elementor adds inline styles and high-specificity selectors to its widget wrappers (`.elementor-element`, `.e-con`, `.elementor-widget`). When your theme CSS needs to override Elementor's spacing or layout, use `!important` on layout properties:
```css
.my-content-area .elementor-element { margin: 0 !important; padding: 0 !important; }
.my-content-area h2.elementor-heading-title { border-top: 1px solid #e2e8f0 !important; }
```

### Modifying Elementor Data via PHP

Elementor stores page content as JSON in the `_elementor_data` postmeta. When modifying it programmatically:

- **Never use `update_post_meta()` with `wp_slash()`** — it can double-escape the JSON and corrupt it. Use `$wpdb` directly:
  ```php
  // DELETE + INSERT is more reliable than UPDATE for large JSON blobs
  $wpdb->query( $wpdb->prepare(
      "DELETE FROM {$wpdb->postmeta} WHERE post_id = %d AND meta_key = '_elementor_data'", $post_id
  ) );
  $wpdb->query( $wpdb->prepare(
      "INSERT INTO {$wpdb->postmeta} (post_id, meta_key, meta_value) VALUES (%d, '_elementor_data', %s)",
      $post_id, $json_string
  ) );
  ```
- **Clear ALL Elementor caches after updating** — Elementor caches rendered output in multiple places:
  ```php
  clean_post_cache( $post_id );
  wp_cache_flush();
  delete_post_meta( $post_id, '_elementor_css' );
  delete_post_meta( $post_id, '_elementor_page_assets' );
  // Also delete CSS files in uploads/elementor/css/post-{ID}*
  ```
- **Also clear cache via admin UI** — after deploy, go to Elementor → Tools → Clear Files & Data. This can be automated by deleting the CSS files in the migration script, but the admin button is the most thorough option.

## Working with Polylang

If the site uses Polylang for multilingual support:

### Language-Aware Navigation

Use `pll_current_language()` to detect the active language and render appropriate nav links:
```php
$is_en = function_exists( 'pll_current_language' ) && pll_current_language() === 'en';
// Then use $is_en to conditionally render nav links with correct URLs and labels
```

### Polylang Permalink Structure

With `hide_default: true` (common config), the default language has no URL prefix while other languages get `/en/`, `/de/`, etc. Post URLs follow the pattern:
- Danish: `/category/post-slug/`
- English: `/en/category/post-slug/`

### Static Front Page with Polylang

When using a static front page (`page_on_front`), Polylang uses the translation relationship to determine which page to show for each language. Ensure:
1. Both language pages exist and are linked as translations in Polylang.
2. The `post_translations` taxonomy correctly maps between the two pages.
3. The language switcher (`pll_the_languages()`) generates correct URLs for the front page.

### Polylang and CLI Scripts

Polylang requires `$_SERVER['HTTP_HOST']` and `$_SERVER['REQUEST_URI']` to be set when loading WordPress outside of a web request. Always set these before `require wp-load.php` in migration scripts or CLI tools — otherwise Polylang throws a fatal error.

## Development Commands

| Command | Description |
|---------|-------------|
| `dev.bat up` | Start containers |
| `dev.bat down` | Stop containers |
| `dev.bat reset` | Destroy volumes and restart fresh |
| `dev.bat logs` | Follow OpenLiteSpeed's error log and PHP's errors |
| `dev.bat cli plugin list` | Run WP-CLI commands (in the container, as `www-data`) |
| `dev.bat cli litespeed-purge all` | Purge LiteSpeed Cache's page cache |
| `dev.bat backup` | Dump DB to `backups/` |
| `dev.bat restore backups/file.sql` | Restore DB from dump |

## Files Reference

| File | Purpose |
|------|---------|
| `Dockerfile` | Builds the WordPress image (OpenLiteSpeed + lsphp 8.5, core from the official image, WP-CLI, uploads.ini, HEALTHCHECK) |
| `docker/openlitespeed/httpd_config.conf` | OpenLiteSpeed server config (www-data, no web admin, :8080 + :80, cache module) |
| `docker/openlitespeed/vhconf.conf` | The virtual host (`.htaccess` rewrites, dotfiles hidden) |
| `docker/openlitespeed/entrypoint.sh` | Container start: core install/upgrade, wp-config.php, then OpenLiteSpeed |
| `docker/openlitespeed/make-wp-config.php` | Writes wp-config.php from `WORDPRESS_*` (keeps salts + table prefix) |
| `docker/openlitespeed/wp-cli.yml`, `wp.sh` | WP-CLI config (`mod_rewrite` → `.htaccess`) and the `wp` wrapper |
| `tests/docker-compose.smoke.yml` | Smoke-test overrides (no volumes, no published ports) |
| `docker-compose.yml` | Base + local dev config |
| `docker-compose.production.yml` | Production overrides (no ports, nginx-proxy-network) |
| `.env.example` | Template for `.env` |
| `.github/workflows/ci.yml` | Lint + build + smoke test on push/PR |
| `.github/workflows/deploy.yml` | GitHub Actions deploy-on-push |
| `.github/workflows/release.yml` | Tag `v*` → build + publish to GHCR + GitHub Release |
| `.github/dependabot.yml` | Grouped monthly updates (docker, github-actions) |
| `config/uploads.ini` | PHP upload limits (256M) |
| `scripts/setup-server.sh` | One-time server setup (clones, creates .env, builds + starts containers, fixes permissions) |
| `scripts/import-duplicator.sh` | Copy Duplicator files into container; points to DB credentials in .env |
| `scripts/sync-db-from-prod.sh` | Pull production DB to local (bash/Linux/Mac) |
| `scripts/sync-db-from-prod.bat` | Pull production DB to local (Windows cmd) |
| `scripts/healthcheck.sh` | Shared HTTP health probe (CI, deploy, setup) |
| `tests/smoke.sh` | End-to-end smoke test |
| `tests/healthcheck.test.sh` | Regression test for the deploy health check |
| `dev.bat` / `dev.sh` | Local development helper scripts |
