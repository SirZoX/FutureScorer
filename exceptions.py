# exceptions.py
"""
Custom exceptions for FutureScorer bot.
Provides specific error types for better error handling and debugging.
"""

class FutureScorerError(Exception):
    """Base exception for FutureScorer bot."""
    pass

class ConfigurationError(FutureScorerError):
    """Raised when there's a configuration-related error."""
    pass

class ExchangeConnectionError(FutureScorerError):
    """Raised when there's an issue connecting to the exchange."""
    pass

class InsufficientBalanceError(FutureScorerError):
    """Raised when there's insufficient balance for trading."""
    pass

class OrderExecutionError(FutureScorerError):
    """Raised when an order fails to execute."""
    def __init__(self, message: str, symbol: str = None, order_type: str = None):
        super().__init__(message)
        self.symbol = symbol
        self.order_type = order_type

class DataValidationError(FutureScorerError):
    """Raised when data validation fails."""
    pass

class RateLimitError(FutureScorerError):
    """Raised when rate limit is exceeded."""
    pass

class TechnicalAnalysisError(FutureScorerError):
    """Raised when technical analysis fails."""
    pass

class TelegramError(FutureScorerError):
    """Raised when Telegram communication fails."""
    pass

# Aliases for compatibility
ValidationError = DataValidationError
TradingError = OrderExecutionError
APIError = ExchangeConnectionError
