#!/usr/bin/env bash
# Build and deploy 0FFDAYS to one host over SSH. Mirrors UtiliTrust's deploy on
# the same box (rootless podman + podman-compose + host nginx).
#
#   ./infra/deploy.sh k6-server            # ssh alias or user@host
#
# Idempotent: safe to re-run for every release. Syncs the tree, builds the image
# on the host, recreates the container, waits for /api/ready to report the new
# commit, and (re)installs the cron block. Requires on the host: podman,
# podman-compose, rsync, and ~/offdays/infra/.env.prod (see .env.prod.example).
set -euo pipefail

HOST="${1:?usage: deploy.sh <ssh-host>}"
REMOTE_DIR="${REMOTE_DIR:-$(ssh "$HOST" 'echo "$HOME"')/offdays}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GIT_SHA="unknown"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# Production must equal a commit. From a laptop, refuse a dirty tree unless the
# human opts in; CI always deploys a clean checkout of the commit it tested.
if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ] && [ "${ALLOW_DIRTY:-0}" != "1" ]; then
        echo "Refusing to deploy: the working tree has uncommitted changes." >&2
        echo "Commit them, or set ALLOW_DIRTY=1 to deploy anyway." >&2
        git -C "$REPO_ROOT" status --short >&2
        exit 1
    fi
    GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
    [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ] && GIT_SHA="$GIT_SHA-dirty"
    say "Deploying $GIT_SHA"
fi

say "Checking host prerequisites"
ssh "$HOST" 'for c in podman podman-compose rsync; do
    command -v $c >/dev/null || { echo "missing on host: $c"; exit 1; }
  done; echo "  ok"'

say "Syncing source to $HOST:$REMOTE_DIR"
ssh "$HOST" "mkdir -p $REMOTE_DIR/infra \$HOME/offdays-logs \$HOME/offdays-backups"
rsync -az --delete \
    --exclude '.git' --exclude 'node_modules' --exclude '.venv' --exclude 'venv' \
    --exclude '__pycache__' --exclude '*.egg-info' --exclude 'data' \
    --exclude '*.db' --exclude '*.db-wal' --exclude '*.db-shm' \
    --exclude '*.pdf' --exclude 'screenshots' --exclude '.env' \
    --exclude 'infra/.env.prod' \
    "$REPO_ROOT/" "$HOST:$REMOTE_DIR/"

say "Verifying the host's .env.prod"
# A missing secret does not crash the app -- it quietly ships a weaker product
# (forgeable unsubscribe links, a coach seeing the whole program). So the deploy
# is where it gets caught.
#
# Read with grep, never sourced: it is a podman env-file, where values are
# literal. `OFFDAYS_SMTP_FROM=0FFDAYS <no-reply@...>` is correct there and a
# syntax error to a shell, and quoting it for the shell would put the quotes
# into the From header.
ssh "$HOST" "set -eu
  f=$REMOTE_DIR/infra/.env.prod
  test -f \$f || { echo \"missing \$f: create it from infra/.env.prod.example\"; exit 1; }
  get() { grep -E \"^\$1=\" \$f | tail -1 | cut -d= -f2-; }
  for v in OFFDAYS_SECRET OFFDAYS_BASE_URL; do
    [ -n \"\$(get \$v)\" ] || { echo \"  \$v is blank in .env.prod; refusing to deploy\"; exit 1; }
  done
  [ \"\$(get OFFDAYS_STRICT_TEAM_SCOPE)\" = 1 ] || echo '  WARNING: OFFDAYS_STRICT_TEAM_SCOPE is not 1'
  [ -n \"\$(get OFFDAYS_SMTP_HOST)\" ] || echo '  note: SMTP unset, mail is composed but not sent'
  [ -n \"\$(get OFFDAYS_VAPID_PRIVATE_KEY)\" ] || echo '  note: VAPID unset, push is in-app only'
  echo '  ok'"

say "Building the image on the host"
ssh "$HOST" "cd $REMOTE_DIR && podman build -f infra/Containerfile -t offdays:latest --build-arg GIT_SHA='$GIT_SHA' ."

say "Starting the new container"
# --force-recreate: podman-compose otherwise keeps a container whose name is
# taken, which would silently leave the OLD image running.
ssh "$HOST" "cd $REMOTE_DIR/infra && podman-compose --env-file .env.prod -f compose.prod.yaml up -d --force-recreate app" || true

say "Waiting for /api/ready to report $GIT_SHA"
ssh "$HOST" "set -u
  port=\$(grep -E '^PORT_APP=' $REMOTE_DIR/infra/.env.prod | cut -d= -f2); port=\${port:-8810}
  for i in \$(seq 1 45); do
    live=\$(curl -s --max-time 4 http://127.0.0.1:\$port/api/live || true)
    case \"\$live\" in *'\"git_sha\":\"$GIT_SHA\"'*)
      ready=\$(curl -s --max-time 4 http://127.0.0.1:\$port/api/ready || true)
      echo \"  live: \$live\"; echo \"  ready: \$ready\"; exit 0 ;;
    esac
    sleep 2
  done
  echo '  new container never came up; check: podman logs offdays_app_1'; exit 1"

say "Installing the cron block"
# Replace everything between the markers, keep every other line (UtiliTrust's
# backup job lives in the same crontab).
ssh "$HOST" "set -eu
  block=\$(sed -n '/^# BEGIN offdays/,/^# END offdays/p' $REMOTE_DIR/infra/crontab.offdays)
  { crontab -l 2>/dev/null | sed '/^# BEGIN offdays/,/^# END offdays/d'; printf '%s\n' \"\$block\"; } | crontab -
  echo \"  \$(crontab -l | grep -c 'offdays_app_1\|offdays/infra') offdays jobs installed\""

say "Deployed $GIT_SHA"
