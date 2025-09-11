"""
Historical Data Importer - Import existing trade data into intelligent optimizer
"""

import csv
import json
import os
from datetime import datetime
from intelligentOptimizer import optimizer
from logManager import messages
import gvars


def importTradesCSVToLearning():
    """
    Import existing trades from trades.csv into the learning database
    This bootstraps the learning system with historical performance data
    """
    try:
        tradesPath = gvars.tradesLogFile
        if not os.path.exists(tradesPath):
            print("❌ No trades.csv file found")
            return 0
        
        imported = 0
        with open(tradesPath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            
            for row in reader:
                try:
                    # Extract trade data
                    symbol = row['symbol']
                    netProfit = float(row['net_profit_usdt'])
                    investment = float(row['investment_usdt'])
                    leverage = int(row['leverage'])
                    side = row['side']
                    openDate = row['open_date']
                    closeDate = row['close_date']
                    
                    # Calculate profit percentage
                    profitPct = (netProfit / investment) * 100 if investment > 0 else 0
                    
                    # Create synthetic position data (since we don't have original position data)
                    syntheticPosition = {
                        "symbol": symbol,
                        "side": side,
                        "leverage": leverage,
                        "investment_usdt": investment,
                        "timestamp": openDate,
                        "opportunityId": f"historical_{symbol}_{openDate.replace(' ', '_').replace(':', '-')}"
                    }
                    
                    # Create outcome data
                    outcome = {
                        "result": "profit" if netProfit > 0 else "loss" if netProfit < 0 else "breakeven",
                        "profitPct": profitPct / 100.0,  # Convert to decimal
                        "profitUsdt": netProfit,
                        "closeReason": "tp" if netProfit > 0 else "sl",  # Assume TP for profit, SL for loss
                        "timeToClose": calculateTimeToClose(openDate, closeDate),
                        "actualBounce": None,  # Unknown for historical data
                        "bounceAccuracy": None  # Unknown for historical data
                    }
                    
                    # Add to learning system
                    optimizer.analyzeClosedPosition(syntheticPosition, outcome)
                    imported += 1
                    
                    print(f"✅ Imported: {symbol} - {outcome['result']} ({profitPct:+.2f}%)")
                    
                except Exception as e:
                    print(f"❌ Error importing row {row}: {e}")
                    continue
        
        print(f"\n🎯 Successfully imported {imported} historical trades")
        return imported
        
    except Exception as e:
        print(f"❌ Error importing trades.csv: {e}")
        return 0


def calculateTimeToClose(openDate, closeDate):
    """Calculate time to close in seconds"""
    try:
        openDt = datetime.strptime(openDate, '%Y-%m-%d %H:%M:%S')
        closeDt = datetime.strptime(closeDate, '%Y-%m-%d %H:%M:%S')
        return int((closeDt - openDt).total_seconds())
    except:
        return None


def showImportSummary():
    """Show summary after import"""
    status = optimizer.getOptimizationStatus()
    
    print(f"\n📊 LEARNING DATABASE STATUS AFTER IMPORT:")
    print(f"   Total Positions: {status['totalPositions']}")
    print(f"   Win Rate: {status['currentWinRate']:.2%}")
    print(f"   Ready for Optimization: {'Yes ✅' if status['readyForOptimization'] else 'No ❌'}")
    
    if status['readyForOptimization']:
        print(f"   🚀 System is ready to optimize parameters!")
    else:
        needed = optimizer.minimumSampleSize - status['totalPositions']
        print(f"   ⏳ Need {needed} more positions for optimization")


if __name__ == "__main__":
    print("🔄 Importing historical trades into learning database...")
    count = importTradesCSVToLearning()
    
    if count > 0:
        showImportSummary()
        
        # Trigger optimization if ready
        if optimizer.shouldOptimize():
            print("\n🧠 Triggering initial optimization...")
            optimizer.runOptimization()
    else:
        print("❌ No trades were imported")
