# validators.py
"""
Data validation utilities for FutureScorer bot.
Provides validation functions for trading data, configuration, and user inputs.
"""
from typing import Any, Dict, List, Optional, Union, Tuple
import re
from decimal import Decimal, InvalidOperation
from exceptions import DataValidationError, ConfigurationError

def validateSymbol(symbol: str) -> bool:
    """Validate trading symbol format."""
    if not symbol or not isinstance(symbol, str):
        return False
    
    # Pattern for BingX futures symbols: BASE/QUOTE:QUOTE or BASE-QUOTE
    pattern = r'^[A-Z0-9]+[/:-][A-Z0-9]+(?::[A-Z0-9]+)?$'
    return bool(re.match(pattern, symbol.upper()))

# Alias for compatibility
validatePairFormat = validateSymbol

def validateTimeframe(timeframe: str) -> bool:
    """Validate timeframe format (e.g., 1m, 5m, 1h, 1d)."""
    if not timeframe or not isinstance(timeframe, str):
        return False
    
    pattern = r'^\d+[mhd]$'
    return bool(re.match(pattern, timeframe.lower()))

def validatePrice(price: Union[str, int, float, Decimal]) -> bool:
    """Validate price value."""
    try:
        price_decimal = Decimal(str(price))
        return price_decimal > 0
    except (InvalidOperation, ValueError, TypeError):
        return False

def validatePercentage(value: Union[str, int, float], minVal: float = 0, maxVal: float = 100) -> bool:
    """Validate percentage value within range."""
    try:
        num_val = float(value)
        return minVal <= num_val <= maxVal
    except (ValueError, TypeError):
        return False

def validatePositiveNumber(value: Union[str, int, float]) -> bool:
    """Validate positive number."""
    try:
        num_val = float(value)
        return num_val > 0
    except (ValueError, TypeError):
        return False

def validateConfigStructure(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate configuration structure and required fields."""
    errors = []
    required_fields = [
        'apiKey', 'apiSecret', 'telegramToken', 'telegramChatId',
        'maxOpenPositions', 'usdcInvestment', 'timeframe'
    ]
    
    for field in required_fields:
        if field not in config:
            errors.append(f"Missing required field: {field}")
        elif not config[field]:
            errors.append(f"Empty required field: {field}")
    
    # Validate specific field types and ranges
    if 'maxOpenPositions' in config:
        if not isinstance(config['maxOpenPositions'], int) or config['maxOpenPositions'] <= 0:
            errors.append("maxOpenPositions must be a positive integer")
    
    if 'usdcInvestment' in config:
        if not validatePositiveNumber(config['usdcInvestment']):
            errors.append("usdcInvestment must be a positive number")
    
    if 'timeframe' in config:
        if not validateTimeframe(config['timeframe']):
            errors.append("Invalid timeframe format")
    
    # Validate scoring weights
    if 'scoringWeights' in config:
        weights = config['scoringWeights']
        if isinstance(weights, dict):
            required_weights = ['distance', 'volume', 'momentum', 'touches']
            for weight in required_weights:
                if weight not in weights:
                    errors.append(f"Missing scoring weight: {weight}")
                elif not isinstance(weights[weight], (int, float)) or weights[weight] < 0:
                    errors.append(f"Invalid scoring weight for {weight}: must be non-negative number")
    
    return len(errors) == 0, errors

def validateOhlcvData(data: List[List]) -> bool:
    """Validate OHLCV data structure."""
    if not data or not isinstance(data, list):
        return False
    
    for candle in data:
        if not isinstance(candle, list) or len(candle) != 6:
            return False
        
        # Check if all values are numeric
        try:
            timestamp, open_price, high, low, close, volume = candle
            
            # Timestamp should be positive integer
            if not isinstance(timestamp, (int, float)) or timestamp <= 0:
                return False
            
            # OHLC should be positive numbers
            for price in [open_price, high, low, close]:
                if not isinstance(price, (int, float)) or price <= 0:
                    return False
            
            # Volume should be non-negative
            if not isinstance(volume, (int, float)) or volume < 0:
                return False
            
            # High should be >= Low, and both should be within Open/Close range
            if high < low:
                return False
            
        except (ValueError, TypeError):
            return False
    
    return True

def validateTradingParameters(
    symbol: str,
    amount: Union[str, int, float],
    price: Optional[Union[str, int, float]] = None,
    order_type: str = 'market'
) -> Tuple[bool, List[str]]:
    """Validate trading parameters."""
    errors = []
    
    if not validateSymbol(symbol):
        errors.append(f"Invalid symbol format: {symbol}")
    
    if not validatePositiveNumber(amount):
        errors.append(f"Invalid amount: {amount}")
    
    if price is not None and not validatePrice(price):
        errors.append(f"Invalid price: {price}")
    
    valid_order_types = ['market', 'limit', 'stop', 'stop_market', 'take_profit_market']
    if order_type.lower() not in valid_order_types:
        errors.append(f"Invalid order type: {order_type}")
    
    return len(errors) == 0, errors

def sanitizeSymbol(symbol: str) -> str:
    """Sanitize and normalize symbol format."""
    if not symbol:
        raise DataValidationError("Symbol cannot be empty")
    
    # Convert to uppercase and remove extra spaces
    symbol = symbol.strip().upper()
    
    # Normalize separators
    symbol = symbol.replace('-', '/').replace('_', '/')
    
    if not validateSymbol(symbol):
        raise DataValidationError(f"Invalid symbol format: {symbol}")
    
    return symbol

def sanitizeFilename(filename: str) -> str:
    """Sanitize filename for safe file operations."""
    if not filename:
        raise DataValidationError("Filename cannot be empty")
    
    # Remove or replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip(' .')
    
    if not filename:
        raise DataValidationError("Filename becomes empty after sanitization")
    
    return filename

def validatePositionData(position: Dict[str, Any]) -> bool:
    """Validate position data structure."""
    required_fields = ['symbol', 'amount', 'price', 'side']
    
    for field in required_fields:
        if field not in position:
            return False
        
        if field == 'symbol' and not validateSymbol(position[field]):
            return False
        elif field in ['amount', 'price'] and not validatePositiveNumber(position[field]):
            return False
        elif field == 'side' and position[field] not in ['buy', 'sell']:
            return False
    
    return True
