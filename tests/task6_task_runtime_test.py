from pathlib import Path
import asyncio
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.cache.redis_runtime import RedisRuntimeStore
from rag.mq.task_publisher import TaskPublisher
from rag.mq.task_worker import TaskWorker, handle_healthcheck_task


TEST_REDIS_URL = "redis://localhost:6379/6"


class FakeRabbitMQManager:
    def __init__(self) -> None:
        self.topology_declared = 0
        self.published_messages: list[tuple[str, str, str, dict]] = []

    def ensure_task_topology(self) -> None:
        self.topology_declared += 1

    def publish_task_message(self, routing_key: str, message: dict) -> None:
        self.published_messages.append(("direct", "threatrag.tasks", routing_key, message))


async def _new_store() -> RedisRuntimeStore:
    store = RedisRuntimeStore(redis_url=TEST_REDIS_URL)
    await store.clear_prefix()
    return store


def test_healthcheck_task_status_flow():
    async def _run() -> None:
        store = await _new_store()
        mq_manager = FakeRabbitMQManager()
        publisher = TaskPublisher(mq_manager=mq_manager, runtime_store=store)
        worker = TaskWorker(mq_manager=mq_manager, runtime_store=store)

        try:
            task_id = await publisher.publish_healthcheck_task(
                provider="deepseek",
                model_name="deepseek-chat",
            )

            queued_status = await store.get_task_status(task_id)
            assert queued_status == {
                "status": "queued",
                "task_type": "model_healthcheck",
                "provider": "deepseek",
                "model_name": "deepseek-chat",
            }

            assert mq_manager.topology_declared == 1
            assert mq_manager.published_messages == [
                (
                    "direct",
                    "threatrag.tasks",
                    "model_healthcheck",
                    {
                        "task_id": task_id,
                        "task_type": "model_healthcheck",
                        "provider": "deepseek",
                        "model_name": "deepseek-chat",
                    },
                )
            ]

            task_message = mq_manager.published_messages[0][3]
            task_result = await handle_healthcheck_task(task_message, store)
            assert task_result == {
                "healthy": True,
                "provider": "deepseek",
                "model_name": "deepseek-chat",
            }

            result = await worker.process_task_message(task_message)

            assert result == {
                "task_id": task_id,
                "status": "succeeded",
                "task_type": "model_healthcheck",
            }

            final_status = await store.get_task_status(task_id)
            assert final_status == {
                "status": "succeeded",
                "task_type": "model_healthcheck",
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "result": {
                    "healthy": True,
                    "provider": "deepseek",
                    "model_name": "deepseek-chat",
                },
            }

            circuit_state = await store.get_circuit_state("deepseek", "deepseek-chat")
            assert circuit_state == {"state": "closed", "failures": 0}
        finally:
            await store.clear_prefix()
            await store.close()

    asyncio.run(_run())
