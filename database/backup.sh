#!/bin/bash
set -euo pipefail

BACKUP_DIR="/backups"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="sse_backup_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

pg_dump -h "${POSTGRES_HOST:-postgres}" -U "${POSTGRES_USER:-sse_admin}" -d "${POSTGRES_DB:-sse}" \
  | gzip > "${BACKUP_DIR}/${FILENAME}"

# Prune old backups beyond retention period
find "${BACKUP_DIR}" -name "sse_backup_*.sql.gz" \
  -mtime +${RETENTION_DAYS} -delete 2>/dev/null || true

echo "$(date -Iseconds) Backup complete: ${FILENAME} ($(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1))"
