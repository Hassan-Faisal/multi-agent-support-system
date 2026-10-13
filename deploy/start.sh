#!/bin/sh
# Container entrypoint for single-service deploys.
# Every step is idempotent, so it's safe on every start:
#   migrations apply only what's new, seeding skips existing data, and ingestion
#   re-embeds only help-center articles that changed (no OpenAI cost otherwise).
set -e
cd /app
echo "Applying database migrations..."
alembic upgrade head
echo "Seeding demo data (skipped if present)..."
python -m support.db.seed
echo "Indexing the help center (only changed articles)..."
python -m support.rag.ingest
echo "Starting the server on port ${PORT:-8000}..."
exec uvicorn support.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips "*"
