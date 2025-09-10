import json
import time
from datetime import datetime, timedelta
import os
import sys
import threading
import re
from gvars import positionsFile

# Global variables for rate limiting
lastApiCall = 0
apiCallInterval = 1.0  # Minimum 1 second between API calls
rateLimitBackoff = 60  # Start with 60 seconds backoff when rate limited

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
    NUEVA FUNCIÓN SIMPLE: Verifica estado de órdenes TP/SL por ID
    Actualiza campo 'status' en JSON basado en el estado de las órdenes
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
            
            # Get order IDs (prioritize custom IDs, then regular IDs)
            tpOrderId = pos.get('tpOrderId2') or pos.get('tpOrderId1')
            slOrderId = pos.get('slOrderId2') or pos.get('slOrderId1')
            
            # NEW: Get custom IDs for more reliable tracking
            tpCustomId = pos.get('tpCustomId')
            slCustomId = pos.get('slCustomId')
            
            if not tpOrderId and not slOrderId and not tpCustomId and not slCustomId:
                continue
            
            # Check TP order status
            tpStatus = None
            tpExecuted = False
            if tpCustomId or tpOrderId:
                try:
                    # Try custom ID first, fallback to regular ID
                    orderIdToCheck = tpCustomId if tpCustomId else tpOrderId
                    idType = "custom" if tpCustomId else "regular"
                    
                    tpOrder, error = safeApiCall(exchange.fetch_order, orderIdToCheck, symbol)
                    if error:
                        # Check if error indicates order was executed (order not exist)
                        if "order not exist" in str(error).lower() or "80016" in str(error):
                            tpExecuted = True
                            tpStatus = 'executed'
                            messages(f"[ORDER-CHECK] {symbol} TP order {orderIdToCheck} ({idType} ID) was executed (order not exist)", console=0, log=1, telegram=0)
                        else:
                            messages(f"[ORDER-CHECK] Error fetching TP order {orderIdToCheck} ({idType} ID) for {symbol}: {error}", console=0, log=1, telegram=0)
                    else:
                        tpStatus = tpOrder.get('status')
                        messages(f"[ORDER-CHECK] {symbol} TP order {orderIdToCheck} ({idType} ID) status: {tpStatus} (RAW: {tpOrder})", console=0, log=1, telegram=0)
                        if tpStatus in ['filled', 'closed']:
                            tpExecuted = True
                except Exception as e:
                    messages(f"[ORDER-CHECK] Exception checking TP order for {symbol}: {e}", console=0, log=1, telegram=0)
            
            # Check SL order status  
            slStatus = None
            slExecuted = False
            if slCustomId or slOrderId:
                try:
                    # Try custom ID first, fallback to regular ID
                    orderIdToCheck = slCustomId if slCustomId else slOrderId
                    idType = "custom" if slCustomId else "regular"
                    
                    slOrder, error = safeApiCall(exchange.fetch_order, orderIdToCheck, symbol)
                    if error:
                        # Check if error indicates order was executed (order not exist)
                        if "order not exist" in str(error).lower() or "80016" in str(error):
                            slExecuted = True
                            slStatus = 'executed'
                            messages(f"[ORDER-CHECK] {symbol} SL order {orderIdToCheck} ({idType} ID) was executed (order not exist)", console=0, log=1, telegram=0)
                        else:
                            messages(f"[ORDER-CHECK] Error fetching SL order {orderIdToCheck} ({idType} ID) for {symbol}: {error}", console=0, log=1, telegram=0)
                    else:
                        slStatus = slOrder.get('status')
                        messages(f"[ORDER-CHECK] {symbol} SL order {orderIdToCheck} ({idType} ID) status: {slStatus} (RAW: {slOrder})", console=0, log=1, telegram=0)
                        if slStatus in ['filled', 'closed']:
                            slExecuted = True
                except Exception as e:
                    messages(f"[ORDER-CHECK] Exception checking SL order for {symbol}: {e}", console=0, log=1, telegram=0)
            
            # Update position status if any order was executed
            if tpExecuted or slExecuted:
                pos['status'] = 'closed'
                # Determine which order was executed - priority to TP if both appear executed
                if tpExecuted and slExecuted:
                    # Both appear executed - use position comparison to determine which one actually closed it
                    exchangePositions = exchange.fetch_positions()
                    openSymbols = {p['symbol'] for p in exchangePositions if p.get('contracts', 0) > 0}
                    if symbol not in openSymbols:
                        pos['close_reason'] = 'TP'  # Default to TP when unsure
                    else:
                        continue  # Position still open, something wrong
                elif tpExecuted:
                    pos['close_reason'] = 'TP'
                elif slExecuted:
                    pos['close_reason'] = 'SL'
                    
                pos['close_time'] = datetime.now().isoformat()
                if 'notification_sent' not in pos:
                    pos['notification_sent'] = False
                positionsUpdated = True
                
                messages(f"[ORDER-CHECK] Position {symbol} marked as closed ({pos['close_reason']})", console=1, log=1, telegram=1)
        
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
                
                # Calculate basic profit info for notification
                openPrice = float(pos.get('openPrice', 0))
                closeReason = pos.get('close_reason', 'UNKNOWN')
                
                # Basic profit calculation (simplified)
                profitQuote = 0.0  # Will be calculated by notification function
                profitPct = 0.0    # Will be calculated by notification function
                
                try:
                    # Send notification via telegram
                    messages(f"🔔 Position {symbol} closed - {closeReason}", console=1, log=1, telegram=1)
                    
                    # Mark as notified
                    pos['notification_sent'] = True
                    positionsUpdated = True
                    
                    messages(f"[NOTIFY] Sent notification for closed position {symbol}", console=1, log=1, telegram=0)
                    
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
            messages(f"[CLEANUP] Removed {len(toRemove)} closed and notified positions: {toRemove}", console=1, log=1, telegram=0)
        except Exception as e:
            messages(f"[CLEANUP] Error saving cleaned positions: {e}", console=1, log=1, telegram=0)
    else:
        messages("[CLEANUP] No positions to clean", console=0, log=1, telegram=0)
