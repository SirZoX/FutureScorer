#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

print("Deep resistance detection analysis...")

try:
    import pandas as pd
    from connector import bingxConnector
    import supportDetector
    import configManager

    # Initialize exchange
    exchange = bingxConnector()

    # Test with multiple pairs to see resistance patterns
    test_pairs = ["AVAX/USDT:USDT", "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
    timeframe = "1d"
    requestedCandles = 150

    for pair in test_pairs:
        print(f"\n=== Testing {pair} ===")
        
        try:
            # Fetch OHLCV data
            ohlcv = exchange.fetch_ohlcv(pair, timeframe, None, requestedCandles)
            df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
            
            # Load config
            configData = configManager.configManager.config
            tolerancePct = configData.get('tolerancePct', 0.015)
            minTouches = configData.get('minTouches', 3)
            minCandlesSeparationToFindSupportLine = configData.get('minCandlesSeparationToFindSupportLine', 36)
            
            # Get raw data for analysis
            lows = df["low"].tolist()
            highs = df["high"].tolist()
            closes = df["close"].tolist()
            opens = df["open"].tolist()
            
            print(f"Data range: Low {min(lows):.2f} - High {max(highs):.2f}")
            print(f"Last 5 lows: {lows[-5:]}")
            print(f"Last 5 highs: {highs[-5:]}")
            
            # Test horizontal resistance detection specifically
            print("\n--- Testing horizontal resistance detection ---")
            
            # Call the internal function to see what's happening
            # First, let's see what lines are found before validation
            n = len(lows)
            xIdx = list(range(n))
            strictTolerancePct = tolerancePct * 0.5
            noiseThreshold = strictTolerancePct
            
            # Try to call the internal function
            try:
                # This function should be defined in supportDetector
                resistanceLines = supportDetector._findHorizontalLines(
                    lows, highs, closes, opens, 'resistance', xIdx, 
                    strictTolerancePct, noiseThreshold, minTouches, minCandlesSeparationToFindSupportLine
                )
                print(f"Raw resistance lines found: {len(resistanceLines)}")
                for i, line in enumerate(resistanceLines):
                    print(f"  Line {i+1}: level={line.get('level', 'N/A')}, touches={line.get('touchCount', 'N/A')}")
            except Exception as e:
                print(f"Error calling _findHorizontalLines: {e}")
            
            # Now test the full detection
            opportunities = supportDetector.findPossibleResistancesAndSupports(
                lows, highs, closes, opens, tolerancePct, 
                minCandlesSeparationToFindSupportLine, minTouches
            )
            
            # Count by type
            long_count = sum(1 for opp in opportunities if opp['type'] == 'long')
            short_count = sum(1 for opp in opportunities if opp['type'] == 'short')
            
            print(f"Final result: {long_count} LONG, {short_count} SHORT")
            
        except Exception as e:
            print(f"Error processing {pair}: {e}")
            import traceback
            traceback.print_exc()

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
