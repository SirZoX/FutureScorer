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
    
    try:
        with open(positionsFile, 'r', encoding='utf-8') as f:
            positions = json.load(f)
    except Exception as e:
        messages(f"[ORDER-CHECK] Error loading positions: {e}", console=1, log=1, telegram=0)
        return
    
    exchange = bingxConnector()
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
            
            # Get order IDs (prioritize active orders)
            tpOrderId = pos.get('tpOrderId2') or pos.get('tpOrderId1')
            slOrderId = pos.get('slOrderId2') or pos.get('slOrderId1')
            
            if not tpOrderId and not slOrderId:
                continue
            
            # Check TP order status
            tpStatus = None
            if tpOrderId:
                try:
                    tpOrder, error = safeApiCall(exchange.fetch_order, tpOrderId, symbol)
                    if error:
                        messages(f"[ORDER-CHECK] Error fetching TP order {tpOrderId} for {symbol}: {error}", console=0, log=1, telegram=0)
                    else:
                        tpStatus = tpOrder.get('status')
                        messages(f"[ORDER-CHECK] {symbol} TP order {tpOrderId} status: {tpStatus} (RAW: {tpOrder})", console=0, log=1, telegram=0)
                except Exception as e:
                    messages(f"[ORDER-CHECK] Exception checking TP order for {symbol}: {e}", console=0, log=1, telegram=0)
            
            # Check SL order status  
            slStatus = None
            if slOrderId:
                try:
                    slOrder, error = safeApiCall(exchange.fetch_order, slOrderId, symbol)
                    if error:
                        messages(f"[ORDER-CHECK] Error fetching SL order {slOrderId} for {symbol}: {error}", console=0, log=1, telegram=0)
                    else:
                        slStatus = slOrder.get('status')
                        messages(f"[ORDER-CHECK] {symbol} SL order {slOrderId} status: {slStatus} (RAW: {slOrder})", console=0, log=1, telegram=0)
                except Exception as e:
                    messages(f"[ORDER-CHECK] Exception checking SL order for {symbol}: {e}", console=0, log=1, telegram=0)
            
            # Update position status if any order is filled
            if tpStatus in ['filled', 'closed'] or slStatus in ['filled', 'closed']:
                pos['status'] = 'closed'
                pos['close_reason'] = 'TP' if tpStatus in ['filled', 'closed'] else 'SL'
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
    from fileManager import notifyPositionClosure
    
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
                    # Send notification
                    notifyPositionClosure(symbol, closeReason, profitQuote, profitPct, 0, {})
                    
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
