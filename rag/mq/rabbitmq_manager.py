import json
import logging
import os
from urllib.parse import urlparse
from typing import Any, Callable

from dotenv import load_dotenv
from rag.config.runtime_config import RuntimeConfig

try:
    import pika
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal test environments
    class _MissingBasicProperties:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _MissingPika:
        BasicProperties = _MissingBasicProperties

        @staticmethod
        def PlainCredentials(*args: Any, **kwargs: Any) -> None:
            raise ModuleNotFoundError("pika is required to connect to RabbitMQ")

        @staticmethod
        def ConnectionParameters(*args: Any, **kwargs: Any) -> None:
            raise ModuleNotFoundError("pika is required to connect to RabbitMQ")

        @staticmethod
        def BlockingConnection(*args: Any, **kwargs: Any) -> None:
            raise ModuleNotFoundError("pika is required to connect to RabbitMQ")

    pika = _MissingPika()  # type: ignore[assignment]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()


class RabbitMQManager:
    """RabbitMQ connection and topology manager."""

    def __init__(self) -> None:
        self.config = RuntimeConfig.from_env()
        parsed_url = urlparse(self.config.rabbitmq_url)

        self.host = parsed_url.hostname or os.getenv("RABBITMQ_HOST", "localhost")
        self.port = parsed_url.port or int(os.getenv("RABBITMQ_PORT", "5672"))
        self.username = parsed_url.username or os.getenv("RABBITMQ_USERNAME", "guest")
        self.password = parsed_url.password or os.getenv("RABBITMQ_PASSWORD", "guest")
        self.vhost = parsed_url.path[1:] if parsed_url.path and parsed_url.path != "/" else os.getenv("RABBITMQ_VHOST", "/")

        self.task_exchange = self.config.rabbitmq_task_exchange
        self.task_queue = self.config.rabbitmq_task_queue
        self.retry_queue = self.config.rabbitmq_retry_queue
        self.dead_letter_queue = self.config.rabbitmq_dlq
        self.retry_delay_ms = self.config.rabbitmq_retry_delay_ms
        self.max_retries = self.config.rabbitmq_max_retries

        self.connection = None
        self.channel = None
        self.connect()

    def connect(self) -> None:
        """Establish a blocking RabbitMQ connection."""
        try:
            credentials = pika.PlainCredentials(self.username, self.password)
            parameters = pika.ConnectionParameters(
                host=self.host,
                port=self.port,
                virtual_host=self.vhost,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            logger.info("Connected to RabbitMQ")
        except Exception as exc:
            logger.error("Failed to connect to RabbitMQ: %s", exc)
            raise

    def reconnect(self) -> None:
        try:
            if self.connection and self.connection.is_open:
                self.connection.close()
            self.connect()
            logger.info("Reconnected to RabbitMQ")
        except Exception as exc:
            logger.error("Failed to reconnect to RabbitMQ: %s", exc)
            raise

    def declare_queue(self, queue_name: str, durable: bool = True, arguments: dict[str, Any] | None = None) -> None:
        try:
            self.channel.queue_declare(queue=queue_name, durable=durable, arguments=arguments or {})
        except Exception as exc:
            logger.error("Failed to declare queue %s: %s", queue_name, exc)
            self.reconnect()
            self.channel.queue_declare(queue=queue_name, durable=durable, arguments=arguments or {})

    def ensure_task_topology(self) -> None:
        """Declare the direct task exchange, main queue, retry queue, and DLQ."""
        try:
            self.channel.exchange_declare(exchange=self.task_exchange, exchange_type="direct", durable=True)

            self.channel.queue_declare(
                queue=self.task_queue,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": self.dead_letter_queue,
                },
            )
            self.channel.queue_bind(exchange=self.task_exchange, queue=self.task_queue, routing_key="model_healthcheck")

            self.channel.queue_declare(
                queue=self.retry_queue,
                durable=True,
                arguments={
                    "x-message-ttl": self.retry_delay_ms,
                    "x-dead-letter-exchange": self.task_exchange,
                    "x-dead-letter-routing-key": "model_healthcheck",
                },
            )
            self.channel.queue_declare(queue=self.dead_letter_queue, durable=True)
        except Exception as exc:
            logger.error("Failed to declare task topology: %s", exc)
            self.reconnect()
            self.ensure_task_topology()

    def publish_message(self, queue_name: str, message: dict[str, Any]) -> None:
        try:
            self.declare_queue(queue_name)
            self.channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            )
        except Exception as exc:
            logger.error("Failed to publish message to %s: %s", queue_name, exc)
            self.reconnect()
            self.publish_message(queue_name, message)

    def publish_task_message(self, routing_key: str, message: dict[str, Any]) -> None:
        self._publish_exchange_message(self.task_exchange, routing_key, message)

    def publish_retry_message(self, message: dict[str, Any]) -> None:
        self.publish_message(self.retry_queue, message)

    def _publish_exchange_message(self, exchange: str, routing_key: str, message: dict[str, Any]) -> None:
        try:
            self.channel.basic_publish(
                exchange=exchange,
                routing_key=routing_key,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            )
            logger.info("Published message to exchange=%s routing_key=%s", exchange, routing_key)
        except Exception as exc:
            logger.error("Failed to publish message to exchange=%s routing_key=%s: %s", exchange, routing_key, exc)
            self.reconnect()
            self._publish_exchange_message(exchange, routing_key, message)

    def consume_messages(self, queue_name: str, callback: Callable, auto_ack: bool = False) -> None:
        try:
            self.declare_queue(queue_name)
            self.channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=auto_ack)
            self.channel.start_consuming()
        except Exception as exc:
            logger.error("Failed to consume messages from %s: %s", queue_name, exc)
            self.reconnect()
            self.consume_messages(queue_name, callback, auto_ack)

    def consume_task_messages(self, callback: Callable, auto_ack: bool = False, prefetch_count: int = 1) -> None:
        self.ensure_task_topology()
        self.channel.basic_qos(prefetch_count=prefetch_count)
        self.channel.basic_consume(queue=self.task_queue, on_message_callback=callback, auto_ack=auto_ack)
        logger.info("Consuming task messages from %s", self.task_queue)
        self.channel.start_consuming()

    def close(self) -> None:
        if self.connection and self.connection.is_open:
            self.connection.close()
            logger.info("RabbitMQ connection closed")
