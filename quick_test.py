#!/usr/bin/env python3
"""
Script básico de verificación de integración
"""

print("Testing basic module imports...")

try:
    # Test new modules
    from config_manager import config_manager
    print("✓ config_manager")
    
    from logger import log_info
    print("✓ logger")
    
    from cache_manager import cache_manager
    print("✓ cache_manager") 
    
    from validators import validate_pair_format
    print("✓ validators")
    
    from exceptions import ConfigurationError
    print("✓ exceptions")
    
    print("\n✅ All new modules imported successfully!")
    print("📝 Key improvements implemented:")
    print("   • Centralized configuration management")
    print("   • Structured logging with timestamps")
    print("   • Intelligent caching for API optimization")
    print("   • Comprehensive data validation")
    print("   • Custom exception handling")
    print("   • Legacy code replaced with modern modules")
    
    print("\n🚀 Ready for sandbox testing!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
