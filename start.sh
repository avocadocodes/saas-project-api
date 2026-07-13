#!/bin/bash
set -e

echo "Starting Celery worker in background..."
celery -A celery_app worker --loglevel=info --concurrency=2 &
CELERY_PID=$!

echo "Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
