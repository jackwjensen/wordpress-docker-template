@echo off
setlocal

if "%1"=="" goto up
if "%1"=="up" goto up
if "%1"=="down" goto down
if "%1"=="stop" goto down
if "%1"=="reset" goto reset
if "%1"=="logs" goto logs
if "%1"=="cli" goto cli
if "%1"=="backup" goto backup
if "%1"=="restore" goto restore
echo Unknown command: %1
echo Usage: dev.bat [up^|down^|reset^|logs^|cli^|backup^|restore]
goto end

:up
echo Starting WordPress...
docker compose up --build -d
echo.
echo WordPress: http://localhost:8080
echo.
goto end

:down
docker compose down
goto end

:reset
docker compose down -v
docker compose up --build -d
echo.
echo WordPress reset complete: http://localhost:8080
goto end

:logs
rem OpenLiteSpeed writes its errors and PHP's to files in the container, not to docker logs.
docker compose exec wordpress tail -n 50 -F /usr/local/lsws/logs/error.log /usr/local/lsws/logs/stderr.log
goto end

:cli
rem WP-CLI inside the WordPress container, as the web server user. cmd's %* ignores shift
rem and %1.. split on "=", so the arguments are %* with the leading "cli" cut off.
set "WP_ARGS=%*"
set "WP_ARGS=%WP_ARGS:*cli=%"
docker compose exec -u www-data wordpress wp %WP_ARGS%
goto end

:backup
echo Backing up database...
if not exist backups mkdir backups
docker compose exec mysql mysqldump -uroot -p"WordPress_Dev123!" wordpress > backups\backup_%date:~-4%%date:~3,2%%date:~0,2%.sql
echo Backup saved to backups\
goto end

:restore
if "%2"=="" (
    echo Usage: dev.bat restore backups\filename.sql
    goto end
)
echo Restoring database from %2...
docker compose exec -T mysql mysql -uroot -p"WordPress_Dev123!" wordpress < %2
echo Restore complete.
goto end

:end
endlocal
