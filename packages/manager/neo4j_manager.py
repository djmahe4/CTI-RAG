import os
import subprocess
import time
import psutil
import threading
from pathlib import Path
from ..utils import logger


class Neo4jManager:
    """Neo4jServer Manager"""
    
    def __init__(self, data_dir="./neo4j_data", port=7688, http_port=7474, host="127.0.0.1"):
        self.data_dir = Path(data_dir).resolve()
        self.port = port
        self.http_port = http_port
        self.host = host
        self.process = None
        self.is_running = False
        
        # Ensure that data directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
    def _check_neo4j_installed(self):
        """InspectionNeo4jInstalled"""
        try:
            # Check if the Neo4j command is available.
            result = subprocess.run(['neo4j', 'version'], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def _is_port_in_use(self, port):
        """Check if port is occupied"""
        for conn in psutil.net_connections():
            if conn.laddr.port == port:
                return True
        return False
    
    def _wait_for_neo4j_ready(self, timeout=60):
        """WaitNeo4jServer Ready"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self._is_port_in_use(self.port):
                # Try Connection Test
                try:
                    from neo4j import GraphDatabase
                    driver = GraphDatabase.driver(f"bolt://{self.host}:{self.port}", 
                                                auth=("neo4j", "12345678"))
                    with driver.session() as session:
                        session.run("RETURN 1")
                    driver.close()
                    logger.info(f"Neo4jServer is ready，Listen Port {self.port}")
                    return True
                except Exception:
                    pass
            time.sleep(2)
        return False
    
    def start(self):
        """StartNeo4jServers"""
        if self.is_running:
            logger.info("Neo4jServer is running")
            return True
            
        # Check if port is occupied
        if self._is_port_in_use(self.port):
            logger.info(f"Port {self.port} Already occupied，AssumptionsNeo4jRunning")
            if self._wait_for_neo4j_ready(timeout=10):
                self.is_running = True
                return True
            else:
                logger.error(f"Port {self.port} Occupied but unable to connectNeo4jServices")
                return False
        
        # Check for Neo4j installed
        if not self._check_neo4j_installed():
            logger.warning("Not detectedNeo4jInstall，Please install manuallyNeo4j")
            logger.info("Installation Guide: https://neo4j.com/docs/operations-manual/current/installation/")
            return False
        
        try:
            logger.info(f"StartingNeo4jServers，Data Directory: {self.data_dir}")
            
            # Set up the Neo4j environment variable
            env = os.environ.copy()
            env['NEO4J_HOME'] = str(self.data_dir)
            env['NEO4J_CONF'] = str(self.data_dir / "conf")
            env['NEO4J_DATA'] = str(self.data_dir / "data")
            env['NEO4J_LOGS'] = str(self.data_dir / "logs")
            
            # Create the necessary directory
            (self.data_dir / "conf").mkdir(exist_ok=True)
            (self.data_dir / "data").mkdir(exist_ok=True)
            (self.data_dir / "logs").mkdir(exist_ok=True)
            
            # Start Neo4j server
            cmd = ['neo4j', 'console']
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=str(self.data_dir)
            )
            
            # Waiting for server startup
            if self._wait_for_neo4j_ready():
                self.is_running = True
                logger.info("Neo4jServer started successfully")
                
                # Start log monitoring thread
                self._start_log_monitor()
                return True
            else:
                logger.error("Neo4jServer start timeout")
                self.stop()
                return False
                
        except Exception as e:
            logger.error(f"StartNeo4jServer failed: {e}")
            return False
    
    def _start_log_monitor(self):
        """Start log monitoring thread"""
        def monitor_logs():
            if self.process:
                for line in iter(self.process.stdout.readline, ''):
                    if line.strip():
                        logger.debug(f"Neo4j: {line.strip()}")
                    if not self.is_running:
                        break
        
        log_thread = threading.Thread(target=monitor_logs, daemon=True)
        log_thread.start()
    
    def stop(self):
        """StopNeo4jServers"""
        if not self.is_running:
            return
            
        self.is_running = False
        
        if self.process:
            try:
                # The graceful closing.
                self.process.terminate()
                
                # Waiting for the end of the process
                try:
                    self.process.wait(timeout=15)
                    logger.info("Neo4jServer stopped")
                except subprocess.TimeoutExpired:
                    # Force kill process
                    self.process.kill()
                    self.process.wait()
                    logger.info("Neo4jServer has been forced to stop")
                    
            except Exception as e:
                logger.error(f"StopNeo4jError on server: {e}")
            finally:
                self.process = None
    
    def restart(self):
        """RestartNeo4jServers"""
        logger.info("RestartingNeo4jServers...")
        self.stop()
        time.sleep(3)
        return self.start()
    
    def get_status(self):
        """AccessNeo4jServer Status"""
        if not self.is_running:
            return {"status": "stopped", "port": self.port, "data_dir": str(self.data_dir)}
        
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(f"bolt://{self.host}:{self.port}", 
                                        auth=("neo4j", "12345678"))
            with driver.session() as session:
                result = session.run("MATCH (n) RETURN count(n) as node_count")
                node_count = result.single()["node_count"]
            driver.close()
            
            return {
                "status": "running",
                "port": self.port,
                "http_port": self.http_port,
                "host": self.host,
                "data_dir": str(self.data_dir),
                "node_count": node_count
            }
        except Exception as e:
            return {
                "status": "error",
                "port": self.port,
                "data_dir": str(self.data_dir),
                "error": str(e)
            }


# Example of a global Neo4j manager
neo4j_manager = None

def get_neo4j_manager(data_dir="./neo4j_data", port=7688, http_port=7474, host="127.0.0.1"):
    """AccessNeo4jManager Example"""
    global neo4j_manager
    if neo4j_manager is None:
        neo4j_manager = Neo4jManager(data_dir, port, http_port, host)
    return neo4j_manager

def start_neo4j_server(data_dir="./neo4j_data", port=7688, http_port=7474, host="127.0.0.1"):
    """StartNeo4jEasy function of the server"""
    manager = get_neo4j_manager(data_dir, port, http_port, host)
    return manager.start()

def stop_neo4j_server():
    """StopNeo4jEasy function of the server"""
    global neo4j_manager
    if neo4j_manager:
        neo4j_manager.stop()
