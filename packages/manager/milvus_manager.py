import os
import subprocess
import time
import signal
import psutil
import threading
from pathlib import Path
from ..utils import logger


class MilvusManager:
    """MilvusServer Manager"""

    def __init__(self, data_dir="./milvus_lite", port=19530, host="127.0.0.1"):
        self.port = port
        self.host = host
        self.is_running = False

    def _check_milvus_available(self):
        """InspectionMilvusAvailability of services"""
        try:
            from pymilvus import MilvusClient
            client = MilvusClient(uri=f"http://{self.host}:{self.port}")
            client.list_collections()
            return True
        except Exception:
            return False

    def start(self):
        """InspectionMilvusAvailability of services"""
        if self.is_running:
            logger.info("MilvusService is already running")
            return True

        if self._check_milvus_available():
            self.is_running = True
            logger.info(f"MilvusServices available，Listen {self.host}:{self.port}")
            return True
        else:
            logger.error(f"Could not initialise BonoboMilvusServices {self.host}:{self.port}")
            logger.error("Make sure it's started.MilvusServices，You can use the following commands:：")
            logger.error("docker run -d --name milvus_standalone -p 19530:19530 -p 9091:9091 milvusdb/milvus:latest")
            return False

    def stop(self):
        """StopMilvusService inspection"""
        self.is_running = False
        logger.info("MilvusService check stopped")

    def restart(self):
        """RestartMilvusService inspection"""
        logger.info("RestartingMilvusService inspection...")
        self.stop()
        return self.start()

    def get_status(self):
        """AccessMilvusService Status"""
        if not self.is_running:
            return {"status": "stopped", "port": self.port, "host": self.host}

        try:
            from pymilvus import MilvusClient
            client = MilvusClient(uri=f"http://{self.host}:{self.port}")
            collections = client.list_collections()
            return {
                "status": "running",
                "port": self.port,
                "host": self.host,
                "collections_count": len(collections)
            }
        except Exception as e:
            return {
                "status": "error",
                "port": self.port,
                "host": self.host,
                "error": str(e)
            }


# Global example of a Milvus manager
milvus_manager = None

def get_milvus_manager(data_dir="./milvus_lite", port=19530, host="127.0.0.1"):
    """AccessmilvusManager Example"""
    global milvus_manager
    if milvus_manager is None:
        milvus_manager = MilvusManager(data_dir, port, host)
    return milvus_manager

def start_milvus_server(data_dir="./milvus_lite", port=19530, host="127.0.0.1"):
    """StartmilvusEasy function of the server"""
    manager = get_milvus_manager(data_dir, port, host)
    return manager.start()

def stop_milvus_server():
    """StopmilvusEasy function of the server"""
    global milvus_manager
    if milvus_manager:
        milvus_manager.stop()
