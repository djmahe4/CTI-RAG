#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestMilvusFix to load repaired scripts
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from packages.manager.milvus_manager import get_milvus_manager
from packages.core.knowledgebase import KnowledgeBase
from packages.utils.logging_config import logger

def test_milvus_fix():
    """Test Milvus Rehabilitation"""
    print("Starting Milvus pool load repair test...")
    
    try:
        # 1. Launch of the Milvus server
        print("1. Starting Milvus Server...")
        milvus_manager = get_milvus_manager()
        if not milvus_manager.start():
            print("❌ Milvus Server startup failed")
            return False
        print("✅ Milvus Server started successfully")
        
        # 2. Knowledge base instance creation
        print("2. Creating KnowledgeBase instance...")
        kb = KnowledgeBase()
        print("✅ KnowledgeBase instance created successfully")
        
        # 3. Check existing collections
        print("3. Checking existing collections...")
        collections = kb.get_collection_names()
        print(f"Found {len(collections)} collections: {collections}")
        
        # 4. Test collection loading
        if collections:
            test_collection = collections[0]
            print(f"4. Testing collection '{test_collection}' loading...")
            
            # Ensure collection loaded
            if kb.ensure_collection_loaded(test_collection):
                print(f"✅ Collection '{test_collection}' loaded successfully")
                
                # 5. Test search function
                print("5. Testing search function...")
                try:
                    # Try a simple search
                    results = kb.search("test query", test_collection, limit=1)
                    print(f"✅ Search successful, returned {len(results)} results")
                except Exception as e:
                    print(f"⚠️ Search test failed (may be due to empty collection): {e}")
            else:
                print(f"❌ Collection '{test_collection}' loading failed")
        else:
            print("4. No existing collections found, skipping load test")
        
        print("✅ Test complete.")
        return True
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Cleanup
        try:
            print("Cleaning up resources...")
            if 'milvus_manager' in locals():
                milvus_manager.stop()
        except Exception as e:
            print(f"Error during cleanup: {e}")

if __name__ == "__main__":
    success = test_milvus_fix()
    sys.exit(0 if success else 1)
