#!/usr/bin/env python3
# Manual cleanup script for closed positions

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from orderManager import OrderManager

def manualCleanup():
    print("=== Manual Position Cleanup ===")
    try:
        om = OrderManager()
        
        print(f"Current positions in file: {list(om.positions.keys())}")
        
        # Get exchange positions
        print("Fetching exchange positions...")
        exchangePositions = om.getExchangeOpenPositions()
        print(f"Open positions on exchange: {exchangePositions}")
        
        # Clean closed positions
        print("Running cleanup...")
        om.cleanClosedPositions()
        
        # Reload and check
        om.positions = om.loadPositions()
        print(f"Positions after cleanup: {list(om.positions.keys())}")
        
    except Exception as e:
        print(f"Error during cleanup: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    manualCleanup()
