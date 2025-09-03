def findPossibleResistancesAndSupports(lows, highs, closes, opens, tolerancePct, minSeparation, minTouches, closeViolationPct=0.02):
    """
    Detects possible support (long) and resistance (short) lines using improved algorithm.
    Detects both horizontal and diagonal lines with strict touch validation and noise allowance.
    Returns a list of opportunities, each with type ('long' or 'short'), slope, intercept, touchCount, lineExp, bases, and validation flags.
    """
    n = len(lows)
    if n < minSeparation + 2:
        return []
    
    xIdx = np.arange(n)
    allLines = []
    strictTolerancePct = 0.002  # Much stricter tolerance for real touches (0.2%)
    noiseThreshold = 0.10  # Allow 10% of early candles to be noise
    
    # 1. Find horizontal support lines
    horizontalSupports = _findHorizontalLines(lows, highs, closes, opens, 'support', xIdx, strictTolerancePct, noiseThreshold, minTouches, minSeparation)
    allLines.extend(horizontalSupports)
    
    # 2. Find horizontal resistance lines  
    horizontalResistances = _findHorizontalLines(lows, highs, closes, opens, 'resistance', xIdx, strictTolerancePct, noiseThreshold, minTouches, minSeparation)
    allLines.extend(horizontalResistances)
    
    # 3. Find diagonal support lines
    diagonalSupports = _findDiagonalLines(lows, highs, closes, opens, 'support', xIdx, strictTolerancePct, noiseThreshold, minTouches, minSeparation)
    allLines.extend(diagonalSupports)
    
    # 4. Find diagonal resistance lines
    diagonalResistances = _findDiagonalLines(lows, highs, closes, opens, 'resistance', xIdx, strictTolerancePct, noiseThreshold, minTouches, minSeparation)
    allLines.extend(diagonalResistances)
    
    # Sort by quality score and apply bounce validation
    allLines.sort(key=lambda x: x['qualityScore'], reverse=True)
    
    # Apply bounce validation to the best lines
    opportunities = []
    for line in allLines:
        if _validateBounce(line, lows, highs, closes, opens, n, strictTolerancePct):
            opportunities.append(line)
    
    return opportunities


def _findHorizontalLines(lows, highs, closes, opens, lineType, xIdx, strictTolerancePct, noiseThreshold, minTouches, minSeparation):
    """Find horizontal support or resistance lines"""
    lines = []
    n = len(lows)
    data = lows if lineType == 'support' else highs
    
    # Find potential horizontal levels by clustering similar price points
    priceClusters = _findPriceClusters(data, strictTolerancePct)
    
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
        
        if len(touchIndices) < minTouches:
            continue
        
        # Check line respect with noise allowance
        lineExp = np.full(n, level)
        respectScore = _calculateLineRespect(lineExp, lows, highs, closes, lineType, noiseThreshold)
        
        if respectScore['isValid']:
            qualityScore = _calculateQualityScore(len(touchIndices), respectScore, 0.0)  # slope = 0 for horizontal
            
            # Calculate ratios for compatibility
            closesAbove = closes > lineExp
            closesBelow = closes < lineExp
            ratioAbove = closesAbove.sum() / n
            ratioBelow = closesBelow.sum() / n
            
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
                'lineType': 'horizontal',
                'ratioAbove': ratioAbove,
                'ratioBelow': ratioBelow
            })
    
    return lines


def _findDiagonalLines(lows, highs, closes, opens, lineType, xIdx, strictTolerancePct, noiseThreshold, minTouches, minSeparation):
    """Find diagonal support or resistance lines"""
    lines = []
    n = len(lows)
    data = lows if lineType == 'support' else highs
    
    # Test diagonal lines between significant points
    for i in range(0, n - minSeparation):
        for j in range(i + minSeparation, n):
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
            
            if len(touchIndices) < minTouches:
                continue
            
            # Check line respect with noise allowance
            respectScore = _calculateLineRespect(lineExp, lows, highs, closes, lineType, noiseThreshold)
            
            if respectScore['isValid']:
                qualityScore = _calculateQualityScore(len(touchIndices), respectScore, abs(slope))
                
                # Calculate ratios for compatibility
                closesAbove = closes > lineExp
                closesBelow = closes < lineExp
                ratioAbove = closesAbove.sum() / n
                ratioBelow = closesBelow.sum() / n
                
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
                    'lineType': 'diagonal',
                    'ratioAbove': ratioAbove,
                    'ratioBelow': ratioBelow
                })
    
    return lines


def _findPriceClusters(data, tolerance):
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


def _calculateLineRespect(lineExp, lows, highs, closes, lineType, noiseThreshold):
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


def _calculateQualityScore(touchCount, respectScore, slope):
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


def _validateBounce(line, lows, highs, closes, opens, n, tolerancePct):
    """Apply bounce validation to a line (from original algorithm)"""
    lineExp = line['lineExp']
    lineType = line['type']
    
    if lineType == 'long':  # Support validation
        # Last two candles must be above the line (allow some tolerance)
        tolerance = abs(lineExp[-1]) * tolerancePct
        if lows[-1] < lineExp[-1] - tolerance or lows[-2] < lineExp[-2] - tolerance:
            return False
        
        # Check for bounce: touch + at least 1 green candle (more lenient)
        hasTouchToSupport = False
        for k in range(max(0, n-3), n):
            if (lows[k] <= lineExp[k] and 
                abs(lows[k] - lineExp[k]) <= abs(lineExp[k]) * tolerancePct):
                hasTouchToSupport = True
                break
        
        # More lenient bounce condition: at least 1 green candle
        hasGreenBounce = (closes[-1] > opens[-1] or closes[-2] > opens[-2])
        bounce = hasTouchToSupport and hasGreenBounce
        
        # More lenient ratio requirement
        if line['ratioAbove'] > 1 - 0.05 and bounce:  # Relaxed from 0.02 to 0.05
            line['bounce'] = bounce
            line['hasTouchToSupport'] = hasTouchToSupport
            line['hasGreenBounce'] = hasGreenBounce
            line['minPctBounceAllowed'] = cfg.get('minPctBounceAllowed', 0.002)
            line['maxPctBounceAllowed'] = cfg.get('maxPctBounceAllowed', 0.002)
            return True
    
    elif lineType == 'short':  # Resistance validation
        # Last two candles must be below the line
        if highs[-1] > lineExp[-1] or highs[-2] > lineExp[-2]:
            return False
        
        # Check for bounce: touch + 2 red candles
        hasTouchToResistance = False
        for k in range(max(0, n-3), n):
            if (highs[k] >= lineExp[k] and 
                abs(highs[k] - lineExp[k]) <= abs(lineExp[k]) * tolerancePct):
                hasTouchToResistance = True
                break
        
        hasRedBounce = (closes[-1] < opens[-1] and closes[-2] < opens[-2])
        bounce = hasTouchToResistance and hasRedBounce
        
        if line['ratioBelow'] > 1 - 0.02 and bounce:  # closeViolationPct = 0.02
            line['bounce'] = bounce
            line['hasTouchToResistance'] = hasTouchToResistance
            line['hasRedBounce'] = hasRedBounce
            line['minPctBounceAllowed'] = cfg.get('minPctBounceAllowed', 0.002)
            line['maxPctBounceAllowed'] = cfg.get('maxPctBounceAllowed', 0.002)
            return True
    
    return False

# supportDetector.py
import json
import numpy as np
from gvars import configFile
from configManager import configManager

cfg = configManager.config
tolerancePct = cfg['tolerancePct']
# bouncePct = cfg['bouncePct']
bouncePct = cfg['minPctBounceAllowed']
# Fixed: max % of closes below support line allowed (close violation percent)
closeViolationPct = 0.02  # 2%


def findSupportLine(
    lows: np.ndarray,
    closes: np.ndarray,
    opens: np.ndarray,
    tolerancePct: float,
    minSeparation: int,
    minTouches: int
):
    """
    Detect the best support line based on:
    1) Minimal close violations
    2) Max touch count
    3) Highest slope (if tie)
    Final candidate must also:
    - Have last 2 lows above line
    - Be followed by a real rebound (2 green candles, close > prev, close > line * (1 + bouncePct))
    """

    n = len(lows)
    if n < minSeparation + 2:
        return 0.0, 0.0, 0, np.zeros(n), []

    xIdx = np.arange(n)
    bestLine = None

    for i in range(n - minSeparation):
        for j in range(i + minSeparation, n):
            y1, y2 = lows[i], lows[j]
            x1, x2 = i, j

            slope = (y2 - y1) / (x2 - x1)
            if slope <= 0: continue

            intercept = y1 - slope * x1
            lineExp = slope * xIdx + intercept

            # Skip si alguno de los dos puntos cae por debajo
            if lows[-1] < lineExp[-1] or lows[-2] < lineExp[-2]:
                continue

            # Percentage of candles with close below the support line (close violation)
            closeViolations = closes < lineExp
            violationRatio = closeViolations.sum() / n
            if violationRatio > closeViolationPct:
                continue

            # Touches within tolerance: use the support line value at each candle, not the lowest low
            touchMask = np.abs(lows - lineExp) <= lineExp * tolerancePct
            touchCount = int(touchMask.sum())
            if touchCount < minTouches:
                continue

            # Cierre actual debe superar la línea en bouncePct
            if not (closes[-1] > opens[-1] and closes[-2] > opens[-2]):
                continue
            if closes[-1] <= closes[-2]:
                continue
            if (closes[-1] - lineExp[-1]) / lineExp[-1] < bouncePct:
                continue

            scoreTuple = (violationRatio, -touchCount, -slope)
            if not bestLine or scoreTuple < bestLine['score']:
                bestLine = {
                    'slope': slope,
                    'intercept': intercept,
                    'touchCount': touchCount,
                    'lineExp': lineExp,
                    'bases': [i, j],
                    'score': scoreTuple
                }

    if not bestLine:
        # Buscar la mejor línea candidata aunque no cumpla todos los criterios
        # Recorrer de nuevo y guardar la de mayor touchCount
        maxTouches = 0
        candidate = None
        for i in range(n - minSeparation):
            for j in range(i + minSeparation, n):
                y1, y2 = lows[i], lows[j]
                x1, x2 = i, j
                slope = (y2 - y1) / (x2 - x1)
                intercept = y1 - slope * x1
                lineExp = slope * xIdx + intercept
                touchMask = np.abs(lows - lineExp) <= np.abs(lineExp) * tolerancePct
                touchCount = int(touchMask.sum())
                if touchCount > maxTouches:
                    maxTouches = touchCount
                    candidate = {
                        'slope': slope,
                        'intercept': intercept,
                        'touchCount': touchCount,
                        'lineExp': lineExp,
                        'bases': [i, j]
                    }
        if candidate:
            return (
                candidate['slope'],
                candidate['intercept'],
                candidate['touchCount'],
                candidate['lineExp'],
                candidate['bases']
            )
        else:
            return 0.0, 0.0, 0, np.zeros(n), []

    return (
        bestLine['slope'],
        bestLine['intercept'],
        bestLine['touchCount'],
        bestLine['lineExp'],
        bestLine['bases']
    )
