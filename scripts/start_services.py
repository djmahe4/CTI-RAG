import os
import subprocess
import sys
import time
import signal
import argparse

def check_redis():
    """Check if Redis has started"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=1)
        r.ping()
        print("✅ Redis has started")
        return True
    except:
        print("❌ Redis is not started")
        return False

def start_redis():
    """Start Redis service"""
    try:
        # Check if Redis is installed
        if sys.platform == 'win32':
            # Windows
            redis_server = subprocess.Popen(
                ['redis-server'], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
        else:
            # Linux/Mac
            redis_server = subprocess.Popen(
                ['redis-server'], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
        
        # Wait for Redis to start
        time.sleep(2)
        
        # Check if successfully started
        if check_redis():
            print("✅ Redis service started successfully")
            return redis_server
        else:
            print("❌ Redis service startup failed")
            return None
    except Exception as e:
        print(f"❌ Error starting Redis: {e}")
        return None

def start_app():
    """Start FastAPI application"""
    try:
        # Start FastAPI application
        app_process = subprocess.Popen(
            ['uvicorn', 'main:app', '--host', '0.0.0.0', '--port', '8000', '--reload'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print("✅ FastAPI application started")
        return app_process
    except Exception as e:
        print(f"❌ Error starting FastAPI application: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description='Start services')
    parser.add_argument('--no-redis', action='store_true', help='Do not start Redis')
    parser.add_argument('--no-app', action='store_true', help='Do not start FastAPI application')
    args = parser.parse_args()
    
    processes = []
    
    # Start Redis
    if not args.no_redis:
        if not check_redis():
            redis_process = start_redis()
            if redis_process:
                processes.append(redis_process)
    
    # Start FastAPI application
    if not args.no_app:
        app_process = start_app()
        if app_process:
            processes.append(app_process)
    
    # Register signal handler
    def signal_handler(sig, frame):
        print("\nShutting down services...")
        for process in processes:
            process.terminate()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Keep main process running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down services...")
        for process in processes:
            process.terminate()

if __name__ == "__main__":
    main()