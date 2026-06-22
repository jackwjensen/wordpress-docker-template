@echo off
setlocal
REM Pull production database to local development (Windows).
REM Usage: sync-db-from-prod.bat <site-name> [prod-domain] [local-url]
REM Requires: DEPLOY_HOST env var (set DEPLOY_HOST=203.0.113.10) and SSH access.
REM Mirrors scripts/sync-db-from-prod.sh.
REM
REM CAVEAT: URL replacement uses raw MySQL REPLACE(), which is NOT
REM serialization-aware. For sites with heavy serialized option/meta data,
REM run `wp search-replace` from a host that has WP-CLI instead.

if "%~1"=="" (
    echo Usage: sync-db-from-prod.bat ^<site-name^> [prod-domain] [local-url]
    echo Requires the DEPLOY_HOST env var to be set.
    goto end
)
if "%DEPLOY_HOST%"=="" (
    echo ERROR: set DEPLOY_HOST first, e.g.  set DEPLOY_HOST=203.0.113.10
    goto end
)

set SITE_NAME=%~1
set PROD_DOMAIN=%~2
set LOCAL_URL=%~3
if "%LOCAL_URL%"=="" set LOCAL_URL=http://localhost:8080
set DEV_DB_PASSWORD=WordPress_Dev123!

if not exist backups mkdir backups

echo Step 1: Dumping production database...
echo   (You may be prompted for your SSH passphrase)
ssh root@%DEPLOY_HOST% "cd /opt/apps/%SITE_NAME% && MYSQL_PWD=$(grep MYSQL_ROOT_PASSWORD .env | cut -d= -f2) docker compose exec -T -e MYSQL_PWD mysql mysqldump -uroot wordpress" > backups\prod_sync.sql
if errorlevel 1 (
    echo ERROR: Failed to dump production database. Check SSH connection.
    goto end
)

echo Step 2: Importing into local database...
docker compose exec -T -e MYSQL_PWD=%DEV_DB_PASSWORD% mysql mysql -uroot wordpress < backups\prod_sync.sql

echo Step 3: Fixing URLs...
if not "%PROD_DOMAIN%"=="" (
    docker compose exec -T -e MYSQL_PWD=%DEV_DB_PASSWORD% mysql mysql -uroot wordpress -e "UPDATE wp_options SET option_value = REPLACE(option_value, 'https://%PROD_DOMAIN%', '%LOCAL_URL%') WHERE option_value LIKE '%%%PROD_DOMAIN%%%'; UPDATE wp_options SET option_value = REPLACE(option_value, 'http://%PROD_DOMAIN%', '%LOCAL_URL%') WHERE option_value LIKE '%%%PROD_DOMAIN%%%';"
    docker compose exec -T -e MYSQL_PWD=%DEV_DB_PASSWORD% mysql mysql -uroot wordpress -e "UPDATE wp_posts SET post_content = REPLACE(post_content, 'https://%PROD_DOMAIN%', '%LOCAL_URL%') WHERE post_content LIKE '%%%PROD_DOMAIN%%%'; UPDATE wp_posts SET guid = REPLACE(guid, 'https://%PROD_DOMAIN%', '%LOCAL_URL%') WHERE guid LIKE '%%%PROD_DOMAIN%%%';"
    docker compose exec -T -e MYSQL_PWD=%DEV_DB_PASSWORD% mysql mysql -uroot wordpress -e "UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, 'https://%PROD_DOMAIN%', '%LOCAL_URL%') WHERE meta_value LIKE '%%%PROD_DOMAIN%%%';"
)

echo Step 4: Fixing uploads permissions...
docker compose exec -T wordpress chown -R www-data:www-data /var/www/html/wp-content/uploads

echo.
echo Done! Local DB is now a copy of production.
echo Open %LOCAL_URL%

:end
endlocal
