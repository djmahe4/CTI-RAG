from pathlib import Path
import asyncio
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.cache.redis_runtime import RedisRuntimeStore


TEST_REDIS_URL = "redis://localhost:6379/2"


async def _new_store() -> RedisRuntimeStore:
    store = RedisRuntimeStore(redis_url=TEST_REDIS_URL)
    await store.clear_prefix()
    return store


def test_breaker_state_roundtrip():
    async def _run() -> None:
        store = await _new_store()
        try:
            await store.set_circuit_state("deepseek", "deepseek-chat", "open", failures=5)
            state = await store.get_circuit_state("deepseek", "deepseek-chat")
            assert state == {"state": "open", "failures": 5}
        finally:
            await store.clear_prefix()
            await store.close()

    asyncio.run(_run())


def test_default_breaker_state_when_absent():
    async def _run() -> None:
        store = await _new_store()
        try:
            state = await store.get_circuit_state("deepseek", "deepseek-chat")
            assert state == {"state": "closed", "failures": 0}
        finally:
            await store.clear_prefix()
            await store.close()

    asyncio.run(_run())


def test_idempotency_key_roundtrip():
    async def _run() -> None:
        store = await _new_store()
        try:
            first = await store.claim_idempotency_key("request-123", ttl_seconds=30)
            second = await store.claim_idempotency_key("request-123", ttl_seconds=30)

            assert first is True
            assert second is False
        finally:
            await store.clear_prefix()
            await store.close()

    asyncio.run(_run())


def test_task_status_roundtrip():
    async def _run() -> None:
        store = await _new_store()
        try:
            await store.set_task_status(
                "task-123",
                "queued",
                {"message": "queued", "progress": 10},
            )
            status = await store.get_task_status("task-123")
            assert status == {"status": "queued", "message": "queued", "progress": 10}
        finally:
            await store.clear_prefix()
            await store.close()

    asyncio.run(_run())


def test_clear_prefix_removes_all_runtime_keys():
    async def _run() -> None:
        store = await _new_store()
        try:
            await store.set_circuit_state("deepseek", "deepseek-chat", "open", failures=5)
            await store.claim_idempotency_key("request-123", ttl_seconds=30)
            await store.set_task_status("task-123", "queued", {"message": "queued"})

            deleted = await store.clear_prefix()

            assert deleted == 3
            assert await store.get_circuit_state("deepseek", "deepseek-chat") == {
                "state": "closed",
                "failures": 0,
            }
            assert await store.claim_idempotency_key("request-123", ttl_seconds=30) is True
            assert await store.get_task_status("task-123") is None
        finally:
            await store.clear_prefix()
            await store.close()

    asyncio.run(_run())
