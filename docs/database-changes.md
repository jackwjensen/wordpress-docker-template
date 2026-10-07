---
audience: dev
type: how-to
---

# Change a site's database, and copy production's to local

WordPress has no migration framework like Laravel or Django. The approach:

- **Initial setup**: Duplicator on production, then sync the DB to local.
- **Plugin install/uninstall**: do it locally, commit the plugin files. WordPress runs `dbDelta()`
  on activation, so the schema converges.
- **Pull the production DB to local**: `./scripts/sync-db-from-prod.sh` (dumps, imports, URL
  replace). For serialized data, use `./dev.sh cli search-replace` instead of its SQL replace.
- **Never push the local DB to production** — WordPress and plugins upgrade their own schema.
  User content (posts, comments) lives only in production.

## Deploy-time PHP migrations

<!-- standards: docs-stale-symbol exempt -- migrate.php is a file a site adds to its own theme; the template ships none -->
For a one-time or idempotent change the admin cannot make, add `migrate.php` to the theme and
run it from the deploy workflow, after the health check:

```yaml
docker compose exec -T -u www-data wordpress wp eval-file wp-content/themes/<theme>/migrate.php || echo "Migration skipped"
```

`wp eval-file` bootstraps WordPress for you. A script run with plain `php` must bootstrap itself:

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

- **It must be idempotent** — safe to re-run on every deploy (conditional checks, or
  DELETE + INSERT).
- **Polylang needs `$_SERVER['HTTP_HOST']`** — without it Polylang throws a fatal error, so set
  it before `require wp-load.php`.

## Copy the production DB by hand (Windows)

If the sync scripts don't work (SSH passphrase prompts, no bash):

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
