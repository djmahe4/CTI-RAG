#!/bin/bash
set -euo pipefail

echo "🚀 Starting ThreatRAG services..."

if [ -x /app/scripts/init-services.sh ]; then
  echo "🧩 Running dependency service initialization script scripts/init-services.sh"
  /app/scripts/init-services.sh || true
fi

echo "📚 Building entity candidate cache..."
python -m packages.core.entity_cache_builder --include-embeddings || echo "⚠️  Failed to build entity candidate cache, proceeding to start API, please check logs"

echo "🎯 Starting ThreatRAG API..."
exec python /app/main.py


