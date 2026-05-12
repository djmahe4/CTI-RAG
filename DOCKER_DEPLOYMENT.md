# ThreatRAG Docker 部署指南

## 🏗️ 架构概览

ThreatRAG 使用微服务架构，包含以下服务：

```
┌─────────────────┐    ┌──────────────────┐
│   ThreatRAG     │◄──►│   PostgreSQL     │
│   API Service   │    │   (知识库数据)    │
└─────────────────┘    └──────────────────┘
         │
         ├──────────────┬──────────────────┬───────────────
         ▼              ▼                  ▼               ▼
┌─────────────┐ ┌─────────────┐  ┌─────────────┐ ┌─────────────┐
│    Redis    │ │    Neo4j    │  │   Milvus    │ │   MinIO     │
│  (会话缓存)  │ │  (知识图谱)  │  │ (向量存储)   │ │ (对象存储)   │
└─────────────┘ └─────────────┘  └─────────────┘ └─────────────┘
                                         │
                                         ▼
                                 ┌─────────────┐
                                 │    Etcd     │
                                 │(服务发现)    │
                                 └─────────────┘
```

## 🚀 快速启动

### 方法 1: 使用启动脚本 (推荐)

```bash
# 克隆项目
git clone <your-repo-url>
cd ThreatRAG

# 一键启动
./scripts/start.sh

# 重新构建并启动
./scripts/start.sh --build
```

### 方法 2: 使用 Docker Compose (自动初始化)

```bash
# 创建环境配置
cp .env.example .env

# 启动所有服务（自动运行初始化脚本）
docker-compose up -d

# 重新构建并启动
docker-compose up -d --build
```

### 方法 3: 开发环境 (支持热重载)

```bash
# 启动开发环境（支持源代码和配置热重载）
./scripts/start-dev.sh

# 或者直接使用 docker-compose
docker-compose -f docker-compose.dev.yml up -d
```

### 方法 4: 测试自动初始化功能

```bash
# 运行自动初始化测试
./scripts/test_auto_init.sh

# 查看服务状态
docker-compose ps

# 运行初始化脚本（手动方式，通常不需要）
./scripts/init-services.sh
```

## ⚙️ 环境变量配置

ThreatRAG 使用 `.env` 文件来管理环境变量配置，支持动态修改和热重载。

### 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `FASTAPI_ENV` | `development` | 运行环境 (development/production) |
| `BASE_MODEL` | `deepseek-ai/DeepSeek-V3` | 基础模型名称 |
| `NEO4J_USERNAME` | `neo4j` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | `12345678` | Neo4j 密码 |
| `OPENAI_API_KEY` | - | OpenAI API 密钥 |
| `ZHIPUAI_API_KEY` | - | 智谱AI API 密钥 |
| `DEEPSEEK_API_KEY` | - | DeepSeek API 密钥 |
| `SILICONFLOW_API_KEY` | - | SiliconFlow API 密钥 |
| `SILICONFLOW_API_BASE` | `https://api.siliconflow.cn/v1` | SiliconFlow API 基础URL |
| `SESSION_EXPIRE_TIME` | `3600` | 会话过期时间（秒） |
| `MAX_HISTORY_LENGTH` | `50` | 最大历史记录长度 |
| `MAX_CONCURRENT_CHATS` | `20` | 最大并发聊天数 |

### 配置热重载

在开发环境中，修改 `.env` 文件后可以通过以下方式使配置生效：

```bash
# 重启 ThreatRAG 服务
docker-compose -f docker-compose.dev.yml restart threatrag

# 或者重启所有服务
docker-compose -f docker-compose.dev.yml down && docker-compose -f docker-compose.dev.yml up -d
```

### 环境变量优先级

1. Docker Compose `environment` 部分（最高优先级）
2. `.env` 文件
3. 系统环境变量
4. 默认值（最低优先级）

## 🔧 自动初始化功能

ThreatRAG 现在支持自动初始化功能，当使用 `docker-compose up -d` 启动服务时，系统会自动：

### 自动执行的操作

1. **等待依赖服务启动** - 自动等待 PostgreSQL、Redis、Neo4j、Milvus 等服务健康检查通过
2. **运行初始化脚本** - 自动执行 `scripts/init-services.sh` 脚本
3. **服务连接测试** - 测试与各个数据库的连接状态
4. **创建必要索引** - 在 Neo4j 中创建实体和关系的索引
5. **启动 API 服务** - 在所有依赖服务就绪后启动 ThreatRAG API

### 初始化日志

启动时你会看到类似以下的日志输出：

```
🚀 启动 ThreatRAG 服务...
⏳ 等待依赖服务启动...
🔧 运行服务初始化...
🚀 开始初始化 ThreatRAG 服务...
📋 检查服务状态...
等待 PostgreSQL 服务启动...
✓ PostgreSQL 服务已启动
等待 Redis 服务启动...
✓ Redis 服务已启动
等待 Neo4j 服务启动...
✓ Neo4j 服务已启动
等待 Milvus 服务启动...
✓ Milvus 服务已启动
🔧 开始服务配置...
检查 PostgreSQL 连接...
✓ PostgreSQL 连接正常
检查 Redis 连接...
✓ Redis 连接正常
检查 Neo4j 连接...
✓ Neo4j 连接正常
创建 Neo4j 索引...
✓ Neo4j 索引创建完成
检查 Milvus 连接...
✓ Milvus 服务正常
🎉 依赖服务初始化完成！
🎯 启动 ThreatRAG API...
```

### 手动初始化

如果自动初始化失败，你仍然可以手动运行初始化脚本：

```bash
# 在容器内运行
docker-compose exec threatrag /app/scripts/init-services.sh

# 或者在宿主机运行（需要先启动服务）
./scripts/init-services.sh
```

## 📋 服务端口说明

| 服务 | 端口 | 用途 | 访问地址 |
|------|------|------|----------|
| ThreatRAG API | 8000 | REST API服务 | http://localhost:8000 |
| API 文档 | 8000 | Swagger文档 | http://localhost:8000/docs |
| PostgreSQL | 5432 | 数据库连接 | localhost:5432 |
| Redis | 6379 | 缓存服务 | localhost:6379 |
| Neo4j HTTP | 7474 | 图数据库管理界面 | http://localhost:7474 |
| Neo4j Bolt | 7687 | 图数据库连接 | bolt://localhost:7687 |
| Milvus | 19530 | 向量数据库 | localhost:19530 |
| Milvus Management | 9091 | 健康检查 | http://localhost:9091 |
| MinIO | 9000 | 对象存储 | http://localhost:9000 |
| MinIO Console | 9001 | 管理界面 | http://localhost:9001 |

## 🔐 默认账号密码

| 服务 | 用户名 | 密码 | 说明 |
|------|--------|------|------|
| Neo4j | neo4j | 12345678 | 图数据库 |
| PostgreSQL | postgres | 12345678 | 关系数据库 |
| MinIO | minioadmin | minioadmin | 对象存储 |
| Redis | - | - | 无密码 |

## 📁 数据持久化

所有数据都会持久化存储在 Docker Volumes 中：

- `postgres_data`: PostgreSQL 数据
- `redis_data`: Redis 数据
- `neo4j_data`: Neo4j 数据
- `neo4j_logs`: Neo4j 日志
- `milvus_data`: Milvus 向量数据
- `etcd_data`: Etcd 配置数据
- `minio_data`: MinIO 对象数据

## 🔧 开发和调试

### 查看服务日志

```bash
# 查看所有服务日志
docker-compose logs

# 查看特定服务日志
docker-compose logs -f threatrag

# 查看实时日志
docker-compose logs -f --tail=100
```

### 进入容器

```bash
# 进入 API 容器
docker-compose exec threatrag bash

# 进入 PostgreSQL 容器
docker-compose exec postgres psql -U postgres -d knowledge_db

# 进入 Neo4j 容器
docker-compose exec neo4j cypher-shell -u neo4j -p 12345678

# 进入 Redis 容器
docker-compose exec redis redis-cli
```

### 重启特定服务

```bash
# 重启 API 服务
docker-compose restart threatrag

# 重启数据库
docker-compose restart postgres

# 重启所有服务
docker-compose restart
```

## 🛠️ 配置自定义

### 环境变量配置

编辑 `.env` 文件来自定义配置：

```bash
# 复制并编辑环境配置
cp .env.example .env
nano .env

# 重启服务应用配置
docker-compose down
docker-compose up -d
```

### 主要配置项

```env
# 基础模型
BASE_MODEL=deepseek-ai/DeepSeek-V3

# 数据库配置
POSTGRES_PASSWORD=your_password
NEO4J_PASSWORD=your_password

# API Keys
OPENAI_API_KEY=your_api_key
SILICONFLOW_API_KEY=your_api_key

# 会话配置
SESSION_EXPIRE_TIME=3600
MAX_CONCURRENT_CHATS=20
```

## 🚨 故障排除

### 1. 端口冲突

如果遇到端口被占用的错误：

```bash
# 查看端口占用
lsof -i :8000
lsof -i :5432

# 修改 docker-compose.yml 中的端口映射
# 例如将 8000:8000 改为 8080:8000
```

### 2. 服务启动失败

```bash
# 查看服务状态
docker-compose ps

# 查看失败服务的日志
docker-compose logs service_name

# 重新构建镜像
docker-compose build --no-cache service_name
```

### 3. 数据库连接失败

```bash
# 检查数据库健康状态
docker-compose exec postgres pg_isready -U postgres

# 重启数据库
docker-compose restart postgres

# 检查网络连接
docker network ls
docker network inspect threatrag_threatrag-network
```

### 4. 向量数据库问题

```bash
# 检查 Milvus 健康状态
curl http://localhost:9091/healthz

# 检查依赖服务
docker-compose logs etcd
docker-compose logs minio

# 重启 Milvus 及依赖
docker-compose restart etcd minio milvus-standalone
```

## 🧹 清理和重置

### 停止服务

```bash
# 优雅停止
./scripts/stop.sh

# 停止并删除容器
./scripts/stop.sh --remove

# 完全清理 (删除所有数据)
./scripts/stop.sh --clean
```

### 手动清理

```bash
# 停止所有服务
docker-compose down

# 删除所有数据卷 (⚠️ 会删除所有数据!)
docker-compose down -v

# 删除所有镜像
docker-compose down --rmi all

# 清理系统
docker system prune -a
```

## 📈 性能优化

### 资源限制

在 `docker-compose.yml` 中添加资源限制：

```yaml
services:
  threatrag:
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '2'
        reservations:
          memory: 2G
          cpus: '1'
```

### 健康检查

所有服务都配置了健康检查，可以通过以下命令查看：

```bash
docker-compose ps
```

健康的服务会显示 "healthy" 状态。

## 🔒 安全建议

1. **修改默认密码**: 在生产环境中务必修改所有默认密码
2. **网络隔离**: 使用防火墙限制外部访问
3. **SSL/TLS**: 在生产环境中启用 HTTPS
4. **备份策略**: 定期备份重要数据卷
5. **监控日志**: 设置日志监控和告警

## 📚 进一步阅读

- [Docker Compose 官方文档](https://docs.docker.com/compose/)
- [Neo4j 容器化部署](https://neo4j.com/docs/operations-manual/current/docker/)
- [Milvus 部署指南](https://milvus.io/docs/install_standalone-docker.md)
- [PostgreSQL Docker 镜像](https://hub.docker.com/_/postgres)
