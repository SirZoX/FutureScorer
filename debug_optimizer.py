"""
Debug script for intelligent optimizer
"""

from intelligentOptimizer import optimizer
import traceback

def test_optimizer():
    print("Testing optimizer...")
    
    pos = {
        'symbol': 'TEST/USDT:USDT',
        'opportunityId': 'test123',
        'side': 'LONG',
        'leverage': 30
    }
    
    outcome = {
        'result': 'profit',
        'profitPct': 0.15,
        'profitUsdt': 15.0,
        'closeReason': 'tp'
    }
    
    print(f"Before: Total positions = {optimizer.learningDb['totalClosedPositions']}")
    
    # Test extractEntryParameters first
    print("Testing extractEntryParameters...")
    try:
        params = optimizer.extractEntryParameters(pos)
        print(f"Entry params: {params}")
    except Exception as e:
        print(f"❌ Error in extractEntryParameters: {e}")
        traceback.print_exc()
        return
    
    # Test captureMarketConditions
    print("Testing captureMarketConditions...")
    try:
        market = optimizer.captureMarketConditions(pos)
        print(f"Market conditions: {market}")
    except Exception as e:
        print(f"❌ Error in captureMarketConditions: {e}")
        traceback.print_exc()
        return
    
    # Test full function
    print("Testing full analyzeClosedPosition...")
    try:
        optimizer.analyzeClosedPosition(pos, outcome)
        print(f"After: Total positions = {optimizer.learningDb['totalClosedPositions']}")
        print("✅ Success!")
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    test_optimizer()
