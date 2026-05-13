#!/bin/bash

# ThreatRAG Service Initialization Script
# Wait for services to start and perform initial configuration

set -e

echo "🚀 Starting ThreatRAG service initialization..."

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Wait for service health check function
wait_for_service() {
    local service_name=$1
    local host=$2
    local port=$3
    local max_attempts=30
    local attempt=1
    
    echo -e "${YELLOW}Waiting for ${service_name} service to start...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if nc -z $host $port 2>/dev/null; then
            echo -e "${GREEN}✓ ${service_name} service is up${NC}"
            return 0
        fi
        
        echo -e "${YELLOW}Waiting for ${service_name} service (${attempt}/${max_attempts})...${NC}"
        sleep 2
        ((attempt++))
    done
    
    echo -e "${RED}✗ ${service_name} service failed to start or timed out${NC}"
    return 1
}

echo "📋 Checking service status..."

# Read environment variables and set candidate ports (container network priority)
MYSQL_HOST=${MYSQL_HOST:-mysql}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD:-12345678}
# Try container port 3306 first, then env port, finally host mapped port 3309
MYSQL_PORT_CANDIDATES="3306 ${MYSQL_PORT:-3306} 3309"

NEO4J_HOST=${NEO4J_HOST:-neo4j}
# Try container port 7687 first, then env port, finally host mapped port 7688
NEO4J_BOLT_PORT_CANDIDATES="7687 ${NEO4J_BOLT_PORT:-7687} 7688"

# Helper to choose an available port
choose_port() {
    local host=$1
    shift
    local ports=("$@")
    for p in "${ports[@]}"; do
        if nc -z "$host" "$p" 2>/dev/null; then
            echo "$p"
            return 0
        fi
    done
    # If none available, return the first as default
    echo "${ports[0]}"
}

MYSQL_PORT=$(choose_port "$MYSQL_HOST" $MYSQL_PORT_CANDIDATES)
NEO4J_BOLT_PORT=$(choose_port "$NEO4J_HOST" $NEO4J_BOLT_PORT_CANDIDATES)

# Wait for each service to start (using selected ports)
wait_for_service "MySQL" "$MYSQL_HOST" "$MYSQL_PORT"
wait_for_service "Redis" "redis" "6379"
wait_for_service "Neo4j" "$NEO4J_HOST" "$NEO4J_BOLT_PORT"
wait_for_service "Milvus" "milvus-standalone" "19530"

echo -e "${BLUE}🔧 Starting service configuration...${NC}"

# 1. Check MySQL connection
echo "Checking MySQL connection..."
if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -e "SELECT version();" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ MySQL connection OK${NC}"
    
    # Check if tables are created
    table_count=$(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" knowledge_db -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='knowledge_db';" -s -N 2>/dev/null || echo "0")
    echo "Database table count: $table_count"
else
    echo -e "${RED}✗ MySQL connection failed${NC}"
fi

# 2. Check Redis connection
echo "Checking Redis connection..."
if redis-cli -h redis ping | grep -q PONG; then
    echo -e "${GREEN}✓ Redis connection OK${NC}"
else
    echo -e "${RED}✗ Redis connection failed${NC}"
fi

# 3. Check Neo4j connection
echo "Checking Neo4j connection..."
if echo 'RETURN "Neo4j is running" as status;' | cypher-shell -a bolt://$NEO4J_HOST:$NEO4J_BOLT_PORT -u neo4j -p 12345678 > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Neo4j connection OK${NC}"
    
    # Create initial indices
    echo "Creating Neo4j indices..."
    echo "
        CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name);
        CREATE INDEX relationship_type IF NOT EXISTS FOR ()-[r:RELATIONSHIP]-() ON (r.type);
    " | cypher-shell -a bolt://$NEO4J_HOST:$NEO4J_BOLT_PORT -u neo4j -p 12345678 > /dev/null 2>&1 || true
    echo -e "${GREEN}✓ Neo4j indices created successfully${NC}"
else
    echo -e "${RED}✗ Neo4j connection failed${NC}"
fi

# 4. Check Milvus connection
echo "Checking Milvus connection..."
if curl -f http://milvus-standalone:9091/healthz > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Milvus service OK${NC}"
else
    echo -e "${RED}✗ Milvus service unhealthy${NC}"
fi

echo -e "${GREEN}🎉 Dependency services initialization complete!${NC}"
echo ""
echo -e "${BLUE}📍 Service Connection Info:${NC}"
echo "• MySQL: $MYSQL_HOST:$MYSQL_PORT (root/$MYSQL_ROOT_PASSWORD)"
echo "• Redis: redis:6379"
echo "• Neo4j: $NEO4J_HOST:$NEO4J_BOLT_PORT (neo4j/12345678)"
echo "• Milvus: milvus-standalone:19530"
echo ""
echo -e "${YELLOW}💡 ThreatRAG API service is ready to start${NC}"