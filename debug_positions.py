#!/usr/bin/env python3
# Debug script to check position status

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from orderManager import OrderManager
import json

def checkPositions():
    om = OrderManager()
    
    # Load positions from file
    with open(om.positionsFile, 'r', encoding='utf-8') as f:
        positions = json.load(f)
    
    print("=== Position Status Check ===")
    for symbol, pos in positions.items():
        print(f"\n{symbol}:")
        print(f"  Open Price: {pos.get('openPrice')}")
        print(f"  Amount: {pos.get('amount')}")
        print(f"  TP Order ID1: {pos.get('tpOrderId1')}")
        print(f"  SL Order ID1: {pos.get('slOrderId1')}")
        print(f"  TP Order ID2: {pos.get('tpOrderId2')}")
        print(f"  SL Order ID2: {pos.get('slOrderId2')}")
        
        # Check active orders
        tpOrderId1 = pos.get('tpOrderId1')
        slOrderId1 = pos.get('slOrderId1')
        tpOrderId2 = pos.get('tpOrderId2')
        slOrderId2 = pos.get('slOrderId2')
        
        activeTpOrderId = tpOrderId2 if tpOrderId2 else tpOrderId1
        activeSlOrderId = slOrderId2 if slOrderId2 else slOrderId1
        
        try:
            if activeTpOrderId:
                tpInfo = om.exchange.fetch_order(activeTpOrderId, symbol)
                print(f"  TP Status: {tpInfo.get('status')}")
            else:
                print(f"  TP Status: No active TP order")
                
            if activeSlOrderId:
                slInfo = om.exchange.fetch_order(activeSlOrderId, symbol)
                print(f"  SL Status: {slInfo.get('status')}")
            else:
                print(f"  SL Status: No active SL order")
                
        except Exception as e:
            print(f"  Error checking orders: {e}")
            # Try to get recent trades
            try:
                trades = om.exchange.fetch_my_trades(symbol)
                openTsUnix = pos.get('open_ts_unix', 0)
                sellTrades = [t for t in trades if t.get('side') == 'sell' and t.get('timestamp', 0) >= openTsUnix * 1000]
                print(f"  Recent sell trades: {len(sellTrades)}")
                if sellTrades:
                    print(f"  Last sell trade: {sellTrades[-1]}")
            except Exception as te:
                print(f"  Error checking trades: {te}")

if __name__ == "__main__":
    checkPositions()
