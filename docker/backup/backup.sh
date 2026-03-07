#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Thinktank.ai — Automated PostgreSQL Backup Script
# ─────────────────────────────────────────────────────────────────────────────
# Performs pg_dump backups with compression, optional S3 upload, and retention.
#
# Environment variables:
#   PGHOST          - PostgreSQL host (default: postgres)
#   PGPORT          - PostgreSQL port (default: 5432)
#   PGUSER          - PostgreSQL user (default: thinktank)
#   PGPASSWORD      - PostgreSQL password (required)
#   PGDATABASE      - Database name (default: thinktank)
#   BACKUP_DIR      - Local backup directory (default: /backups)
#   S3_BUCKET       - S3 bucket for remote backups (optional)
#   S3_PREFIX       - S3 key prefix (default: backups/)
#   S3_ENDPOINT_URL - S3 endpoint for MinIO (optional)
#   RETENTION_DAILY - Daily backups to keep (default: 7)
#   RETENTION_WEEKLY  - Weekly backups to keep (default: 4)
#   RETENTION_MONTHLY - Monthly backups to keep (default: 3)
# ─────────────────────────────────────────────────────────────────────────────

# ── Configuration ────────────────────────────────────────────────────────────

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-thinktank}"
PGDATABASE="${PGDATABASE:-thinktank}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-backups/}"
S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-}"
RETENTION_DAILY="${RETENTION_DAILY:-3}"
RETENTION_WEEKLY="${RETENTION_WEEKLY:-4}"
RETENTION_MONTHLY="${RETENTION_MONTHLY:-3}"

# ── Helpers ──────────────────────────────────────────────────────────────────

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE_TAG=$(date +%Y%m%d)
DAY_OF_WEEK=$(date +%u)   # 1=Monday, 7=Sunday
DAY_OF_MONTH=$(date +%d)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

# ── Backup Functions ─────────────────────────────────────────────────────────

create_backup() {
    local backup_type="$1"
    local filename="thinktank_${backup_type}_${TIMESTAMP}.sql.gz"
    local filepath="${BACKUP_DIR}/${backup_type}/${filename}"

    mkdir -p "${BACKUP_DIR}/${backup_type}"

    log "Starting ${backup_type} backup: ${filename}"

    # Run pg_dump with custom format for faster restore, piped through gzip
    if pg_dump \
        -h "$PGHOST" \
        -p "$PGPORT" \
        -U "$PGUSER" \
        -d "$PGDATABASE" \
        --no-owner \
        --no-acl \
        --clean \
        --if-exists \
        | gzip -9 > "${filepath}"; then

        local size
        size=$(stat -f%z "${filepath}" 2>/dev/null || stat -c%s "${filepath}" 2>/dev/null || echo "unknown")
        log "Backup created: ${filepath} (${size} bytes)"
        echo "${filepath}"
        return 0
    else
        log_error "pg_dump failed for ${backup_type} backup"
        rm -f "${filepath}"
        return 1
    fi
}

verify_backup() {
    local filepath="$1"

    log "Verifying backup integrity: ${filepath}"

    # Check file exists and is not empty
    if [[ ! -f "$filepath" ]] || [[ ! -s "$filepath" ]]; then
        log_error "Backup file is missing or empty: ${filepath}"
        return 1
    fi

    # Verify gzip integrity
    if ! gzip -t "$filepath" 2>/dev/null; then
        log_error "Backup file is corrupted (gzip check failed): ${filepath}"
        return 1
    fi

    # Verify content contains SQL (check first few lines)
    if ! zcat "$filepath" 2>/dev/null | head -5 | grep -q "PostgreSQL\|pg_dump\|SET\|--"; then
        log_error "Backup does not appear to contain valid SQL: ${filepath}"
        return 1
    fi

    log "Backup verification passed: ${filepath}"
    return 0
}

upload_to_s3() {
    local filepath="$1"
    local filename
    filename=$(basename "$filepath")
    local backup_type
    backup_type=$(basename "$(dirname "$filepath")")
    local s3_key="${S3_PREFIX}${backup_type}/${filename}"

    if [[ -z "$S3_BUCKET" ]]; then
        log "S3_BUCKET not set, skipping S3 upload"
        return 0
    fi

    log "Uploading to s3://${S3_BUCKET}/${s3_key}"

    local aws_args=()
    if [[ -n "$S3_ENDPOINT_URL" ]]; then
        aws_args+=(--endpoint-url "$S3_ENDPOINT_URL")
    fi

    if aws s3 cp "${aws_args[@]}" "$filepath" "s3://${S3_BUCKET}/${s3_key}"; then
        log "Upload complete: s3://${S3_BUCKET}/${s3_key}"
        return 0
    else
        log_error "S3 upload failed for ${filepath}"
        return 1
    fi
}

# ── Retention ────────────────────────────────────────────────────────────────

apply_retention() {
    local backup_type="$1"
    local keep_count="$2"
    local dir="${BACKUP_DIR}/${backup_type}"

    if [[ ! -d "$dir" ]]; then
        return 0
    fi

    local count
    count=$(find "$dir" -name "*.sql.gz" -type f 2>/dev/null | wc -l | tr -d ' ')

    if [[ "$count" -le "$keep_count" ]]; then
        log "Retention (${backup_type}): ${count} backups, keeping all (limit: ${keep_count})"
        return 0
    fi

    local to_remove=$((count - keep_count))
    log "Retention (${backup_type}): removing ${to_remove} old backup(s) (keeping ${keep_count})"

    find "$dir" -name "*.sql.gz" -type f -print0 \
        | sort -z \
        | head -z -n "$to_remove" \
        | xargs -0 rm -f

    # Also remove from S3 if configured
    if [[ -n "$S3_BUCKET" ]]; then
        local aws_args=()
        if [[ -n "$S3_ENDPOINT_URL" ]]; then
            aws_args+=(--endpoint-url "$S3_ENDPOINT_URL")
        fi
        # List and remove old S3 objects matching removed local files
        log "S3 retention cleanup for ${backup_type} not yet automated — manage manually or via S3 lifecycle rules"
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    log "========================================="
    log "  Thinktank.ai Database Backup"
    log "========================================="
    log "Host: ${PGHOST}:${PGPORT}, Database: ${PGDATABASE}"

    # Verify PostgreSQL is reachable
    if ! pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -q 2>/dev/null; then
        log_error "PostgreSQL is not reachable at ${PGHOST}:${PGPORT}"
        exit 1
    fi

    local exit_code=0

    # 1. Always create a daily backup
    local daily_file
    if daily_file=$(create_backup "daily"); then
        if verify_backup "$daily_file"; then
            upload_to_s3 "$daily_file" || exit_code=1
        else
            exit_code=1
        fi
    else
        exit_code=1
    fi

    # 2. Weekly backup on Sunday (day 7)
    if [[ "$DAY_OF_WEEK" == "7" ]]; then
        local weekly_file
        if weekly_file=$(create_backup "weekly"); then
            if verify_backup "$weekly_file"; then
                upload_to_s3 "$weekly_file" || exit_code=1
            else
                exit_code=1
            fi
        else
            exit_code=1
        fi
    fi

    # 3. Monthly backup on the 1st
    if [[ "$DAY_OF_MONTH" == "01" ]]; then
        local monthly_file
        if monthly_file=$(create_backup "monthly"); then
            if verify_backup "$monthly_file"; then
                upload_to_s3 "$monthly_file" || exit_code=1
            else
                exit_code=1
            fi
        else
            exit_code=1
        fi
    fi

    # 4. Apply retention policy
    apply_retention "daily" "$RETENTION_DAILY"
    apply_retention "weekly" "$RETENTION_WEEKLY"
    apply_retention "monthly" "$RETENTION_MONTHLY"

    if [[ "$exit_code" -eq 0 ]]; then
        log "Backup completed successfully"
    else
        log_error "Backup completed with errors"
    fi

    return $exit_code
}

# Allow sourcing for testing without executing
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
