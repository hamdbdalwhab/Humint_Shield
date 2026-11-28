#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HUMINT Shield - daily database backup.
#
#   PostgreSQL : pg_dump --format=custom (restore with pg_restore)
#   SQLite     : "VACUUM INTO" consistent online copy (falls back to .backup)
#
# Backups land in $BACKUP_DIR (default ./backups) as
#   humint_shield_<UTC timestamp>.<ext>
# and anything older than $RETENTION_DAYS (default 30) is removed.
#
# Cron (see DEPLOYMENT.md):
#   15 2 * * * /opt/humint-shield/scripts/backup_db.sh >> /var/log/humint-backup.log 2>&1
#
# Required for PostgreSQL: pg_dump on PATH, or run inside the db container.
# Exit codes: 0 success, 1 configuration/backup failure.
# ---------------------------------------------------------------------------
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DATABASE_URL="${DATABASE_URL:-}"

mkdir -p "$BACKUP_DIR"

log() { printf '%s [backup] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

fail() {
  log "ERROR: $*"
  exit 1
}

if [[ -z "$DATABASE_URL" ]]; then
  # Fall back to the application's dotenv (never printed).
  for candidate in "${ENV_FILE:-.env}" "$(dirname "${BASH_SOURCE[0]}")/../backend/.env"; do
    if [[ -f "$candidate" ]]; then
      # shellcheck disable=SC1090
      DATABASE_URL="$(grep -E '^DATABASE_URL=' "$candidate" | tail -n1 | cut -d= -f2- | tr -d '"'"'"'')"
      [[ -n "$DATABASE_URL" ]] && break
    fi
  done
fi

[[ -n "$DATABASE_URL" ]] || fail "DATABASE_URL is not set"

umask 077

if [[ "$DATABASE_URL" == postgresql* || "$DATABASE_URL" == postgres* ]]; then
  command -v pg_dump >/dev/null 2>&1 || fail "pg_dump not found on PATH"
  # SQLAlchemy URLs use postgresql+asyncpg:// which pg_dump does not accept.
  PG_URL="${DATABASE_URL/postgresql+asyncpg/postgresql}"
  PG_URL="${PG_URL/postgres+asyncpg/postgres}"
  TARGET="$BACKUP_DIR/humint_shield_${STAMP}.dump"
  log "dumping PostgreSQL to $TARGET"
  pg_dump --format=custom --no-owner --no-privileges --file "$TARGET" "$PG_URL" \
    || fail "pg_dump failed"
elif [[ "$DATABASE_URL" == sqlite* ]]; then
  DB_PATH="${DATABASE_URL##*///}"
  DB_PATH="${DB_PATH#./}"
  [[ -f "$DB_PATH" ]] || fail "SQLite database not found: $DB_PATH"
  TARGET="$BACKUP_DIR/humint_shield_${STAMP}.db"
  log "copying SQLite database to $TARGET"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$TARGET'" || fail "sqlite3 .backup failed"
  else
    # A plain copy of a live SQLite file can be inconsistent; warn loudly.
    log "WARNING: sqlite3 CLI not found, using a filesystem copy"
    cp -- "$DB_PATH" "$TARGET"
  fi
else
  fail "unsupported DATABASE_URL scheme"
fi

[[ -s "$TARGET" ]] || fail "backup file is empty: $TARGET"

# Verify the archive is readable before rotating old copies.
if [[ "$TARGET" == *.dump ]]; then
  command -v pg_restore >/dev/null 2>&1 && pg_restore --list "$TARGET" >/dev/null \
    || log "WARNING: could not verify the pg_dump archive"
else
  head -c 16 "$TARGET" | grep -q "SQLite format 3" \
    || log "WARNING: backup does not look like a SQLite database"
fi

log "removing backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -type f \( -name 'humint_shield_*.dump' -o -name 'humint_shield_*.db' \) \
  -mtime "+${RETENTION_DAYS}" -print -delete

log "done: $(du -h "$TARGET" | cut -f1) at $TARGET"
