#!/bin/bash
set -e

echo "Starting Celery worker in background..."
celery -A celery_app worker --loglevel=info --concurrency=${CELERY_CONCURRENCY:-2} &

echo "Starting Celery beat in background..."
celery -A celery_app beat --loglevel=info &

echo "Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers ${WEB_CONCURRENCY:-2} \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
