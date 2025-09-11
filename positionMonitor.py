import json
import time
from datetime import datetime
import os
import sys
import re
import csv
from gvars import positionsFile, tradesLogFile

# Global variables for rate limiting
lastApiCall = 0
apiCallInterval = 1.0  # Minimum 1 second between API calls
rateLimitBackoff = 60  # Start with 60 seconds backoff when rate limited

def logTradeDirectly(symbol, position, closeReason, netProfitUsdt):
    """
    Log trade directly to trades.csv without creating OrderManager instance
    """
    try:
        # Extract position data
        openDateIso = position.get('timestamp', '')  # Format: "2025-08-26 16-30-59"
        openPrice = float(position.get('openPrice', 0))
        amount = float(position.get('amount', 0))
        leverage = int(position.get('leverage', 10))
        side = position.get('side', 'UNKNOWN')
        
        # Calculate investment (amount * price / leverage)
        investmentUsdt = (amount * openPrice) / leverage
        
        # Format dates
        currentTime = datetime.now()
        
        if openDateIso:
            try:
                openDateObj = datetime.strptime(openDateIso, '%Y-%m-%d %H-%M-%S')
                openDateHuman = openDateObj.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                openDateHuman = openDateIso
                openDateObj = None
        else:
            openDateHuman = "Unknown"
            openDateObj = None
        
        closeDateHuman = currentTime.strftime('%Y-%m-%d %H:%M:%S')
        
        # Calculate elapsed time
        if openDateObj:
            try:
                elapsed = currentTime - openDateObj
                totalSeconds = int(elapsed.total_seconds())
                hours = totalSeconds // 3600
                minutes = (totalSeconds % 3600) // 60
                seconds = totalSeconds % 60
                
                if hours > 0:
                    elapsedHuman = f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    elapsedHuman = f"{minutes}m {seconds}s"
                else:
                    elapsedHuman = f"{seconds}s"
            except Exception:
                elapsedHuman = "Unknown"
        else:
            elapsedHuman = "Unknown"
        
        # Prepare trade record
        tradeRecord = {
            'symbol': symbol,
            'open_date': openDateHuman,
            'close_date': closeDateHuman,
            'elapsed': elapsedHuman,
            'investment_usdt': f"{investmentUsdt:.4f}",
            'leverage': str(leverage),
            'net_profit_usdt': f"{netProfitUsdt:.4f}",
            'side': side
        }
        
        # Check if file exists and has header
        fileExists = os.path.exists(tradesLogFile)
        
        # Append the trade record
        with open(tradesLogFile, 'a', encoding='utf-8', newline='') as f:
            fieldnames = ['symbol', 'open_date', 'close_date', 'elapsed', 'investment_usdt', 'leverage', 'net_profit_usdt', 'side']
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
            
            # Write header if file is new or empty
            if not fileExists or os.path.getsize(tradesLogFile) == 0:
                writer.writeheader()
            
            writer.writerow(tradeRecord)
            
    except Exception as e:
        from logManager import messages
        messages(f"[TRADE-LOG] Error logging trade directly for {symbol}: {e}", console=0, log=1, telegram=0)

def updateSelectionLogWithClose(symbol, position, closeReason, netProfitUsdt, netProfitPct):
    """
    Update selectionLog.csv with closing data for completed positions
    """
    try:
        from datetime import datetime
        import tempfile
        import shutil
        from gvars import selectionLogFile
        
        # Get order IDs to match with the log entry
        tpId = position.get("tpOrderId1", "") or position.get("tpOrderId2", "")
        slId = position.get("slOrderId1", "") or position.get("slOrderId2", "")
        orderId = f"{tpId}-{slId}" if (tpId or slId) else ""
        
        if not orderId or orderId == "-":
            return  # Cannot update without order ID
        
        # Calculate closing data
        openTimestamp = position.get('open_ts_unix', 0)
        closeTimestamp = int(datetime.now().timestamp())
        timeToCloseS = closeTimestamp - openTimestamp if openTimestamp else 0
        closeTimeIso = datetime.now().strftime('%Y-%m-%d %H-%M-%S')
        
        # Read and update the file
        if not os.path.exists(selectionLogFile):
            return
            
        updated = False
        with open(selectionLogFile, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Update the matching line
        for i, line in enumerate(lines):
            if line.startswith(orderId + ";"):
                parts = line.strip().split(';')
                if len(parts) >= 37:  # Ensure we have enough columns (updated count)
                    # Update closing fields (last 5 columns)
                    parts[-5] = f"{netProfitUsdt:.4f}"  # profitQuote
                    parts[-4] = f"{netProfitPct:.2f}"   # profitPct
                    parts[-3] = closeTimeIso            # close_ts_iso
                    parts[-2] = str(closeTimestamp)     # close_ts_unix
                    parts[-1] = str(timeToCloseS)       # time_to_close_s
                    lines[i] = ";".join(parts) + "\n"
                    updated = True
                    break
        
        # Write back the updated file
        if updated:
            with open(selectionLogFile, 'w', encoding='utf-8') as f:
                f.writelines(lines)
                
    except Exception as e:
        from logManager import messages
        messages(f"[SELECTION-LOG] Error updating selection log for {symbol}: {e}", console=0, log=1, telegram=0)

def detectSandboxMode():
    """
    Detect if we're running in sandbox mode by checking command line args
    or looking for sandbox indicators
    """
    # Check command line arguments
    if '-test' in sys.argv or '--sandbox' in sys.argv:
        return True
    
    # Check if any arg contains 'sandbox' or 'test'
    for arg in sys.argv:
        if 'sandbox' in arg.lower() or 'test' in arg.lower():
            return True
    
    # Check environment variable if set
    if os.environ.get('FUTSCO_SANDBOX', '').lower() in ['true', '1', 'yes']:
        return True
        
    return False

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

def checkOrderStatusPeriodically():
    """
    Verifica estado de órdenes TP/SL usando fetchOrderStatus
    Estados posibles: open, closed, canceled
    - open: la orden sigue abierta, no se ha ejecutado nada
    - closed: la orden se ha ejecutado, calcular PnL y flujo normal  
    - canceled: la orden se canceló porque se ejecutó la otra orden
    """
    from connector import bingxConnector
    from logManager import messages
    
    global rateLimitBackoff
    
    # Check if we're in a rate limit backoff period
    if rateLimitBackoff > 60:
        return  # Skip this cycle if we're heavily rate limited
    
    # Detect sandbox mode
    isSandboxMode = detectSandboxMode()
    if isSandboxMode:
        messages("[ORDER-CHECK] Running in SANDBOX mode", console=0, log=1, telegram=0)
    
    try:
        with open(positionsFile, 'r', encoding='utf-8') as f:
            positions = json.load(f)
    except Exception as e:
        messages(f"[ORDER-CHECK] Error loading positions: {e}", console=1, log=1, telegram=0)
        return
    
    exchange = bingxConnector(isSandbox=isSandboxMode)
    positionsUpdated = False
    
    for symbol, pos in positions.items():
        try:
            # Skip if already closed
            if pos.get('status') == 'closed':
                continue
            
            # Set default status if not present
            if 'status' not in pos:
                pos['status'] = 'open'
                positionsUpdated = True
            
            # Get order IDs (use regular IDs only)
            tpOrderId = pos.get('tpOrderId1')
            slOrderId = pos.get('slOrderId1')
            
            if not tpOrderId and not slOrderId:
                continue
            
            # Check TP order status
            tpStatus = None
            if tpOrderId:
                try:
                    tpStatus, error = safeApiCall(exchange.fetchOrderStatus, tpOrderId, symbol)
                    if error:
                        messages(f"[ORDER-CHECK] Error fetching TP order status {tpOrderId} for {symbol}: {error}", console=0, log=1, telegram=0)
                    else:
                        messages(f"[ORDER-CHECK] {symbol} TP order {tpOrderId} status: {tpStatus}", console=0, log=1, telegram=0)
                except Exception as e:
                    messages(f"[ORDER-CHECK] Exception checking TP order status for {symbol}: {e}", console=0, log=1, telegram=0)
            
            # Check SL order status  
            slStatus = None
            if slOrderId:
                try:
                    slStatus, error = safeApiCall(exchange.fetchOrderStatus, slOrderId, symbol)
                    if error:
                        messages(f"[ORDER-CHECK] Error fetching SL order status {slOrderId} for {symbol}: {error}", console=0, log=1, telegram=0)
                    else:
                        messages(f"[ORDER-CHECK] {symbol} SL order {slOrderId} status: {slStatus}", console=0, log=1, telegram=0)
                except Exception as e:
                    messages(f"[ORDER-CHECK] Exception checking SL order status for {symbol}: {e}", console=0, log=1, telegram=0)
            
            # Process order status results
            if tpStatus == 'closed' or slStatus == 'closed':
                # One of the orders was executed - mark position as closed
                pos['status'] = 'closed'
                
                # Determine which order was executed
                if tpStatus == 'closed' and slStatus == 'closed':
                    # Both show as closed - this shouldn't happen, default to TP
                    pos['close_reason'] = 'TP'
                elif tpStatus == 'closed':
                    pos['close_reason'] = 'TP'
                elif slStatus == 'closed':
                    pos['close_reason'] = 'SL'
                    
                pos['close_time'] = datetime.now().isoformat()
                if 'notification_sent' not in pos:
                    pos['notification_sent'] = False
                positionsUpdated = True
                
                messages(f"[ORDER-CHECK] Position {symbol} marked as closed ({pos['close_reason']})", console=0, log=1, telegram=0)
        
        except Exception as e:
            messages(f"[ORDER-CHECK] Error processing {symbol}: {e}", console=0, log=1, telegram=0)
            continue
    
    # Save updated positions if any changes were made
    if positionsUpdated:
        try:
            with open(positionsFile, 'w', encoding='utf-8') as f:
                json.dump(positions, f, indent=2)
            messages("[ORDER-CHECK] Position statuses updated", console=0, log=1, telegram=0)
        except Exception as e:
            messages(f"[ORDER-CHECK] Error saving updated positions: {e}", console=1, log=1, telegram=0)

def notifyClosedPositions():
    """
    NUEVA FUNCIÓN SIMPLE: Notifica posiciones cerradas que aún no han sido notificadas
    """
    from logManager import messages
    
    try:
        with open(positionsFile, 'r', encoding='utf-8') as f:
            positions = json.load(f)
    except Exception as e:
        messages(f"[NOTIFY] Error loading positions: {e}", console=1, log=1, telegram=0)
        return
    
    positionsUpdated = False
    
    for symbol, pos in positions.items():
        try:
            # Notify only closed positions that haven't been notified
            if pos.get('status') == 'closed' and not pos.get('notification_sent', False):
                
                # Calculate PnL for notification
                openPrice = float(pos.get('openPrice', 0))
                closeReason = pos.get('close_reason', 'UNKNOWN')
                amount = float(pos.get('amount', 0))
                side = pos.get('side', 'LONG')
                investment = float(pos.get('investment_usdt', 0))
                leverage = int(pos.get('leverage', 1))
                
                # Determine close price based on TP or SL
                if closeReason == 'TP':
                    closePrice = float(pos.get('tpPrice', openPrice))
                elif closeReason == 'SL':
                    closePrice = float(pos.get('slPrice', openPrice))
                else:
                    closePrice = openPrice  # Fallback
                
                # Calculate PnL based on side
                if side == 'LONG':
                    pnlQuote = amount * (closePrice - openPrice)
                else:  # SHORT
                    pnlQuote = amount * (openPrice - closePrice)
                
                # Calculate PnL percentage based on investment
                pnlPct = (pnlQuote / investment) * 100 if investment > 0 else 0
                
                # Format symbol for display (remove :USDT suffix)
                symbolDisplay = symbol.replace('/USDT:USDT', '').replace(':USDT', '')
                
                # Create notification message like before
                if closeReason == 'TP':
                    emoji = "💰💰"
                elif closeReason == 'SL':
                    emoji = "☠️☠️"
                else:
                    emoji = "🔔"
                
                notificationMsg = f"{emoji} {side} {symbolDisplay} - P/L: {pnlQuote:.2f} USDT ({pnlPct:.2f}%) - Investment: {investment:.1f} ({leverage}x)"
                
                try:
                    # Send notification via telegram
                    messages(notificationMsg, console=1, log=1, telegram=1)
                    
                    # Log the trade to trades.csv
                    try:
                        # Log trade directly here to avoid circular dependency
                        logTradeDirectly(symbol, pos, closeReason, pnlQuote)
                        messages(f"[TRADE-LOG] Trade logged to trades.csv for {symbol}", console=0, log=1, telegram=0)
                    except Exception as tradeLogError:
                        messages(f"[TRADE-LOG] Error logging trade for {symbol}: {tradeLogError}", console=0, log=1, telegram=0)
                    
                    # Add position to intelligent optimizer learning system
                    try:
                        from intelligentOptimizer import optimizer
                        
                        # Prepare outcome data
                        outcome = {
                            "result": "profit" if pnlQuote > 0 else "loss" if pnlQuote < 0 else "breakeven",
                            "profitPct": pnlPct / 100.0,  # Convert to decimal
                            "profitUsdt": pnlQuote,
                            "closeReason": closeReason,
                            "timeToClose": None,  # TODO: Calculate time to close in seconds
                            "actualBounce": None,  # TODO: Analyze if actual bounce occurred
                            "bounceAccuracy": None  # TODO: Calculate bounce accuracy
                        }
                        
                        # Add to learning system
                        optimizer.analyzeClosedPosition(pos, outcome)
                        messages(f"[OPTIMIZER] Added position {symbol} to learning database", console=0, log=1, telegram=0)
                        
                    except Exception as optimizerError:
                        messages(f"[OPTIMIZER] Error adding position to learning system: {optimizerError}", console=0, log=1, telegram=0)
                    
                    # Update selectionLog.csv with closing data
                    try:
                        updateSelectionLogWithClose(symbol, pos, closeReason, pnlQuote, pnlPct)
                        messages(f"[SELECTION-LOG] Updated selectionLog.csv for {symbol}", console=0, log=1, telegram=0)
                    except Exception as selectionLogError:
                        messages(f"[SELECTION-LOG] Error updating selectionLog for {symbol}: {selectionLogError}", console=0, log=1, telegram=0)
                    
                    # Mark as notified
                    pos['notification_sent'] = True
                    positionsUpdated = True
                    
                    messages(f"[NOTIFY] Sent notification for closed position {symbol}", console=0, log=1, telegram=0)
                    
                except Exception as e:
                    messages(f"[NOTIFY] Failed to notify {symbol}: {e}", console=1, log=1, telegram=0)
        
        except Exception as e:
            messages(f"[NOTIFY] Error processing notification for {symbol}: {e}", console=0, log=1, telegram=0)
            continue
    
    # Save updated positions if any notifications were sent
    if positionsUpdated:
        try:
            with open(positionsFile, 'w', encoding='utf-8') as f:
                json.dump(positions, f, indent=2)
            messages("[NOTIFY] Notification statuses updated", console=0, log=1, telegram=0)
        except Exception as e:
            messages(f"[NOTIFY] Error saving notification updates: {e}", console=1, log=1, telegram=0)

def managePositionsSequentially():
    """
    NUEVA FUNCIÓN MAESTRA: Ejecuta todas las tareas de gestión de posiciones secuencialmente
    Evita conflictos de concurrencia al ejecutar todo en orden:
    1. Verificar estado de órdenes
    2. Notificar posiciones cerradas  
    3. Limpiar posiciones notificadas
    """
    from logManager import messages
    
    try:
        messages("[POSITION-MANAGER] Starting sequential position management cycle", console=0, log=1, telegram=0)
        
        # Paso 1: Verificar estado de órdenes TP/SL
        messages("[POSITION-MANAGER] Step 1: Checking order status", console=0, log=1, telegram=0)
        checkOrderStatusPeriodically()
        
        # Paso 2: Notificar posiciones cerradas
        messages("[POSITION-MANAGER] Step 2: Notifying closed positions", console=0, log=1, telegram=0)
        notifyClosedPositions()
        
        # Paso 3: Limpiar posiciones notificadas
        messages("[POSITION-MANAGER] Step 3: Cleaning notified positions", console=0, log=1, telegram=0)
        cleanNotifiedPositions()
        
        messages("[POSITION-MANAGER] Sequential position management cycle completed", console=0, log=1, telegram=0)
        
    except Exception as e:
        messages(f"[POSITION-MANAGER] Error in sequential management: {e}", console=1, log=1, telegram=0)

def cleanNotifiedPositions():
    """
    NUEVA FUNCIÓN SIMPLE: Elimina posiciones cerradas y notificadas
    """
    from logManager import messages
    
    try:
        with open(positionsFile, 'r', encoding='utf-8') as f:
            positions = json.load(f)
    except Exception as e:
        messages(f"[CLEANUP] Error loading positions: {e}", console=1, log=1, telegram=0)
        return
    
    toRemove = []
    for symbol, pos in positions.items():
        if pos.get('status') == 'closed' and pos.get('notification_sent', False):
            toRemove.append(symbol)
    
    if toRemove:
        for symbol in toRemove:
            del positions[symbol]
        
        try:
            with open(positionsFile, 'w', encoding='utf-8') as f:
                json.dump(positions, f, indent=2)
            messages(f"[CLEANUP] Removed {len(toRemove)} closed and notified positions: {toRemove}", console=0, log=1, telegram=0)
        except Exception as e:
            messages(f"[CLEANUP] Error saving cleaned positions: {e}", console=1, log=1, telegram=0)
    else:
        messages("[CLEANUP] No positions to clean", console=0, log=1, telegram=0)
