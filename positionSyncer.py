import json
import time
from datetime import datetime
from logManager import messages
from gvars import positionsFile
from cacheManager import cachedCall

def checkPositionDiscrepancies(orderManager):
    """
    Check for discrepancies between exchange positions and local openedPositions.json
    Returns tuple: (local_count, exchange_count, missing_in_local, extra_in_local)
    """
    try:
        # Get positions from exchange (cached)
        exchangePositions = cachedCall(
            "exchange_positions_syncer", 
            orderManager.exchange.fetch_positions, 
            ttl=60
        )
        
        exchangeSymbols = set()
        for pos in exchangePositions:
            contracts = float(pos.get('contracts', 0))
            if contracts > 0:
                exchangeSymbols.add(pos.get('symbol', ''))
        
        # Get local positions
        try:
            with open(positionsFile, encoding='utf-8') as f:
                localPositions = json.load(f)
        except Exception:
            localPositions = {}
        
        localSymbols = set(localPositions.keys())
        
        # Find discrepancies
        missingInLocal = exchangeSymbols - localSymbols  # En exchange pero no en local
        extraInLocal = localSymbols - exchangeSymbols    # En local pero no en exchange
        
        return len(localSymbols), len(exchangeSymbols), missingInLocal, extraInLocal
        
    except Exception as e:
        messages(f"[SYNC ERROR] Error checking position discrepancies: {e}", console=1, log=1, telegram=0)
        return 0, 0, set(), set()

def reconstructMissingPositions(orderManager, missingSymbols):
    """
    Attempt to reconstruct missing positions from exchange data and recent trades
    """
    if not missingSymbols:
        return True
    
    messages(f"[SYNC] Attempting to reconstruct {len(missingSymbols)} missing positions: {missingSymbols}", console=1, log=1, telegram=1)
    
    reconstructed = 0
    for symbol in missingSymbols:
        try:
            # Get current position from exchange
            exchangePositions = orderManager.exchange.fetch_positions([symbol])
            currentPosition = None
            
            for pos in exchangePositions:
                if pos.get('symbol') == symbol and float(pos.get('contracts', 0)) > 0:
                    currentPosition = pos
                    break
            
            if not currentPosition:
                messages(f"[SYNC] Position {symbol} no longer exists on exchange", console=0, log=1, telegram=0)
                continue
            
            # Try to find the opening trade in recent trades
            try:
                trades = orderManager.exchange.fetch_my_trades(symbol, limit=50)
                openingTrade = None
                
                # Look for the most recent buy trade
                for trade in reversed(trades):  # Most recent first
                    if trade.get('side') == 'buy':
                        openingTrade = trade
                        break
                
                if openingTrade:
                    # Reconstruct position data
                    positionData = {
                        'symbol': symbol,
                        'amount': str(openingTrade.get('amount', 0)),
                        'openPrice': str(openingTrade.get('price', 0)),
                        'timestamp': openingTrade.get('datetime', datetime.utcnow().isoformat()),
                        'open_ts_unix': int(openingTrade.get('timestamp', time.time()) / 1000),
                        'side': 'long',  # Assuming long positions
                        'reconstructed': True,
                        'reconstruction_date': datetime.utcnow().isoformat()
                    }
                    
                    # Add to local positions
                    try:
                        with open(positionsFile, encoding='utf-8') as f:
                            positions = json.load(f)
                    except Exception:
                        positions = {}
                    
                    positions[symbol] = positionData
                    
                    with open(positionsFile, 'w', encoding='utf-8') as f:
                        json.dump(positions, f, indent=2)
                    
                    reconstructed += 1
                    messages(f"[SYNC] Reconstructed position {symbol} from opening trade at {positionData['openPrice']}", console=1, log=1, telegram=1)
                    
                else:
                    messages(f"[SYNC] Could not find opening trade for {symbol}", console=1, log=1, telegram=0)
                    
            except Exception as e:
                messages(f"[SYNC] Error fetching trades for {symbol}: {e}", console=1, log=1, telegram=0)
                
        except Exception as e:
            messages(f"[SYNC] Error reconstructing position {symbol}: {e}", console=1, log=1, telegram=0)
    
    if reconstructed > 0:
        messages(f"[SYNC] Successfully reconstructed {reconstructed} positions", console=1, log=1, telegram=1)
    
    return reconstructed > 0

def syncPositions(orderManager):
    """
    Main synchronization function - checks discrepancies and fixes them
    """
    localCount, exchangeCount, missingInLocal, extraInLocal = checkPositionDiscrepancies(orderManager)
    
    # Log status
    messages(f"[SYNC] Position status: Local={localCount}, Exchange={exchangeCount}", console=1, log=1, telegram=0)
    
    # Handle discrepancies
    hasDiscrepancies = False
    
    if missingInLocal:
        hasDiscrepancies = True
        messages(f"[SYNC] Missing in local: {missingInLocal}", console=1, log=1, telegram=1)
        reconstructMissingPositions(orderManager, missingInLocal)
    
    if extraInLocal:
        hasDiscrepancies = True
        messages(f"[SYNC] Extra in local (will be cleaned by updatePositions): {extraInLocal}", console=1, log=1, telegram=0)
        # Let the normal updatePositions() handle closing these
        orderManager.updatePositions()
    
    if not hasDiscrepancies:
        messages(f"[SYNC] Positions in sync: {localCount} positions", console=0, log=1, telegram=0)
    
    return not hasDiscrepancies

def schedulePositionSync(orderManager, intervalMinutes=5):
    """
    Schedule periodic position synchronization
    Returns the scheduled function for use with schedule library
    """
    def runSync():
        try:
            syncPositions(orderManager)
        except Exception as e:
            messages(f"[SYNC] Error in scheduled sync: {e}", console=1, log=1, telegram=1)
    
    return runSync

def manualSync(orderManager):
    """
    Run manual position synchronization immediately
    Useful for on-demand checks
    """
    messages("[SYNC] Manual position synchronization requested", console=1, log=1, telegram=0)
    return syncPositions(orderManager)
