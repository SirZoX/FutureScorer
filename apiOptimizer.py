"""
ARCHIVO SIMPLIFICADO - Se eliminó el sistema de caché para mayor simplicidad
Ahora todas las llamadas van directamente al exchange sin caché intermedio
"""

from connector import bingxConnector
from logManager import messages
import time

class ApiOptimizer:
    def __init__(self, exchange):
        self.exchange = exchange
    
    def getTicker(self, symbol):
        """Get real-time ticker - Direct call to exchange"""
        return self.exchange.fetch_ticker(symbol)
    
    def getPositions(self):
        """Get positions - Direct call to exchange"""
        return self.exchange.fetch_positions()
    
    def getBalance(self):
        """Get balance - Direct call to exchange"""
        return self.exchange.fetch_balance()
    
    def getMarkets(self):
        """Get markets - Direct call to exchange"""
        return self.exchange.load_markets()

# Global instance
apiOptimizer = None

def initializeApiOptimizer(exchange):
    global apiOptimizer
    apiOptimizer = ApiOptimizer(exchange)
    
def getOptimizedPositions():
    """Get positions - Direct call without caching"""
    if apiOptimizer:
        return apiOptimizer.getPositions()
    return None

def getOptimizedBalance():
    """Get balance - Direct call without caching"""
    if apiOptimizer:
        return apiOptimizer.getBalance()
    return None
