import json
import os
import threading
import time
import uuid
import asyncio
from typing import Dict, Any, List, Optional, Callable
import pika
from rag.mq.rabbitmq_manager import RabbitMQManager
from rag.chains.conversation_chain import StreamingConversationChain
from rag.vector.vector_database import get_vector_database_instance
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConversationWorker:
    """Conversation worker that handles asynchronous session requests."""
    
    def __init__(self, num_workers: int = 3):
        """Initialize the conversation worker.
        
        Args:
            num_workers: Number of worker threads.
        """
        self.mq_manager = RabbitMQManager()
        self.conversation_queue = "conversation_queue"
        self.conversation_result_queue = "conversation_result_queue"
        self.num_workers = num_workers
        self.workers = []
        
        # Declare queues
        self.mq_manager.declare_queue(self.conversation_queue)
        self.mq_manager.declare_queue(self.conversation_result_queue)
        
        # Result callback registry
        self.result_callbacks = {}
        self.result_lock = threading.Lock()
        
        # Start result listener thread
        self.result_thread = threading.Thread(
            target=self._listen_for_results,
            daemon=True
        )
        self.result_thread.start()
    
    def start_workers(self):
        """Start the worker threads."""
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_thread,
                args=(i,),
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
            logger.info(f"Conversation worker thread {i} started")
    
    def _worker_thread(self, worker_id: int):
        """Worker thread function.
        
        Args:
            worker_id: Worker thread ID.
        """
        logger.info(f"Conversation worker thread {worker_id} is running")
        
        # Create independent RabbitMQ connection
        mq = RabbitMQManager()
        
        # Create conversation chain instance
        conversation_chain = StreamingConversationChain(
            verbose=False,
            model_name=os.getenv("BASE_MODEL"),
            api_base=os.getenv("API_BASE"),
            api_key=os.getenv("API_KEY"),
            use_rag=True,
            vector_database=get_vector_database_instance()
        )
        
        def callback(ch, method, properties, body):
            """Message processing callback function."""
            try:
                # Parse message
                message = json.loads(body)
                logger.info(f"Worker {worker_id} received conversation request: {message.get('request_id')}")
                
                # Extract parameters
                request_id = message.get("request_id", "")
                conversation_id = message.get("conversation_id", "")
                user_message = message.get("message", "")
                temperature = message.get("temperature", 0.7)
                
                # Get or create conversation ID
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                conversation_id = loop.run_until_complete(
                    conversation_chain.get_or_create_conversation(conversation_id)
                )
                
                # Process conversation
                full_response = ""
                rag_context = []
                
                # Create async generator wrapper
                async def process_stream():
                    nonlocal full_response
                    async for token in conversation_chain.astream(
                        message=user_message,
                        conversation_id=conversation_id
                    ):
                        if token:
                            # Check if it's RAG context
                            if token.startswith("[rag_context]:"):
                                try:
                                    rag_data = json.loads(token[14:])
                                    rag_context.extend(rag_data)
                                except:
                                    pass
                            else:
                                full_response += token
                
                # Run async generator
                loop.run_until_complete(process_stream())
                
                # Get conversation title
                conversation_title = loop.run_until_complete(
                    conversation_chain.get_title_from_conversation(conversation_id)
                )
                
                # Close event loop
                loop.close()
                
                # Send result
                result_message = {
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "response": full_response,
                    "conversation_title": conversation_title,
                    "rag_context": rag_context,
                    "timestamp": time.time()
                }
                
                mq.publish_message(self.conversation_result_queue, result_message)
                logger.info(f"Worker {worker_id} completed conversation request: {request_id}")
                
                # Acknowledge message
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"Worker {worker_id} failed to process message: {str(e)}")
                # Reject message and requeue
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        
        # Set QoS to process one message at a time
        mq.channel.basic_qos(prefetch_count=1)
        
        # Start consuming messages
        mq.consume_messages(self.conversation_queue, callback, auto_ack=False)
    
    def _listen_for_results(self):
        """Thread function to listen for results in the queue."""
        logger.info("Started listening to conversation result queue")
        
        # Create independent RabbitMQ connection
        mq = RabbitMQManager()
        
        def callback(ch, method, properties, body):
            """Result processing callback function."""
            try:
                # Parse message
                result = json.loads(body)
                request_id = result.get("request_id", "")
                
                # Find and invoke callback function
                with self.result_lock:
                    if request_id in self.result_callbacks:
                        callback_func = self.result_callbacks[request_id]
                        # Remove from registry
                        del self.result_callbacks[request_id]
                        # Invoke callback
                        callback_func(result)
                
                # Acknowledge message
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"Failed to process result message: {str(e)}")
                # Reject message
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        
        # Set QoS
        mq.channel.basic_qos(prefetch_count=10)
        
        # Start consuming messages
        mq.consume_messages(self.conversation_result_queue, callback, auto_ack=False)
    
    def submit_conversation_task(self, message: str, conversation_id: str = None, 
                                temperature: float = 0.7, callback: Callable = None) -> str:
        """Submit a conversation task.
        
        Args:
            message: User message.
            conversation_id: Session ID.
            temperature: Temperature parameter.
            callback: Result callback function.
            
        Returns:
            str: Request ID.
        """
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Register callback function
        if callback:
            with self.result_lock:
                self.result_callbacks[request_id] = callback
        
        # Create message
        message_data = {
            "request_id": request_id,
            "conversation_id": conversation_id,
            "message": message,
            "temperature": temperature,
            "timestamp": time.time()
        }
        
        # Publish message
        self.mq_manager.publish_message(self.conversation_queue, message_data)
        logger.info(f"Submitted conversation task: {request_id}")
        
        return request_id