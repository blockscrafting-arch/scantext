#!/bin/bash
set -e

# Ожидание доступности базы данных можно не делать здесь, если depends_on: db: condition: service_healthy справляется.
# Но запустить миграции полезно. Только бот (один контейнер) должен делать миграции, чтобы не было гонок.
# Однако, alembic нормально обрабатывает гонки (lock), поэтому можно запускать и там и там. Но лучше пусть бот делает.
if [ "$RUN_MIGRATIONS" = "1" ]; then
    echo "Running database migrations..."
    alembic upgrade head
fi

echo "Starting application..."
exec "$@"
