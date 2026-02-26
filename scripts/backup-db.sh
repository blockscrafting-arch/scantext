#!/bin/bash
# Дамп PostgreSQL из контейнера db. Запускать из корня проекта.
# На VPS: добавить в cron, например 0 3 * * * /path/to/project/scripts/backup-db.sh
# Для prod: COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml ./scripts/backup-db.sh

set -e
cd "$(dirname "$0")/.."
# На VPS задать: export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
export COMPOSE_FILE
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/elenabot_$(date +%Y%m%d_%H%M%S).sql"

docker-compose exec -T db pg_dump -U elenabot elenabot > "$FILE"

echo "Backup written to $FILE"
