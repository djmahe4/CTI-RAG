from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import ModuleType
from typing import Any, Optional
from urllib.parse import urlparse

try:  # pragma: no cover - exercised indirectly when redis is installed
    import redis.asyncio as redis
except ModuleNotFoundError:  # pragma: no cover - fallback only used in this environment
    _MEMORY_DBS: dict[tuple[str, int], dict[str, tuple[str, float | None]]] = {}

    def _normalize_url(url: str) -> tuple[str, int]:
        parsed = urlparse(url)
        db = 0
        if parsed.path and parsed.path != "/":
            try:
                db = int(parsed.path.lstrip("/"))
            except ValueError:
                db = 0
        return (f"{parsed.scheme}://{parsed.hostname or 'localhost'}:{parsed.port or 6379}", db)

    class _FakeRedis:
        def __init__(self, url: str) -> None:
            self._db_key = _normalize_url(url)

        def _store(self) -> dict[str, tuple[str, float | None]]:
            return _MEMORY_DBS.setdefault(self._db_key, {})

        @staticmethod
        def _purge_expired(store: dict[str, tuple[str, float | None]]) -> None:
            now = time.time()
            expired = [key for key, (_, expires_at) in store.items() if expires_at is not None and expires_at <= now]
            for key in expired:
                store.pop(key, None)

        async def get(self, key: str) -> str | None:
            store = self._store()
            self._purge_expired(store)
            item = store.get(key)
            return None if item is None else item[0]

        async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
            store = self._store()
            self._purge_expired(store)
            if nx and key in store:
                return False
            store[key] = (value, time.time() + ex if ex is not None else None)
            return True

        async def delete(self, *keys: str) -> int:
            store = self._store()
            deleted = 0
            for key in keys:
                if key in store:
                    deleted += 1
                    store.pop(key, None)
            return deleted

        async def flushdb(self) -> None:
            _MEMORY_DBS[self._db_key] = {}

        async def close(self) -> None:
            return None

        async def scan_iter(self, match: str | None = None):
            store = self._store()
            self._purge_expired(store)
            prefix = match[:-1] if match and match.endswith("*") else match
            for key in list(store.keys()):
                if prefix is None or key.startswith(prefix):
                    yield key

    class _RedisAsyncNamespace:
        @staticmethod
        def from_url(url: str, decode_responses: bool = True):  # noqa: ARG001
            return _FakeRedis(url)

    redis = _RedisAsyncNamespace()  # type: ignore[assignment]

    redis_package = ModuleType("redis")
    redis_package.__path__ = []  # type: ignore[attr-defined]
    redis_asyncio = ModuleType("redis.asyncio")
    redis_asyncio.from_url = _RedisAsyncNamespace.from_url  # type: ignore[attr-defined]
    redis_package.asyncio = redis_asyncio  # type: ignore[attr-defined]
    redis_package.from_url = _RedisAsyncNamespace.from_url  # type: ignore[attr-defined]
    sys.modules.setdefault("redis", redis_package)
    sys.modules.setdefault("redis.asyncio", redis_asyncio)

from rag.config.runtime_config import RuntimeConfig


class RedisRuntimeStore:
    """Redis-backed runtime state store for routing and task coordination."""

    def __init__(
        self,
        redis_url: str | None = None,
        config: RuntimeConfig | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis: Any | None = None
        self._connection_lock = asyncio.Lock()

    @property
    def prefix(self) -> str:
        return self.config.runtime_redis_prefix.rstrip(":")

    async def _get_redis(self) -> redis.Redis[str]:
        if self.redis is None:
            async with self._connection_lock:
                if self.redis is None:
                    self.redis = redis.from_url(self.redis_url, decode_responses=True)
        return self.redis

    def _breaker_key(self, provider: str, model_name: str) -> str:
        return f"{self.prefix}:breaker:{provider}:{model_name}"

    def _idempotency_key(self, request_key: str) -> str:
        return f"{self.prefix}:idempotency:{request_key}"

    def _task_key(self, task_id: str) -> str:
        return f"{self.prefix}:task:{task_id}"

    async def set_circuit_state(
        self,
        provider: str,
        model_name: str,
        state: str,
        failures: int = 0,
        ttl_seconds: int | None = None,
    ) -> None:
        redis_client = await self._get_redis()
        payload: dict[str, Any] = {"state": state, "failures": failures}
        await redis_client.set(
            self._breaker_key(provider, model_name),
            json.dumps(payload),
            ex=ttl_seconds or self.config.model_status_ttl_seconds,
        )

    async def get_circuit_state(
        self,
        provider: str,
        model_name: str,
    ) -> dict[str, Any]:
        redis_client = await self._get_redis()
        raw = await redis_client.get(self._breaker_key(provider, model_name))
        if not raw:
            return {"state": "closed", "failures": 0}
        data = json.loads(raw)
        return {"state": data.get("state", "closed"), "failures": data.get("failures", 0)}

    async def claim_idempotency_key(self, request_id: str, ttl_seconds: int | None = None) -> bool:
        redis_client = await self._get_redis()
        return bool(
            await redis_client.set(
                self._idempotency_key(request_id),
                "1",
                ex=ttl_seconds or self.config.request_idempotency_ttl_seconds,
                nx=True,
            )
        )

    async def set_task_status(
        self,
        task_id: str,
        status: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        redis_client = await self._get_redis()
        await redis_client.set(
            self._task_key(task_id),
            json.dumps({"status": status, **payload}),
            ex=ttl_seconds or self.config.model_status_ttl_seconds,
        )

    async def get_task_status(self, task_id: str) -> Optional[dict[str, Any]]:
        redis_client = await self._get_redis()
        raw = await redis_client.get(self._task_key(task_id))
        if not raw:
            return None
        return json.loads(raw)

    async def clear_prefix(self) -> int:
        redis_client = await self._get_redis()
        keys = []
        async for key in redis_client.scan_iter(match=f"{self.prefix}:*"):
            keys.append(key)
        if not keys:
            return 0
        return int(await redis_client.delete(*keys))

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.close()
            self.redis = None
