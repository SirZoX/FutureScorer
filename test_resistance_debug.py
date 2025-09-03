#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

print("Starting resistance detection test...")

try:
    import pandas as pd
    print("Pandas imported successfully")
    
    from connector import bingxConnector
    print("Connector imported successfully")
    
    import supportDetector
    print("SupportDetector imported successfully")
    
    import gvars
    print("Gvars imported successfully")
    
    import configManager
    print("ConfigManager imported successfully")

    # Initialize exchange
    exchange = bingxConnector()
    print("Exchange initialized")

    # Test with one pair to see if resistances are detected
    pair = "AVAX/USDT:USDT"
    timeframe = "1d"
    requestedCandles = 150

    print(f"Testing resistance detection for {pair}")

    # Fetch OHLCV data
    ohlcv = exchange.fetch_ohlcv(pair, timeframe, None, requestedCandles)
    df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
    
    print(f"Got {len(df)} candles")
    
    # Load config
    configData = configManager.configManager.config
    tolerancePct = configData.get('tolerancePct', 0.015)
    minTouches = configData.get('minTouches', 3)
    minCandlesSeparationToFindSupportLine = configData.get('minCandlesSeparationToFindSupportLine', 36)
    
    print(f"Config loaded: tolerancePct={tolerancePct}, minTouches={minTouches}, minSeparation={minCandlesSeparationToFindSupportLine}")
    
    # Detect support and resistance lines
    opportunities = supportDetector.findPossibleResistancesAndSupports(
        df["low"].tolist(), 
        df["high"].tolist(), 
        df["close"].tolist(), 
        df["open"].tolist(),
        tolerancePct, 
        minCandlesSeparationToFindSupportLine, 
        minTouches
    )
    
    print(f"Found {len(opportunities)} total opportunities")
    
    # Count by type
    long_count = sum(1 for opp in opportunities if opp['type'] == 'long')
    short_count = sum(1 for opp in opportunities if opp['type'] == 'short')
    
    print(f"LONG opportunities: {long_count}")
    print(f"SHORT opportunities: {short_count}")
    
    # Show details of each opportunity
    for i, opp in enumerate(opportunities):
        print(f"Opportunity {i+1}: type={opp['type']}, touches={opp['touchCount']}, slope={opp['slope']:.6f}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
