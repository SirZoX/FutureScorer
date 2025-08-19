def auto_refill_bnb(exchange, usdc_symbol="USDC", bnb_symbol="BNB/USDC", min_usdc=1, refill_usdc=10):
    """
    Checks BNB balance (converted to USDC). If less than min_usdc, buys refill_usdc in BNB using ccxt.
    Logs all actions and errors.
    """
    try:
        bal = exchange.fetch_balance()
        bnb = bal.get('BNB', {})
        bnb_amt = float(bnb.get('free', 0) or 0)
        # Get BNB/USDC price
        ticker = exchange.fetch_ticker(bnb_symbol)
        price = float(ticker.get('last') or ticker.get('close') or 0)
        bnb_usdc = bnb_amt * price
        if bnb_usdc >= min_usdc:
            messages(f"[BNB REFILL] Suficiente BNB para fees: {bnb_amt:.6f} BNB ({bnb_usdc:.4f} USDC)", console=0, log=1, telegram=0, pair=bnb_symbol)
            return False
        # Calcular cantidad de BNB a comprar
        qty = refill_usdc / price if price else 0
        # Comprar BNB
        order = exchange.create_market_buy_order(bnb_symbol, qty)
        messages(f"[BNB REFILL] Comprados {qty:.6f} BNB (aprox {refill_usdc} USDC) para fees", console=1, log=1, telegram=1, pair=bnb_symbol)
        return True
    except Exception as e:
        messages(f"[BNB REFILL] Error al comprobar o comprar BNB: {e}", console=1, log=1, telegram=1, pair=bnb_symbol)
        return False

import requests
import json
import gvars
from logManager import messages




with open(gvars.configFile, encoding='utf-8') as f:
    configData = json.load(f)



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
    
    token   = configData['telegramToken']
    chat_id = configData['telegramChatId']
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