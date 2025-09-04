from cacheManager import cachedCall
from connector import bingxConnector
from logManager import messages
import time

class ApiOptimizer:
    def __init__(self, exchange):
        self.exchange = exchange
    
    def getTicker(self, symbol):
        """Get real-time ticker - NO CACHING for price data"""
        return self.exchange.fetch_ticker(symbol)
    
    def getPositionsCached(self, ttl=60):
        """Get positions with 60-second caching - positions don't change frequently"""
        return cachedCall(
            "exchange_positions", 
            self.exchange.fetch_positions, 
            ttl=ttl
        )
    
    def getBalanceCached(self, ttl=180):
        """Get balance with aggressive caching - balance changes only with trades"""
        return cachedCall(
            "exchange_balance", 
            self.exchange.fetch_balance, 
            ttl=ttl
        )
    
    def getMarketsCached(self, ttl=3600):
        """Get markets with very aggressive caching - markets rarely change"""
        return cachedCall(
            "exchange_markets", 
            self.exchange.load_markets, 
            ttl=ttl
        )

# Global instance
apiOptimizer = None

def initializeApiOptimizer(exchange):
    global apiOptimizer
    apiOptimizer = ApiOptimizer(exchange)
    
def getOptimizedPositions():
    """Get cached positions - reduces API calls significantly"""
    if apiOptimizer:
        return apiOptimizer.getPositionsCached()
    return None

def getOptimizedBalance():
    """Get cached balance - reduces API calls significantly"""
    if apiOptimizer:
        return apiOptimizer.getBalanceCached()
    return None
    if apiOptimizer:
        return apiOptimizer.getTickerCached(symbol)
    return None
