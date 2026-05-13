#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Independent Start Milvus Script for Server
"""

import sys
import os

# Fix path to allow relative imports if run as a script
if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packages.manager.milvus_manager import get_milvus_manager
from packages.utils.logging_config import logger

def start_milvus_only():
    """Start only Milvus Server"""
    print("Starting Milvus Server...")
    
    try:
        milvus_manager = get_milvus_manager()
        if milvus_manager.start():
            print("✅ Milvus Server started successfully")
            
            # Keep running
            print("Milvus Server is running. Press Ctrl+C to stop...")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nStopping Milvus Server...")
                milvus_manager.stop()
                print("✅ Milvus Server stopped")
                return True
        else:
            print("❌ Milvus Server startup failed")
            return False
            
    except Exception as e:
        print(f"❌ Error during startup: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = start_milvus_only()
    sys.exit(0 if success else 1)
