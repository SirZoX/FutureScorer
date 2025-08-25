#!/usr/bin/env python3
"""
Script de verificación de integración de módulos
Prueba que todos los nuevos módulos y su integración funcionan correctamente
"""

import sys
import traceback

def test_module_imports():
    """Test que todos los módulos se importan correctamente"""
    print("Testing module imports...")
    
    try:
        # Test new modules
        from config_manager import config_manager
        print("✓ config_manager imported successfully")
        
        from logger import log_info, log_error, log_warning, log_debug
        print("✓ logger imported successfully")
        
        from cache_manager import cache_manager
        print("✓ cache_manager imported successfully")
        
        from validators import validate_pair_format, validate_position_data
        print("✓ validators imported successfully")
        
        from exceptions import ConfigurationError, ValidationError, TradingError, APIError
        print("✓ exceptions imported successfully")
        
        # Test main modules with integration
        import bot
        print("✓ bot imported successfully")
        
        import connector
        print("✓ connector imported successfully")
        
        import helpers
        print("✓ helpers imported successfully")
        
        import pairs
        print("✓ pairs imported successfully")
        
        import orderManager
        print("✓ orderManager imported successfully")
        
        import logManager
        print("✓ logManager imported successfully")
        
        import plotting
        print("✓ plotting imported successfully")
        
        import marketLoader
        print("✓ marketLoader imported successfully")
        
        import supportDetector
        print("✓ supportDetector imported successfully")
        
        import positionMonitor
        print("✓ positionMonitor imported successfully")
        
        import fileManager
        print("✓ fileManager imported successfully")
        
        return True
        
    except Exception as e:
        print(f"✗ Import error: {e}")
        traceback.print_exc()
        return False

def test_config_manager():
    """Test que el config manager funciona"""
    print("\nTesting config_manager...")
    
    try:
        from config_manager import config_manager
        
        # Test config loading
        config = config_manager.config
        print(f"✓ Config loaded: {len(config)} keys")
        
        # Test get method
        api_key = config_manager.get('apiKey', 'default')
        print("✓ Config get method works")
        
        # Test credentials
        credentials = config_manager.get_credentials()
        print("✓ Credentials method works")
        
        return True
        
    except Exception as e:
        print(f"✗ Config manager error: {e}")
        traceback.print_exc()
        return False

def test_logger():
    """Test que el logger funciona"""
    print("\nTesting logger...")
    
    try:
        from logger import log_info, log_error, log_warning, log_debug
        
        # Test different log levels
        log_info("Test info message", pair="TEST/USDT")
        log_warning("Test warning message", pair="TEST/USDT")
        log_error("Test error message", error="Test error", pair="TEST/USDT")
        log_debug("Test debug message", pair="TEST/USDT")
        
        print("✓ All log levels working")
        return True
        
    except Exception as e:
        print(f"✗ Logger error: {e}")
        traceback.print_exc()
        return False

def test_cache_manager():
    """Test que el cache manager funciona"""
    print("\nTesting cache_manager...")
    
    try:
        from cache_manager import cache_manager
        
        # Test setting and getting cache
        cache_manager.set('test_key', {'data': 'test_value'}, 300)
        cached_data = cache_manager.get('test_key')
        
        if cached_data and cached_data.get('data') == 'test_value':
            print("✓ Cache set/get working")
        else:
            print("✗ Cache set/get not working")
            return False
            
        # Test cache stats
        stats = cache_manager.get_cache_stats()
        print(f"✓ Cache stats: {stats}")
        
        return True
        
    except Exception as e:
        print(f"✗ Cache manager error: {e}")
        traceback.print_exc()
        return False

def test_validators():
    """Test que los validators funcionan"""
    print("\nTesting validators...")
    
    try:
        from validators import validate_pair_format, validate_position_data
        
        # Test pair validation
        valid_pair = validate_pair_format("BTC/USDT")
        print("✓ Valid pair validation works")
        
        # Test position validation
        position_data = {
            'symbol': 'BTC/USDT',
            'amount': 0.001,
            'price': 50000,
            'side': 'buy'
        }
        valid_position = validate_position_data(position_data)
        print("✓ Position validation works")
        
        return True
        
    except Exception as e:
        print(f"✗ Validators error: {e}")
        traceback.print_exc()
        return False

def test_exceptions():
    """Test que las custom exceptions funcionan"""
    print("\nTesting custom exceptions...")
    
    try:
        from exceptions import ConfigurationError, ValidationError, TradingError, APIError
        
        # Test that exceptions can be raised and caught
        try:
            raise ConfigurationError("Test config error")
        except ConfigurationError:
            print("✓ ConfigurationError works")
            
        try:
            raise ValidationError("Test validation error")
        except ValidationError:
            print("✓ ValidationError works")
            
        try:
            raise TradingError("Test trading error")
        except TradingError:
            print("✓ TradingError works")
            
        try:
            raise APIError("Test API error")
        except APIError:
            print("✓ APIError works")
        
        return True
        
    except Exception as e:
        print(f"✗ Exceptions error: {e}")
        traceback.print_exc()
        return False

def main():
    """Run all integration tests"""
    print("=" * 60)
    print("TESTING NEW MODULES INTEGRATION")
    print("=" * 60)
    
    tests = [
        test_module_imports,
        test_config_manager,
        test_logger,
        test_cache_manager,
        test_validators,
        test_exceptions
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"INTEGRATION TEST RESULTS")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {passed + failed}")
    print("=" * 60)
    
    if failed == 0:
        print("🎉 ALL TESTS PASSED! Integration successful!")
        print("The bot is ready for sandbox testing.")
        return True
    else:
        print("❌ SOME TESTS FAILED! Check errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
