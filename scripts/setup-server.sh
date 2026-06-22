#!/usr/bin/env bash
# Provision a server for this site (run once on the target host).
# Usage: ./scripts/setup-server.sh <site-name> <repo-url>
# Example: ./scripts/setup-server.sh my-site git@github.com:you/my-site.git
#
# For GitHub Actions auto-deploy, configure these on the repo first:
#   1. Create a per-repo SSH deploy key:
#        ssh-keygen -t ed25519 -C "deploy-<site-name>" -f ~/.ssh/deploy_<site-name> -N ""
#   2. Add the PUBLIC key as a GitHub deploy key (Settings → Deploy keys; allow write).
#   3. Add the PRIVATE key as the DEPLOY_SSH_KEY repository secret.
#   4. Add the DEPLOY_HOST secret (the server host/IP).
# If one server hosts several repos, give each its own key plus an SSH config
# alias so git selects the right one.

set -euo pipefail

SITE_NAME="${1:?Usage: setup-server.sh <site-name> <repo-url>}"
REPO_URL="${2:?Usage: setup-server.sh <site-name> <repo-url>}"
APP_DIR="/opt/apps/${SITE_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -d "$APP_DIR" ]; then
  echo "Error: $APP_DIR already exists" >&2
  exit 1
fi

# Clone the repo
git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

# Generate a strong, shell-safe password (alphanumeric only)
MYSQL_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"

# Create production .env
cat > .env <<EOF
COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml
COMPOSE_PROJECT_NAME=${SITE_NAME}
MYSQL_ROOT_PASSWORD=${MYSQL_PASSWORD}
EOF

# Build the image and start containers
echo "Building image and starting containers..."
docker compose up --build -d

# Wait until WordPress actually serves HTTP (replaces a fixed sleep). Probes
# inside the container because production publishes no host port.
echo "Waiting for WordPress to come up..."
bash "${SCRIPT_DIR}/healthcheck.sh" "http://localhost/" 30 5 wordpress

# Fix wp-content permissions for plugin installs and Duplicator
docker compose exec -T wordpress chown -R www-data:www-data /var/www/html/wp-content

echo ""
echo "=== Setup complete ==="
echo "App directory:  $APP_DIR"
echo "MySQL password: saved in ${APP_DIR}/.env (MYSQL_ROOT_PASSWORD)"
echo "Container name: ${SITE_NAME}-wordpress"
echo ""
echo "Next steps:"
echo "  1. Configure NPM: add proxy host → ${SITE_NAME}-wordpress:80 (port 80, not 8080)"
echo "  2. Complete WordPress install via browser (throwaway - will be overwritten by Duplicator)"
echo "  3. Import with Duplicator (see: scripts/import-duplicator.sh)"
echo ""
