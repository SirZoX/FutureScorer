def manageDynamicTpSl():
    """
    Monitors all open positions and manages dynamic TP/SL logic:
    - If price reaches 75% of the way to TP1, cancels current OCO and places new OCO with TP2.
    - Updates explicit fields in openedPositions.json (tp1, tp2, sl1, tpOrderId1, tpOrderId2, etc.).
    - Logs all relevant events and errors. Sends Telegram alert if OCO cannot be placed.
    """
    import ccxt
    from connector import bingxConnector
    from logManager import messages
    from gvars import positionsFile, configFile
    try:
        with open(positionsFile, encoding='utf-8') as f:
            positions = json.load(f)
    except Exception as e:
        messages(f"[DYN-TP/SL] Error loading positions: {e}", console=1, log=1, telegram=1)
        return
    from connector import loadConfig
    try:
        config = loadConfig()
    except Exception as e:
        messages(f"[DYN-TP/SL] Error loading config: {e}", console=1, log=1, telegram=1)
        return
    exchange = bingxConnector()
    for symbol, pos in positions.items():
        try:
            openPrice = float(pos.get('openPrice', 0))
            tp1 = float(pos.get('tp1', 0))
            tp2 = float(config.get('tp2', 0))
            sl1 = float(pos.get('sl1', 0))
            tpOrderId1 = pos.get('tpOrderId1')
            slOrderId1 = pos.get('slOrderId1')
            tpOrderId2 = pos.get('tpOrderId2')
            slOrderId2 = pos.get('slOrderId2')
            # Fetch current price
            ticker = exchange.fetch_ticker(symbol)
            currentPrice = float(ticker.get('last') or ticker.get('close') or 0)
            # Calculate progress to TP1
            if tp1 == openPrice:
                continue
            progress = (currentPrice - openPrice) / (tp1 - openPrice) if tp1 != openPrice else 0
            # If already at TP2, skip
            if tpOrderId2:
                continue
            # If price >= 75% to TP1 and TP2 not set, update OCO
            if progress >= 0.75 and not tpOrderId2:
                # Cancel current OCO
                try:
                    if tpOrderId1:
                        exchange.cancel_order(tpOrderId1, symbol)
                    if slOrderId1:
                        exchange.cancel_order(slOrderId1, symbol)
                    messages(f"[DYN-TP/SL] Cancelled OCO for {symbol} at 75% to TP1", console=1, log=1, telegram=0)
                except Exception as e:
                    messages(f"[DYN-TP/SL] Error cancelling OCO for {symbol}: {e}", console=1, log=1, telegram=1)
                    continue
                # Place new OCO with TP2
                amount = float(pos.get('amount', 0))
                sl2 = sl1  # For now, keep SL2 same as SL1
                try:
                    # Calculate tickSize if needed (not implemented here)
                    order = exchange.create_order(symbol, 'OCO', 'sell', amount, tp2, {'stopPrice': sl2})
                    tpOrderId2 = order.get('id')
                    slOrderId2 = order.get('params', {}).get('stopOrderId')
                    pos['tp2'] = tp2
                    pos['sl2'] = sl2
                    pos['tpOrderId2'] = tpOrderId2
                    pos['slOrderId2'] = slOrderId2
                    messages(f"[DYN-TP/SL] Nueva OCO TP2 para {symbol}: TP2={tp2}, SL2={sl2}", console=1, log=1, telegram=1)
                except Exception as e:
                    messages(f"[DYN-TP/SL] Error placing OCO TP2 for {symbol}: {e}", console=1, log=1, telegram=1)
                    continue
        except Exception as e:
            messages(f"[DYN-TP/SL] Error in dynamic TP/SL for {symbol}: {e}", console=1, log=1, telegram=1)
    # Save updated positions
    try:
        with open(positionsFile, 'w', encoding='utf-8') as f:
            json.dump(positions, f, indent=2, default=str)
    except Exception as e:
        messages(f"[DYN-TP/SL] Error saving updated positions: {e}", console=1, log=1, telegram=1)

def syncOpenedPositions():
    """
    Syncs openedPositions.json with actual open positions in BingX.
    Removes from the file any position that is not open in the exchange.
    """
    from connector import bingxConnector
    from gvars import positionsFile
    from logManager import messages
    import time
    try:
        with open(positionsFile, encoding='utf-8') as f:
            positions = json.load(f)
    except Exception as e:
        messages(f"[SYNC] Error loading positions: {e}", console=1, log=1, telegram=1)
        return
    exchange = bingxConnector()
    toRemove = []
    for symbol in list(positions.keys()):
        normSymbol = symbol.replace(':USDT', '') if symbol.endswith(':USDT') else symbol
        try:
            # Llama a fetch_positions solo para el símbolo concreto
            posList = exchange.fetch_positions([normSymbol])
            # Si no hay posición abierta para ese símbolo, lo eliminamos
            if not posList or all(p.get('contracts', 0) == 0 for p in posList):
                messages(f"[SYNC] Eliminando posición cerrada: {symbol}", console=1, log=1, telegram=0)
                toRemove.append(symbol)
            # Espera breve para evitar rate limit
            time.sleep(0.5)
        except Exception as e:
            messages(f"[SYNC] Error consultando {symbol}: {e}", console=1, log=1, telegram=1)
            continue
    if toRemove:
        for symbol in toRemove:
            positions.pop(symbol)
        with open(positionsFile, 'w', encoding='utf-8') as f:
            json.dump(positions, f, indent=2, default=str)
    else:
        messages("[SYNC] Todas las posiciones del fichero están abiertas en BingX", console=1, log=1, telegram=0)

import json
import time
from datetime import datetime, timedelta
import os
import sys
import threading

# Global event to control monitor execution
monitorActive = threading.Event()
monitorActive.set()  # Start enabled by default

def colorText(text, color):
    """
    Returns text colored for console output (red/green)
    """
    colors = {
        'red': '\033[91m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'orange': '\033[38;5;208m',
        'reset': '\033[0m'
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"

def fmtNum(num, maxInt=5, maxDec=6):
    """
    Formats a number with up to maxInt integer digits and exactly maxDec decimals, padding with zeros if needed
    """
    if isinstance(num, int):
        return f"{num:>{maxInt}}.{'0'*maxDec}"
    s = f"{num:.{maxDec}f}"
    parts = s.split('.')
    if len(parts[0]) > maxInt:
        parts[0] = parts[0][-maxInt:]
    # Pad decimals to maxDec
    if len(parts) == 2:
        parts[1] = parts[1].ljust(maxDec, '0')
        return f"{parts[0]}.{parts[1]}"
    else:
        return f"{parts[0]}.{'0'*maxDec}"

def fmtSymbol(symbol):
    return symbol.ljust(25)[:25]

def fmtTimeDelta(seconds):
    td = timedelta(seconds=seconds)
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}"

def getCurrentPrices(symbols):
    # Dummy prices for now, replace with real fetch if needed
    # Return dict {symbol: price}
    return {s: None for s in symbols}

def printPositionsTable():
    import ccxt
    path = os.path.join(os.path.dirname(__file__), '_files', 'config', 'openedPositions.json')
    if not os.path.isfile(path):
        print("No openedPositions.json found.")
        return
    with open(path, encoding='utf-8') as f:
        positions = json.load(f)
    if not positions:
        return
    now = int(time.time())
    symbols = [pos.get('symbol', '') for pos in positions.values()]
    # Fetch tickers in parallel (max 10 threads)
    import concurrent.futures
    try:
        exchange = ccxt.binance()
        def fetchTicker(symbol):
            try:
                return symbol, exchange.fetch_ticker(symbol)
            except Exception:
                return symbol, {}
        tickers = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(fetchTicker, symbols)
            for symbol, ticker in results:
                tickers[symbol] = ticker
    except Exception:
        tickers = {}
    header = f"{'Hora':19} | {'Par':25} | {'TP':>4} {'SL':>5} | {'%':>8} | {'Inversión':>14} | {'Entrada':>10} | {'TP':>10} | {'SL':>10} | {'Abierta':>12}"
    print()
    print('-'*len(header))
    print(header)
    print('-'*len(header))
    for pos in positions.values():
        symbol = fmtSymbol(pos.get('symbol', ''))
        openPrice = float(pos.get('openPrice', 0))
        amount = float(pos.get('amount', 0))
        # Use the latest TP/SL if present, else fallback to tp1/sl1
        tpPrice = (
            float(pos.get('tp2')) if pos.get('tp2') not in (None, 0, '', 'null') else
            float(pos.get('tp1', 0))
        )
        slPrice = (
            float(pos.get('sl2')) if pos.get('sl2') not in (None, 0, '', 'null') else
            float(pos.get('sl1', 0))
        )
        invest = openPrice * amount
        investStr = fmtNum(invest, 6, 6)
        openPriceStr = fmtNum(openPrice, 6, 6)
        tpPriceStr = fmtNum(tpPrice, 6, 6)
        slPriceStr = fmtNum(slPrice, 6, 6)
        entryTs = int(pos.get('open_ts_unix', now))
        delta = now - entryTs
        deltaStr = fmtTimeDelta(delta)
        # Get TP/SL percent from JSON (show the latest if present)
        tpPercent = (
            float(pos.get('tpPercent2')) if pos.get('tpPercent2') not in (None, 0, '', 'null') else
            float(pos.get('tpPercent', None))
        )
        slPercent = (
            float(pos.get('slPercent2')) if pos.get('slPercent2') not in (None, 0, '', 'null') else
            float(pos.get('slPercent', None))
        )
        tpPercentStr = colorText(fmtNum(tpPercent, 2, 2) if tpPercent is not None else '--', 'green')
        slPercentStr = colorText(fmtNum(slPercent, 2, 2) if slPercent is not None else '--', 'red')
        # Get current price from ticker
        ticker = tickers.get(pos.get('symbol', ''), {})
        currentPrice = ticker.get('last', openPrice)
        pct = ((currentPrice - openPrice) / openPrice) * 100 if openPrice else 0
        pctStr = fmtNum(pct, 3, 2)
        # Ajusta espacios para cuadrar la columna % y alinear el símbolo
        if pct >= 0:
            pctStr = f" {pctStr} %"
        else:
            pctStr = f"{pctStr} %"
        # Color logic for profit-loss percentage
        if pct >= 0:
            pctColor = 'green'
        else:
            slValid = slPercent is not None and abs(float(slPercent)) > 0
            if slValid:
                slAbs = abs(float(slPercent))
                pctAbs = abs(pct)
                ratio = pctAbs / slAbs
                if ratio <= 0.33:
                    pctColor = 'yellow'
                elif ratio <= 0.66:
                    pctColor = 'orange'
                else:
                    pctColor = 'red'
            else:
                pctColor = 'red'
        hora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"{hora:19} | {symbol} | {tpPercentStr:>5} {slPercentStr:>5} | {colorText(pctStr, pctColor):>10} | {investStr:>14} | {openPriceStr:>10} | {tpPriceStr:>10} | {slPriceStr:>10} | {deltaStr:>12}")

def monitorPositions():
    while True:
        monitorActive.wait()  # Wait until monitor is enabled
        printPositionsTable()
        try:
            manageDynamicTpSl()
        except Exception as e:
            from logManager import messages
            messages(f"[DYN-TP/SL] Error en manageDynamicTpSl: {e}", console=1, log=1, telegram=1)
        time.sleep(10)
if __name__ == '__main__':
    monitorPositions()
