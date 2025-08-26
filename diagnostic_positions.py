#!/usr/bin/env python3
"""
Diagnostic script to compare local positions with exchange state
"""

import json
import ccxt
from datetime import datetime
import time

# Import from existing modules
from connector import bingxConnector
from gvars import positionsFile

def loadLocalPositions():
    """Load positions from local JSON file"""
    try:
        with open(positionsFile, 'r', encoding='utf-8') as f:
            positions = json.load(f)
        return positions
    except Exception as e:
        print(f"❌ Error loading local positions: {e}")
        return {}

def checkExchangePositions(exchange):
    """Get all positions from exchange"""
    try:
        positions = exchange.fetch_positions()
        print(f"📊 Exchange returned {len(positions)} total position records")
        
        openPositions = []
        for pos in positions:
            symbol = pos.get('symbol', '')
            contracts = float(pos.get('contracts', 0))
            side = pos.get('side', '')
            notional = pos.get('notional', 0)
            unrealizedPnl = pos.get('unrealizedPnl', 0)
            
            if contracts > 0:
                openPositions.append({
                    'symbol': symbol,
                    'contracts': contracts,
                    'side': side,
                    'notional': notional,
                    'pnl': unrealizedPnl
                })
        
        return openPositions
    except Exception as e:
        print(f"❌ Error fetching exchange positions: {e}")
        return []

def checkIndividualOrders(exchange, localPositions):
    """Check individual orders/trades for each local position"""
    print("\n🔍 CHECKING INDIVIDUAL ORDERS/TRADES:")
    print("=" * 60)
    
    for symbol, posData in localPositions.items():
        print(f"\n📋 Checking {symbol}:")
        print(f"   Local data: opened={posData.get('open_ts_iso', 'N/A')}")
        
        # Check TP/SL orders
        tpOrderId = posData.get('tp_order_id')
        slOrderId = posData.get('sl_order_id')
        
        if tpOrderId:
            try:
                tpOrder = exchange.fetch_order(tpOrderId, symbol)
                tpStatus = tpOrder.get('status', 'unknown')
                print(f"   TP Order {tpOrderId}: {tpStatus}")
            except Exception as e:
                print(f"   TP Order {tpOrderId}: ERROR - {e}")
        
        if slOrderId:
            try:
                slOrder = exchange.fetch_order(slOrderId, symbol)
                slStatus = slOrder.get('status', 'unknown')
                print(f"   SL Order {slOrderId}: {slStatus}")
            except Exception as e:
                print(f"   SL Order {slOrderId}: ERROR - {e}")
        
        # Check recent trades
        try:
            openTsUnix = posData.get('open_ts_unix', 0)
            allTrades = exchange.fetch_my_trades(symbol)
            
            # Filter trades since position open
            relevantTrades = [
                t for t in allTrades
                if t.get('timestamp', 0) >= openTsUnix * 1000
            ]
            
            buyTrades = [t for t in relevantTrades if t.get('side') == 'buy']
            sellTrades = [t for t in relevantTrades if t.get('side') == 'sell']
            
            print(f"   Trades since open: {len(buyTrades)} buy, {len(sellTrades)} sell")
            
            if sellTrades:
                print(f"   🔴 SELL TRADES FOUND - Position likely closed!")
                for trade in sellTrades[-3:]:  # Show last 3
                    tradeTime = datetime.fromtimestamp(trade.get('timestamp', 0) / 1000)
                    print(f"      {tradeTime.strftime('%H:%M:%S')}: {trade.get('side')} {trade.get('amount')} @ {trade.get('price')}")
            else:
                print(f"   ✅ No sell trades - Position likely still open")
                
        except Exception as e:
            print(f"   Trades check: ERROR - {e}")

def main():
    print("🔧 POSITION DIAGNOSTIC TOOL")
    print("=" * 50)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load local positions
    print("\n📂 Loading local positions...")
    localPositions = loadLocalPositions()
    print(f"Found {len(localPositions)} local positions:")
    
    for symbol in localPositions.keys():
        posData = localPositions[symbol]
        openTime = posData.get('open_ts_iso', 'N/A')
        print(f"  - {symbol} (opened: {openTime})")
    
    # Initialize exchange
    print("\n🔌 Connecting to exchange...")
    try:
        exchange = bingxConnector()
        print("✅ Exchange connection established")
    except Exception as e:
        print(f"❌ Failed to connect to exchange: {e}")
        return
    
    # Check exchange positions
    print("\n📊 Checking exchange positions...")
    exchangePositions = checkExchangePositions(exchange)
    
    if exchangePositions:
        print(f"Found {len(exchangePositions)} open positions on exchange:")
        for pos in exchangePositions:
            print(f"  - {pos['symbol']}: {pos['contracts']} contracts, {pos['side']}, PnL: {pos['pnl']}")
    else:
        print("❌ No open positions found on exchange")
    
    # Compare local vs exchange
    print("\n🔄 COMPARISON:")
    print("=" * 30)
    
    localSymbols = set(localPositions.keys())
    exchangeSymbols = set(pos['symbol'] for pos in exchangePositions)
    
    onlyLocal = localSymbols - exchangeSymbols
    onlyExchange = exchangeSymbols - localSymbols
    both = localSymbols & exchangeSymbols
    
    if both:
        print(f"✅ In both local and exchange: {list(both)}")
    
    if onlyLocal:
        print(f"⚠️  Only in local file: {list(onlyLocal)}")
        print("   ^ These positions may be closed but not cleaned up")
    
    if onlyExchange:
        print(f"⚠️  Only on exchange: {list(onlyExchange)}")
        print("   ^ These positions are not tracked locally")
    
    # Check individual orders for problematic positions
    if onlyLocal:
        checkIndividualOrders(exchange, {k: v for k, v in localPositions.items() if k in onlyLocal})
    
    print("\n✅ Diagnostic complete!")

if __name__ == "__main__":
    main()
