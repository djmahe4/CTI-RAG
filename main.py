from neo4j._sync.auth_management import Neo4jAuthTokenManager
import uvicorn
import threading
from rag.vector.vector_database import create_vector_database_instance
import yaml
import signal
import sys
import atexit
from packages.manager.milvus_manager import get_milvus_manager
# Import graph database indexer
from packages.core.graph_indexer import graph_indexer
from rag.cache.redis_session import RedisSessionManager
import redis
MILVUE_HOST="milvus-standalone"
Neo4j_HOST="neo4j"

config = None
milvus_manager = None

def load_config():
    """Load configuration file using UTF-8 encoding."""
    try:
        with open("./config.yaml", "r", encoding='utf-8') as f:
            config = yaml.safe_load(f)  # Use safe_load for better security
        return config
    except UnicodeDecodeError as e:
        print(f"Configuration file encoding error: {e}")
        print("Attempting to load using alternative encoding...")
        try:
            with open("./config.yaml", "r", encoding='gbk') as f:
                config = yaml.safe_load(f)
            return config
        except Exception as e2:
            print(f"Failed to load using GBK encoding: {e2}")
            raise
    except Exception as e:
        print(f"Failed to load configuration file: {e}")
        raise

def start_milvus():
    """Start the Milvus server."""
    global milvus_manager
    if config.get("milvus", {}).get("auto_start", True):
        print("Starting Milvus server...")
        milvus_config = config.get("milvus", {})
        data_dir = milvus_config.get("data_dir", "./milvus_lite")
        host = milvus_config.get("host", "milvus-standalone")
        port = milvus_config.get("port", 19530)

        milvus_manager = get_milvus_manager(data_dir, port, host)
        if milvus_manager.start():
            print(f"✓ Milvus server started successfully, listening on {host}:{port}")
            return True
        else:
            print("✗ Failed to start Milvus server")
            return False
    else:
        print("Milvus auto-start disabled, please start the Milvus server manually")
        return True

def stop_milvus():
    """Stop the Milvus server."""
    global milvus_manager
    if milvus_manager:
        print("Stopping Milvus server...")
        milvus_manager.stop()
        print("✓ Milvus server stopped")

def start_server(host = "0.0.0.0", port = 8000):
    """Start the FastAPI server."""
    # Lazy import to ensure Milvus is started before importing
    from rag.api.server import fastapi_server
    uvicorn.run(fastapi_server, host=host, port=port, proxy_headers=True, forwarded_allow_ips='*')


def signal_handler(sig, frame):
    """Handle signals to ensure all threads are terminated when the main process exits."""
    print("Received termination signal, shutting down services...")
    stop_milvus()
    sys.exit(0)

def check_redis():
    """Check if Redis is running."""
    try:
        r = redis.Redis(host='redis', port=6379, db=0, socket_connect_timeout=1)
        r.ping()
        print("Redis server is already running")
        return True
    except:
        print("Redis server is not running")
        return False

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Register exit cleanup function
    atexit.register(stop_milvus)

    config = load_config()

    # Check if Redis is running
    if not check_redis():
        print("Warning: Redis server is not running, session cache will be unavailable")
        print("Please install and start the Redis server to enable session caching")
        print("Installation guide: https://redis.io/docs/getting-started/")

    # Start Milvus server
    if not start_milvus():
        print("Failed to start Milvus server, exiting program")
        sys.exit(1)

    # Start Neo4j server (if auto-start is configured)
    if config.get("neo4j", {}).get("auto_start", False):
        from packages.manager.neo4j_manager import start_neo4j_server
        start_neo4j_server(
            data_dir=config.get("neo4j", {}).get("data_dir", "./neo4j_data"),
            port=config.get("neo4j", {}).get("port", 7688),
            http_port=config.get("neo4j", {}).get("http_port", 7474),
            host=config.get("neo4j", {}).get("host", "neo4j")
        )

    # Start graph database indexer (if knowledge graph is enabled)
    if config.get("enable_knowledge_graph", False):
        # Set index interval (default 1 hour)
        index_interval = config.get("neo4j", {}).get("index_interval", 3600)
        graph_indexer.interval = index_interval
        graph_indexer.start()


    # Start server (main thread)
    try:
        print(f"Starting FastAPI server, listening on {config['fastapi_server']['host']}:{config['fastapi_server']['port']}")
        start_server(host=config["fastapi_server"]["host"], port=config["fastapi_server"]["port"])
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
    except Exception as e:
        print(f"Server start failed: {e}")
    finally:
        stop_milvus()

