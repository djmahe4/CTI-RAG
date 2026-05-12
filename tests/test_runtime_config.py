from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

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
    monkeypatch.setenv(
        "MODEL_ROUTER_FALLBACK_CHAIN",
        "deepseek:deepseek-chat,ollama:qwen3:30b",
    )

    cfg = RuntimeConfig.from_env()

    assert cfg.model_router_enabled is True
    assert cfg.circuit_breaker_enabled is True
    assert cfg.default_route == ("deepseek", "deepseek-chat")
    assert cfg.fallback_chain[-1] == ("ollama", "qwen3:30b")
    assert cfg.circuit_breaker_failure_threshold == 5
    assert cfg.short_cache_ttl_seconds == 120
    assert cfg.rabbitmq_task_exchange == "threatrag.tasks"
    assert cfg.rabbitmq_url == "amqp://guest:guest@rabbitmq:5672/"


def test_parse_fallback_chain_rejects_malformed_entry():
    with pytest.raises(ValueError, match="Invalid MODEL_ROUTER_FALLBACK_CHAIN entry 'deepseek'"):
        parse_fallback_chain("deepseek")
