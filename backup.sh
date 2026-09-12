#!/usr/bin/env bash
set -euo pipefail

# Backup the PostgreSQL database to a timestamped SQL dump on the host.
#
# Usage: ./backup.sh [output_dir]
# Default output_dir: ./backups

PROJECT="barq-assessment"
DB_USER="barq_app"
DB_NAME="barq_tasks"
DB_CONTAINER="postgres"
OUTPUT_DIR="${1:-./backups}"

mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="${OUTPUT_DIR}/backup_${TIMESTAMP}.sql"

echo "=== PostgreSQL Backup ==="
echo "Project:   $PROJECT"
echo "Container: $DB_CONTAINER"
echo "Database:  $DB_NAME"
echo "Output:    $BACKUP_FILE"
echo ""

# Verify the postgres container is running before attempting a dump
STATE=$(docker compose -p "$PROJECT" ps "$DB_CONTAINER" --format '{{.State}}' 2>/dev/null || echo "")
if [[ "$STATE" != "running" ]]; then
  echo "ERROR: postgres container is not running (state='$STATE'). Aborting backup." >&2
  exit 1
fi

# Run pg_dump inside the container and stream the output to a host file
docker compose -p "$PROJECT" exec -T "$DB_CONTAINER" \
  pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists > "$BACKUP_FILE"

if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file is empty. Something went wrong." >&2
  rm -f "$BACKUP_FILE"
  exit 1
fi

LINES=$(wc -l < "$BACKUP_FILE")
SIZE=$(du -h "$BACKUP_FILE" | cut -f1)

echo "Backup complete."
echo "File:  $BACKUP_FILE"
echo "Size:  $SIZE"
echo "Lines: $LINES"
