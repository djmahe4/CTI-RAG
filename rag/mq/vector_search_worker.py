import json
import os
import threading
import time
import uuid
from typing import Dict, Any
import pika
from rag.mq.rabbitmq_manager import RabbitMQManager
from rag.vector.vector_database import get_vector_database_instance
import logging

# Configure Log
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VectorSearchWorker:
    """Vector Retrieval Worker，Processing requests for helipads"""
    
    def __init__(self, num_workers: int = 3):
        """Initialization vector searcher
        
        Args:
            num_workers: Number of workspaces
        """
        self.mq_manager = RabbitMQManager()
        self.vector_db = get_vector_database_instance()
        self.search_queue = "vector_search_queue"
        self.result_queue = "vector_search_result_queue"
        self.num_workers = num_workers
        self.workers = []
        
        # Declaration Queue
        self.mq_manager.declare_queue(self.search_queue)
        self.mq_manager.declare_queue(self.result_queue)
    
    def start_workers(self):
        """Start a workspace"""
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_thread,
                args=(i,),
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
            logger.info(f"Vector search workspace {i} Started")
    
    def _worker_thread(self, worker_id: int):
        """Workline Functions
        
        Args:
            worker_id: WorkspaceID
        """
        logger.info(f"Vector search workspace {worker_id} Start running")
        
        # Create independent RabbitMQ connection
        mq = RabbitMQManager()
        
        def callback(ch, method, properties, body):
            """Message Processing Retal function"""
            try:
                # Can not open message
                message = json.loads(body)
                logger.info(f"Workspace {worker_id} Retrieval requests received: {message.get('request_id')}")
                
                # Extract query parameters
                query = message.get("query", "")
                k = message.get("k", 5)
                request_id = message.get("request_id", "")
                conversation_id = message.get("conversation_id", "")
                
                # Execute vector search
                start_time = time.time()
                results = self.vector_db.query_vector_database(query)
                search_time = time.time() - start_time
                
                # Format Results
                formatted_results = []
                for doc in results:
                    formatted_results.append({
                        "content": doc.page_content,
                        "metadata": doc.metadata
                    })
                
                # Send Results
                result_message = {
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "results": formatted_results,
                    "search_time": search_time,
                    "timestamp": time.time()
                }
                
                mq.publish_message(self.result_queue, result_message)
                logger.info(f"Workspace {worker_id} Complete search request: {request_id}, Time consuming: {search_time:.2f}sec")
                
                # Confirm message.
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"Workspace {worker_id} Can not open message: {str(e)}")
                # Deny the message and re-enter.
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        
        # Set QoS to process only one message at a time
        mq.channel.basic_qos(prefetch_count=1)
        
        # Start Consumption Message
        mq.consume_messages(self.search_queue, callback, auto_ack=False)
    
    def submit_search_task(self, query: str, conversation_id: str = None, k: int = 5) -> str:
        """Submit search assignments
        
        Args:
            query: Query Text
            conversation_id: SessionID
            k: Number of returns
            
        Returns:
            str: RequestID
        """
        # Generate Request ID
        request_id = str(uuid.uuid4())
        
        # Can not open message
        message = {
            "request_id": request_id,
            "conversation_id": conversation_id,
            "query": query,
            "k": k,
            "timestamp": time.time()
        }
        
        # Send Message
        self.mq_manager.publish_message(self.search_queue, message)
        logger.info(f"A search assignment has been submitted: {request_id}")
        
        return request_id