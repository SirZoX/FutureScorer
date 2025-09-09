"""
ARCHIVO OBSOLETO - Ya no se utiliza tras la simplificación del sistema
El nuevo sistema no requiere inicialización de trackers ya que todo se maneja con el campo 'status' en el JSON
"""

from logManager import messages

def initializeExistingPositions():
    """
    FUNCIÓN OBSOLETA - Ya no es necesaria
    El nuevo sistema gestiona automáticamente el estado de las posiciones usando el campo 'status'
    """
    messages("[INIT] Este archivo ya no es necesario tras la simplificación del sistema", console=1, log=1, telegram=0)
    messages("[INIT] El estado de posiciones se maneja automáticamente con el campo 'status' en el JSON", console=1, log=1, telegram=0)

if __name__ == "__main__":
    initializeExistingPositions()
