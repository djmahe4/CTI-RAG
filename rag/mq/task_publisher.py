import uuid

from rag.cache.redis_runtime import RedisRuntimeStore
from rag.mq.rabbitmq_manager import RabbitMQManager


class TaskPublisher:
    """Publish background task messages and prime runtime status."""

    def __init__(
        self,
        mq_manager: RabbitMQManager | None = None,
        runtime_store: RedisRuntimeStore | None = None,
    ) -> None:
        self.mq_manager = mq_manager or RabbitMQManager()
        self.runtime_store = runtime_store or RedisRuntimeStore()

    async def publish_healthcheck_task(
        self,
        provider: str,
        model_name: str,
        task_id: str | None = None,
    ) -> str:
        task_id = task_id or str(uuid.uuid4())
        message = {
            "task_id": task_id,
            "task_type": "model_healthcheck",
            "provider": provider,
            "model_name": model_name,
        }

        await self.runtime_store.set_task_status(
            task_id,
            "queued",
            {
                "task_type": "model_healthcheck",
                "provider": provider,
                "model_name": model_name,
            },
        )
        self.mq_manager.ensure_task_topology()
        self.mq_manager.publish_task_message("model_healthcheck", message)
        return task_id
