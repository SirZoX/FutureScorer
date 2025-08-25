# configManager.py
"""
Centralized configuration management for FutureScorer bot.
Singleton pattern to ensure consistent config across modules.
"""
import json
import os
from typing import Dict, Any, Optional

class ConfigManager:
    _instance: Optional['ConfigManager'] = None
    _config: Optional[Dict[str, Any]] = None
    _config_file_path = os.path.join(os.path.dirname(__file__), '_files', 'config', 'config.json')
    
    def __new__(cls) -> 'ConfigManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self.reload_config()
    
    def reload_config(self) -> None:
        """Reload configuration from file."""
        try:
            with open(self._config_file_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
        except Exception as e:
            raise Exception(f"Error loading config: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with optional default."""
        if self._config is None:
            self.reload_config()
        return self._config.get(key, default)
    
    def get_nested(self, keys: str, default: Any = None) -> Any:
        """Get nested configuration value using dot notation (e.g., 'scoring.weights.distance')."""
        if self._config is None:
            self.reload_config()
        
        value = self._config
        for key in keys.split('.'):
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
    
    def update(self, key: str, value: Any) -> None:
        """Update configuration value (in memory only)."""
        if self._config is None:
            self.reload_config()
        self._config[key] = value
    
    def save(self) -> None:
        """Save current configuration to file."""
        if self._config is None:
            return
        
        with open(self._config_file_path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get the entire configuration dictionary."""
        if self._config is None:
            self.reload_config()
        return self._config.copy()
    
    def get_credentials(self) -> Dict[str, str]:
        """Get trading credentials."""
        return {
            'apikey': self.config.get('apiKey', ''),
            'apisecret': self.config.get('apiSecret', ''),
            'sandbox': self.config.get('sandbox', False)
        }
    
    def is_sandbox(self) -> bool:
        """Check if running in sandbox mode."""
        return self.config.get('sandbox', False)

# Global instance for easy access
configManager = ConfigManager()

# Convenience functions for backward compatibility
def loadConfig() -> Dict[str, Any]:
    """Legacy function for backward compatibility."""
    return configManager.config

def getConfig(key: str, default: Any = None) -> Any:
    """Get config value with default."""
    return configManager.get(key, default)
