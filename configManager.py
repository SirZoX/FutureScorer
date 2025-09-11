# configManager.py
"""
Centralized configuration management for FutureScorer bot.
Singleton pattern to ensure consistent config across modules.
"""
import json
import os
import threading
import time
from typing import Dict, Any, Optional

class ConfigManager:
    _instance: Optional['ConfigManager'] = None
    _config: Optional[Dict[str, Any]] = None
    _config_file_path = os.path.join(os.path.dirname(__file__), '_files', 'config', 'config.json')
    _file_mtime: Optional[float] = None
    _watcher_thread: Optional[threading.Thread] = None
    _watcher_running = False
    
    def __new__(cls) -> 'ConfigManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self.reload_config()
            self.start_file_watcher()
    
    def start_file_watcher(self) -> None:
        """Start file watcher thread to monitor config.json changes."""
        if self._watcher_thread is None:
            self._watcher_running = True
            self._watcher_thread = threading.Thread(target=self._watch_config_file, daemon=True)
            self._watcher_thread.start()
    
    def stop_file_watcher(self) -> None:
        """Stop file watcher thread."""
        self._watcher_running = False
        if self._watcher_thread:
            self._watcher_thread = None
    
    def _watch_config_file(self) -> None:
        """Monitor config file for changes and reload when detected."""
        while self._watcher_running:
            try:
                if os.path.exists(self._config_file_path):
                    current_mtime = os.path.getmtime(self._config_file_path)
                    
                    # Initialize mtime on first check
                    if self._file_mtime is None:
                        self._file_mtime = current_mtime
                    # Check if file has been modified
                    elif current_mtime > self._file_mtime:
                        self._file_mtime = current_mtime
                        self._reload_with_change_detection()
                
                # Check every 2 seconds
                time.sleep(2)
            except Exception as e:
                # Lazy import to avoid circular dependency
                from logManager import messages
                messages(f"Error in config file watcher: {e}", console=1, log=1, telegram=0)
                time.sleep(5)  # Wait longer on error
    
    def _reload_with_change_detection(self) -> None:
        """Reload config and detect changes."""
        try:
            # Store old config for comparison
            oldConfig = self._config.copy() if self._config else {}
            
            # Reload config
            with open(self._config_file_path, 'r', encoding='utf-8') as f:
                newConfig = json.load(f)
            
            # Detect changes
            changes = self._detect_changes(oldConfig, newConfig)
            
            # Update config
            self._config = newConfig
            
            # Report changes
            if changes:
                # Lazy import to avoid circular dependency
                from logManager import messages
                messages(f"Config changes detected: {len(changes)} parameters updated", console=1, log=1, telegram=0)
                for change in changes:
                    messages(f"  {change}", console=1, log=1, telegram=0)
            
        except Exception as e:
            # Lazy import to avoid circular dependency
            from logManager import messages
            messages(f"Error reloading config: {e}", console=1, log=1, telegram=0)
    
    def _detect_changes(self, oldConfig: Dict[str, Any], newConfig: Dict[str, Any]) -> list:
        """Detect changes between old and new config."""
        changes = []
        
        # Check for modified and new values
        for key, newValue in newConfig.items():
            if key not in oldConfig:
                changes.append(f"{key}: NEW -> {newValue}")
            elif oldConfig[key] != newValue:
                changes.append(f"{key}: {oldConfig[key]} -> {newValue}")
        
        # Check for removed values
        for key in oldConfig:
            if key not in newConfig:
                changes.append(f"{key}: REMOVED (was {oldConfig[key]})")
        
        return changes
    
    def reload_config(self) -> None:
        """Reload configuration from file."""
        try:
            with open(self._config_file_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
            
            # Update file mtime for watcher
            if os.path.exists(self._config_file_path):
                self._file_mtime = os.path.getmtime(self._config_file_path)
                
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
