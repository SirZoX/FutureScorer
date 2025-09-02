#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autonomous Support/Resistance Testing Tool
100% independent file for testing and adjusting support/resistance detection
"""

import os
import sys
import json
import time
import ccxt
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import required modules
from connector import bingxConnector
from configManager import configManager
from logManager import messages

class SupportResistanceTester:
    def __init__(self):
        """Initialize the tester with exchange connection and config"""
        self.exchange = bingxConnector()
        self.config = configManager.config
        self.rate_limiter = RateLimiter(max_calls=20, period=1.0)
        
        # Test parameters
        self.timeframe = "15m"
        self.requestedCandles = 180
        self.tolerancePct = 0.0075
        self.minTouches = 3
        self.minSeparation = 36
        self.closeViolationPct = 0.02
        
        # Output directory
        self.plotsDir = os.path.join(os.path.dirname(__file__), "plotsTest")
        if not os.path.exists(self.plotsDir):
            os.makedirs(self.plotsDir)
    
    def getTop25Pairs(self):
        """Get top 25 trading pairs by volume"""
        try:
            # Load markets data
            with open(os.path.join(os.path.dirname(__file__), "..", "_files", "config", "markets.json"), encoding='utf-8') as f:
                markets = json.load(f)
            
            # Filter futures pairs and get top 25 by volume
            futuresPairs = []
            for symbol, info in markets.items():
                if (info.get('type') == 'swap' and 
                    info.get('active', False) and 
                    symbol.endswith('USDT:USDT') and
                    info.get('info', {}).get('status') == '1'):
                    futuresPairs.append(symbol)
            
            # Take first 25 (they should be ordered by volume already)
            return futuresPairs[:25]
            
        except Exception as e:
            messages(f"Error getting top pairs: {e}", console=1, log=1, telegram=0)
            return []
    
    def downloadOHLCV(self, symbol):
        """Download OHLCV data for a symbol"""
        try:
            self.rate_limiter.acquire()
            ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, None, self.requestedCandles)
            
            if ohlcv and len(ohlcv) > 0:
                df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                
                # Save to CSV
                csvFileName = f"{symbol.replace('/', '_').replace(':', '_')}_{self.timeframe}_{self.requestedCandles}.csv"
                csvPath = os.path.join(self.plotsDir, csvFileName)
                df.to_csv(csvPath, index=False)
                
                return csvPath, df
            else:
                return None, None
                
        except Exception as e:
            messages(f"Error downloading {symbol}: {e}", console=1, log=1, telegram=0)
            return None, None
    
    def findBestSupportResistanceLines(self, lows, highs, closes, opens):
        """
        Find the best support/resistance lines with improved algorithm
        Detects both horizontal and diagonal lines with strict touch validation
        """
        n = len(lows)
        if n < self.minSeparation + 2:
            return []
        
        xIdx = np.arange(n)
        allLines = []
        strictTolerancePct = 0.002  # Much stricter tolerance for real touches (0.2%)
        noiseThreshold = 0.10  # Allow 10% of early candles to be noise
        
        # 1. Find horizontal support lines
        horizontalSupports = self._findHorizontalLines(lows, highs, closes, opens, 'support', xIdx, strictTolerancePct, noiseThreshold)
        allLines.extend(horizontalSupports)
        
        # 2. Find horizontal resistance lines  
        horizontalResistances = self._findHorizontalLines(lows, highs, closes, opens, 'resistance', xIdx, strictTolerancePct, noiseThreshold)
        allLines.extend(horizontalResistances)
        
        # 3. Find diagonal support lines
        diagonalSupports = self._findDiagonalLines(lows, highs, closes, opens, 'support', xIdx, strictTolerancePct, noiseThreshold)
        allLines.extend(diagonalSupports)
        
        # 4. Find diagonal resistance lines
        diagonalResistances = self._findDiagonalLines(lows, highs, closes, opens, 'resistance', xIdx, strictTolerancePct, noiseThreshold)
        allLines.extend(diagonalResistances)
        
        # Sort by quality score and return best ones
        allLines.sort(key=lambda x: x['qualityScore'], reverse=True)
        return allLines
    
    def _findHorizontalLines(self, lows, highs, closes, opens, lineType, xIdx, strictTolerancePct, noiseThreshold):
        """Find horizontal support or resistance lines"""
        lines = []
        n = len(lows)
        data = lows if lineType == 'support' else highs
        
        # Find potential horizontal levels by clustering similar price points
        priceClusters = self._findPriceClusters(data, strictTolerancePct)
        
        for level in priceClusters:
            if lineType == 'support':
                # For support, count touches where low touches the level
                touchIndices = []
                for i in range(n):
                    if abs(lows[i] - level) <= level * strictTolerancePct:
                        touchIndices.append(i)
            else:
                # For resistance, count touches where high touches the level
                touchIndices = []
                for i in range(n):
                    if abs(highs[i] - level) <= level * strictTolerancePct:
                        touchIndices.append(i)
            
            if len(touchIndices) < self.minTouches:
                continue
            
            # Check line respect with noise allowance
            lineExp = np.full(n, level)
            respectScore = self._calculateLineRespect(lineExp, lows, highs, closes, lineType, noiseThreshold)
            
            if respectScore['isValid']:
                qualityScore = self._calculateQualityScore(len(touchIndices), respectScore, 0.0)  # slope = 0 for horizontal
                
                lines.append({
                    'type': 'long' if lineType == 'support' else 'short',
                    'slope': 0.0,
                    'intercept': level,
                    'touchCount': len(touchIndices),
                    'lineExp': lineExp,
                    'bases': [touchIndices[0], touchIndices[-1]] if touchIndices else [0, n-1],
                    'touchIndices': touchIndices,
                    'respectScore': respectScore,
                    'qualityScore': qualityScore,
                    'lineType': 'horizontal'
                })
        
        return lines
    
    def _findDiagonalLines(self, lows, highs, closes, opens, lineType, xIdx, strictTolerancePct, noiseThreshold):
        """Find diagonal support or resistance lines"""
        lines = []
        n = len(lows)
        data = lows if lineType == 'support' else highs
        
        # Test diagonal lines between significant points
        for i in range(0, n - self.minSeparation):
            for j in range(i + self.minSeparation, n):
                y1, y2 = data[i], data[j]
                x1, x2 = i, j
                
                slope = (y2 - y1) / (x2 - x1)
                
                # Filter by slope direction
                if lineType == 'support' and slope < 0:
                    continue  # Support lines should be ascending or flat
                if lineType == 'resistance' and slope > 0:
                    continue  # Resistance lines should be descending or flat
                
                intercept = y1 - slope * x1
                lineExp = slope * xIdx + intercept
                
                # Count real touches (very strict)
                touchIndices = []
                for k in range(n):
                    if lineType == 'support':
                        if abs(lows[k] - lineExp[k]) <= abs(lineExp[k]) * strictTolerancePct:
                            touchIndices.append(k)
                    else:
                        if abs(highs[k] - lineExp[k]) <= abs(lineExp[k]) * strictTolerancePct:
                            touchIndices.append(k)
                
                if len(touchIndices) < self.minTouches:
                    continue
                
                # Check line respect with noise allowance
                respectScore = self._calculateLineRespect(lineExp, lows, highs, closes, lineType, noiseThreshold)
                
                if respectScore['isValid']:
                    qualityScore = self._calculateQualityScore(len(touchIndices), respectScore, abs(slope))
                    
                    lines.append({
                        'type': 'long' if lineType == 'support' else 'short',
                        'slope': slope,
                        'intercept': intercept,
                        'touchCount': len(touchIndices),
                        'lineExp': lineExp,
                        'bases': [i, j],
                        'touchIndices': touchIndices,
                        'respectScore': respectScore,
                        'qualityScore': qualityScore,
                        'lineType': 'diagonal'
                    })
        
        return lines
    
    def _findPriceClusters(self, data, tolerance):
        """Find price levels where multiple data points cluster together"""
        clusters = []
        sorted_prices = sorted(set(data))
        
        i = 0
        while i < len(sorted_prices):
            cluster_prices = [sorted_prices[i]]
            j = i + 1
            
            # Group nearby prices into same cluster
            while j < len(sorted_prices) and sorted_prices[j] - sorted_prices[i] <= sorted_prices[i] * tolerance * 2:
                cluster_prices.append(sorted_prices[j])
                j += 1
            
            # Only consider clusters with multiple price points
            if len(cluster_prices) >= 2:
                clusters.append(sum(cluster_prices) / len(cluster_prices))  # Average price of cluster
            
            i = j
        
        return clusters
    
    def _calculateLineRespect(self, lineExp, lows, highs, closes, lineType, noiseThreshold):
        """Calculate how well the line is respected with noise allowance"""
        n = len(lineExp)
        
        if lineType == 'support':
            # For support: lows should not pierce below line (except initial noise)
            violations = lows < lineExp
        else:
            # For resistance: highs should not pierce above line (except initial noise)
            violations = highs > lineExp
        
        # Allow noise in the first portion of the data
        noiseAllowedCandles = int(n * noiseThreshold)
        violationsAfterNoise = violations[noiseAllowedCandles:]
        
        totalViolations = violations.sum()
        significantViolations = violationsAfterNoise.sum()
        violationRatio = significantViolations / (n - noiseAllowedCandles) if n > noiseAllowedCandles else totalViolations / n
        
        # Line is valid if violation ratio is very low
        isValid = violationRatio <= 0.05  # Allow max 5% violations after noise period
        
        return {
            'isValid': isValid,
            'violationRatio': violationRatio,
            'totalViolations': totalViolations,
            'significantViolations': significantViolations,
            'noiseViolations': totalViolations - significantViolations
        }
    
    def _calculateQualityScore(self, touchCount, respectScore, slope):
        """Calculate overall quality score for a line"""
        # Base score from touches
        touchScore = touchCount * 10
        
        # Penalty for violations (heavy penalty)
        violationPenalty = respectScore['violationRatio'] * 100
        
        # Slight preference for horizontal lines (easier to trade)
        slopePenalty = abs(slope) * 5
        
        # Bonus for very few violations
        if respectScore['violationRatio'] < 0.01:
            violationBonus = 20
        else:
            violationBonus = 0
        
        qualityScore = touchScore - violationPenalty - slopePenalty + violationBonus
        
        return max(0, qualityScore)  # Ensure non-negative score
    
    def findPossibleResistancesAndSupports(self, lows, highs, closes, opens):
        """
        Original method for finding opportunities with strict bounce criteria
        Keep this for future transfer to production code
        """
        n = len(lows)
        if n < self.minSeparation + 2:
            return []
        
        xIdx = np.arange(n)
        opportunities = []
        
        for i in range(n - self.minSeparation):
            for j in range(i + self.minSeparation, n):
                y1, y2 = lows[i], lows[j]
                x1, x2 = i, j
                slope = (y2 - y1) / (x2 - x1)
                intercept = y1 - slope * x1
                lineExp = slope * xIdx + intercept
                
                # Determine if this is support (positive slope) or resistance (negative slope)
                if slope > 0:
                    # Support line - use lows for touches
                    touchMask = np.abs(lows - lineExp) <= np.abs(lineExp) * self.tolerancePct
                else:
                    # Resistance line - use highs for touches  
                    touchMask = np.abs(highs - lineExp) <= np.abs(lineExp) * self.tolerancePct
                    
                touchCount = int(touchMask.sum())
                if touchCount < self.minTouches:
                    continue
                
                # Improve line calculation: adjust to pass closer to recent bounce points
                recentTouchIdx = None
                recentTouchValue = None
                
                if slope > 0:  # Support line
                    # For support, look for candles that touch or pierce the line
                    for k in range(max(0, n-5), n):
                        if lows[k] <= lineExp[k] and np.abs(lows[k] - lineExp[k]) <= np.abs(lineExp[k]) * self.tolerancePct:
                            recentTouchIdx = k
                            # Use the open price of the bounce candle for better line fitting
                            if closes[k] > opens[k]:  # Green candle
                                recentTouchValue = opens[k]
                            else:
                                recentTouchValue = lows[k]  # Use low if red candle
                            break
                else:  # Resistance line
                    for k in range(max(0, n-5), n):
                        if highs[k] >= lineExp[k] and np.abs(highs[k] - lineExp[k]) <= np.abs(lineExp[k]) * self.tolerancePct:
                            recentTouchIdx = k
                            if closes[k] < opens[k]:  # Red candle
                                recentTouchValue = opens[k]
                            else:
                                recentTouchValue = highs[k]  # Use high if green candle
                            break
                
                # If we found a recent touch, adjust the line
                if recentTouchIdx is not None and recentTouchIdx != j and recentTouchValue is not None:
                    y1, y2 = lows[i], recentTouchValue
                    x1, x2 = i, recentTouchIdx
                    
                    if x2 != x1:
                        slope = (y2 - y1) / (x2 - x1)
                        intercept = y1 - slope * x1
                        lineExp = slope * xIdx + intercept
                        
                        # Recalculate touches with adjusted line
                        if slope > 0:
                            touchMask = np.abs(lows - lineExp) <= np.abs(lineExp) * self.tolerancePct
                        else:
                            touchMask = np.abs(highs - lineExp) <= np.abs(lineExp) * self.tolerancePct
                        touchCount = int(touchMask.sum())
                
                # Percentage of candles with close above/below the line
                closesAbove = closes > lineExp
                closesBelow = closes < lineExp
                ratioAbove = closesAbove.sum() / n
                ratioBelow = closesBelow.sum() / n
                
                # Support validation with strict bounce criteria
                if slope > 0:
                    # Last two candles must be above the line
                    if lows[-1] < lineExp[-1] or lows[-2] < lineExp[-2]:
                        continue
                    
                    # Check for bounce: touch + 2 green candles
                    hasTouchToSupport = False
                    for k in range(max(0, n-3), n):
                        if (lows[k] <= lineExp[k] and 
                            abs(lows[k] - lineExp[k]) <= abs(lineExp[k]) * self.tolerancePct):
                            hasTouchToSupport = True
                            break
                    
                    hasGreenBounce = (closes[-1] > opens[-1] and closes[-2] > opens[-2])
                    bounce = hasTouchToSupport and hasGreenBounce
                    
                    if ratioAbove > 1 - self.closeViolationPct and bounce:
                        opportunities.append({
                            'type': 'long',
                            'slope': slope,
                            'intercept': intercept,
                            'touchCount': touchCount,
                            'lineExp': lineExp,
                            'bases': [i, j],
                            'ratioAbove': ratioAbove,
                            'ratioBelow': ratioBelow,
                            'bounce': bounce,
                            'recentTouchIdx': recentTouchIdx,
                            'recentTouchValue': recentTouchValue
                        })
                
                # Resistance validation with strict bounce criteria
                elif slope < 0:
                    # Last two candles must be below the line
                    if highs[-1] > lineExp[-1] or highs[-2] > lineExp[-2]:
                        continue
                    
                    # Check for bounce: touch + 2 red candles
                    hasTouchToResistance = False
                    for k in range(max(0, n-3), n):
                        if (highs[k] >= lineExp[k] and 
                            abs(highs[k] - lineExp[k]) <= abs(lineExp[k]) * self.tolerancePct):
                            hasTouchToResistance = True
                            break
                    
                    hasRedBounce = (closes[-1] < opens[-1] and closes[-2] < opens[-2])
                    bounce = hasTouchToResistance and hasRedBounce
                    
                    if ratioBelow > 1 - self.closeViolationPct and bounce:
                        opportunities.append({
                            'type': 'short',
                            'slope': slope,
                            'intercept': intercept,
                            'touchCount': touchCount,
                            'lineExp': lineExp,
                            'bases': [i, j],
                            'ratioAbove': ratioAbove,
                            'ratioBelow': ratioBelow,
                            'bounce': bounce,
                            'recentTouchIdx': recentTouchIdx,
                            'recentTouchValue': recentTouchValue
                        })
        
        return opportunities
        """
        Improved support/resistance detection with better line fitting
        """
        n = len(lows)
        if n < self.minSeparation + 2:
            return []
        
        xIdx = np.arange(n)
        opportunities = []
        
        for i in range(n - self.minSeparation):
            for j in range(i + self.minSeparation, n):
                y1, y2 = lows[i], lows[j]
                x1, x2 = i, j
                slope = (y2 - y1) / (x2 - x1)
                intercept = y1 - slope * x1
                lineExp = slope * xIdx + intercept
                
                # Determine if this is support (positive slope) or resistance (negative slope)
                if slope > 0:
                    # Support line - use lows for touches
                    touchMask = np.abs(lows - lineExp) <= np.abs(lineExp) * self.tolerancePct
                else:
                    # Resistance line - use highs for touches  
                    touchMask = np.abs(highs - lineExp) <= np.abs(lineExp) * self.tolerancePct
                    
                touchCount = int(touchMask.sum())
                if touchCount < self.minTouches:
                    continue
                
                # Improve line calculation: adjust to pass closer to recent bounce points
                recentTouchIdx = None
                recentTouchValue = None
                
                if slope > 0:  # Support line
                    # For support, look for candles that touch or pierce the line
                    for k in range(max(0, n-5), n):
                        if lows[k] <= lineExp[k] and np.abs(lows[k] - lineExp[k]) <= np.abs(lineExp[k]) * self.tolerancePct:
                            recentTouchIdx = k
                            # Use the open price of the bounce candle for better line fitting
                            if closes[k] > opens[k]:  # Green candle
                                recentTouchValue = opens[k]
                            else:
                                recentTouchValue = lows[k]  # Use low if red candle
                            break
                else:  # Resistance line
                    for k in range(max(0, n-5), n):
                        if highs[k] >= lineExp[k] and np.abs(highs[k] - lineExp[k]) <= np.abs(lineExp[k]) * self.tolerancePct:
                            recentTouchIdx = k
                            if closes[k] < opens[k]:  # Red candle
                                recentTouchValue = opens[k]
                            else:
                                recentTouchValue = highs[k]  # Use high if green candle
                            break
                
                # If we found a recent touch, adjust the line
                if recentTouchIdx is not None and recentTouchIdx != j and recentTouchValue is not None:
                    y1, y2 = lows[i], recentTouchValue
                    x1, x2 = i, recentTouchIdx
                    
                    if x2 != x1:
                        slope = (y2 - y1) / (x2 - x1)
                        intercept = y1 - slope * x1
                        lineExp = slope * xIdx + intercept
                        
                        # Recalculate touches with adjusted line
                        if slope > 0:
                            touchMask = np.abs(lows - lineExp) <= np.abs(lineExp) * self.tolerancePct
                        else:
                            touchMask = np.abs(highs - lineExp) <= np.abs(lineExp) * self.tolerancePct
                        touchCount = int(touchMask.sum())
                
                # Percentage of candles with close above/below the line
                closesAbove = closes > lineExp
                closesBelow = closes < lineExp
                ratioAbove = closesAbove.sum() / n
                ratioBelow = closesBelow.sum() / n
                
                # Support validation
                if slope > 0:
                    # Last two candles must be above the line
                    if lows[-1] < lineExp[-1] or lows[-2] < lineExp[-2]:
                        continue
                    
                    # Check for bounce: touch + 2 green candles
                    hasTouchToSupport = False
                    for k in range(max(0, n-3), n):
                        if (lows[k] <= lineExp[k] and 
                            abs(lows[k] - lineExp[k]) <= abs(lineExp[k]) * self.tolerancePct):
                            hasTouchToSupport = True
                            break
                    
                    hasGreenBounce = (closes[-1] > opens[-1] and closes[-2] > opens[-2])
                    bounce = hasTouchToSupport and hasGreenBounce
                    
                    if ratioAbove > 1 - self.closeViolationPct and bounce:
                        opportunities.append({
                            'type': 'long',
                            'slope': slope,
                            'intercept': intercept,
                            'touchCount': touchCount,
                            'lineExp': lineExp,
                            'bases': [i, j],
                            'ratioAbove': ratioAbove,
                            'ratioBelow': ratioBelow,
                            'bounce': bounce,
                            'recentTouchIdx': recentTouchIdx,
                            'recentTouchValue': recentTouchValue
                        })
                
                # Resistance validation
                elif slope < 0:
                    # Last two candles must be below the line
                    if highs[-1] > lineExp[-1] or highs[-2] > lineExp[-2]:
                        continue
                    
                    # Check for bounce: touch + 2 red candles
                    hasTouchToResistance = False
                    for k in range(max(0, n-3), n):
                        if (highs[k] >= lineExp[k] and 
                            abs(highs[k] - lineExp[k]) <= abs(lineExp[k]) * self.tolerancePct):
                            hasTouchToResistance = True
                            break
                    
                    hasRedBounce = (closes[-1] < opens[-1] and closes[-2] < opens[-2])
                    bounce = hasTouchToResistance and hasRedBounce
                    
                    if ratioBelow > 1 - self.closeViolationPct and bounce:
                        opportunities.append({
                            'type': 'short',
                            'slope': slope,
                            'intercept': intercept,
                            'touchCount': touchCount,
                            'lineExp': lineExp,
                            'bases': [i, j],
                            'ratioAbove': ratioAbove,
                            'ratioBelow': ratioBelow,
                            'bounce': bounce,
                            'recentTouchIdx': recentTouchIdx,
                            'recentTouchValue': recentTouchValue
                        })
        
        return opportunities
    
    def generatePlot(self, symbol, df, opportunities):
        """Generate plot for a symbol with detected opportunities"""
        try:
            if df is None or len(df) == 0 or len(opportunities) == 0:
                return
            
            # Take the best opportunity (first one)
            opp = opportunities[0]
            
            # Create plot
            fig, ax = plt.subplots(figsize=(15, 8))
            
            # Convert timestamps for plotting
            df['timestampNum'] = mdates.date2num(df['timestamp'])
            
            # Create candlestick data
            candlestick_data = []
            for idx, row in df.iterrows():
                candlestick_data.append([
                    row['timestampNum'], row['open'], row['high'], row['low'], row['close']
                ])
            
            # Plot candlesticks manually
            for i, (t, o, h, l, c) in enumerate(candlestick_data):
                color = 'green' if c >= o else 'red'
                ax.plot([t, t], [l, h], color='black', linewidth=0.5)
                ax.add_patch(plt.Rectangle((t - 0.0008, min(o, c)), 0.0016, abs(c - o), 
                                         facecolor=color, edgecolor='black', linewidth=0.5))
            
            # Plot support/resistance line
            lineColor = 'orange' if opp['type'] == 'long' else 'purple'
            lineLabel = 'Support Line' if opp['type'] == 'long' else 'Resistance Line'
            ax.plot(df['timestampNum'], opp['lineExp'], color=lineColor, linewidth=2, label=lineLabel)
            
            # Mark all touch points with circles
            if 'touchIndices' in opp and opp['touchIndices']:
                touchTimes = []
                touchPrices = []
                
                for touchIdx in opp['touchIndices']:
                    touchTimes.append(df['timestampNum'].iloc[touchIdx])
                    
                    # Use the appropriate price for the touch (low for support, high for resistance)
                    if opp['type'] == 'long':
                        touchPrices.append(df['low'].iloc[touchIdx])
                    else:
                        touchPrices.append(df['high'].iloc[touchIdx])
                
                # Plot touch points as purple circles
                ax.scatter(touchTimes, touchPrices, color='purple', s=100, 
                          edgecolors='black', linewidth=2, label='Line Touches', marker='o')
            
            # Mark base points (if using diagonal lines)
            if 'bases' in opp and opp['lineType'] == 'diagonal':
                bases = opp['bases']
                if opp['type'] == 'long':
                    basePrice1 = df['low'].iloc[bases[0]]
                    basePrice2 = df['low'].iloc[bases[1]]
                else:
                    basePrice1 = df['high'].iloc[bases[0]]
                    basePrice2 = df['high'].iloc[bases[1]]
                    
                ax.plot(df['timestampNum'].iloc[bases[0]], basePrice1, 'bo', markersize=8, label='Base Points')
                ax.plot(df['timestampNum'].iloc[bases[1]], basePrice2, 'bo', markersize=8)
            
            # Add quality information to title
            respectInfo = ""
            if 'respectScore' in opp:
                respectInfo = f" - Violations: {opp['respectScore']['violationRatio']:.1%}"
            
            qualityInfo = ""
            if 'qualityScore' in opp:
                qualityInfo = f" - Quality: {opp['qualityScore']:.1f}"
                
            lineTypeInfo = f" - {opp.get('lineType', 'unknown').title()}"
            
            # Format plot
            ax.set_title(f"{symbol} - {opp['type'].upper()} - Touches: {opp['touchCount']}{lineTypeInfo}{respectInfo}{qualityInfo}")
            ax.set_xlabel('Date')
            ax.set_ylabel('Price')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            # Format x-axis
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
            plt.xticks(rotation=45)
            
            # Save plot
            plotFileName = f"{symbol.replace('/', '_').replace(':', '_')}_{opp['type']}.png"
            plotPath = os.path.join(self.plotsDir, plotFileName)
            plt.tight_layout()
            plt.savefig(plotPath, dpi=150, bbox_inches='tight')
            plt.close()
            
            messages(f"Plot saved: {plotFileName}", console=1, log=0, telegram=0)
            
        except Exception as e:
            messages(f"Error generating plot for {symbol}: {e}", console=1, log=1, telegram=0)
    
    def analyzeSymbol(self, symbol):
        """Analyze a single symbol and always generate a plot with the best line found"""
        try:
            messages(f"Analyzing {symbol}...", console=1, log=0, telegram=0)
            
            # Download data
            csvPath, df = self.downloadOHLCV(symbol)
            if df is None:
                return None
            
            # Filter outliers
            q_low, q_high = df['low'].quantile(0.01), df['low'].quantile(0.99)
            df = df[(df['low'] >= q_low) & (df['low'] <= q_high)].reset_index(drop=True)
            
            # Find best support/resistance lines (always returns something if data is valid)
            allLines = self.findBestSupportResistanceLines(
                df["low"].values,
                df["high"].values, 
                df["close"].values,
                df["open"].values
            )
            
            if allLines:
                # Generate plot for best line found
                self.generatePlot(symbol, df, [allLines[0]])  # Pass best line as list
                messages(f"Plot generated for {symbol} - Best line: {allLines[0]['type']} with {allLines[0]['touchCount']} touches", console=1, log=0, telegram=0)
                
                # Also check for opportunities using original method (keep for future transfer)
                opportunities = self.findPossibleResistancesAndSupports(
                    df["low"].values,
                    df["high"].values, 
                    df["close"].values,
                    df["open"].values
                )
                
                return len(opportunities)  # Return opportunity count for stats
            else:
                messages(f"No valid lines found for {symbol}", console=1, log=0, telegram=0)
                return 0
                
        except Exception as e:
            messages(f"Error analyzing {symbol}: {e}", console=1, log=1, telegram=0)
            return None
    
    def run(self):
        """Main execution function"""
        messages("Starting Support/Resistance Testing Tool", console=1, log=1, telegram=0)
        
        # Clean plots directory
        for file in os.listdir(self.plotsDir):
            if file.endswith(('.png', '.csv')):
                os.remove(os.path.join(self.plotsDir, file))
        
        # Get top 25 pairs
        pairs = self.getTop25Pairs()
        if not pairs:
            messages("No pairs found", console=1, log=1, telegram=0)
            return
        
        messages(f"Found {len(pairs)} pairs to analyze", console=1, log=1, telegram=0)
        
        # Analyze pairs
        totalOpportunities = 0
        successfulAnalyses = 0
        
        for symbol in pairs:
            time.sleep(0.3)  # Rate limiting
            result = self.analyzeSymbol(symbol)
            if result is not None:
                successfulAnalyses += 1
                totalOpportunities += result
        
        messages(f"Analysis complete. Processed {successfulAnalyses}/{len(pairs)} pairs", console=1, log=1, telegram=0)
        messages(f"Total opportunities found: {totalOpportunities}", console=1, log=1, telegram=0)
        messages(f"Plots saved to: {self.plotsDir}", console=1, log=1, telegram=0)

# Rate limiter class
class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            while self.calls and self.calls[0] <= now - self.period:
                self.calls.pop(0)
            if len(self.calls) >= self.max_calls:
                to_sleep = self.period - (now - self.calls[0])
                time.sleep(to_sleep)
            self.calls.append(time.time())

# Main execution
if __name__ == "__main__":
    tester = SupportResistanceTester()
    tester.run()
