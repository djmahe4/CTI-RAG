import os
import sys
import time
import logging
from dotenv import load_dotenv
from rag.mq.task_worker import TaskWorker

# Load Environmental Variables
load_dotenv()

# Configure Log
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Worker main function"""
    # Type and quantity of worker acquired
    worker_type = os.getenv("WORKER_TYPE", "task").lower()
    worker_count = int(os.getenv("WORKER_COUNT", "3"))
    
    logger.info(f"Start Worker: Type={worker_type}, Number={worker_count}")

    if worker_type in ["task", "tasks"]:
        task_worker = TaskWorker()
        logger.info("Start Backstage Task Worker")
        task_worker.run()
        return
    
    # Start Session Worker
    if worker_type in ["conversation", "all"]:
        from rag.mq.conversation_worker import ConversationWorker

        conversation_worker = ConversationWorker(num_workers=worker_count)
        conversation_worker.start_workers()
        logger.info(f"Started {worker_count} Session Worker")
    
    # Start vector search worker
    if worker_type in ["vector", "all"]:
        from rag.mq.vector_search_worker import VectorSearchWorker

        vector_worker = VectorSearchWorker(num_workers=worker_count)
        vector_worker.start_workers()
        logger.info(f"Started {worker_count} Vector Retrieval Worker")
    
    # Keep process running
    try:
        while True:
            time.sleep(60)
            logger.info("Worker running...")
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user, exiting.")
    except Exception as e:
        logger.error(f"Error running worker: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
