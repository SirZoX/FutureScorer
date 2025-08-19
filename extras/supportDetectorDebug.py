# supportDetectorDebug.py

import numpy as np

def findSupportLine(lows, closes, opens, tolerancePct, minSeparation, minTouches):
    bestLine = None
    bestScore = -np.inf
    allLines = []

    length = len(lows)
    lowestIdx = int(np.argmin(lows))
    timestamps = np.arange(length)

    for j in range(lowestIdx + minSeparation, length):
        x1, y1 = timestamps[lowestIdx], lows[lowestIdx]
        x2, y2 = timestamps[j], lows[j]

        slope = (y2 - y1) / (x2 - x1)
        intercept = y1 - slope * x1
        lineExp = slope * timestamps + intercept

        # REGLA 1: máximo 5% de cierres por debajo
        closeBelow = np.sum(closes < lineExp)
        if closeBelow / length > 0.05: continue

        # Calcular toques (close cerca de la línea)
        tolerance = lineExp * tolerancePct
        touches = np.sum(np.abs(lows - lineExp) <= tolerance)

        # Calcular score ponderado
        touchScore = touches / length
        slopeScore = slope
        belowPct = closeBelow / length
        score = (1 - belowPct) * 0.5 + touchScore * 0.3 + slopeScore * 0.2

        currentLine = {
            'slope': slope,
            'intercept': intercept,
            'lineExp': lineExp,
            'touchCount': touches,
            'score': score,
            'bases': (lowestIdx, j),
            'belowRatio': belowPct
        }
        allLines.append(currentLine)

        if score > bestScore:
            bestScore = score
            bestLine = currentLine

    if bestLine:
        print(f"✅ Best line i={bestLine['bases'][0]}, j={bestLine['bases'][1]}, touches={bestLine['touchCount']}, belowRatio={bestLine['belowRatio']:.3f}, score={bestLine['score']:.4f}")

    return bestLine['slope'], bestLine['intercept'], bestLine['score'], bestLine['lineExp'], bestLine['bases'], allLines
