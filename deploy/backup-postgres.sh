#!/bin/sh
set -eu

PROJECT_DIR=${PROJECT_DIR:-/opt/video-review}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/video-review}
RETENTION_DAYS=${RETENTION_DAYS:-30}
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"
cd "$PROJECT_DIR"

docker compose --env-file .env.server exec -T database \
    pg_dump --clean --if-exists --no-owner --username video_review video_review \
    | gzip > "$BACKUP_DIR/video-review-$TIMESTAMP.sql.gz"

find "$BACKUP_DIR" -type f -name 'video-review-*.sql.gz' -mtime "+$RETENTION_DAYS" -delete
echo "备份完成：$BACKUP_DIR/video-review-$TIMESTAMP.sql.gz"