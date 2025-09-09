"""
Script de inicialización para marcar posiciones existentes como ya procesadas
Esto evita que se sigan reconstruyendo posiciones que están abiertas
"""

from notifiedTracker import markPositionAsNotified
from logManager import messages
import time

def initializeExistingPositions():
    """
    Marca las posiciones actualmente abiertas como ya procesadas para evitar reconstrucciones infinitas
    """
    # Posiciones que están causando problemas de reconstrucción constante
    existingPositions = [
        {
            'symbol': 'DOGE/USDT:USDT',
            'openPrice': 0.23671,  # Precio de reconstrucción mostrado en logs
            'openTimestamp': int(time.time() - 3600)  # Aproximadamente 1 hora atrás
        },
        {
            'symbol': 'TRUMP/USDT:USDT', 
            'openPrice': 8.302,  # Precio de reconstrucción mostrado en logs
            'openTimestamp': int(time.time() - 3600)  # Aproximadamente 1 hora atrás
        }
    ]
    
    messages("[INIT] Marking existing positions to prevent reconstruction loops", console=1, log=1, telegram=0)
    
    for position in existingPositions:
        # Marcar como ya notificada (aunque no se haya cerrado) para evitar reconstrucciones
        markPositionAsNotified(
            position['symbol'], 
            position['openPrice'], 
            position['openTimestamp'], 
            profitUsdt=0  # No se ha cerrado, profit 0
        )
        messages(f"[INIT] Marked {position['symbol']} as processed to prevent reconstruction", console=1, log=1, telegram=0)
    
    messages("[INIT] Initialization complete", console=1, log=1, telegram=0)

if __name__ == "__main__":
    initializeExistingPositions()
