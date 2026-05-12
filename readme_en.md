# CTI-RAG

CTI-RAG is a Retrieval-Augmented Generation (RAG) framework for Cyber Threat Intelligence (CTI), integrating knowledge graph and causal reasoning capabilities to provide security analysts with an intelligent threat intelligence analysis tool.

## Project Architecture

CTI-RAG consists of the following main modules:

- **RAG Module**: A retrieval-augmented generation system based on LangChain, supporting various document formats and vector databases
- **Knowledge Graph (KG) Module**: Entity relationship extraction, graph construction and storage
- **API Service**: Backend service implemented with FastAPI, providing conversation and retrieval interfaces

```
CTI-RAG/
├── rag/                # Retrieval-Augmented Generation module
│   ├── api/            # API interfaces
│   ├── agents/         # Intelligent agents
│   ├── chains/         # LLM chains
│   └── vector/         # Vector database
├── kg/                 # Knowledge Graph module
│   ├── data_process/   # Data processing
│   └── data_spider/    # Data crawling
├── experiment/         # Experiment module
│   └── rl_moldel/      # Reinforcement learning model
└── main.py             # Main program entry
```

## Features

- **Intelligent Retrieval**: Similarity-based retrieval using vector databases, supporting various document formats
- **Entity Relationship Extraction**: Extracting entities and relationships from unstructured threat intelligence reports
- **Knowledge Graph Construction**: Saving extracted entity relationships to Neo4j graph database
- **Causal Reasoning**: Graph relationship reasoning and completion based on reinforcement learning
- **Streaming Conversation**: Conversation interface with streaming output support

## Quick Start

### Environment Setup

1. Clone the project and install dependencies:

```bash
git clone https://github.com/Ais1on/CTI-RAG.git
cd CTI-RAG
pip install -r requirements.txt
```

The dependency layout is now split into three layers:

- `requirements.txt`: umbrella entry for local development, including API runtime and research/experimental dependencies
- `requirements-api.txt`: runtime dependencies used by the API image
- `requirements-worker.txt`: minimal dependency set used by the task worker image

For local development or debugging, installing `requirements.txt` is sufficient.

2. Configure environment variables (create .env file):

```dotenv
# Model settings
BASE_MODEL=deepseek-ai/DeepSeek-V3
DEEPSEEK_API_KEY=your_deepseek_api_key
OPENAI_API_KEY=your_openai_api_key
OLLAMA_API_BASE=http://localhost:11434

# Environment
FASTAPI_ENV=development

# Neo4j
NEO4J_URL=bolt://localhost:7688
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=12345678

# Redis / RabbitMQ (Phase 1 availability runtime)
REDIS_URL=redis://localhost:6379
RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# Model routing and circuit breaker
MODEL_ROUTER_ENABLED=true
MODEL_ROUTER_DEFAULT_PROVIDER=deepseek
MODEL_ROUTER_DEFAULT_MODEL=deepseek-chat
MODEL_ROUTER_FALLBACK_CHAIN=deepseek:deepseek-chat,ollama:qwen3:30b,ollama:qwen2.5:7b
MODEL_CIRCUIT_BREAKER_ENABLED=true
```

### Start Service

Start the project:

```bash
python ./main.py
```

### Phase 1 Docker Compose Deployment

Use `docker-compose.yml` to bring up the infrastructure, API, and background worker together.

Build the application images first:

```bash
docker compose build threatrag threatrag-worker
```

Then start the full stack:

```bash
docker compose up -d
```

- `threatrag` uses [Dockerfile](/home/lxp/workspace/ThreatRAG/Dockerfile:1) and installs `requirements-api.txt` via `uv`
- `rabbitmq` is the background task transport and healthcheck channel.
- `threatrag-worker` is built from [Dockerfile.worker](/home/lxp/workspace/ThreatRAG/Dockerfile.worker:1), starts with `WORKER_TYPE=task` by default, and only installs `requirements-worker.txt`
- For rollout, bring up healthy `rabbitmq` first, then start `threatrag-worker`, and only then roll API instances so healthcheck tasks do not queue without consumers.

If you only want to validate the Phase 1 availability path, you can start a smaller subset:

```bash
docker compose up -d redis rabbitmq ollama threatrag threatrag-worker
```

Recommended Phase 1 runtime variables in `.env`:

```dotenv
MODEL_ROUTER_ENABLED=true
MODEL_ROUTER_DEFAULT_PROVIDER=deepseek
MODEL_ROUTER_DEFAULT_MODEL=deepseek-chat
MODEL_ROUTER_FALLBACK_CHAIN=deepseek:deepseek-chat,ollama:qwen3:30b,ollama:qwen2.5:7b
MODEL_CIRCUIT_BREAKER_ENABLED=true
MODEL_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
MODEL_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS=60
MODEL_CIRCUIT_BREAKER_OPEN_SECONDS=120
MODEL_CIRCUIT_BREAKER_HALF_OPEN_PROBES=2
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
```

Chat API responses now include routed metadata fields such as `expected_model_provider`, `expected_model_name`, `actual_model_provider`, `actual_model_name`, `degraded`, and `route_reason`.

### Image And Build Notes

This repository does not package every dependency into a single monolithic image. It keeps an "application images + infrastructure images" split:

- Application layer: `threatrag`, `threatrag-worker`
- Infrastructure: `mysql`, `redis`, `rabbitmq`
- Stateful services: `neo4j`, `milvus`, `minio`, `etcd`, `ollama`

This layout is better suited for production operations, upgrades, troubleshooting, and scaling.

### Database Configuration

#### Neo4j

- Username: neo4j
- Password: 12345678
- Access URL: http://localhost:7474/browser/

#### Milvus

By default, Milvus is started through `docker-compose.yml` together with `etcd + minio + milvus-standalone`. Manual local `milvus-server` installation is no longer the recommended path.

## Module Description

### RAG Module

The RAG module is implemented based on LangChain, supporting various document formats and vector databases, providing intelligent retrieval and conversation capabilities.

Key features:
- Support for multiple document formats including PDF, TXT, DOCX, etc.
- Efficient retrieval using FAISS vector database
- Conversation interface with streaming output support
- Automatic detection and update of document changes

### Knowledge Graph Module

The Knowledge Graph module is responsible for extracting entities and relationships from unstructured threat intelligence reports and constructing knowledge graphs.

Main functions:
- Named entity recognition and relationship extraction using large language models
- Support for batch inference and processing
- Saving extracted entity relationships to Neo4j graph database
- Providing graph query and visualization interfaces

### Causal Reasoning Module

The Causal Reasoning module is based on discrete-time topological Hawkes process and reinforcement learning, implementing threat intelligence graph relationship reasoning and completion.

Key features:
- Causality-aware relationship prediction
- Counterfactual reasoning capability
- Graph completion capability
- Explainability guarantee

## Frontend Interface

Frontend project repository: [https://github.com/rstarall/br-cti-chat](https://github.com/rstarall/br-cti-chat)

## Contribution Guidelines

Contributions and issues are welcome! Please follow these steps:

1. Fork the project
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
