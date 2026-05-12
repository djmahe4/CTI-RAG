import asyncio
import json
import logging
import os
from typing import Any

from rag.cache.redis_runtime import RedisRuntimeStore
from rag.mq.rabbitmq_manager import RabbitMQManager


logger = logging.getLogger(__name__)


async def handle_healthcheck_task(
    message: dict[str, Any],
    runtime_store: RedisRuntimeStore,
) -> dict[str, Any]:
    provider = message["provider"]
    model_name = message["model_name"]
    await runtime_store.set_circuit_state(provider, model_name, "closed", failures=0)
    return {
        "healthy": True,
        "provider": provider,
        "model_name": model_name,
    }


class TaskWorker:
    """Background task consumer and task handler runtime."""

    def __init__(
        self,
        mq_manager: RabbitMQManager | None = None,
        runtime_store: RedisRuntimeStore | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.mq_manager = mq_manager or RabbitMQManager()
        self.runtime_store = runtime_store or RedisRuntimeStore()
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("TASK_MAX_RETRIES", "3"))
        self._handlers = {
            "model_healthcheck": handle_healthcheck_task,
        }

    async def process_task_message(self, message: dict[str, Any]) -> dict[str, Any]:
        task_id = message["task_id"]
        task_type = message["task_type"]
        provider = message.get("provider")
        model_name = message.get("model_name")

        await self.runtime_store.set_task_status(
            task_id,
            "running",
            {
                "task_type": task_type,
                "provider": provider,
                "model_name": model_name,
            },
        )

        try:
            handler = self._handlers[task_type]
            result = await handler(message, self.runtime_store)
        except Exception as exc:
            await self.runtime_store.set_task_status(
                task_id,
                "failed",
                {
                    "task_type": task_type,
                    "provider": provider,
                    "model_name": model_name,
                    "error": str(exc),
                },
            )
            if provider and model_name:
                await self.runtime_store.set_circuit_state(provider, model_name, "open", failures=1)
            raise

        await self.runtime_store.set_task_status(
            task_id,
            "succeeded",
            {
                "task_type": task_type,
                "provider": provider,
                "model_name": model_name,
                "result": result,
            },
        )
        return {"task_id": task_id, "status": "succeeded", "task_type": task_type}

    def build_callback(self):
        def _callback(ch, method, properties, body) -> None:
            message = json.loads(body)
            attempts = int(message.get("attempts", 0))

            try:
                asyncio.run(self.process_task_message(message))
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception:
                logger.exception("Task processing failed for %s", message.get("task_id"))
                if attempts < self.max_retries:
                    retry_message = dict(message)
                    retry_message["attempts"] = attempts + 1
                    self.mq_manager.publish_retry_message(retry_message)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return
                ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)

        return _callback

    def run(self) -> None:
        self.mq_manager.ensure_task_topology()
        self.mq_manager.consume_task_messages(
            callback=self.build_callback(),
            auto_ack=False,
            prefetch_count=int(os.getenv("TASK_WORKER_PREFETCH", "1")),
        )
