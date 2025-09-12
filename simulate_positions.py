#!/usr/bin/env python3
"""
Simulate additional positions to test the full optimization cycle
"""

import sys
import os
import json
from datetime import datetime, timezone
import random

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from intelligentOptimizer import optimizer
import gvars

def generateTestPosition(index: int) -> dict:
    """Generate a test position with realistic data"""
    pairs = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "ADA/USDT:USDT", "DOT/USDT:USDT"]
    sides = ["LONG", "SHORT"]
    
    # Generate realistic parameters with some variation
    isProfit = random.choice([True, True, False])  # 67% win rate
    
    position = {
        "id": f"sim_{index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "pair": random.choice(pairs),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entryParams": {
            "scoreThreshold": round(random.uniform(0.35, 0.45), 3),
            "tolerancePct": round(random.uniform(0.006, 0.009), 4),
            "minTouches": random.choice([2, 3, 4]),
            "scoringWeights": {
                "distance": round(random.uniform(0.15, 0.25), 3),
                "volume": round(random.uniform(0.30, 0.40), 3),
                "momentum": round(random.uniform(0.20, 0.30), 3),
                "touches": round(random.uniform(0.15, 0.25), 3)
            },
            "topCoinsPctAnalyzed": 50,
            "leverage": random.choice([30, 35]),
            "tp1": 0.3,
            "tp2": 0.5,
            "sl1": 0.4
        },
        "outcome": {
            "result": "profit" if isProfit else "loss",
            "profitPct": round(random.uniform(0.20, 0.35), 4) if isProfit else round(random.uniform(-0.45, -0.35), 4),
            "profitUsdt": round(random.uniform(15, 35), 2) if isProfit else round(random.uniform(-45, -25), 2),
            "closeReason": "tp" if isProfit else "sl",
            "timeToClose": random.randint(1000, 30000)
        },
        "marketConditions": {
            "side": random.choice(sides),
            "leverage": random.choice([30, 35]),
            "openPrice": 0,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    }
    
    return position

def simulateAdditionalPositions(count: int = 25):
    """Simulate additional positions to reach the optimization threshold"""
    print(f"🔄 Simulating {count} additional positions...")
    
    current_count = optimizer.learningDb["totalClosedPositions"]
    print(f"📊 Current positions: {current_count}")
    
    for i in range(count):
        position = generateTestPosition(i + 1)
        
        # Analyze the position like a real close
        outcome = {
            "result": position["outcome"]["result"],
            "profitPct": position["outcome"]["profitPct"],
            "profitUsdt": position["outcome"]["profitUsdt"],
            "closeReason": position["outcome"]["closeReason"],
            "timeToClose": position["outcome"]["timeToClose"],
            "actualBounce": None,
            "bounceAccuracy": None
        }
        
        optimizer.analyzeClosedPosition(position, outcome)
        
        new_count = optimizer.learningDb["totalClosedPositions"]
        win_rate = optimizer.calculateCurrentWinRate()
        
        print(f"📈 Position {i+1}/{count}: {position['outcome']['result']} | Total: {new_count} | Win Rate: {win_rate:.1%}")
        
        # Check if optimization was triggered
        if optimizer.shouldOptimize():
            print(f"🚀 Optimization triggered at {new_count} positions!")
            break
    
    final_count = optimizer.learningDb["totalClosedPositions"]
    final_win_rate = optimizer.calculateCurrentWinRate()
    
    print(f"\n✅ Simulation complete:")
    print(f"   📊 Final positions: {final_count}")
    print(f"   🎯 Final win rate: {final_win_rate:.1%}")
    print(f"   🚀 Ready for optimization: {'Yes' if optimizer.shouldOptimize() else 'No'}")

if __name__ == "__main__":
    print("🎲 POSITION SIMULATION FOR OPTIMIZATION TEST")
    print("="*60)
    
    print("📋 Current status:")
    status = optimizer.getOptimizationStatus()
    print(f"   📊 Positions: {status['totalPositions']}")
    print(f"   🎯 Win Rate: {status['currentWinRate']:.1%}")
    print(f"   ⏳ Need: {50 - status['totalPositions']} more positions")
    
    if status['totalPositions'] < 50:
        needed = 50 - status['totalPositions']
        simulateAdditionalPositions(needed + 2)  # Add 2 extra to trigger optimization
    else:
        print("✅ Already have enough positions for optimization!")
    
    print("\n📊 Final optimization status:")
    final_status = optimizer.getOptimizationStatus()
    for key, value in final_status.items():
        print(f"   {key}: {value}")
