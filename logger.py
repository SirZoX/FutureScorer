# logger.py
"""
Enhanced logging system for FutureScorer bot.
Provides structured logging with different levels and formatters.
"""
import logging
import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
import gvars

class BotLogger:
    def __init__(self, name: str = "FutureScorer"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Prevent duplicate handlers
        if not self.logger.handlers:
            self._setup_handlers()
    
    def _setup_handlers(self) -> None:
        """Setup file and console handlers with proper formatting."""
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        
        # File handler
        log_dir = Path(gvars.logsFolder) / datetime.now().strftime('%Y_%m')
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{datetime.now().strftime('%d%m%Y')}.log"
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%d/%m/%Y %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        
        # Add handlers
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
    
    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        self.logger.debug(self._format_message(message, **kwargs))
    
    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        self.logger.info(self._format_message(message, **kwargs))
    
    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        self.logger.warning(self._format_message(message, **kwargs))
    
    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        self.logger.error(self._format_message(message, **kwargs))
    
    def critical(self, message: str, **kwargs) -> None:
        """Log critical message."""
        self.logger.critical(self._format_message(message, **kwargs))
    
    def _format_message(self, message: str, **kwargs) -> str:
        """Format message with additional context."""
        if not kwargs:
            return message
        
        context_parts = []
        for key, value in kwargs.items():
            context_parts.append(f"{key}={value}")
        
        if context_parts:
            return f"{message} | {' | '.join(context_parts)}"
        return message
    
    def trade_log(self, action: str, symbol: str, **kwargs) -> None:
        """Specialized logging for trading actions."""
        context = {'action': action, 'symbol': symbol}
        context.update(kwargs)
        self.info("TRADE", **context)
    
    def performance_log(self, operation: str, duration: float, **kwargs) -> None:
        """Log performance metrics."""
        context = {'operation': operation, 'duration_s': f"{duration:.2f}"}
        context.update(kwargs)
        self.info("PERFORMANCE", **context)

# Global logger instance
bot_logger = BotLogger()

# Convenience functions
def log_debug(message: str, **kwargs) -> None:
    bot_logger.debug(message, **kwargs)

def log_info(message: str, **kwargs) -> None:
    bot_logger.info(message, **kwargs)

def log_warning(message: str, **kwargs) -> None:
    bot_logger.warning(message, **kwargs)

def log_error(message: str, **kwargs) -> None:
    bot_logger.error(message, **kwargs)

def log_trade(action: str, symbol: str, **kwargs) -> None:
    bot_logger.trade_log(action, symbol, **kwargs)
