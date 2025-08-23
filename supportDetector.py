def findPossibleResistancesAndSupports(lows, closes, opens, tolerancePct, minSeparation, minTouches, closeViolationPct=0.02):
    """
    Detects possible support (long) and resistance (short) lines in a single pass.
    Returns a list of opportunities, each with type ('long' or 'short'), slope, intercept, touchCount, lineExp, bases, and validation flags.
    """
    n = len(lows)
    if n < minSeparation + 2:
        return []
    xIdx = np.arange(n)
    opportunities = []
    for i in range(n - minSeparation):
        for j in range(i + minSeparation, n):
            y1, y2 = lows[i], lows[j]
            x1, x2 = i, j
            slope = (y2 - y1) / (x2 - x1)
            intercept = y1 - slope * x1
            lineExp = slope * xIdx + intercept
            # Touches within tolerance
            touchMask = np.abs(lows - lineExp) <= np.abs(lineExp) * tolerancePct
            touchCount = int(touchMask.sum())
            if touchCount < minTouches:
                continue
            # Percentage of candles with close above/below the line
            closesAbove = closes > lineExp
            closesBelow = closes < lineExp
            ratioAbove = closesAbove.sum() / n
            ratioBelow = closesBelow.sum() / n
            violationRatio = min(ratioBelow, ratioAbove)
            # Soporte (long): slope positivo y % de velas por encima suficiente
            if slope > 0:
                # Últimas dos velas deben estar por encima de la línea
                if lows[-1] < lineExp[-1] or lows[-2] < lineExp[-2]:
                    continue
                # Rebote: dos velas verdes y cierre > línea * (1 + bouncePct)
                bounce = closes[-1] > opens[-1] and closes[-2] > opens[-2] and closes[-1] > closes[-2] and (closes[-1] - lineExp[-1]) / lineExp[-1] >= bouncePct
                if ratioAbove > 1 - closeViolationPct and bounce:
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
                        'minPctBounceAllowed': cfg.get('minPctBounceAllowed', 0.002),
                        'maxPctBounceAllowed': cfg.get('maxPctBounceAllowed', 0.002),
                    })
            # Resistencia (short): slope negativo y % de velas por debajo suficiente
            elif slope < 0:
                # Últimas dos velas deben estar por debajo de la línea
                if lows[-1] > lineExp[-1] or lows[-2] > lineExp[-2]:
                    continue
                # Rebote: dos velas rojas y cierre < línea * (1 - bouncePct)
                bounce = closes[-1] < opens[-1] and closes[-2] < opens[-2] and closes[-1] < closes[-2] and (lineExp[-1] - closes[-1]) / lineExp[-1] >= bouncePct
                if ratioBelow > 1 - closeViolationPct and bounce:
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
                        'minPctBounceAllowed': cfg.get('minPctBounceAllowed', 0.002),
                        'maxPctBounceAllowed': cfg.get('maxPctBounceAllowed', 0.002),
                    })
    return opportunities

# supportDetector.py
import json
import numpy as np
from gvars import configFile
from connector import loadConfig


cfg = loadConfig()
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
