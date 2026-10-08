# syntax=docker/dockerfile:1

# Allegro IT WordPress image: OpenLiteSpeed + lsphp 8.5, one container that serves HTTP itself.
#
# OpenLiteSpeed, because the sites Allegro IT hosts run the LiteSpeed Cache plugin, and its page
# cache only works on a LiteSpeed web server — nginx and Apache ignore the plugin's
# X-LiteSpeed-Cache-Control headers (README, "Page cache: LiteSpeed Cache"). Local dev,
# production and CI all build this image; tagged releases publish it to GHCR.

# WordPress core and nothing else: the official image's /usr/src/wordpress. The entrypoint
# installs it into the wp-html volume, and upgrades the volume's core when this stage is newer.
# Its wp-config-docker.php reads the environment on every request, which lsphp cannot — dropped;
# docker/openlitespeed/make-wp-config.php writes wp-config.php instead.
FROM wordpress:7.1-php8.5-fpm AS core
RUN rm /usr/src/wordpress/wp-config-docker.php

FROM litespeedtech/openlitespeed:1.9.2-lsphp85

# curl: the container HEALTHCHECK below, the deploy-time health probe (scripts/healthcheck.sh
# in "compose service" mode) and the WP-CLI download.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# `php` on the PATH is lsphp's own CLI — the same PHP build and ini files the site runs on.
RUN ln -s /usr/local/lsws/lsphp85/bin/php /usr/local/bin/php

# WP-CLI, pinned and checksum-verified (sha256 from the release's own .sha256 asset), behind a
# `wp` wrapper. pipefail so a failed download cannot be masked by the checksum pipe.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG WP_CLI_VERSION=2.12.0
ARG WP_CLI_SHA256=ce34ddd838f7351d6759068d09793f26755463b4a4610a5a5c0a97b68220d85c
RUN mkdir -p /usr/local/lib/wp-cli \
    && curl -fsSL -o /usr/local/lib/wp-cli/wp-cli.phar \
        "https://github.com/wp-cli/wp-cli/releases/download/v${WP_CLI_VERSION}/wp-cli-${WP_CLI_VERSION}.phar" \
    && echo "${WP_CLI_SHA256}  /usr/local/lib/wp-cli/wp-cli.phar" | sha256sum -c -
COPY --chmod=755 docker/openlitespeed/wp.sh /usr/local/bin/wp
# WP-CLI is not a web request, so WordPress cannot see that the server reads .htaccess.
# This tells it, so `wp rewrite flush --hard` writes the permalink rules as the admin would.
COPY docker/openlitespeed/wp-cli.yml /etc/wp-cli/config.yml
ENV WP_CLI_CONFIG_PATH=/etc/wp-cli/config.yml

# PHP upload / execution limits (large media uploads + Duplicator migration packages), loaded
# after lsphp's own ini files. Baked into the image so the limits travel with it.
COPY config/uploads.ini /usr/local/lsws/lsphp85/etc/php/8.5/mods-available/zz-uploads.ini

# The server configuration: one virtual host for /var/www/html on :8080 (local) and :80
# (production, behind a reverse proxy), PHP and the files as www-data, no web admin.
RUN rm -rf /usr/local/lsws/conf/vhosts/Example
COPY docker/openlitespeed/httpd_config.conf /usr/local/lsws/conf/httpd_config.conf
COPY docker/openlitespeed/vhconf.conf /usr/local/lsws/conf/vhosts/wordpress/vhconf.conf

COPY --from=core --chown=www-data:www-data /usr/src/wordpress /usr/src/wordpress
COPY docker/openlitespeed/make-wp-config.php /usr/local/lib/wordpress-docker/make-wp-config.php
COPY --chmod=755 docker/openlitespeed/entrypoint.sh /usr/local/bin/wordpress-entrypoint

# Everything runs as www-data — OpenLiteSpeed, lsphp, the entrypoint, WP-CLI. Docker lets an
# unprivileged process bind :80 inside the container (net.ipv4.ip_unprivileged_port_start=0),
# so root buys nothing here. OpenLiteSpeed gets the directories it reads and writes; the
# docroot and wp-content's mount points are created owned by www-data, so a NEW named volume
# mounted there is seeded with that ownership (Docker copies it from the image).
#
# The container runs read-only (docker-compose.yml). OpenLiteSpeed writes parsed copies of its
# configuration into conf/ and a download into admin/conf/ at every start, so those two are
# tmpfs mounts, and the configuration itself is kept in *.image here and copied in by the
# entrypoint — a volume there would freeze the first image's configuration forever.
RUN chown -R www-data:www-data \
        /usr/local/lsws/conf /usr/local/lsws/admin /usr/local/lsws/logs /usr/local/lsws/tmp \
        /usr/local/lsws/cachedata /usr/local/lsws/cgid /usr/local/lsws/autoupdate \
    && cp -a /usr/local/lsws/conf /usr/local/lsws/conf.image \
    && cp -a /usr/local/lsws/admin/conf /usr/local/lsws/admin/conf.image \
    && mkdir -p /var/www/html/wp-content/uploads /var/www/html/wp-content/themes \
        /var/www/html/wp-content/plugins \
    && chown -R www-data:www-data /var/www/html
# /usr/local/bin first: the base image's PATH lists it LAST, so its own unwrapped
# /usr/bin/wp would shadow the pinned, checksum-verified WP-CLI and wrapper above.
# WP-CLI's download cache: www-data's home is not writable in the read-only container.
ENV PATH="/usr/local/bin:${PATH}" \
    WP_CLI_CACHE_DIR=/tmp/wp-cli-cache
# www-data, by number (Ubuntu's uid/gid 33): a name may not resolve on the host, and the
# compose tmpfs mounts are given to uid=33 to match.
USER 33:33

WORKDIR /var/www/html
EXPOSE 80 8080
ENTRYPOINT ["/usr/local/bin/wordpress-entrypoint"]

# Report real health: a fresh install legitimately 302-redirects to the install wizard
# (curl -f treats 2xx/3xx as success, 5xx as failure). Exec (JSON) form per hadolint DL3025;
# the explicit `sh -c` keeps `|| exit 1`, which maps any curl failure code onto Docker's
# "unhealthy" exit status 1.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD ["sh", "-c", "curl -fsS -o /dev/null http://127.0.0.1/ || exit 1"]

# OCI metadata. The release workflow injects version/revision labels via
# docker/metadata-action; these are sensible defaults for local + CI builds.
LABEL org.opencontainers.image.title="wordpress-docker-template" \
      org.opencontainers.image.description="Production-ready Docker WordPress (WordPress 7.1 + OpenLiteSpeed + PHP 8.5) template by Allegro IT" \
      org.opencontainers.image.vendor="Allegro IT ApS" \
      org.opencontainers.image.url="https://allegroit.dk/" \
      org.opencontainers.image.source="https://github.com/jackwjensen/wordpress-docker-template" \
      org.opencontainers.image.licenses="MIT"
