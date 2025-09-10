# exceptions.py
"""
Custom exceptions for FutureScorer bot.
Provides specific error types for better error handling and debugging.
"""

class FutureScorerError(Exception):
    """Base exception for FutureScorer bot."""
    def __init__(self, message: str, console: int = 0, log: int = 1, telegram: int = 0):
        super().__init__(message)
        # Import here to avoid circular import
        from logManager import messages
        messages(f"[EXCEPTION] {self.__class__.__name__}: {message}", console=console, log=log, telegram=telegram)

class ConfigurationError(FutureScorerError):
    """Raised when there's a configuration-related error."""
    def __init__(self, message: str, console: int = 1, log: int = 1, telegram: int = 0):
        super().__init__(message, console, log, telegram)

class ExchangeConnectionError(FutureScorerError):
    """Raised when there's an issue connecting to the exchange."""
    def __init__(self, message: str, console: int = 0, log: int = 1, telegram: int = 0):
        super().__init__(message, console, log, telegram)

class InsufficientBalanceError(FutureScorerError):
    """Raised when there's insufficient balance for trading."""
    def __init__(self, message: str, console: int = 1, log: int = 1, telegram: int = 1):
        super().__init__(message, console, log, telegram)

class OrderExecutionError(FutureScorerError):
    """Raised when an order fails to execute."""
    def __init__(self, message: str, symbol: str = None, order_type: str = None, console: int = 0, log: int = 1, telegram: int = 0):
        self.symbol = symbol
        self.order_type = order_type
        error_msg = f"{message}"
        if symbol:
            error_msg += f" (Symbol: {symbol})"
        if order_type:
            error_msg += f" (Type: {order_type})"
        super().__init__(error_msg, console, log, telegram)

class DataValidationError(FutureScorerError):
    """Raised when data validation fails."""
    def __init__(self, message: str, console: int = 0, log: int = 1, telegram: int = 0):
        super().__init__(message, console, log, telegram)

class RateLimitError(FutureScorerError):
    """Raised when rate limit is exceeded."""
    def __init__(self, message: str, console: int = 0, log: int = 1, telegram: int = 0):
        super().__init__(message, console, log, telegram)

class TechnicalAnalysisError(FutureScorerError):
    """Raised when technical analysis fails."""
    def __init__(self, message: str, console: int = 0, log: int = 1, telegram: int = 0):
        super().__init__(message, console, log, telegram)

class TelegramError(FutureScorerError):
    """Raised when Telegram communication fails."""
    def __init__(self, message: str, console: int = 0, log: int = 1, telegram: int = 0):
        super().__init__(message, console, log, telegram)

# Aliases for compatibility
ValidationError = DataValidationError
TradingError = OrderExecutionError
APIError = ExchangeConnectionError
