#!/usr/bin/env python3
"""
Test script for intelligent optimizer with 50+ positions simulation
"""

import sys
import os
import json
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from intelligentOptimizer import optimizer
import gvars

def simulateOptimization():
    """Temporarily modify the minimum sample size to test optimization"""
    print("🧪 Testing optimization with current data...")
    
    # Backup original values
    originalMinimum = optimizer.minimumSampleSize
    originalFrequency = optimizer.optimizationFrequency
    
    try:
        # Temporarily set minimum to current count for testing
        currentCount = optimizer.learningDb["totalClosedPositions"]
        optimizer.minimumSampleSize = max(1, currentCount - 1)  # Set just below current count
        optimizer.optimizationFrequency = 1  # Optimize every position for testing
        
        print(f"📊 Current positions: {currentCount}")
        print(f"🎯 Temporary minimum set to: {optimizer.minimumSampleSize}")
        print(f"🔄 Temporary frequency set to: {optimizer.optimizationFrequency}")
        
        # Check if optimization should run
        if optimizer.shouldOptimize():
            print("✅ Optimization criteria met - running optimization...")
            optimizer.runOptimization()
        else:
            print("❌ Optimization criteria not met")
            
    except Exception as e:
        print(f"❌ Error during optimization test: {e}")
        
    finally:
        # Restore original values
        optimizer.minimumSampleSize = originalMinimum
        optimizer.optimizationFrequency = originalFrequency
        print(f"🔄 Restored minimum sample size to: {originalMinimum}")
        print(f"🔄 Restored optimization frequency to: {originalFrequency}")

def showOptimizationStatus():
    """Show current optimization status"""
    status = optimizer.getOptimizationStatus()
    
    print("\n" + "="*60)
    print("🧠 OPTIMIZATION TEST STATUS")
    print("="*60)
    print(f"📊 Total Positions: {status['totalPositions']}")
    print(f"🎯 Current Win Rate: {status['currentWinRate']:.2%}")
    print(f"⚙️  Learning Enabled: {'Yes ✅' if status['learningEnabled'] else 'No ❌'}")
    print(f"🚀 Ready for Optimization: {'Yes ✅' if status['readyForOptimization'] else 'No ❌'}")
    print(f"📅 Last Optimization: {status['lastOptimization'] or 'Never'}")
    print("="*60)

if __name__ == "__main__":
    print("🔬 INTELLIGENT OPTIMIZER TEST")
    print("="*60)
    
    showOptimizationStatus()
    
    print("\n🧪 Running optimization simulation...")
    simulateOptimization()
    
    print("\n📈 Final status:")
    showOptimizationStatus()
    
    print("\n✅ Test completed!")
