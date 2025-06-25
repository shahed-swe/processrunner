#!/usr/bin/env python3
"""
Simple client to test the WhatsApp Notification API
"""

import requests
import json

# API base URL
BASE_URL = "http://localhost:5001"

def test_api():
    """Test the WhatsApp API"""
    
    print("🚀 Testing WhatsApp Notification API")
    print("=" * 50)
    
    # 1. Health check
    print("\n1. Health Check:")
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")
    
    # 2. Run WhatsApp script in test mode
    print("\n2. Run WhatsApp Script (Test Mode):")
    try:
        response = requests.get(f"{BASE_URL}/api/run-whatsapp?env=test")
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"Success: {result.get('success')}")
        print(f"Message: {result.get('message')}")
        print(f"Return Code: {result.get('return_code')}")
        if result.get('stdout'):
            print(f"Output:\n{result.get('stdout')}")
        if result.get('stderr'):
            print(f"Errors:\n{result.get('stderr')}")
    except Exception as e:
        print(f"Error: {e}")
    
    # 3. Run WhatsApp script in production mode (commented out for safety)
    print("\n3. Run WhatsApp Script (Production Mode) - COMMENTED OUT")
    print("   Uncomment the code below to test production mode")
    """
    try:
        response = requests.get(f"{BASE_URL}/api/run-whatsapp?env=prod")
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"Success: {result.get('success')}")
        print(f"Message: {result.get('message')}")
        if result.get('stdout'):
            print(f"Output:\n{result.get('stdout')}")
    except Exception as e:
        print(f"Error: {e}")
    """

if __name__ == "__main__":
    test_api()
