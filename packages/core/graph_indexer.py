import time
import threading
import traceback
from datetime import datetime

from .. import config
from ..utils import logger
from .graphbase import graph_base

class GraphIndexer:
    """Graph database indexer, periodically scans and creates embeddings for entities without vectors."""
    
    def __init__(self, interval=3600, batch_size=100, kgdb_name='neo4j'):
        """
        Initialize the graph database indexer.
        
        Args:
            interval: Scan interval in seconds, default is 1 hour (3600s).
            batch_size: Number of entities to process per batch, default is 100.
            kgdb_name: Graph database name, default is 'neo4j'.
        """
        self.interval = interval
        self.batch_size = batch_size
        self.kgdb_name = kgdb_name
        self.running = False
        self.thread = None
        self.last_run_time = None
        self.total_indexed = 0
    
    def start(self):
        """Start the indexer."""
        if self.running:
            logger.warning("Graph database indexer is already running.")
            return False
        
        if not config.enable_knowledge_graph:
            logger.warning("Knowledge graph is not enabled; the indexer will not start.")
            return False
        
        if not graph_base.is_running():
            logger.warning("Graph database is not running; the indexer will not start.")
            return False
        
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Graph database indexer started, scan interval: {self.interval}s.")
        return True
    
    def stop(self):
        """Stop the indexer."""
        if not self.running:
            return
        
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10)
        logger.info("Graph database indexer stopped.")
    
    def _run(self):
        """Main indexing loop."""
        while self.running:
            try:
                self._index_nodes()
                self.last_run_time = datetime.now()
                # Wait for the next scan.
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in graph database indexing process: {e}, {traceback.format_exc()}")
                # Wait for a minute before retrying after an error.
                time.sleep(60)
    
    def _index_nodes(self):
        """Index nodes that do not have embeddings."""
        if not graph_base.is_running():
            logger.warning("Graph database is not running; skipping this indexing cycle.")
            return 0
        
        # Query for nodes without embeddings.
        nodes_without_embedding = graph_base.query_nodes_without_embedding(self.kgdb_name)
        total_nodes = len(nodes_without_embedding)
        
        if total_nodes == 0:
            logger.info("No nodes require indexing.")
            return 0
        
        logger.info(f"Found {total_nodes} nodes without embeddings; starting indexing.")
        
        # Batch process nodes.
        indexed_count = 0
        for i in range(0, total_nodes, self.batch_size):
            if not self.running:
                break
                
            batch = nodes_without_embedding[i:i+self.batch_size]
            logger.info(f"Processing batch {i//self.batch_size + 1}/{(total_nodes-1)//self.batch_size + 1} ({len(batch)} nodes).")
            
            try:
                count = graph_base.add_embedding_to_nodes(batch, self.kgdb_name)
                indexed_count += count
                logger.info(f"Successfully added embeddings to {count} nodes.")
            except Exception as e:
                logger.error(f"Failed to add embeddings to batch: {e}, {traceback.format_exc()}")
        
        self.total_indexed += indexed_count
        logger.info(f"Indexing complete; successfully added embeddings to {indexed_count} nodes in total.")
        return indexed_count
    
    def get_status(self):
        """Get the current status of the indexer."""
        return {
            "running": self.running,
            "last_run_time": self.last_run_time.isoformat() if self.last_run_time else None,
            "total_indexed": self.total_indexed,
            "interval": self.interval,
            "batch_size": self.batch_size,
            "kgdb_name": self.kgdb_name
        }

# Create a global indexer instance.
graph_indexer = GraphIndexer()

def get_graph_indexer():
    """Get the global graph database indexer instance."""
    return graph_indexer