from __future__ import annotations

from dataclasses import dataclass
import os


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_fallback_chain(raw: str | None) -> list[tuple[str, str]]:
    chain: list[tuple[str, str]] = []
    if not raw:
        return chain

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue

        if ":" not in item:
            raise ValueError(
                f"Invalid MODEL_ROUTER_FALLBACK_CHAIN entry '{item}': expected 'provider:model'"
            )

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
