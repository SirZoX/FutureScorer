import json
import time
from datetime import datetime, timedelta
import os
import sys
import threading
import re

# Global variables for rate limiting
lastApiCall = 0
apiCallInterval = 1.0  # Minimum 1 second between API calls
rateLimitBackoff = 60  # Start with 60 seconds backoff when rate limited

def checkRateLimit(errorMsg):
    """
    Check if error is rate limit related and extract backoff time
    Returns (isRateLimit, backoffTime)
    """
    if not errorMsg:
        return False, 0
    
    # Check for BingX rate limit error code
    if "100410" in str(errorMsg) or "frequency limit" in str(errorMsg).lower():
        # Try to extract unblock timestamp from error message
        match = re.search(r'unblocked after (\d+)', str(errorMsg))
        if match:
            unblockTimestamp = int(match.group(1)) / 1000  # Convert to seconds
            currentTimestamp = time.time()
            backoffTime = max(unblockTimestamp - currentTimestamp, 30)  # At least 30 seconds
            return True, min(backoffTime, 300)  # Cap at 5 minutes
        return True, rateLimitBackoff
    
    return False, 0

def safeApiCall(func, *args, **kwargs):
    """
    Execute API call with rate limiting and error handling
    """
    global lastApiCall, rateLimitBackoff
    
    # Ensure minimum time between API calls
    now = time.time()
    elapsed = now - lastApiCall
    if elapsed < apiCallInterval:
        time.sleep(apiCallInterval - elapsed)
    
    try:
        result = func(*args, **kwargs)
        lastApiCall = time.time()
        # Reset backoff on successful call
        rateLimitBackoff = 60
        return result, None
    except Exception as e:
        lastApiCall = time.time()
        isRateLimit, backoffTime = checkRateLimit(str(e))
        if isRateLimit:
            rateLimitBackoff = backoffTime
            return None, f"Rate limit hit, backing off for {int(backoffTime)}s"
        return None, str(e)

def manageDynamicTpSl():
    """
    Monitors all open positions and manages dynamic TP/SL logic:
    - If price reaches 75% of the way to TP1, cancels current OCO and places new OCO with TP2.
    - Updates explicit fields in openedPositions.json (tp1, tp2, sl1, tpOrderId1, tpOrderId2, etc.).
    - Logs all relevant events and errors. Sends Telegram alert if OCO cannot be placed.
    """
    import ccxt
    from connector import bingxConnector
    from configManager import configManager
    from logManager import messages # log_info, log_error
    from logManager import messages  # Para mantener compatibilidad temporal
    from gvars import positionsFile, configFile
    
    global rateLimitBackoff
    
    # Check if we're in a rate limit backoff period
    if rateLimitBackoff > 60:
        return  # Skip this cycle if we're heavily rate limited
    
    try:
        with open(positionsFile, encoding='utf-8') as f:
            positions = json.load(f)
    except Exception as e:
        messages(f"[DYN-TP/SL] Error loading positions: {e}", console=1, log=1, telegram=1)
        return
    try:
        config = configManager.config
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
            
            # Fetch current price with rate limiting
            ticker, error = safeApiCall(exchange.fetch_ticker, symbol)
            if error:
                if "Rate limit" in error:
                    messages(f"[DYN-TP/SL] Rate limit for {symbol}, skipping this cycle", console=0, log=1, telegram=0)
                    return  # Exit function to avoid more rate limit errors
                else:
                    messages(f"[DYN-TP/SL] Error fetching ticker for {symbol}: {error}", console=0, log=1, telegram=0)
                continue
                
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
                        _, error = safeApiCall(exchange.cancel_order, tpOrderId1, symbol)
                        if error and "Rate limit" in error:
                            messages(f"[DYN-TP/SL] Rate limit hit while cancelling TP order for {symbol}, skipping", console=0, log=1, telegram=0)
                            return
                    if slOrderId1:
                        _, error = safeApiCall(exchange.cancel_order, slOrderId1, symbol)
                        if error and "Rate limit" in error:
                            messages(f"[DYN-TP/SL] Rate limit hit while cancelling SL order for {symbol}, skipping", console=0, log=1, telegram=0)
                            return
                    messages(f"[DYN-TP/SL] Cancelled OCO for {symbol} at 75% to TP1", console=1, log=1, telegram=0)
                except Exception as e:
                    isRateLimit, _ = checkRateLimit(str(e))
                    if isRateLimit:
                        messages(f"[DYN-TP/SL] Rate limit while cancelling OCO for {symbol}, skipping", console=0, log=1, telegram=0)
                        return
                    else:
                        messages(f"[DYN-TP/SL] Error cancelling OCO for {symbol}: {e}", console=0, log=1, telegram=0)
                    continue
                # Place new OCO with TP2
                amount = float(pos.get('amount', 0))
                sl2 = sl1  # For now, keep SL2 same as SL1
                try:
                    # Calculate tickSize if needed (not implemented here)
                    order, error = safeApiCall(exchange.create_order, symbol, 'OCO', 'sell', amount, tp2, {'stopPrice': sl2})
                    if error:
                        if "Rate limit" in error:
                            messages(f"[DYN-TP/SL] Rate limit while placing OCO TP2 for {symbol}, skipping", console=0, log=1, telegram=0)
                            return
                        else:
                            messages(f"[DYN-TP/SL] Error placing OCO TP2 for {symbol}: {error}", console=0, log=1, telegram=0)
                        continue
                    tpOrderId2 = order.get('id')
                    slOrderId2 = order.get('params', {}).get('stopOrderId')
                    pos['tp2'] = tp2
                    pos['sl2'] = sl2
                    pos['tpOrderId2'] = tpOrderId2
                    pos['slOrderId2'] = slOrderId2
                    messages(f"[DYN-TP/SL] Nueva OCO TP2 para {symbol}: TP2={tp2}, SL2={sl2}", console=1, log=1, telegram=1)
                except Exception as e:
                    isRateLimit, _ = checkRateLimit(str(e))
                    if isRateLimit:
                        messages(f"[DYN-TP/SL] Rate limit while placing OCO TP2 for {symbol}, skipping", console=0, log=1, telegram=0)
                        return
                    else:
                        messages(f"[DYN-TP/SL] Error placing OCO TP2 for {symbol}: {e}", console=0, log=1, telegram=0)
                    continue
        except Exception as e:
            isRateLimit, _ = checkRateLimit(str(e))
            if isRateLimit:
                messages(f"[DYN-TP/SL] Rate limit hit for {symbol}, stopping dynamic TP/SL for this cycle", console=0, log=1, telegram=0)
                return  # Exit completely to avoid more rate limit errors
            else:
                messages(f"[DYN-TP/SL] Error in dynamic TP/SL for {symbol}: {e}", console=0, log=1, telegram=0)
    # Save updated positions
    try:
        with open(positionsFile, 'w', encoding='utf-8') as f:
            json.dump(positions, f, indent=2, default=str)
    except Exception as e:
        messages(f"[DYN-TP/SL] Error saving updated positions: {e}", console=1, log=1, telegram=1)

def syncOpenedPositions():
    """
    Sync opened positions removing closed positions and sending results via Telegram
    """
    from orderManager import OrderManager
    from logManager import messages
    from gvars import positionsFile
    
    try:
        # Check if there are positions to process
        try:
            with open(positionsFile, encoding='utf-8') as f:
                positions = json.load(f)
        except Exception:
            positions = {}
        
        if not positions:
            # No positions to sync, but don't return - let the monitor continue
            messages("[SYNC] No positions to synchronize", console=0, log=1, telegram=0)
            return
            
        # Use OrderManager.updatePositions() which handles closing positions and Telegram notifications
        om = OrderManager()
        om.updatePositions()
        messages("[SYNC] Position synchronization completed", console=0, log=1, telegram=0)
    except Exception as e:
        messages(f"[SYNC] Error during position synchronization: {e}", console=1, log=1, telegram=1)

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
    return symbol.ljust(20)[:20]  # Reduced from 25 to 20 for better fit

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
    from connector import bingxConnector
    from gvars import positionsFile
    
    if not os.path.isfile(positionsFile):
        print("No openedPositions.json found.")
        return
    with open(positionsFile, encoding='utf-8') as f:
        positions = json.load(f)
    if not positions:
        return
    now = int(time.time())
    symbols = [pos.get('symbol', '') for pos in positions.values()]
    
    global rateLimitBackoff
    
    # Check if we're in heavy rate limit backoff
    if rateLimitBackoff > 120:  # If backoff is more than 2 minutes, use cached prices
        tickers = {}
    else:
        # Fetch tickers with rate limiting (no parallel execution to avoid rate limits)
        try:
            exchange = bingxConnector()
            tickers = {}
            for symbol in symbols:
                ticker, error = safeApiCall(exchange.fetch_ticker, symbol)
                if error:
                    if "Rate limit" in error:
                        # If we hit rate limit, stop fetching more tickers and use open price
                        break
                    tickers[symbol] = {}
                else:
                    tickers[symbol] = ticker
                # Small delay between ticker requests
                time.sleep(0.2)
        except Exception:
            tickers = {}
    # Updated header with Long/Short column and properly aligned
    header = f"{'Hora':19} | {'Par':20} | {'L/S':4} | {'TP%':5} | {'SL%':5} | {'P/L%':9} | {'Inversión':12} | {'Entrada':10} | {'TP':10} | {'SL':10} | {'Abierta':12}"
    print()
    print('-'*len(header))
    print(header)
    print('-'*len(header))
    for pos in positions.values():
        symbol = fmtSymbol(pos.get('symbol', ''))
        
        # Get position side (default to LONG if not specified)
        side = pos.get('side', 'LONG')
        sideStr = 'L' if side.upper() == 'LONG' else 'S'
        
        openPrice = float(pos.get('openPrice', 0))
        amount = float(pos.get('amount', 0))
        # Use the latest TP/SL if present, else fallback to tpPrice/slPrice
        tpPrice = (
            float(pos.get('tp2')) if pos.get('tp2') not in (None, 0, '', 'null') else
            float(pos.get('tpPrice', 0))
        )
        slPrice = (
            float(pos.get('sl2')) if pos.get('sl2') not in (None, 0, '', 'null') else
            float(pos.get('slPrice', 0))
        )
        invest = openPrice * amount
        investStr = fmtNum(invest, 5, 4)  # Adjusted for better fit
        openPriceStr = fmtNum(openPrice, 5, 5)
        tpPriceStr = fmtNum(tpPrice, 5, 5)
        slPriceStr = fmtNum(slPrice, 5, 5)
        entryTs = int(pos.get('open_ts_unix', now))
        delta = now - entryTs
        deltaStr = fmtTimeDelta(delta)
        # Get TP/SL percent from JSON (show the latest if present)
        tpPercent = (
            float(pos.get('tpPercent2')) if pos.get('tpPercent2') not in (None, 0, '', 'null') else
            float(pos.get('tpPercent', 0))
        )
        slPercent = (
            float(pos.get('slPercent2')) if pos.get('slPercent2') not in (None, 0, '', 'null') else
            float(pos.get('slPercent', 0))
        )
        tpPercentStr = colorText(f"{tpPercent:4.1f}" if tpPercent is not None else ' --', 'green')
        slPercentStr = colorText(f"{slPercent:4.1f}" if slPercent is not None else ' --', 'red')
        # Get current price from ticker
        ticker = tickers.get(pos.get('symbol', ''), {})
        currentPrice = ticker.get('last', openPrice)
        pct = ((currentPrice - openPrice) / openPrice) * 100 if openPrice else 0
        pctStr = f"{pct:+6.2f}%"  # Always show sign (+/-) for consistent width
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
        print(f"{hora:19} | {symbol:20} | {sideStr:4} | {tpPercentStr:>5} | {slPercentStr:>5} | {colorText(pctStr, pctColor):>9} | {investStr:>12} | {openPriceStr:>10} | {tpPriceStr:>10} | {slPriceStr:>10} | {deltaStr:>12}")

def monitorPositions():
    from logManager import messages
    global rateLimitBackoff
    
    while True:
        monitorActive.wait()  # Wait until monitor is enabled
        
        # Dynamic sleep based on rate limit status
        if rateLimitBackoff > 120:
            sleepTime = 60  # Sleep 1 minute if heavily rate limited
            messages(f"[MONITOR] Rate limited, using {sleepTime}s interval (backoff: {int(rateLimitBackoff)}s)", console=0, log=1, telegram=0)
        elif rateLimitBackoff > 60:
            sleepTime = 40  # Sleep 40 seconds if moderately rate limited
        else:
            sleepTime = 20  # Normal 20 second interval (reduced from 10s to save API calls)
            
        try:
            syncOpenedPositions()  # Sincroniza y limpia el fichero antes de mostrar la tabla
        except Exception as e:
            messages(f"[SYNC] Error ejecutando syncOpenedPositions: {e}", console=1, log=1, telegram=1)
        
        printPositionsTable()
        
        try:
            manageDynamicTpSl()
        except Exception as e:
            isRateLimit, backoffTime = checkRateLimit(str(e))
            if isRateLimit:
                messages(f"[DYN-TP/SL] Rate limit detected, backing off for {int(backoffTime)}s", console=0, log=1, telegram=0)
                rateLimitBackoff = backoffTime
            else:
                messages(f"[DYN-TP/SL] Error en manageDynamicTpSl: {e}", console=0, log=1, telegram=0)
        
        # Decay rate limit backoff over time
        if rateLimitBackoff > 60:
            rateLimitBackoff = max(60, rateLimitBackoff * 0.9)
            
        time.sleep(sleepTime)
if __name__ == '__main__':
    monitorPositions()
