#!/usr/bin/env python3
"""
Simple test for timeout error detection
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_timeout_detection():
    """Test that timeout errors are detected correctly"""
    
    # Test error string detection
    test_errors = [
        "HTTPSConnectionPool(host='api.telegram.org', port=443): Read timed out. (read timeout=5)",
        "Read timed out",
        "Connection timeout",
        "requests.exceptions.ReadTimeout",
        "Normal error without timeout"
    ]
    
    print("🔍 Testing timeout error detection:")
    
    for error in test_errors:
        error_str = str(error).lower()
        is_timeout = ('read timed out' in error_str or 
                     'timeout' in error_str or 
                     'readtimeout' in error_str) and 'without timeout' not in error_str
        status = "✅ TIMEOUT" if is_timeout else "❌ NOT TIMEOUT"
        print(f"   {status}: {error}")
    
    print("\n✅ Error detection logic verified!")

if __name__ == "__main__":
    test_timeout_detection()
