# syntax=docker/dockerfile:1

# Allegro IT WordPress base image.
#
# Extends the official WordPress runtime with our tuned PHP upload limits so the
# image is self-contained — production and CI both build this, and tagged
# releases publish it to GHCR. No host bind-mount is needed for the PHP config.
FROM wordpress:7.0-php8.4-apache

# Ensure the curl CLI is present — it powers the container HEALTHCHECK below and
# the deploy-time health probe (scripts/healthcheck.sh in "compose service"
# mode). The current base image already includes curl, but install it explicitly
# so the health check never silently breaks if a future base image drops it.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# PHP upload / execution limits (large media uploads + Duplicator migration
# packages). Baked into the image so the limits travel with it.
COPY config/uploads.ini /usr/local/etc/php/conf.d/uploads.ini

# Report real health: a fresh install legitimately 302-redirects to the install
# wizard (curl -f treats 2xx/3xx as success, 5xx as failure). Exec (JSON) form
# per hadolint DL3025; the explicit `sh -c` keeps `|| exit 1`, which maps any
# curl failure code onto Docker's "unhealthy" exit status 1.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD ["sh", "-c", "curl -fsS -o /dev/null http://localhost/ || exit 1"]

# OCI metadata. The release workflow injects version/revision labels via
# docker/metadata-action; these are sensible defaults for local + CI builds.
LABEL org.opencontainers.image.title="wordpress-docker-template" \
      org.opencontainers.image.description="Production-ready Docker WordPress (WordPress 7.0 + PHP 8.4) template by Allegro IT" \
      org.opencontainers.image.vendor="Allegro IT ApS" \
      org.opencontainers.image.url="https://allegroit.dk/" \
      org.opencontainers.image.source="https://github.com/jackwjensen/wordpress-docker-template" \
      org.opencontainers.image.licenses="MIT"
