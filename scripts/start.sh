#!/bin/bash
set -euo pipefail

echo "🚀 启动 ThreatRAG 服务..."

if [ -x /app/scripts/init-services.sh ]; then
  echo "🧩 运行依赖服务初始化脚本 scripts/init-services.sh"
  /app/scripts/init-services.sh || true
fi

echo "📚 构建实体候选缓存..."
python -m packages.core.entity_cache_builder --include-embeddings || echo "⚠️  构建实体候选缓存失败，将继续启动 API，请检查日志"

echo "🎯 启动ThreatRAG API..."
exec python /app/main.py


