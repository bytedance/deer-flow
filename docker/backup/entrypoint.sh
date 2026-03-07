#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Thinktank.ai — Backup Container Entrypoint
# ─────────────────────────────────────────────────────────────────────────────
# Runs the backup script on a cron schedule.
# Also supports one-shot mode for manual backups.
#
# Modes:
#   CMD (default)  — Start cron scheduler for periodic backups
#   backup         — Run a single backup immediately
#   restore [args] — Run the restore script with arguments
# ─────────────────────────────────────────────────────────────────────────────

BACKUP_SCHEDULE="${BACKUP_SCHEDULE:-0 2 * * *}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ENTRYPOINT: $*"; }

case "${1:-cron}" in
    cron)
        log "Starting backup scheduler"
        log "Schedule: ${BACKUP_SCHEDULE}"
        log "Backup dir: ${BACKUP_DIR:-/backups}"
        log "Target: ${PGHOST:-postgres}:${PGPORT:-5432}/${PGDATABASE:-thinktank}"

        if [[ -n "${S3_BUCKET:-}" ]]; then
            log "S3 upload enabled: s3://${S3_BUCKET}/${S3_PREFIX:-backups/}"
        else
            log "S3 upload disabled (S3_BUCKET not set)"
        fi

        # Set up cron job by writing a crontab entry
        # Export all environment variables for the cron job
        env | grep -E '^(PG|BACKUP_|S3_|RETENTION_|AWS_)' > /tmp/backup_env 2>/dev/null || true
        {
            echo "# Thinktank.ai backup schedule"
            echo "SHELL=/bin/bash"
            # Source environment and run backup
            echo "${BACKUP_SCHEDULE} . /tmp/backup_env && /usr/local/bin/backup.sh >> /proc/1/fd/1 2>> /proc/1/fd/2"
        } > /tmp/backup_crontab

        # Install crontab
        crontab /tmp/backup_crontab
        log "Cron job installed"

        # Run crond in foreground
        exec crond -f -l 2
        ;;

    backup)
        log "Running one-shot backup"
        exec /usr/local/bin/backup.sh
        ;;

    restore)
        shift
        log "Running restore"
        exec /usr/local/bin/restore.sh "$@"
        ;;

    *)
        exec "$@"
        ;;
esac
