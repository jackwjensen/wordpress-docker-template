#!/usr/bin/env bash
# Provision a server for this site (run once, as root, on the target host).
# Usage: ./scripts/setup-server.sh <site-name> <repo-url>
# Example: ./scripts/setup-server.sh my-site git@github-my-site:you/my-site.git
#
# The site is owned and deployed by a named non-root user (default `deploy`, override with
# DEPLOY_USER=...) in the docker group — never root (.claude/rules/publishing.md). Docker-group
# membership is still root-ADJACENT, so this is one rung down from root, not least privilege.
#
# Before running, give that user read access to the repo on GitHub:
#   1. Create a per-repo deploy key AS the deploy user (GitHub rejects reusing one key across
#      repos):  ssh-keygen -t ed25519 -C "github-<site-name>" -f ~deploy/.ssh/<site-name>_deploy_key -N ""
#   2. Add its PUBLIC key as a GitHub deploy key (Settings → Deploy keys, read access).
#   3. In ~deploy/.ssh/config, an alias so git picks that key:
#        Host github-<site-name>
#          HostName github.com
#          IdentityFile ~/.ssh/<site-name>_deploy_key
#      and use git@github-<site-name>:<owner>/<repo>.git as <repo-url>.
# For GitHub Actions deploys, the script prints what to add to the repo's secrets at the end.

set -euo pipefail

SITE_NAME="${1:?Usage: setup-server.sh <site-name> <repo-url>}"
REPO_URL="${2:?Usage: setup-server.sh <site-name> <repo-url>}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="/opt/apps/${SITE_NAME}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: run as root — it creates the $DEPLOY_USER user and $APP_DIR" >&2
  exit 1
fi
if [ -e "$APP_DIR" ]; then
  echo "Error: $APP_DIR already exists" >&2
  exit 1
fi

# The deploy user: created once per server, shared by every site on it.
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  echo "Creating user $DEPLOY_USER..."
  useradd --create-home --shell /bin/bash "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"

# Runs a command as the deploy user, in a login shell (so the docker group applies).
as_deploy() { su - "$DEPLOY_USER" -c "$1"; }

# Clone AS the deploy user: if it cannot reach the repo, this fails now rather than at the
# first deploy's git pull.
install -d -m 755 /opt/apps
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR"
as_deploy "git clone $(printf '%q' "$REPO_URL") $(printf '%q' "$APP_DIR")"

# Production .env: a strong, shell-safe database password (alphanumeric only), readable by the
# deploy user alone.
MYSQL_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"
cat > "$APP_DIR/.env" <<EOF
COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml
COMPOSE_PROJECT_NAME=${SITE_NAME}
MYSQL_ROOT_PASSWORD=${MYSQL_PASSWORD}
EOF
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

echo "Building image and starting containers..."
as_deploy "cd $(printf '%q' "$APP_DIR") && docker compose up --build -d"

# Wait until WordPress actually serves HTTP (replaces a fixed sleep). Probes inside the
# container because production publishes no host port.
echo "Waiting for WordPress to come up..."
as_deploy "cd $(printf '%q' "$APP_DIR") && bash scripts/healthcheck.sh http://localhost/ 30 5 wordpress"

# The host key the deploy pins. appleboy/ssh-action is a Go client, which negotiates ECDSA where
# OpenSSH prefers ed25519 — so the ECDSA fingerprint is the one it checks.
HOST_FINGERPRINT="$(ssh-keygen -lf /etc/ssh/ssh_host_ecdsa_key.pub 2>/dev/null | awk '{print $2}' || true)"

echo ""
echo "=== Setup complete ==="
echo "App directory:   $APP_DIR (owned by $DEPLOY_USER)"
echo "MySQL password:  saved in ${APP_DIR}/.env (MYSQL_ROOT_PASSWORD)"
echo "Container name:  ${SITE_NAME}-web"
echo ""
echo "Next steps:"
echo "  1. Nginx Proxy Manager: proxy host → ${SITE_NAME}-web, port 80 (not 8080)"
echo "  2. GitHub Actions deploy — repository secrets:"
echo "       DEPLOY_HOST              this server's address"
echo "       DEPLOY_SSH_KEY           a NEW private key for CI; put its PUBLIC half in"
echo "                                /home/$DEPLOY_USER/.ssh/authorized_keys, comment"
echo "                                github-actions-${SITE_NAME}-deploy-key"
echo "       DEPLOY_HOST_FINGERPRINT  ${HOST_FINGERPRINT:-<no ECDSA host key: use ssh-keygen -lf on the key sshd offers>}"
echo "     (repository variable DEPLOY_USER only if the user is not '$DEPLOY_USER')"
echo "  3. Complete the WordPress install in the browser (throwaway values if Duplicator follows)"
echo "  4. Import with Duplicator if migrating (scripts/import-duplicator.sh)"
echo ""
