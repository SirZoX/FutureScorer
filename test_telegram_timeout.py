#!/usr/bin/env python3
"""
Test script to simulate Telegram timeout and verify sleep behavior
"""

import time
import requests
from unittest.mock import patch, MagicMock
from helpers import checkTelegram
from logManager import sendTelegramMessage

def test_telegram_timeout():
    """Test timeout handling in checkTelegram"""
    print("🔬 Testing Telegram timeout handling...")
    
    # Simulate timeout exception
    with patch('requests.get') as mock_get:
        mock_get.side_effect = requests.exceptions.ReadTimeout("Read timed out. (read timeout=5)")
        
        print("⏱️  Simulating timeout - starting timer...")
        start_time = time.time()
        
        try:
            checkTelegram()
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"✅ Timeout handled - elapsed time: {elapsed:.1f}s")
        
        if elapsed >= 15:
            print("✅ Sleep of 15s was executed correctly")
        else:
            print(f"⚠️  Sleep may not have worked - expected 15s, got {elapsed:.1f}s")

def test_telegram_send_timeout():
    """Test timeout handling in sendTelegramMessage"""
    print("\n🔬 Testing Telegram send timeout handling...")
    
    # Simulate timeout exception in POST request
    with patch('requests.post') as mock_post:
        mock_post.side_effect = requests.exceptions.ReadTimeout("Read timed out. (read timeout=10)")
        
        print("⏱️  Simulating send timeout - starting timer...")
        start_time = time.time()
        
        try:
            sendTelegramMessage("Test message")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"✅ Send timeout handled - elapsed time: {elapsed:.1f}s")
        
        if elapsed >= 15:
            print("✅ Sleep of 15s was executed correctly")
        else:
            print(f"⚠️  Sleep may not have worked - expected 15s, got {elapsed:.1f}s")

if __name__ == "__main__":
    print("🚀 TELEGRAM TIMEOUT TESTING")
    print("="*50)
    
    # Test both functions
    test_telegram_timeout()
    test_telegram_send_timeout()
    
    print("\n✅ All timeout tests completed!")
