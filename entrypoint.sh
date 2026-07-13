#!/bin/bash
set -e

echo "Waiting for database..."
until python -c "
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()
from django.db import connection
connection.ensure_connection()
print('Database is ready.')
" 2>/dev/null; do
  echo "Database not ready, retrying in 2s..."
  sleep 2
done

echo "Running migrations..."
python manage.py migrate --noinput

exec "$@"
