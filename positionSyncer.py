import json
import time
import csv
from datetime import datetime
from logManager import messages
from gvars import positionsFile, selectionLogFile
from cacheManager import cachedCall

def getSelectionLogData(symbol, tradeDateTime):
    """
    Search for position data in selectionLog.csv based on symbol and approximate time
    Returns dict with tpPrice, slPrice, slope, intercept if found
    """
    try:
        # Convert trade datetime to unix timestamp for comparison
        if tradeDateTime:
            if 'T' in tradeDateTime and 'Z' in tradeDateTime:
                # Format: 2025-08-24T13:00:24.000Z
                tradeTime = datetime.fromisoformat(tradeDateTime.replace('Z', '+00:00'))
            else:
                # Try other formats
                tradeTime = datetime.fromisoformat(tradeDateTime)
            
            tradeTimestamp = int(tradeTime.timestamp())
            
            # Search in selectionLog.csv (last 100 entries for performance)
            with open(selectionLogFile, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            # Check last 100 entries (most recent first)
            for line in reversed(lines[-100:]):
                if symbol in line and 'accepted;1' in line:  # Only accepted positions
                    parts = line.strip().split(';')
                    if len(parts) >= 20:  # Ensure we have enough columns
                        try:
                            logSymbol = parts[3]  # pair column
                            logTimestamp = int(parts[2])  # timestamp_unix column
                            
                            # Check if symbol matches and time is within 2 hours
                            if logSymbol == symbol and abs(logTimestamp - tradeTimestamp) < 7200:
                                return {
                                    'tpPrice': float(parts[16].replace(',', '.')) if parts[16] not in ['0,000000', '0.000000', '0', ''] else None,
                                    'slPrice': float(parts[17].replace(',', '.')) if parts[17] not in ['0,000000', '0.000000', '0', ''] else None,
                                    'slope': float(parts[13].replace(',', '.')) if parts[13] else None,
                                    'intercept': float(parts[14].replace(',', '.')) if parts[14] else None
                                }
                        except (ValueError, IndexError):
                            continue
        
        return None
        
    except Exception as e:
        messages(f"[SYNC] Error reading selectionLog for {symbol}: {e}", console=0, log=1, telegram=0)
        return None

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
    Enhanced to get more data from selectionLog and avoid constant reconstructions
    """
    if not missingSymbols:
        return True
    
    # Reduce telegram noise - only log to console and file
    messages(f"[SYNC] Attempting to reconstruct {len(missingSymbols)} missing positions: {missingSymbols}", console=1, log=1, telegram=0)
    
    reconstructed = 0
    for symbol in missingSymbols:
        try:
            # Check if position was already marked as reconstructed recently
            try:
                with open(positionsFile, encoding='utf-8') as f:
                    existingPositions = json.load(f)
                if symbol in existingPositions and existingPositions[symbol].get('reconstructed'):
                    # Skip if already reconstructed recently (within last hour)
                    reconstructDate = existingPositions[symbol].get('reconstruction_date', '')
                    if reconstructDate:
                        reconstructTime = datetime.fromisoformat(reconstructDate.replace('Z', '+00:00'))
                        if (datetime.utcnow() - reconstructTime.replace(tzinfo=None)).total_seconds() < 3600:
                            messages(f"[SYNC] Skipping {symbol} - already reconstructed recently", console=0, log=1, telegram=0)
                            continue
            except Exception:
                pass
            
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
                    # Try to get additional data from selectionLog
                    selectionData = getSelectionLogData(symbol, openingTrade.get('datetime', ''))
                    
                    # Reconstruct position data with enhanced info
                    positionData = {
                        'symbol': symbol,
                        'amount': str(openingTrade.get('amount', 0)),
                        'openPrice': str(openingTrade.get('price', 0)),
                        'timestamp': openingTrade.get('datetime', datetime.utcnow().isoformat()),
                        'open_ts_unix': int(openingTrade.get('timestamp', time.time()) / 1000),
                        'side': 'LONG',  # Assuming long positions
                        'reconstructed': True,
                        'reconstruction_date': datetime.utcnow().isoformat()
                    }
                    
                    # Add selectionLog data if found
                    if selectionData:
                        positionData.update({
                            'tpPrice': selectionData.get('tpPrice'),
                            'slPrice': selectionData.get('slPrice'),
                            'slope': selectionData.get('slope'),
                            'intercept': selectionData.get('intercept'),
                            'leverage': 20,  # Default leverage
                            'investment_usdt': 70.0,  # Default investment
                            'tpPercent': 12.0,
                            'slPercent': 30.0
                        })
                        messages(f"[SYNC] Enhanced reconstruction with selectionLog data for {symbol}", console=0, log=1, telegram=0)
                    else:
                        messages(f"[SYNC] Basic reconstruction for {symbol} - selectionLog data not found", console=0, log=1, telegram=0)
                    
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
                    messages(f"[SYNC] Reconstructed position {symbol} from opening trade at {positionData['openPrice']}", console=1, log=1, telegram=0)
                    
                else:
                    messages(f"[SYNC] Could not find opening trade for {symbol}", console=1, log=1, telegram=0)
                    
            except Exception as e:
                messages(f"[SYNC] Error fetching trades for {symbol}: {e}", console=1, log=1, telegram=0)
                
        except Exception as e:
            messages(f"[SYNC] Error reconstructing position {symbol}: {e}", console=1, log=1, telegram=0)
    
    if reconstructed > 0:
        messages(f"[SYNC] Successfully reconstructed {reconstructed} positions", console=1, log=1, telegram=0)
    
    return reconstructed > 0

def syncPositions(orderManager):
    """
    Main synchronization function - checks discrepancies and fixes them
    """
    localCount, exchangeCount, missingInLocal, extraInLocal = checkPositionDiscrepancies(orderManager)
    
    # Log status (reduced verbosity)
    messages(f"[SYNC] Position status: Local={localCount}, Exchange={exchangeCount}", console=0, log=1, telegram=0)
    
    # Handle discrepancies
    hasDiscrepancies = False
    
    if missingInLocal:
        hasDiscrepancies = True
        # No telegram messages for SYNC - only console and log
        messages(f"[SYNC] Missing in local: {missingInLocal}", console=1, log=1, telegram=0)
        reconstructMissingPositions(orderManager, missingInLocal)
    
    if extraInLocal:
        hasDiscrepancies = True
        messages(f"[SYNC] Extra in local (will be cleaned by updatePositions): {extraInLocal}", console=0, log=1, telegram=0)
        # Let the normal updatePositions() handle closing these
        orderManager.updatePositions()
    
    if not hasDiscrepancies:
        # Only log this occasionally (every 6th sync = 30 minutes)
        if int(time.time()) % 1800 < 300:  # Only during first 5 minutes of each 30-min period
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
            messages(f"[SYNC] Error in scheduled sync: {e}", console=1, log=1, telegram=0)
    
    return runSync

def manualSync(orderManager):
    """
    Run manual position synchronization immediately
    Useful for on-demand checks
    """
    messages("[SYNC] Manual position synchronization requested", console=1, log=1, telegram=0)
    return syncPositions(orderManager)
