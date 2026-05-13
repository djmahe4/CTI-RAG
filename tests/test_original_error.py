#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test original error script - Simulation API Call
"""

import sys
import os
import requests
import json
import time

def test_original_error():
    """Test original API Error"""
    print("Testing Original API Error...")
    
    # API Endpoint
    url = "http://localhost:8000/data/query-test"
    
    # Test Data
    test_data = {
        "query": "test query",
        "meta": {
            "maxQueryCount": 20,
            "topK": 10
        }
    }
    
    try:
        print("Sending API request...")
        response = requests.post(url, json=test_data, timeout=30)
        
        if response.status_code == 200:
            print("✅ API call successful")
            result = response.json()
            print(f"Return Result: {result}")
            return True
        else:
            print(f"❌ API call failed, Status Code: {response.status_code}")
            print(f"Error message: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to server. Make sure the server is running.")
        return False
    except Exception as e:
        print(f"❌ Error in request: {e}")
        return False

def wait_for_server(max_wait=60):
    """Waiting for server startup"""
    print("Waiting for server startup...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            response = requests.get("http://localhost:8000/", timeout=5)
            if response.status_code == 200:
                print("✅ Server started")
                return True
        except:
            pass
        time.sleep(2)
    
    print("❌ Server start timeout")
    return False

if __name__ == "__main__":
    if wait_for_server():
        success = test_original_error()
        sys.exit(0 if success else 1)
    else:
        print("Server not started. Could not perform test.")
        sys.exit(1)
