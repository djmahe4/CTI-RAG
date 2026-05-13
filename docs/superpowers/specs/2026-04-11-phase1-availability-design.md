# ThreatRAG High Availability & Operational Reliability Design (Phase 1)

## 1. Background & Objectives

ThreatRAG currently utilizes a Redis session cache, a RabbitMQ prototype worker, and multi-model access. However, the primary chat pipeline remains dependent on synchronous model invocation within the API process, and model selection is statically configured. While sufficient for development, this architecture is not production-ready due to:

- **Instability**: API processes are directly exposed to upstream model latency and failures, amplifying downstream disruption.
- **Lack of Governance**: There is no centralized management for model health, circuit breaking, fallback chains, or shared state.
- **Underutilized Infrastructure**: Redis is limited to session caching rather than cross-instance state coordination. RabbitMQ remains experimental without a defined production role.

**Phase 1 Goal**: Achieve "Operational Reliability" without major architectural restructuring. We aim to enhance availability and portability while maintaining existing front-end protocols and core interfaces.

---

## 2. Non-Goals (Scope Boundaries)

The following are explicitly excluded from Phase 1:
- Converting the `/chat/stream` endpoint into a fully asynchronous worker-driven flow.
- Introducing new service discovery components or complex presentation systems.
- Refactoring core RAG logic (Retriever, History Manager, MySQL schema).
- Designing for multi-region or multi-datacenter disaster recovery.
- Modifying front-end interaction protocols or event formats.

---

## 3. High-Level Approach: "Stable Hybrid Integration"

- **Synchronous Consistency**: Retain the synchronous streaming output mode for primary interfaces (`/chat/stream`, `/chat/temporary`).
- **Unified Routing Layer**: Introduce a dedicated execution layer for model selection, timeouts, retries, circuit breaking, and fallbacks.
- **Redis as Shared State**: Upgrade Redis to manage distributed runtime state, including model health, circuit status, and task metadata.
- **RabbitMQ for Background Tasks**: Offload non-real-time or high-latency tasks (background searches, health probes, cache preheating) to RabbitMQ.
- **Configuration-First Safety**: Implement feature flags for all new behaviors to allow immediate rollback via environment variables.

---

## 4. Architectural Layers

### 4.1 API Layer
The API layer continues to handle request validation, history persistence, and streaming output, but delegates model selection and resilience logic to the Routing Layer.

### 4.2 Model Routing Layer
A new centralized gateway for all chat model invocations. It accepts an "Expected Model" and a "Decline Strategy," returning execution results and routing telemetry.

### 4.3 Redis Runtime Store
Manages cross-instance coordination of model availability, circuit breaker status, and idempotency keys, separate from persistent session data.

### 4.4 RabbitMQ Task Layer
Handles background jobs and spike buffering to prevent "Head-of-Line" blocking in the primary synchronous chat link.

---

## 5. Model Routing, Circuit Breaking & Fallback Design

### 5.1 Routing Entry Point
Implement `packages/models/router.py`. All model calls must pass through this router rather than directly instantiating specific model classes.

### 5.2 Fallback Chains
Requests specify a preferred model. The router generates a candidate chain based on configuration (e.g., `deepseek-chat` -> `qwen-72b-instruct` -> `local-qwen-7b`). It attempts the primary model first, falling back sequentially if failures occur.

### 5.3 Error Classification
- **Usability Failures (Trigger Circuit Breaking)**: Network errors, timeouts, 429 Rate Limits, Upstream 5xx, streaming disconnects.
- **Logic Failures (Ignore for Circuit Breaking)**: Model not found, missing configuration, invalid parameters, application logic errors.

### 5.4 Circuit Breaker State Machine
Each model maintains a state in Redis:
- **CLOSED**: Normal operation.
- **OPEN**: Failures exceeded threshold; routing to this model is blocked for a cooling period (e.g., 120s).
- **HALF-OPEN**: Cooling period elapsed; allows limited "probe" requests to verify recovery.

### 5.5 Resilience Strategy
- **Retries**: A single "light" retry is allowed per model to minimize latency.
- **Degradation**: If the primary model is unavailable, the router switches to the next alternative in the chain.

### 5.6 Telemetry & Metadata
The `meta` block in API responses will now include:
- `expected_model_name`, `actual_model_name`
- `expected_model_provider`, `actual_model_provider`
- `degraded` (Boolean flag)
- `route_reason` (e.g., "primary_tripped", "timeout_fallback")

---

## 6. Functional Boundaries: Redis vs. RabbitMQ

### 6.1 Redis Responsibilities
- Circuit breaker state & failure counters.
- Short-lived result caching.
- Request idempotency tracking.
- Active task heartbeat monitoring.

### 6.2 RabbitMQ Responsibilities
- Long-running "Deep Research" tasks.
- Periodic model health probes.
- Cache preheating.
- Retrying failed background integrations with exponential backoff.

---

## 7. Implementation Roadmap

### 7.1 New Components
- `packages/models/router.py`: Core routing and circuit breaker logic.
- `packages/models/router_types.py`: Pydantic schemas for routing telemetry.
- `rag/cache/redis_runtime.py`: Distributed state management.
- `rag/mq/task_publisher.py`: Standardized API-to-MQ gateway.
- `rag/mq/task_worker.py`: Background job consumers.

### 7.2 Modifications
- `rag/api/routers/chat_api.py`: Integrated with the router and enhanced metadata.
- `rag/mq/rabbitmq_manager.py`: Enhanced with DLQ (Dead Letter Queue) and retry logic.
- `docker-compose.yml`: Added RabbitMQ and Worker services with proper health checks.

---

## 8. Risk Mitigation & Rollback

### 8.1 Safety Switches
Configuration-driven flags allow for zero-downtime disabling of the new routing logic:
- `MODEL_ROUTER_ENABLED=false`
- `MODEL_CIRCUIT_BREAKER_ENABLED=false`

### 8.2 Rollback Strategy
If the HA layer introduces anomalies, toggle the environment variables to bypass the router. This falls back to the original static selection logic without requiring a full code rollback.

---

## 9. Definition of Success (Phase 1)
Success is defined not by architectural complexity, but by:
1. **Measured Uptime**: Reduction in 5xx errors during upstream provider outages.
2. **Predictable Performance**: Consistent P95 latency even when primary models are lagging.
3. **Operational Visibility**: Clear telemetry on when and why model degradation occurs.
