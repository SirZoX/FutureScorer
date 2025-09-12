"""
Position Syncer - Synchronizes openedPositions.json with exchange reality
Removes positions that no longer exist in the exchange (manually canceled orders)
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional
from connector import bingxConnector
from configManager import configManager
from logManager import messages
import gvars
import args

class PositionSyncer:
    """
    Synchronizes local openedPositions.json with actual exchange positions
    Removes positions where TP/SL orders no longer exist on exchange
    """
    
    def __init__(self):
        self.positionsFile = gvars.positionsFile
        self.connector = None
        
    def initializeConnector(self):
        """Initialize exchange connector"""
        try:
            self.connector = bingxConnector(isSandbox=args.isSandbox)
            return True
        except Exception as e:
            messages(f"[SYNCER] Error initializing connector: {e}", console=0, log=1, telegram=0)
            return False
    
    def loadPositions(self) -> Dict:
        """Load positions from JSON file"""
        try:
            if os.path.exists(self.positionsFile):
                with open(self.positionsFile, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            messages(f"[SYNCER] Error loading positions file: {e}", console=0, log=1, telegram=0)
            return {}
    
    def savePositions(self, positions: Dict):
        """Save positions to JSON file"""
        try:
            with open(self.positionsFile, 'w', encoding='utf-8') as f:
                json.dump(positions, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            messages(f"[SYNCER] Error saving positions file: {e}", console=0, log=1, telegram=0)
            return False
    
    def checkOrderExists(self, orderId: str, symbol: str) -> bool:
        """
        Check if an order exists on the exchange
        Returns True if order exists, False if not found or canceled
        """
        try:
            # Method 1: Try fetchOrderStatus
            try:
                result = self.connector.fetchOrderStatus(orderId, symbol)
                if result:
                    return True
            except:
                pass
            
            # Method 2: Try fetch_order
            try:
                result = self.connector.fetch_order(orderId, symbol)
                if result and isinstance(result, dict):
                    status = result.get('status', '').lower()
                    # Consider order as existing if it's not canceled/expired/rejected
                    if status in ['open', 'partial', 'closed', 'filled']:
                        return True
                    elif status in ['canceled', 'cancelled', 'expired', 'rejected']:
                        return False
            except:
                pass
            
            # Method 3: Search in fetchOrders list
            try:
                orders = self.connector.fetchOrders(symbol=symbol, limit=100)
                if orders:
                    for order in orders:
                        if str(order.get('id')) == str(orderId):
                            status = order.get('status', '').lower()
                            if status in ['open', 'partial', 'closed', 'filled']:
                                return True
                            elif status in ['canceled', 'cancelled', 'expired', 'rejected']:
                                return False
            except:
                pass
            
            # If all methods fail, assume order doesn't exist
            return False
            
        except Exception as e:
            messages(f"[SYNCER] Error checking order {orderId} for {symbol}: {e}", console=0, log=1, telegram=0)
            return False
    
    def syncPosition(self, symbol: str, position: Dict) -> bool:
        """
        Check if a position's TP/SL orders still exist on exchange
        Returns True if position should be kept, False if should be removed
        """
        try:
            tpOrderId = position.get('tpOrderId1')
            slOrderId = position.get('slOrderId1')
            
            tpExists = True
            slExists = True
            
            # Check TP order if exists
            if tpOrderId:
                tpExists = self.checkOrderExists(tpOrderId, symbol)
                if not tpExists:
                    messages(f"[SYNCER] TP order {tpOrderId} for {symbol} not found on exchange, possibly canceled manually", 
                           console=0, log=1, telegram=0)
            
            # Check SL order if exists  
            if slOrderId:
                slExists = self.checkOrderExists(slOrderId, symbol)
                if not slExists:
                    messages(f"[SYNCER] SL order {slOrderId} for {symbol} not found on exchange, possibly canceled manually", 
                           console=0, log=1, telegram=0)
            
            # Keep position only if both TP and SL orders exist (or don't have order IDs)
            shouldKeep = tpExists and slExists
            
            if not shouldKeep:
                messages(f"[SYNCER] Position {symbol} will be removed from openedPositions.json due to missing orders", 
                       console=0, log=1, telegram=0)
            
            return shouldKeep
            
        except Exception as e:
            messages(f"[SYNCER] Error syncing position {symbol}: {e}", console=0, log=1, telegram=0)
            # On error, keep the position to be safe
            return True
    
    def performSync(self) -> Dict:
        """
        Main sync function - checks all positions and removes invalid ones
        Returns updated positions dict
        """
        try:
            syncStart = time.time()
            messages(f"[SYNCER] Starting position synchronization with exchange", console=0, log=1, telegram=0)
            
            # Initialize connector
            if not self.initializeConnector():
                messages(f"[SYNCER] Failed to initialize connector, skipping sync", console=0, log=1, telegram=0)
                return self.loadPositions()
            
            # Load current positions
            positions = self.loadPositions()
            originalCount = len(positions)
            
            if originalCount == 0:
                messages(f"[SYNCER] No positions to sync", console=0, log=1, telegram=0)
                return positions
            
            messages(f"[SYNCER] Checking {originalCount} positions against exchange", console=0, log=1, telegram=0)
            
            # Check each position
            positionsToRemove = []
            for symbol, position in positions.items():
                try:
                    if not self.syncPosition(symbol, position):
                        positionsToRemove.append(symbol)
                except Exception as e:
                    messages(f"[SYNCER] Error checking position {symbol}: {e}", console=0, log=1, telegram=0)
            
            # Remove invalid positions
            for symbol in positionsToRemove:
                del positions[symbol]
                messages(f"[SYNCER] Removed position {symbol} from openedPositions.json", console=0, log=1, telegram=0)
            
            # Save updated positions
            if positionsToRemove:
                if self.savePositions(positions):
                    removedCount = len(positionsToRemove)
                    finalCount = len(positions)
                    syncElapsed = time.time() - syncStart
                    
                    messages(f"[SYNCER] Sync completed in {syncElapsed:.2f}s. Removed {removedCount} invalid positions. {finalCount}/{originalCount} positions remain", 
                           console=0, log=1, telegram=0)
                else:
                    messages(f"[SYNCER] Failed to save updated positions file", console=0, log=1, telegram=0)
            else:
                syncElapsed = time.time() - syncStart
                messages(f"[SYNCER] Sync completed in {syncElapsed:.2f}s. All {originalCount} positions are valid", 
                       console=0, log=1, telegram=0)
            
            return positions
            
        except Exception as e:
            messages(f"[SYNCER] Error in performSync: {e}", console=0, log=1, telegram=0)
            import traceback
            traceback.print_exc()
            return self.loadPositions()

# Global instance
positionSyncer = PositionSyncer()

def syncPositionsWithExchange() -> Dict:
    """
    Public function to trigger position synchronization
    Returns updated positions dict
    """
    return positionSyncer.performSync()

def getValidPositionsCount() -> int:
    """
    Get count of valid (synchronized) positions
    """
    try:
        positions = positionSyncer.loadPositions()
        return len(positions)
    except:
        return 0
