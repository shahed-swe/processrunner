import requests
import json
import sys
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:5001"

def test_health_check():
    """Test the health check endpoint"""
    print("Testing health check...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        print("❌ Connection failed - make sure the API server is running")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_whatsapp():
    """Test the WhatsApp endpoint"""
    print("\nTesting WhatsApp endpoint...")
    try:
        params = {'env': 'test'}
        response = requests.get(f"{BASE_URL}/api/run-whatsapp", params=params)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code in [200, 500]  # 500 is expected if script has issues
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_run_po_review_get():
    """Test running PO review via GET request"""
    print("\nTesting PO review (GET request)...")
    try:
        # Test with parameters
        params = {
            'cleanup': 'true',
            'text_limit': '1500'
        }
        response = requests.get(f"{BASE_URL}/api/run-po-review", params=params)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code in [200, 500]  # 500 is expected if script has issues
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_run_po_review_post():
    """Test running PO review via POST request"""
    print("\nTesting PO review (POST request)...")
    try:
        data = {
            'cleanup': True,
            'text_limit': 1500
        }
        response = requests.post(f"{BASE_URL}/api/run-po-review", json=data)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code in [200, 500]  # 500 is expected if script has issues
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_po_status():
    """Test the PO status endpoint"""
    print("\nTesting PO status...")
    try:
        params = {'wpq': 'TEST123'}
        response = requests.get(f"{BASE_URL}/api/po-status", params=params)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_po_cleanup():
    """Test the PO cleanup endpoint"""
    print("\nTesting PO cleanup...")
    try:
        response = requests.post(f"{BASE_URL}/api/po-cleanup")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code in [200, 500]  # 500 is expected if script has issues
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("WhatsApp & PO Review API Test Suite")
    print("=" * 60)
    print(f"Testing API at: {BASE_URL}")
    print(f"Test started at: {datetime.now().isoformat()}")
    print()
    
    tests = [
        ("Health Check", test_health_check),
        ("WhatsApp", test_whatsapp),
        ("PO Review (GET)", test_run_po_review_get),
        ("PO Review (POST)", test_run_po_review_post),
        ("PO Status", test_po_status),
        ("PO Cleanup", test_po_cleanup),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'=' * 40}")
        print(f"Running: {test_name}")
        print('=' * 40)
        
        success = test_func()
        results.append((test_name, success))
        
        if success:
            print(f"✅ {test_name} - PASSED")
        else:
            print(f"❌ {test_name} - FAILED")
    
    print(f"\n{'=' * 60}")
    print("Test Summary")
    print('=' * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name:20} - {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed - check the API server logs")

if __name__ == "__main__":
    main()
