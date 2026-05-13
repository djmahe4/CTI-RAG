# Data Persistence & Storage

## 📦 Data Architecture

ThreatRAG utilizes local directory mounting to ensure all data is easily backed up, migrated, and managed. All stateful data is consolidated under the root `data/` directory:

```text
ThreatRAG/
└── data/                   # Unified Persistence Root
    ├── mysql/             # Relational metadata & session history
    ├── redis/             # Caching & real-time state
    ├── neo4j/             # Knowledge graph (entities & relationships)
    ├── milvus/            # High-dimensional vector store
    ├── ollama/            # Local LLM model binaries
    └── kb_*/              # User-specific knowledge base indices
```

### Key Advantages
- **Transparency**: Data is directly accessible on the host filesystem for inspection.
- **Portability**: Migration is as simple as copying the `data/` directory to a new host.
- **Reliability**: Simplified backup workflows via standard filesystem utilities.
- **Observability**: Real-time disk usage monitoring via native OS tools.

---

## 🚀 Initialization

### First-Time Setup
Simply start the stack; the required directories will be provisioned automatically with correct permissions:
```bash
docker compose up -d
```

### Migrating from Docker Volumes
If you are upgrading from a version of ThreatRAG that used managed Docker volumes, run the migration utility:
```bash
sudo bash scripts/migrate-volumes-to-local.sh
```
*For detailed instructions, see the [Volume Migration Guide](volume-migration-guide.md).*

---

## 🔒 Data Protection & Backups

### Manual Backup
```bash
# Create a timestamped archive of all stateful data
tar -czf threatrag-backup-$(date +%Y%m%d).tar.gz data/

# Restoration process
tar -xzf threatrag-backup-[YYYYMMDD].tar.gz
```

### Automated Backup (Cron)
Recommended configuration for daily backups at 02:00:
```cron
0 2 * * * cd /path/to/ThreatRAG && tar -czf /backups/threatrag-$(date +\%Y\%m\%d).tar.gz data/
```

---

## 💾 Disk Space Management

### Monitoring Usage
```bash
du -sh data/*
```

### Storage Requirements
| Component | Minimum | Recommended | Use Case |
| :--- | :--- | :--- | :--- |
| **MySQL** | 1 GB | 5 GB | Session metadata & audit logs |
| **Redis** | 100 MB | 500 MB | Context caching & throughput |
| **Neo4j** | 1 GB | 10 GB | Structural intelligence graph |
| **Milvus** | 5 GB | 50 GB | High-density vector indices |
| **Ollama** | 5 GB | 30 GB | Local model weights |
| **Total** | **~13 GB** | **~100 GB** | |

### Space Optimization
```bash
# Purge unused Ollama models
docker exec -it threatrag-ollama ollama rm <model_name>

# Delete Neo4j logs older than 7 days
find data/neo4j/logs -name "*.log" -mtime +7 -delete

# Clean Docker build artifacts & unused volumes
docker system prune -a
```

---

## 🛡 Version Control
The `.gitignore` is pre-configured to prevent sensitive or heavy data directories from being committed:
```gitignore
data/mysql/
data/redis/
data/neo4j/
data/milvus/
data/ollama/
```
