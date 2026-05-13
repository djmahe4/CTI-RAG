#!/bin/bash
# ThreatRAG - Migrate Docker Volumes data to local directory
# Usage: Copy existing Docker volume data to local ./data directory

set -e

echo "========================================"
# ThreatRAG Volume Data Migration Tool
echo "ThreatRAG Volume Data Migration Tool"
echo "========================================"
echo ""

# Check if running as root or via sudo
if [ "$EUID" -ne 0 ] && [ -z "$SUDO_USER" ]; then 
    echo "⚠️  Recommended to run this script with sudo to avoid permission issues"
    echo "   sudo bash $0"
    echo ""
    read -p "Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$PROJECT_ROOT/data"

echo "📁 Project Root: $PROJECT_ROOT"
echo "📁 Data Directory: $DATA_DIR"
echo ""

# Define volumes to migrate
declare -A VOLUMES=(
    ["threatrag_mysql_data"]="mysql"
    ["threatrag_redis_data"]="redis"
    ["threatrag_neo4j_data"]="neo4j/data"
    ["threatrag_neo4j_logs"]="neo4j/logs"
    ["threatrag_etcd_data"]="etcd"
    ["threatrag_minio_data"]="minio"
    ["threatrag_milvus_data"]="milvus"
    ["threatrag_ollama_data"]="ollama"
)

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running, please start Docker first${NC}"
    exit 1
fi

echo "🔍 Checking existing Docker volumes..."
echo ""

# Check which volumes exist
existing_volumes=()
for volume in "${!VOLUMES[@]}"; do
    if docker volume inspect "$volume" > /dev/null 2>&1; then
        existing_volumes+=("$volume")
        size=$(docker system df -v | grep "$volume" | awk '{print $3}')
        echo -e "  ✓ ${GREEN}$volume${NC} (Size: ${size:-Unknown})"
    fi
done

if [ ${#existing_volumes[@]} -eq 0 ]; then
    echo -e "${YELLOW}⚠️  No existing Docker volumes found${NC}"
    echo "   Possible reasons:"
    echo "   1. This is the first deployment"
    echo "   2. Volume names do not match (check docker volume ls)"
    echo ""
    docker volume ls
    echo ""
    read -p "Continue creating directory structure? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
else
    echo ""
    echo -e "${YELLOW}⚠️  Warning: This operation will:${NC}"
    echo "   1. Stop all ThreatRAG containers"
    echo "   2. Copy volume data to $DATA_DIR"
    echo "   3. Restart containers with new local mounts"
    echo "   4. Original Docker volumes will be preserved (not deleted)"
    echo ""
    read -p "Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Operation cancelled"
        exit 0
    fi
fi

echo ""
echo "=================================="
echo "Starting migration..."
echo "=================================="
echo ""

# 1. Stop containers
echo "🛑 Stopping ThreatRAG containers..."
cd "$PROJECT_ROOT"
docker compose down || true
echo ""

# 2. Create local data directory structure
echo "📁 Creating local directory structure..."
for target_dir in "${VOLUMES[@]}"; do
    mkdir -p "$DATA_DIR/$target_dir"
    echo "   Created: $DATA_DIR/$target_dir"
done
echo ""

# 3. Copy volume data to local
if [ ${#existing_volumes[@]} -gt 0 ]; then
    echo "📦 Starting data copy..."
    for volume in "${existing_volumes[@]}"; do
        target_dir="${VOLUMES[$volume]}"
        echo ""
        echo "  Processing: $volume -> $target_dir"
        
        # Use temporary container to copy data
        # This is the safest method, avoiding direct access to Docker's internal storage
        # Use project configured mirror
        docker run --rm \
            -v "$volume:/source:ro" \
            -v "$DATA_DIR/$target_dir:/target" \
            docker1.aeko.cn/library/alpine:latest \
            sh -c "cp -av /source/. /target/" 2>&1 | sed 's/^/    /'
        
        if [ $? -eq 0 ]; then
            echo -e "  ${GREEN}✓ Done${NC}"
        else
            echo -e "  ${RED}✗ Failed${NC}"
        fi
    done
else
    echo -e "${YELLOW}⚠️  No data to copy${NC}"
fi

echo ""
echo "=================================="
echo "Setting permissions..."
echo "=================================="
echo ""

# 4. Adjust permissions (important!)
echo "🔐 Adjusting directory permissions..."

# MySQL requires specific permissions
if [ -d "$DATA_DIR/mysql" ]; then
    echo "  MySQL: Setting permissions to 999:999 (mysql user)"
    chown -R 999:999 "$DATA_DIR/mysql" 2>/dev/null || \
        echo -e "    ${YELLOW}⚠️  Unable to change permissions, sudo may be required${NC}"
fi

# Neo4j requires specific permissions
if [ -d "$DATA_DIR/neo4j" ]; then
    echo "  Neo4j: Setting permissions to 7474:7474 (neo4j user)"
    chown -R 7474:7474 "$DATA_DIR/neo4j" 2>/dev/null || \
        echo -e "    ${YELLOW}⚠️  Unable to change permissions, sudo may be required${NC}"
fi

# Redis
if [ -d "$DATA_DIR/redis" ]; then
    echo "  Redis: Setting permissions to 999:999"
    chown -R 999:999 "$DATA_DIR/redis" 2>/dev/null || \
        echo -e "    ${YELLOW}⚠️  Unable to change permissions, sudo may be required${NC}"
fi

# Use current user for other directories
echo "  Others: Setting permissions for current user"
if [ -n "$SUDO_USER" ]; then
    # If run via sudo, use original user
    REAL_USER="$SUDO_USER"
    REAL_GROUP=$(id -gn "$SUDO_USER")
else
    REAL_USER="$USER"
    REAL_GROUP=$(id -gn)
fi

for dir in etcd minio milvus ollama; do
    if [ -d "$DATA_DIR/$dir" ]; then
        chown -R "$REAL_USER:$REAL_GROUP" "$DATA_DIR/$dir" 2>/dev/null || true
    fi
done

echo ""
echo "=================================="
echo "Verifying migration results"
echo "=================================="
echo ""

# 5. Display data directory size
echo "📊 Data directory size statistics:"
for dir in "${VOLUMES[@]}"; do
    if [ -d "$DATA_DIR/$dir" ]; then
        size=$(du -sh "$DATA_DIR/$dir" 2>/dev/null | cut -f1)
        echo "  $dir: $size"
    fi
done

echo ""
echo "=================================="
echo "Complete!"
echo "=================================="
echo ""

echo -e "${GREEN}✓ Data migration complete${NC}"
echo ""
echo "Next steps:"
echo "  1. Check $DATA_DIR directory to confirm data was copied"
echo "  2. Start services with new configuration:"
echo "     ${GREEN}docker compose up -d${NC}"
echo ""
echo "  3. Verify services are running normally:"
echo "     ${GREEN}docker compose ps${NC}"
echo ""
echo "Note:"
echo "  • Original Docker volumes are preserved (not deleted)"
echo "  • If needed, you can delete them manually:"
echo "    ${YELLOW}docker volume rm ${existing_volumes[*]}${NC}"
echo ""
echo "  • If you encounter permission issues, run:"
echo "    ${YELLOW}sudo chown -R \$USER:\$USER $DATA_DIR${NC}"
echo ""


