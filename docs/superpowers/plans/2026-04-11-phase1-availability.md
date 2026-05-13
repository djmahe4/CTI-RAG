# Case 1: High Availability Implementation Plan

> [!IMPORTANT]
> **Mandatory Sub-skill Usage**: Use `subagent-driven-development` or `executing-plans` to enforce this plan task-by-task. Maintain progress tracking via the provided checkboxes (`[ ]`).

**Objective**: Implement a robust High Availability (HA) layer for ThreatRAG without disrupting existing synchronous streaming chat pipelines. Key features include: unified model routing, circuit breaking/degradation, a Redis-backed runtime state layer, and RabbitMQ-driven background task infrastructure.

**Architecture**: 
- Keep `rag/api/routers/chat_api.py` as the synchronous entry point.
- Centralize routing logic in `packages/models/router.py`.
- Synchronize service health and task status across instances using `rag/cache/redis_runtime.py`.
- Offload non-critical background tasks and retries to RabbitMQ via `threatrag-worker`, ensuring token streaming remains low-latency.

**Tech Stack**: FastAPI, Redis, RabbitMQ (pika), OpenAI-compatible APIs, pytest, Docker Compose.

---

# 📂 File Structure

### Core Components
- `rag/config/runtime_config.py`: Environment-driven configuration loader.
- `rag/cache/redis_runtime.py`: Distributed state and circuit breaker storage.
- `packages/models/router_types.py`: Unified error and routing data structures.
- `packages/models/router.py`: Model routing and fallback engine.
- `rag/mq/task_publisher.py`: Async task emission gateway.
- `rag/mq/task_worker.py`: Background task consumer logic.

### Testing Suite
- `tests/test_runtime_config.py`: Configuration validation.
- `tests/test_redis_runtime.py`: State persistence verification.
- `tests/test_chat_model_errors.py`: Error classification logic.
- `tests/test_model_router.py`: Routing, fallback, and circuit breaker tests.
- `tests/test_chat_api_router.py`: API integration validation.
- `tests/test_task_worker.py`: Message queue orchestration tests.
- `tests/test_deployment_wiring.py`: Infrastructure and deployment verification.

---

# 🛠 Phase 1: Configuration & Dependency Setup

### Task 1: Runtime Configuration & Environment Mapping
- **Files**: `rag/config/runtime_config.py`, `.env.example`, `requirements.txt`.

- [ ] **Step 1**: Create `tests/test_runtime_config.py` with failing cases for fallback chain parsing.
- [ ] **Step 2**: Implement `RuntimeConfig` in `rag/config/runtime_config.py` with support for:
    - `MODEL_ROUTER_ENABLED`
    - `MODEL_ROUTER_FALLBACK_CHAIN`
    - `MODEL_CIRCUIT_BREAKER_FAILURE_THRESHOLD`
- [ ] **Step 3**: Update `.env.example` and `requirements.txt` (add `pika`).
- [ ] **Step 4**: Verify all configuration tests pass.

---

# 🛠 Phase 2: State Persistence & Distributed Tracking

### Task 2: Redis Runtime Store Implementation
- **Files**: `rag/cache/redis_runtime.py`, `tests/test_redis_runtime.py`.

- [ ] **Step 1**: Implement `RedisRuntimeStore` to manage:
    - Circuit breaker states (Closed, Open, Half-Open).
    - Request idempotency tracking.
    - Background task statuses.
- [ ] **Step 2**: Verify state transitions and TTL logic via `tests/test_redis_runtime.py`.

---

# 🛠 Phase 3: Intelligence & Routing Logic

### Task 3: Error Normalization & Classification
- **Files**: `packages/models/router_types.py`, `packages/models/chat_model.py`.

- [ ] **Step 1**: Define `ModelInvocationError` in `router_types.py` (fields: `retryable`, `counts_for_circuit_breaker`).
- [ ] **Step 2**: Implement `classify_model_exception` in `chat_model.py` to map upstream errors (timeouts, rate limits, 5xx) to normalized types.

### Task 4: Implementation of Model Router (Fallback & Breaker)
- **Files**: `packages/models/router.py`, `packages/models/__init__.py`.

- [ ] **Step 1**: Implement `ModelRouter.predict()` with logic to:
    - Pick the best healthy route based on Redis state.
    - Execute fallbacks upon retryable failures.
    - Trip the circuit breaker on threshold breach.
- [ ] **Step 2**: Fully validate routing behavior in `tests/test_model_router.py`.

---

# 🛠 Phase 4: System Integration

### Task 5: API Gateway Integration
- **Files**: `rag/api/routers/chat_api.py`, `tests/test_chat_api_router.py`.

- [ ] **Step 1**: Replace direct model calls with `model_router.predict()` in the chat routers.
- [ ] **Step 2**: Ensure the `meta` response block includes routing telemetry (`actual_model_name`, `degraded`, etc.).
- [ ] **Step 3**: Verify streaming compatibility and metadata integrity.

### Task 6: Background Worker & RabbitMQ Topology
- **Files**: `rag/mq/task_publisher.py`, `rag/mq/task_worker.py`, `worker.py`, `Dockerfile.worker`.

- [ ] **Step 1**: Configure RabbitMQ exchange and queue topology (including DLQ and Retry Queues).
- [ ] **Step 2**: Implement the background healthcheck task to auto-reset tripped circuits.
- [ ] **Step 3**: Update the Docker worker image and entrypoint.

---

# 🛠 Phase 5: Deployment & Documentation

### Task 7: Infrastructure Wiring & Final Documentation
- **Files**: `docker-compose.yml`, `README.md`, `docs/chat-api-summary.md`.

- [ ] **Step 1**: Add RabbitMQ and worker service definitions to `docker-compose.yml`.
- [ ] **Step 2**: Document the service startup order and HA configuration in the README.
- [ ] **Step 3**: Conduct a final repository audit to verify no Mixed-Language artifacts remain in logs or CLI strings.

---

# 🔍 Final Review Checklist
- [ ] All 7 tasks verified via unit tests.
- [ ] No "TODO" or "PLACEHOLDER" comments in implementation.
- [ ] Circuit breaker threshold logic aligned across API and Worker.
- [ ] Zero Chinese character presence in logs or help strings.
