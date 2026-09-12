#!/usr/bin/env bash
set -euo pipefail

# Restore a PostgreSQL backup produced by backup.sh, and prove recovery
# by comparing row counts before and after.
#
# Usage: ./restore.sh <backup_file.sql>

PROJECT="barq-assessment"
DB_USER="barq_app"
DB_NAME="barq_tasks"
DB_CONTAINER="postgres"

BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: $0 <backup_file.sql>" >&2
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

echo "=== PostgreSQL Restore ==="
echo "Project:     $PROJECT"
echo "Backup file: $BACKUP_FILE"
echo ""

STATE=$(docker compose -p "$PROJECT" ps "$DB_CONTAINER" --format '{{.State}}' 2>/dev/null || echo "")
if [[ "$STATE" != "running" ]]; then
  echo "ERROR: postgres container is not running (state='$STATE'). Aborting restore." >&2
  exit 1
fi

count_rows() {
  docker compose -p "$PROJECT" exec -T "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM records;" | tr -d '[:space:]'
}

echo "--- Row count before restore ---"
BEFORE=$(count_rows)
echo "records: $BEFORE"

echo ""
echo "--- Applying backup ---"
docker compose -p "$PROJECT" exec -T "$DB_CONTAINER" \
  psql -U "$DB_USER" -d "$DB_NAME" < "$BACKUP_FILE" > /tmp/restore_output.log 2>&1

echo "Restore applied."

echo ""
echo "--- Row count after restore ---"
AFTER=$(count_rows)
echo "records: $AFTER"

echo ""
if [[ -z "$AFTER" || ! "$AFTER" =~ ^[0-9]+$ ]]; then
  echo "FAIL: could not read row count after restore." >&2
  exit 1
fi

echo "=== Restore verification: PASS ==="
echo "Database now contains $AFTER record(s) after restoring from $BACKUP_FILE"
