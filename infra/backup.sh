#!/usr/bin/env bash
# Nightly 0FFDAYS backup. Runs from the deploying user's crontab on k6-server
# (no root). Takes a live SQLite backup inside the running container (online
# backup API, the web app keeps serving), copies it out to the host, gzips it,
# keeps KEEP_DAYS days, and -- when OFFSITE is set -- pushes a copy off the box.
#
#   crontab: see infra/crontab.offdays
#   restore: see ops/PRODUCTION_CHECKLIST.md "Restore drill"
#
# OFFSITE is any rclone remote path, e.g. "b2:k6-backups/offdays" or
# "hetzner-box:offdays". Unset means local-only, and the script says so on every
# run so nobody mistakes a same-disk copy for a backup.
set -euo pipefail

CONTAINER="${CONTAINER:-offdays_app_1}"
DIR="${BACKUP_DIR:-$HOME/offdays-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
OFFSITE="${OFFSITE:-}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$DIR/offdays-$STAMP.db.gz"

mkdir -p "$DIR"

# 1. Online backup + integrity check inside the container, to the data volume.
#    health_reap exits non-zero on a merely "degraded" health summary (e.g. a
#    big WAL), which is not a backup failure -- so its exit code is logged, not
#    fatal. Whether the backup exists is checked by the copy-out below.
podman exec "$CONTAINER" python scripts/health_reap.py --quiet \
    --no-checkpoint --no-clean --no-disk \
    --backup "/data/backups/offdays-$STAMP.db" --integrity \
    || echo "health_reap reported issues at $STAMP (see above); checking the backup itself" >&2

# 2. Copy out, compress to a temp name, move on success -- a failed run never
#    leaves a truncated file that looks like a good backup.
if podman cp "$CONTAINER:/data/backups/offdays-$STAMP.db" - \
    | tar -xO | gzip -9 > "$OUT.partial"; then
    mv "$OUT.partial" "$OUT"
else
    rm -f "$OUT.partial"
    echo "backup FAILED at $STAMP" >&2
    exit 1
fi
podman exec "$CONTAINER" rm -f "/data/backups/offdays-$STAMP.db"

SIZE=$(stat -c %s "$OUT")
if [ "$SIZE" -lt 1000 ]; then
    echo "backup at $STAMP is suspiciously small ($SIZE bytes); keeping it but flagging" >&2
fi

find "$DIR" -name 'offdays-*.db.gz' -mtime "+$KEEP_DAYS" -delete

# 3. Off-box copy.
if [ -n "$OFFSITE" ]; then
    rclone copy "$OUT" "$OFFSITE/" --quiet
    echo "$STAMP ok ($(numfmt --to=iec "$SIZE")), copied to $OFFSITE"
else
    echo "$STAMP ok ($(numfmt --to=iec "$SIZE")), LOCAL ONLY: set OFFSITE for an off-box copy"
fi

# 4. Optional heartbeat (UptimeRobot heartbeat / healthchecks.io URL). A missed
#    ping is how you learn the backup stopped running.
if [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
    curl -fsS --max-time 10 "$BACKUP_HEARTBEAT_URL" >/dev/null || true
fi
