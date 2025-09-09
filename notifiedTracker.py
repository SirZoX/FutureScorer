"""
Tracker para posiciones ya notificadas para evitar duplicados
Mantiene un registro persistente de posiciones que ya fueron cerradas y notificadas
"""

import json
import time
from datetime import datetime, timedelta
from logManager import messages
from gvars import jsonFolder
import os

# Path to the notified positions file
notifiedPositionsFile = f"{jsonFolder}/notifiedPositions.json"

def loadNotifiedPositions():
    """
    Carga el registro de posiciones ya notificadas
    """
    try:
        if os.path.exists(notifiedPositionsFile):
            with open(notifiedPositionsFile, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Ensure it's a dict format
                if isinstance(data, dict):
                    return data
                else:
                    # Convert old format to new if needed
                    return {}
        else:
            return {}
    except Exception as e:
        messages(f"[ERROR] Failed to load notified positions: {e}", console=1, log=1, telegram=0)
        return {}

def saveNotifiedPositions(notifiedData):
    """
    Guarda el registro de posiciones notificadas
    """
    try:
        with open(notifiedPositionsFile, 'w', encoding='utf-8') as f:
            json.dump(notifiedData, f, indent=2)
    except Exception as e:
        messages(f"[ERROR] Failed to save notified positions: {e}", console=1, log=1, telegram=0)

def markPositionAsNotified(symbol, openPrice, openTimestamp, profitUsdt=None):
    """
    Marca una posición como ya notificada
    
    Args:
        symbol: El símbolo de la posición
        openPrice: Precio de apertura para identificar únicamente la posición
        openTimestamp: Timestamp de apertura (unix)
        profitUsdt: Profit de la posición (opcional)
    """
    try:
        notifiedData = loadNotifiedPositions()
        
        # Create unique key for this position
        positionKey = f"{symbol}_{openPrice}_{openTimestamp}"
        
        notifiedData[positionKey] = {
            'symbol': symbol,
            'openPrice': openPrice,
            'openTimestamp': openTimestamp,
            'notifiedAt': time.time(),
            'notifiedDate': datetime.now().isoformat(),
            'profitUsdt': profitUsdt
        }
        
        saveNotifiedPositions(notifiedData)
        messages(f"[TRACKER] Marked position {symbol} as notified (key: {positionKey})", console=0, log=1, telegram=0)
        
    except Exception as e:
        messages(f"[ERROR] Failed to mark position {symbol} as notified: {e}", console=1, log=1, telegram=0)

def isPositionAlreadyNotified(symbol, openPrice, openTimestamp):
    """
    Verifica si una posición ya fue notificada
    
    Args:
        symbol: El símbolo de la posición
        openPrice: Precio de apertura
        openTimestamp: Timestamp de apertura (unix)
        
    Returns:
        bool: True si ya fue notificada, False si no
    """
    try:
        notifiedData = loadNotifiedPositions()
        
        # Create unique key for this position
        positionKey = f"{symbol}_{openPrice}_{openTimestamp}"
        
        isNotified = positionKey in notifiedData
        
        if isNotified:
            notifiedInfo = notifiedData[positionKey]
            messages(f"[TRACKER] Position {symbol} already notified on {notifiedInfo.get('notifiedDate', 'unknown date')}", console=0, log=1, telegram=0)
        
        return isNotified
        
    except Exception as e:
        messages(f"[ERROR] Failed to check if position {symbol} was notified: {e}", console=1, log=1, telegram=0)
        return False

def cleanOldNotifiedPositions(maxAgeHours=168):  # 7 days by default
    """
    Limpia posiciones notificadas que son muy antiguas para evitar que el archivo crezca indefinidamente
    
    Args:
        maxAgeHours: Máximo tiempo en horas que se mantienen los registros
    """
    try:
        notifiedData = loadNotifiedPositions()
        
        if not notifiedData:
            return
        
        currentTime = time.time()
        cutoffTime = currentTime - (maxAgeHours * 3600)
        
        # Filter out old entries
        originalCount = len(notifiedData)
        notifiedData = {
            key: value for key, value in notifiedData.items()
            if value.get('notifiedAt', 0) > cutoffTime
        }
        
        cleanedCount = originalCount - len(notifiedData)
        
        if cleanedCount > 0:
            saveNotifiedPositions(notifiedData)
            messages(f"[TRACKER] Cleaned {cleanedCount} old notified position records (older than {maxAgeHours}h)", console=0, log=1, telegram=0)
        
    except Exception as e:
        messages(f"[ERROR] Failed to clean old notified positions: {e}", console=1, log=1, telegram=0)

def getNotifiedPositionsStats():
    """
    Obtiene estadísticas del tracker
    """
    try:
        notifiedData = loadNotifiedPositions()
        
        if not notifiedData:
            return {"total": 0, "recent": 0}
        
        total = len(notifiedData)
        
        # Count recent (last 24 hours)
        currentTime = time.time()
        cutoffTime = currentTime - (24 * 3600)
        recent = sum(1 for value in notifiedData.values() if value.get('notifiedAt', 0) > cutoffTime)
        
        return {"total": total, "recent": recent}
        
    except Exception as e:
        messages(f"[ERROR] Failed to get notified positions stats: {e}", console=1, log=1, telegram=0)
        return {"total": 0, "recent": 0}
