
import requests
import json
import time
import gvars
from logManager import messages
from configManager import configManager
from logManager import messages # log_error, log_debug

# Global reference to orderManager for telegram commands
_orderManager = None

def setOrderManagerReference(om):
    """Set global reference to orderManager for telegram commands"""
    global _orderManager
    _orderManager = om

# Offset para no procesar dos veces el mismo update
update_offset = None

def checkTelegram():
    '''
    Cada vez que se llame:
    1) Hace un getUpdates con el offset actual
    2) Por cada mensaje nuevo, procesa comandos disponibles
    3) Actualiza update_offset para no volver a leerlos
    
    Comandos disponibles:
    - ping: responde "pong!"
    - positions: muestra resumen de posiciones abiertas
    '''
    global update_offset
    
    token   = configManager.get('telegramToken')
    chat_id = configManager.get('telegramChatId')
    url     = f"https://api.telegram.org/bot{token}/getUpdates"
    params  = {'timeout': 0}
    if update_offset is not None:
        params['offset'] = update_offset

    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        for upd in data.get('result', []):
            # avanzamos offset
            update_offset = upd['update_id'] + 1
            msg = upd.get('message', {})
            text = msg.get('text', '').strip().lower()
            # solo respondemos si viene de nuestro chat
            if str(msg.get('chat', {}).get('id')) == str(chat_id):
                if text == 'ping':
                    messages("pong!", console=0, log=0, telegram=1)
                elif text == 'positions':
                    try:
                        if _orderManager:
                            positions = _orderManager.loadPositions()
                            if positions:
                                openCount = sum(1 for pos in positions.values() if pos.get('status', 'open') == 'open')
                                closedCount = sum(1 for pos in positions.values() if pos.get('status') == 'closed')
                                msg = f"📊 Positions Summary:\n• Open: {openCount}\n• Closed (pending cleanup): {closedCount}\n• Total: {len(positions)}"
                                messages(msg, console=0, log=0, telegram=1)
                            else:
                                messages("✅ No positions found", console=0, log=0, telegram=1)
                        else:
                            messages("❌ OrderManager not available", console=0, log=0, telegram=1)
                    except Exception as e:
                        messages(f"❌ Position summary failed: {e}", console=0, log=0, telegram=1)
    except requests.exceptions.ReadTimeout as e:
        messages(f"Telegram read timeout detected - pausing bot for 15 seconds: {e}", console=1, log=1, telegram=0)
        time.sleep(15)  # Pause the entire script for 15 seconds
        messages("Resuming bot operations after Telegram timeout pause", console=1, log=1, telegram=0)
    except requests.exceptions.Timeout as e:
        messages(f"Telegram timeout detected - pausing bot for 15 seconds: {e}", console=1, log=1, telegram=0)
        time.sleep(15)  # Pause the entire script for 15 seconds
        messages("Resuming bot operations after Telegram timeout pause", console=1, log=1, telegram=0)
    except Exception as e:
        # Check if the error message contains timeout indicators
        error_str = str(e).lower()
        if ('read timed out' in error_str or 
            'timeout' in error_str or 
            'readtimeout' in error_str):
            messages(f"Telegram timeout error detected - pausing bot for 15 seconds: {e}", console=1, log=1, telegram=0)
            time.sleep(15)  # Pause the entire script for 15 seconds
            messages("Resuming bot operations after Telegram timeout pause", console=1, log=1, telegram=0)
        else:
            messages(f"Error at checkTelegram: {e}", console=1, log=1, telegram=0)
    






def fmt(num, dec=6):
    """
    Formatea un número con `dec` decimales,
    usa coma como separador decimal y no pone miles.
    """
    s = f"{num:.{dec}f}"
    return s.replace('.', ',')






def formatNum(val):
    return f"{val:.0f}" if val == int(val) else f"{val:.3f}"
