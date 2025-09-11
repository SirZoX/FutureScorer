"""
Optimizer Status Utility - Check the current status of the intelligent optimizer
"""

import json
from intelligentOptimizer import optimizer
from logManager import messages


def printOptimizerStatus():
    """Print detailed optimizer status information"""
    try:
        status = optimizer.getOptimizationStatus()
        
        print("\n" + "="*60)
        print("🧠 INTELLIGENT OPTIMIZER STATUS")
        print("="*60)
        
        print(f"📊 Total Closed Positions: {status['totalPositions']}")
        print(f"🎯 Current Win Rate: {status['currentWinRate']:.2%}")
        print(f"⚙️  Learning Enabled: {'Yes ✅' if status['learningEnabled'] else 'No ❌'}")
        print(f"🚀 Ready for Optimization: {'Yes ✅' if status['readyForOptimization'] else 'No ❌'}")
        
        if status['readyForOptimization']:
            print(f"🔄 Next Optimization At: {status['nextOptimizationAt']} positions")
        else:
            needed = optimizer.minimumSampleSize - status['totalPositions']
            print(f"⏳ Positions Needed: {needed} more positions until first optimization")
        
        if status['lastOptimization']:
            print(f"📅 Last Optimization: {status['lastOptimization']}")
        else:
            print("📅 Last Optimization: Never")
        
        # Show recent optimization history
        if optimizer.learningDb.get('optimizationHistory'):
            print("\n📈 OPTIMIZATION HISTORY:")
            for i, opt in enumerate(optimizer.learningDb['optimizationHistory'][-3:], 1):  # Last 3
                print(f"  {i}. {opt['timestamp'][:19]} - Win Rate: {opt['winRate']:.2%}")
                for param, value in opt['parameters'].items():
                    print(f"     {param}: {value}")
        
        print("\n" + "="*60)
        
    except Exception as e:
        print(f"Error getting optimizer status: {e}")


def showLearningDatabase():
    """Show recent learning database entries"""
    try:
        positions = optimizer.learningDb.get('positionOutcomes', [])
        
        if not positions:
            print("No learning data available yet.")
            return
        
        print(f"\n📚 LEARNING DATABASE (Last 10 positions):")
        print("-" * 80)
        
        for pos in positions[-10:]:  # Last 10 positions
            result = pos['outcome']['result']
            profit = pos['outcome'].get('profitPct', 0)
            pair = pos['pair']
            timestamp = pos['timestamp'][:19]
            
            resultEmoji = "🟢" if result == "profit" else "🔴" if result == "loss" else "🟡"
            print(f"{resultEmoji} {timestamp} | {pair:12} | {result:8} | {profit:+6.2%}")
        
        print("-" * 80)
        
    except Exception as e:
        print(f"Error showing learning database: {e}")


def loadHistoricalDataCommand():
    """Load historical closed positions into learning database"""
    try:
        count = optimizer.loadHistoricalClosedPositions()
        if count > 0:
            print(f"✅ Loaded {count} historical positions into learning database")
        else:
            print("ℹ️  No new historical positions to load")
    except Exception as e:
        print(f"❌ Error loading historical data: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--load-history":
        loadHistoricalDataCommand()
    else:
        printOptimizerStatus()
        showLearningDatabase()
