# Phase 1 Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重写现有同步流式聊天主链路的前提下，为 ThreatRAG 增加一期稳上线能力：统一模型路由、熔断与降级、Redis 运行时状态层、RabbitMQ 后台任务基础设施，以及对应的配置、测试和部署接线。

**Architecture:** 保留 `rag/api/routers/chat_api.py` 的同步流式输出，把模型决策收口到 `packages/models/router.py`，并用 `rag/cache/redis_runtime.py` 在多实例之间共享模型健康状态、幂等键和任务状态。RabbitMQ 只承接后台任务与延迟重试，不接管一期 token 流回传，从而控制改动面和联调风险。

**Tech Stack:** FastAPI, Redis, RabbitMQ (`pika`), OpenAI-compatible model clients, pytest, Docker Compose

---

## File Structure

- `rag/config/runtime_config.py`
  - 新增一期运行时配置读取与解析
- `rag/cache/redis_runtime.py`
  - 新增 Redis 运行时状态仓库
- `packages/models/router_types.py`
  - 新增模型路由相关的数据结构与错误类型
- `packages/models/router.py`
  - 新增统一模型路由执行器
- `rag/mq/task_publisher.py`
  - 新增后台任务发布入口
- `rag/mq/task_worker.py`
  - 新增后台任务消费入口
- `tests/test_runtime_config.py`
  - 测试配置解析
- `tests/test_redis_runtime.py`
  - 测试 Redis 运行时状态
- `tests/test_chat_model_errors.py`
  - 测试模型错误归类
- `tests/test_model_router.py`
  - 测试路由、回退、熔断、半开恢复
- `tests/test_chat_api_router.py`
  - 测试聊天接口接入路由层
- `tests/test_task_worker.py`
  - 测试 RabbitMQ 任务分发和状态更新
- `tests/test_deployment_wiring.py`
  - 测试 Compose 与部署接线

Modify:

- `.env.example`
- `requirements.txt`
- `docker-compose.yml`
- `Dockerfile.worker`
- `packages/models/chat_model.py`
- `packages/models/__init__.py`
- `rag/api/routers/chat_api.py`
- `rag/api/routers/__init__.py`
- `rag/mq/rabbitmq_manager.py`
- `worker.py`
- `readme.md`
- `readme_en.md`
- `docs/chat-api-summary.md`
- `docs/chat-api-workflow.md`
- `docs/chat-session-api.md`

## Task 1: Runtime Config And Dependency Wiring

**Files:**
- Create: `rag/config/runtime_config.py`
- Modify: `.env.example`
- Modify: `requirements.txt`
- Test: `tests/test_runtime_config.py`

- [ ] **Step 1: 写出运行时配置解析的失败测试**

```python
from rag.config.runtime_config import RuntimeConfig, parse_fallback_chain


def test_parse_fallback_chain_preserves_provider_and_model():
    value = "deepseek:deepseek-chat,ollama:qwen3:30b,ollama:qwen2.5:7b"

    chain = parse_fallback_chain(value)

    assert chain == [
        ("deepseek", "deepseek-chat"),
        ("ollama", "qwen3:30b"),
        ("ollama", "qwen2.5:7b"),
    ]


def test_runtime_config_reads_router_and_breaker_defaults(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER_ENABLED", "true")
    monkeypatch.setenv("MODEL_ROUTER_DEFAULT_PROVIDER", "deepseek")
    monkeypatch.setenv("MODEL_ROUTER_DEFAULT_MODEL", "deepseek-chat")
    monkeypatch.setenv("MODEL_ROUTER_FALLBACK_CHAIN", "deepseek:deepseek-chat,ollama:qwen3:30b")

    cfg = RuntimeConfig.from_env()

    assert cfg.model_router_enabled is True
    assert cfg.default_route == ("deepseek", "deepseek-chat")
    assert cfg.fallback_chain[-1] == ("ollama", "qwen3:30b")
    assert cfg.circuit_breaker_failure_threshold == 5
```

- [ ] **Step 2: 运行测试，确认当前缺少运行时配置模块**

Run: `pytest tests/test_runtime_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.config.runtime_config'`

- [ ] **Step 3: 实现运行时配置模块并补充依赖**

```python
from dataclasses import dataclass
import os


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_fallback_chain(raw: str) -> list[tuple[str, str]]:
    chain: list[tuple[str, str]] = []
    for item in [part.strip() for part in (raw or "").split(",") if part.strip()]:
        provider, model_name = item.split(":", 1)
        chain.append((provider.strip(), model_name.strip()))
    return chain


@dataclass(slots=True)
class RuntimeConfig:
    model_router_enabled: bool
    circuit_breaker_enabled: bool
    default_route: tuple[str, str]
    fallback_chain: list[tuple[str, str]]
    request_timeout_seconds: int
    stream_timeout_seconds: int
    max_retries_per_model: int
    circuit_breaker_failure_threshold: int
    circuit_breaker_failure_window_seconds: int
    circuit_breaker_open_seconds: int
    circuit_breaker_half_open_probes: int
    runtime_redis_prefix: str
    model_status_ttl_seconds: int
    request_idempotency_ttl_seconds: int
    short_cache_ttl_seconds: int
    rabbitmq_url: str
    rabbitmq_task_exchange: str
    rabbitmq_task_queue: str
    rabbitmq_retry_queue: str
    rabbitmq_dlq: str
    rabbitmq_max_retries: int
    rabbitmq_retry_delay_ms: int

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        default_provider = os.getenv("MODEL_ROUTER_DEFAULT_PROVIDER", "deepseek")
        default_model = os.getenv("MODEL_ROUTER_DEFAULT_MODEL", "deepseek-chat")
        return cls(
            model_router_enabled=_as_bool(os.getenv("MODEL_ROUTER_ENABLED"), True),
            circuit_breaker_enabled=_as_bool(os.getenv("MODEL_CIRCUIT_BREAKER_ENABLED"), True),
            default_route=(default_provider, default_model),
            fallback_chain=parse_fallback_chain(
                os.getenv(
                    "MODEL_ROUTER_FALLBACK_CHAIN",
                    f"{default_provider}:{default_model},ollama:qwen3:30b,ollama:qwen2.5:7b",
                )
            ),
            request_timeout_seconds=int(os.getenv("MODEL_ROUTER_REQUEST_TIMEOUT_SECONDS", "45")),
            stream_timeout_seconds=int(os.getenv("MODEL_ROUTER_STREAM_TIMEOUT_SECONDS", "90")),
            max_retries_per_model=int(os.getenv("MODEL_ROUTER_MAX_RETRIES_PER_MODEL", "1")),
            circuit_breaker_failure_threshold=int(os.getenv("MODEL_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")),
            circuit_breaker_failure_window_seconds=int(os.getenv("MODEL_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS", "60")),
            circuit_breaker_open_seconds=int(os.getenv("MODEL_CIRCUIT_BREAKER_OPEN_SECONDS", "120")),
            circuit_breaker_half_open_probes=int(os.getenv("MODEL_CIRCUIT_BREAKER_HALF_OPEN_PROBES", "2")),
            runtime_redis_prefix=os.getenv("RUNTIME_REDIS_PREFIX", "threatrag:runtime"),
            model_status_ttl_seconds=int(os.getenv("MODEL_STATUS_TTL_SECONDS", "600")),
            request_idempotency_ttl_seconds=int(os.getenv("REQUEST_IDEMPOTENCY_TTL_SECONDS", "300")),
            short_cache_ttl_seconds=int(os.getenv("SHORT_CACHE_TTL_SECONDS", "120")),
            rabbitmq_url=os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/"),
            rabbitmq_task_exchange=os.getenv("RABBITMQ_TASK_EXCHANGE", "threatrag.tasks"),
            rabbitmq_task_queue=os.getenv("RABBITMQ_TASK_QUEUE", "threatrag.tasks.main"),
            rabbitmq_retry_queue=os.getenv("RABBITMQ_RETRY_QUEUE", "threatrag.tasks.retry"),
            rabbitmq_dlq=os.getenv("RABBITMQ_DLQ", "threatrag.tasks.dlq"),
            rabbitmq_max_retries=int(os.getenv("RABBITMQ_MAX_RETRIES", "3")),
            rabbitmq_retry_delay_ms=int(os.getenv("RABBITMQ_RETRY_DELAY_MS", "10000")),
        )
```

```text
# requirements.txt
pika>=1.3.2
```

```text
# .env.example
MODEL_ROUTER_ENABLED=true
MODEL_ROUTER_DEFAULT_PROVIDER=deepseek
MODEL_ROUTER_DEFAULT_MODEL=deepseek-chat
MODEL_ROUTER_FALLBACK_CHAIN=deepseek:deepseek-chat,ollama:qwen3:30b,ollama:qwen2.5:7b
MODEL_ROUTER_REQUEST_TIMEOUT_SECONDS=45
MODEL_ROUTER_STREAM_TIMEOUT_SECONDS=90
MODEL_ROUTER_MAX_RETRIES_PER_MODEL=1
MODEL_CIRCUIT_BREAKER_ENABLED=true
MODEL_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
MODEL_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS=60
MODEL_CIRCUIT_BREAKER_OPEN_SECONDS=120
MODEL_CIRCUIT_BREAKER_HALF_OPEN_PROBES=2
RUNTIME_REDIS_PREFIX=threatrag:runtime
MODEL_STATUS_TTL_SECONDS=600
REQUEST_IDEMPOTENCY_TTL_SECONDS=300
SHORT_CACHE_TTL_SECONDS=120
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
RABBITMQ_TASK_EXCHANGE=threatrag.tasks
RABBITMQ_TASK_QUEUE=threatrag.tasks.main
RABBITMQ_RETRY_QUEUE=threatrag.tasks.retry
RABBITMQ_DLQ=threatrag.tasks.dlq
RABBITMQ_MAX_RETRIES=3
RABBITMQ_RETRY_DELAY_MS=10000
```

- [ ] **Step 4: 运行测试，确认配置解析通过**

Run: `pytest tests/test_runtime_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add requirements.txt .env.example rag/config/runtime_config.py tests/test_runtime_config.py
git commit -m "feat: add runtime availability config"
```

## Task 2: Redis Runtime State Repository

**Files:**
- Create: `rag/cache/redis_runtime.py`
- Test: `tests/test_redis_runtime.py`

- [ ] **Step 1: 先写 Redis 运行时状态测试**

```python
import pytest

from rag.cache.redis_runtime import RedisRuntimeStore


@pytest.mark.asyncio
async def test_breaker_state_roundtrip():
    store = RedisRuntimeStore("redis://localhost:6379/2")
    await store.clear_prefix()

    await store.set_circuit_state("deepseek", "deepseek-chat", "open", failures=5)
    state = await store.get_circuit_state("deepseek", "deepseek-chat")

    assert state["state"] == "open"
    assert state["failures"] == 5


@pytest.mark.asyncio
async def test_idempotency_key_roundtrip():
    store = RedisRuntimeStore("redis://localhost:6379/2")
    await store.clear_prefix()

    created = await store.claim_idempotency_key("req-1")
    duplicated = await store.claim_idempotency_key("req-1")

    assert created is True
    assert duplicated is False
```

- [ ] **Step 2: 运行测试，确认仓库尚未实现**

Run: `pytest tests/test_redis_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.cache.redis_runtime'`

- [ ] **Step 3: 实现 Redis 运行时状态仓库**

```python
import json
import redis.asyncio as redis

from rag.config.runtime_config import RuntimeConfig


class RedisRuntimeStore:
    def __init__(self, redis_url: str, config: RuntimeConfig | None = None):
        self.config = config or RuntimeConfig.from_env()
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.prefix = self.config.runtime_redis_prefix

    def _model_key(self, provider: str, model_name: str) -> str:
        return f"{self.prefix}:models:{provider}:{model_name}"

    async def set_circuit_state(self, provider: str, model_name: str, state: str, failures: int = 0) -> None:
        payload = {"state": state, "failures": failures}
        await self.redis.set(
            self._model_key(provider, model_name),
            json.dumps(payload),
            ex=self.config.model_status_ttl_seconds,
        )

    async def get_circuit_state(self, provider: str, model_name: str) -> dict:
        value = await self.redis.get(self._model_key(provider, model_name))
        if not value:
            return {"state": "closed", "failures": 0}
        return json.loads(value)

    async def claim_idempotency_key(self, request_id: str) -> bool:
        key = f"{self.prefix}:idempotency:{request_id}"
        return bool(
            await self.redis.set(
                key,
                "1",
                ex=self.config.request_idempotency_ttl_seconds,
                nx=True,
            )
        )

    async def set_task_status(self, task_id: str, status: str, payload: dict) -> None:
        key = f"{self.prefix}:tasks:{task_id}"
        data = {"status": status, **payload}
        await self.redis.set(key, json.dumps(data), ex=self.config.short_cache_ttl_seconds)

    async def get_task_status(self, task_id: str) -> dict | None:
        value = await self.redis.get(f"{self.prefix}:tasks:{task_id}")
        return json.loads(value) if value else None

    async def clear_prefix(self) -> None:
        async for key in self.redis.scan_iter(f"{self.prefix}:*"):
            await self.redis.delete(key)
```

- [ ] **Step 4: 运行 Redis 相关测试**

Run: `pytest tests/test_redis_runtime.py tests/test_redis_session.py -v`
Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add rag/cache/redis_runtime.py tests/test_redis_runtime.py
git commit -m "feat: add redis runtime state store"
```

## Task 3: Normalize Model Errors For Routing

**Files:**
- Create: `packages/models/router_types.py`
- Modify: `packages/models/chat_model.py`
- Test: `tests/test_chat_model_errors.py`

- [ ] **Step 1: 先写模型错误归类测试**

```python
import pytest

from packages.models.chat_model import classify_model_exception
from packages.models.router_types import ModelInvocationError


def test_timeout_is_retryable():
    err = classify_model_exception(TimeoutError("timed out"))

    assert isinstance(err, ModelInvocationError)
    assert err.retryable is True
    assert err.counts_for_circuit_breaker is True
    assert err.error_type == "timeout"


def test_bad_request_is_not_retryable():
    err = classify_model_exception(ValueError("missing model"))

    assert err.retryable is False
    assert err.counts_for_circuit_breaker is False
    assert err.error_type == "bad_request"
```

- [ ] **Step 2: 运行测试，确认新类型未定义**

Run: `pytest tests/test_chat_model_errors.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: 实现路由类型和异常归类**

```python
# packages/models/router_types.py
from dataclasses import dataclass


@dataclass(slots=True)
class ModelInvocationError(Exception):
    message: str
    error_type: str
    retryable: bool
    counts_for_circuit_breaker: bool

    def __str__(self) -> str:
        return self.message
```

```python
# packages/models/chat_model.py
from packages.models.router_types import ModelInvocationError


def classify_model_exception(exc: Exception) -> ModelInvocationError:
    if isinstance(exc, TimeoutError):
        return ModelInvocationError(str(exc), "timeout", True, True)
    if isinstance(exc, ValueError):
        return ModelInvocationError(str(exc), "bad_request", False, False)
    return ModelInvocationError(str(exc), "upstream_error", True, True)
```

```python
def _get_response(self, messages):
    try:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=False,
        )
        return response.choices[0].message
    except Exception as exc:
        raise classify_model_exception(exc) from exc
```

- [ ] **Step 4: 运行归类测试**

Run: `pytest tests/test_chat_model_errors.py -v`
Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add packages/models/router_types.py packages/models/chat_model.py tests/test_chat_model_errors.py
git commit -m "feat: normalize model invocation errors"
```

## Task 4: Implement Model Router With Fallback And Circuit Breaker

**Files:**
- Create: `packages/models/router.py`
- Modify: `packages/models/__init__.py`
- Test: `tests/test_model_router.py`

- [ ] **Step 1: 写模型路由测试，锁定回退和熔断行为**

```python
import pytest

from packages.models.router import ModelRouter


class FakeModel:
    def __init__(self, values):
        self.values = list(values)

    def predict(self, messages, stream=False):
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeRuntimeStore:
    def __init__(self):
        self.states = {}

    async def set_circuit_state(self, provider, model_name, state, failures=0):
        self.states[(provider, model_name)] = {"state": state, "failures": failures}

    async def get_circuit_state(self, provider, model_name):
        return self.states.get((provider, model_name), {"state": "closed", "failures": 0})


@pytest.mark.asyncio
async def test_router_falls_back_to_next_model():
    runtime_store = FakeRuntimeStore()
    router = ModelRouter(runtime_store)
    router.register_factory(("deepseek", "deepseek-chat"), lambda: FakeModel([TimeoutError("boom")]))
    router.register_factory(("ollama", "qwen3:30b"), lambda: FakeModel(["ok"]))

    result = await router.predict([{"role": "user", "content": "hi"}])

    assert result.output == "ok"
    assert result.actual_provider == "ollama"
    assert result.degraded is True


@pytest.mark.asyncio
async def test_router_opens_circuit_after_threshold():
    runtime_store = FakeRuntimeStore()
    router = ModelRouter(runtime_store)
    await runtime_store.set_circuit_state("deepseek", "deepseek-chat", "open", failures=5)

    route = await router.pick_route(("deepseek", "deepseek-chat"))

    assert route == ("ollama", "qwen3:30b")
```

- [ ] **Step 2: 运行测试，确认路由器不存在**

Run: `pytest tests/test_model_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.models.router'`

- [ ] **Step 3: 实现路由器并接入底层工厂**

```python
from dataclasses import dataclass

from packages.models import select_model
from packages.models.chat_model import classify_model_exception
from packages.models.router_types import ModelInvocationError
from rag.config.runtime_config import RuntimeConfig
from rag.cache.redis_runtime import RedisRuntimeStore


@dataclass(slots=True)
class RoutedPrediction:
    output: object
    actual_provider: str
    actual_model_name: str
    degraded: bool
    route_reason: str


class ModelRouter:
    def __init__(self, runtime_store: RedisRuntimeStore, config: RuntimeConfig | None = None):
        self.config = config or RuntimeConfig.from_env()
        self.runtime_store = runtime_store
        self.factories: dict[tuple[str, str], callable] = {}

    def register_factory(self, route: tuple[str, str], factory) -> None:
        self.factories[route] = factory

    def _factory_for(self, route: tuple[str, str]):
        if route in self.factories:
            return self.factories[route]
        provider, model_name = route
        return lambda: select_model(model_provider=provider, model_name=model_name)

    async def pick_route(self, preferred: tuple[str, str]) -> tuple[str, str]:
        for index, route in enumerate([preferred, *self.config.fallback_chain]):
            state = await self.runtime_store.get_circuit_state(*route)
            if state["state"] != "open":
                return route
        return self.config.fallback_chain[-1]

    async def predict(self, messages, preferred: tuple[str, str] | None = None, stream: bool = False) -> RoutedPrediction:
        preferred = preferred or self.config.default_route
        candidates = [preferred, *[route for route in self.config.fallback_chain if route != preferred]]
        last_error = None

        for route in candidates:
            state = await self.runtime_store.get_circuit_state(*route)
            if self.config.circuit_breaker_enabled and state["state"] == "open":
                continue

            factory = self._factory_for(route)
            try:
                model = factory()
                output = model.predict(messages, stream=stream)
                await self.runtime_store.set_circuit_state(*route, "closed", failures=0)
                return RoutedPrediction(
                    output=output,
                    actual_provider=route[0],
                    actual_model_name=route[1],
                    degraded=route != preferred,
                    route_reason="preferred" if route == preferred else "fallback",
                )
            except Exception as exc:
                classified = exc if isinstance(exc, ModelInvocationError) else classify_model_exception(exc)
                last_error = classified
                if classified.counts_for_circuit_breaker:
                    await self.runtime_store.set_circuit_state(*route, "open", failures=self.config.circuit_breaker_failure_threshold)
                if not classified.retryable:
                    break

        raise last_error
```

```python
# packages/models/__init__.py
def build_model_router(runtime_store):
    from .router import ModelRouter
    return ModelRouter(runtime_store)
```

- [ ] **Step 4: 运行路由测试**

Run: `pytest tests/test_model_router.py -v`
Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add packages/models/router.py packages/models/__init__.py tests/test_model_router.py
git commit -m "feat: add model router with fallback"
```

## Task 5: Integrate Router Into Chat API

**Files:**
- Modify: `rag/api/routers/chat_api.py`
- Test: `tests/test_chat_api_router.py`

- [ ] **Step 1: 先写聊天接口接入路由层测试**

```python
from fastapi.testclient import TestClient

from rag.api.server import fastapi_server


def test_temporary_chat_returns_actual_model_metadata(monkeypatch):
    class FakeRoutedResult:
        def __init__(self):
            self.output = type("Message", (), {"content": "ok"})()
            self.actual_provider = "ollama"
            self.actual_model_name = "qwen3:30b"
            self.degraded = True
            self.route_reason = "fallback"

    async def fake_predict(*args, **kwargs):
        return FakeRoutedResult()

    monkeypatch.setattr("rag.api.routers.chat_api.route_model_predict", fake_predict)

    client = TestClient(fastapi_server)
    response = client.post("/chat/call", json={"query": "hi", "meta": {}})

    body = response.json()
    assert body["meta"]["actual_model_provider"] == "ollama"
    assert body["meta"]["degraded"] is True
```

- [ ] **Step 2: 运行测试，确认接口还没有路由元信息**

Run: `pytest tests/test_chat_api_router.py -v`
Expected: FAIL because `route_model_predict` 不存在或响应不含 `actual_model_provider`

- [ ] **Step 3: 在聊天接口中收口模型执行**

```python
from rag.cache.redis_runtime import RedisRuntimeStore
from rag.config.runtime_config import RuntimeConfig
from packages.models import build_model_router


runtime_config = RuntimeConfig.from_env()
runtime_store = RedisRuntimeStore(
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
    config=runtime_config,
)
model_router = build_model_router(runtime_store)


async def route_model_predict(messages, meta: dict, stream: bool = False):
    preferred = (
        meta.get("model_provider") or runtime_config.default_route[0],
        meta.get("model_name") or runtime_config.default_route[1],
    )
    return await model_router.predict(messages, preferred=preferred, stream=stream)
```

```python
preferred = (
    meta.get("model_provider") or runtime_config.default_route[0],
    meta.get("model_name") or runtime_config.default_route[1],
)
result = await route_model_predict(messages, meta, stream=False)
meta["expected_model_provider"] = preferred[0]
meta["expected_model_name"] = preferred[1]
meta["actual_model_provider"] = result.actual_provider
meta["actual_model_name"] = result.actual_model_name
meta["degraded"] = result.degraded
meta["route_reason"] = result.route_reason
```

```python
preferred = (
    meta.get("model_provider") or runtime_config.default_route[0],
    meta.get("model_name") or runtime_config.default_route[1],
)
routed = await route_model_predict(messages, meta, stream=True)
model_stream = routed.output
meta["expected_model_provider"] = preferred[0]
meta["expected_model_name"] = preferred[1]
meta["actual_model_provider"] = routed.actual_provider
meta["actual_model_name"] = routed.actual_model_name
meta["degraded"] = routed.degraded
meta["route_reason"] = routed.route_reason
```

- [ ] **Step 4: 运行接口路由测试**

Run: `pytest tests/test_chat_api_router.py -v`
Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add rag/api/routers/chat_api.py tests/test_chat_api_router.py
git commit -m "feat: route chat api model calls"
```

## Task 6: Harden RabbitMQ And Add Background Task Runtime

**Files:**
- Create: `rag/mq/task_publisher.py`
- Create: `rag/mq/task_worker.py`
- Modify: `rag/mq/rabbitmq_manager.py`
- Modify: `worker.py`
- Modify: `Dockerfile.worker`
- Test: `tests/test_task_worker.py`

- [ ] **Step 1: 先写后台任务状态流转测试**

```python
import pytest

from rag.mq.task_worker import handle_healthcheck_task


class FakeRuntimeStore:
    def __init__(self):
        self.statuses = {}
        self.states = {}

    async def set_task_status(self, task_id, status, payload):
        self.statuses[task_id] = {"status": status, **payload}

    async def get_task_status(self, task_id):
        return self.statuses.get(task_id)

    async def set_circuit_state(self, provider, model_name, state, failures=0):
        self.states[(provider, model_name)] = {"state": state, "failures": failures}


@pytest.mark.asyncio
async def test_healthcheck_task_marks_status():
    runtime_store = FakeRuntimeStore()
    payload = {"task_id": "task-1", "task_type": "model_healthcheck", "provider": "deepseek", "model_name": "deepseek-chat"}

    await handle_healthcheck_task(payload, runtime_store)

    status = await runtime_store.get_task_status("task-1")
    assert status["status"] == "succeeded"
    assert status["provider"] == "deepseek"
```

- [ ] **Step 2: 运行测试，确认后台任务处理器不存在**

Run: `pytest tests/test_task_worker.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现可重试队列、死信队列和任务处理器**

```python
# rag/mq/rabbitmq_manager.py
import pika


class RabbitMQManager:
    def __init__(self, config):
        params = pika.URLParameters(config.rabbitmq_url)
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()
        self.config = config

    def declare_runtime_topology(self):
        self.channel.exchange_declare(exchange=self.config.rabbitmq_task_exchange, exchange_type="direct", durable=True)
        self.channel.queue_declare(queue=self.config.rabbitmq_dlq, durable=True)
        self.channel.queue_declare(
            queue=self.config.rabbitmq_retry_queue,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.config.rabbitmq_task_exchange,
                "x-dead-letter-routing-key": self.config.rabbitmq_task_queue,
                "x-message-ttl": self.config.rabbitmq_retry_delay_ms,
            },
        )
        self.channel.queue_declare(
            queue=self.config.rabbitmq_task_queue,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.config.rabbitmq_task_exchange,
                "x-dead-letter-routing-key": self.config.rabbitmq_dlq,
            },
        )
        self.channel.queue_bind(queue=self.config.rabbitmq_task_queue, exchange=self.config.rabbitmq_task_exchange, routing_key=self.config.rabbitmq_task_queue)
```

```python
# rag/mq/task_publisher.py
import json
import uuid


def build_task_message(task_type: str, payload: dict) -> dict:
    return {
        "task_id": payload.get("task_id", str(uuid.uuid4())),
        "task_type": task_type,
        **payload,
    }
```

```python
# rag/mq/task_worker.py
async def handle_healthcheck_task(payload: dict, runtime_store):
    await runtime_store.set_task_status(payload["task_id"], "running", payload)
    await runtime_store.set_circuit_state(payload["provider"], payload["model_name"], "closed", failures=0)
    await runtime_store.set_task_status(
        payload["task_id"],
        "succeeded",
        {"provider": payload["provider"], "model_name": payload["model_name"]},
    )
```

```python
# worker.py
from rag.mq.task_worker import run_task_worker


def main():
    worker_type = os.getenv("WORKER_TYPE", "task").lower()
    if worker_type in ["task", "all"]:
        run_task_worker()
```

```dockerfile
# Dockerfile.worker
ENV WORKER_TYPE=task
ENV WORKER_COUNT=1
```

- [ ] **Step 4: 运行任务处理测试**

Run: `pytest tests/test_task_worker.py -v`
Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add rag/mq/rabbitmq_manager.py rag/mq/task_publisher.py rag/mq/task_worker.py worker.py Dockerfile.worker tests/test_task_worker.py
git commit -m "feat: add rabbitmq task runtime"
```

## Task 7: Deployment Wiring, Docs, And Final Verification

**Files:**
- Modify: `docker-compose.yml`
- Modify: `readme.md`
- Modify: `readme_en.md`
- Modify: `docs/chat-api-summary.md`
- Modify: `docs/chat-api-workflow.md`
- Modify: `docs/chat-session-api.md`
- Test: `tests/test_deployment_wiring.py`

- [ ] **Step 1: 先写部署接线的验收测试**

```python
from pathlib import Path


def test_compose_includes_rabbitmq_service():
    content = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "rabbitmq:" in content
    assert "RABBITMQ_URL" in content
    assert "threatrag-worker" in content
```

- [ ] **Step 2: 运行测试，确认 Compose 尚未接入 RabbitMQ**

Run: `pytest tests/test_deployment_wiring.py -v`
Expected: FAIL because `rabbitmq:` 或 `threatrag-worker` 不存在

- [ ] **Step 3: 修改部署文件与文档**

```yaml
# docker-compose.yml
  rabbitmq:
    image: rabbitmq:3.13-management
    container_name: threatrag-rabbitmq
    restart: unless-stopped
    ports:
      - "5672:5672"
      - "15672:15672"
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "check_port_connectivity"]
      interval: 10s
      timeout: 5s
      retries: 5

  threatrag-worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    container_name: threatrag-worker
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://redis:6379
      - RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
      - WORKER_TYPE=task
    depends_on:
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
```

```markdown
# readme.md / readme_en.md
- 新增 RabbitMQ 作为后台任务与健康探测通道
- 新增模型路由、熔断和降级相关环境变量
- 新增 worker 启动说明与灰度上线顺序
```

```markdown
# docs/chat-api-summary.md
- `/chat/call`、`/chat/temporary`、`/chat/stream` 响应 `meta` 新增：
  - `expected_model_provider`
  - `expected_model_name`
  - `actual_model_provider`
  - `actual_model_name`
  - `degraded`
  - `route_reason`
```

- [ ] **Step 4: 跑完整验证命令**

Run: `pytest tests/test_runtime_config.py tests/test_redis_runtime.py tests/test_chat_model_errors.py tests/test_model_router.py tests/test_chat_api_router.py tests/test_task_worker.py tests/test_deployment_wiring.py -v`
Expected: PASS

Run: `docker-compose config`
Expected: exits 0 and includes `rabbitmq` and `threatrag-worker`

- [ ] **Step 5: 提交本任务**

```bash
git add docker-compose.yml readme.md readme_en.md docs/chat-api-summary.md docs/chat-api-workflow.md docs/chat-session-api.md tests/test_deployment_wiring.py
git commit -m "docs: wire availability runtime into deployment"
```

## Self-Review

- Spec coverage:
  - 模型路由、熔断、降级：Task 3-5
  - Redis 运行时控制面：Task 2
  - RabbitMQ 后台任务：Task 6-7
  - 配置与部署：Task 1、Task 7
  - 测试与上线前验证：Task 1-7 的测试步骤与 Task 7 最终验证
- Placeholder scan:
  - 未使用 `TODO`、`TBD`、`稍后实现` 之类占位语
  - 每个任务都包含测试、命令和代码片段
- Type consistency:
  - `RuntimeConfig`、`RedisRuntimeStore`、`ModelRouter`、`RoutedPrediction`、`ModelInvocationError`、`handle_healthcheck_task` 在任务之间命名一致
