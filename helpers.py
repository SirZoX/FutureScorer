
import requests
import json
import gvars
from logManager import messages
from config_manager import config_manager
from logger import log_error, log_debug




# Offset para no procesar dos veces el mismo update
update_offset = None

def checkTelegram():
    '''
    Cada vez que se llame:
    1) Hace un getUpdates con el offset actual
    2) Por cada mensaje nuevo, si el texto es "ping", responde "pong!"
    3) Actualiza update_offset para no volver a leerlos
    '''
    global update_offset
    
    token   = config_manager.get('telegramToken')
    chat_id = config_manager.get('telegramChatId')
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
            if str(msg.get('chat', {}).get('id')) == str(chat_id) and text == 'ping':
                messages("pong!", console=0, log=0, telegram=1)
    except Exception as e:
        log_error("Error at checkTelegram", error=str(e))
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