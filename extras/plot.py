# plotPrint.py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import json
from supportDetectorDebug import findSupportLine


# Load config
with open('_files/config/config.json', encoding='utf-8') as cfgFile:
    config = json.load(cfgFile)

tolerancePct = config['tolerancePct']  # Tolerance percentage for support detection
minPctBounceAllowed = config['minPctBounceAllowed']  # Minimum allowed bounce percentage
maxPctBounceAllowed = config['maxPctBounceAllowed']  # Maximum allowed bounce percentage
minTouches = config['minTouches']  # Minimum number of touches for a valid support line
minCandlesSeparationToFindSupportLine = config['minCandlesSeparationToFindSupportLine']  # Minimum candle separation for support line detection

# Ask CSV file name
fileName = input("Enter CSV filename (without .csv): ").strip()
filePath = f"_files/csv/{fileName}.csv"

# Load data
df = pd.read_csv(filePath, parse_dates=['timestamp'])
df['dateNum'] = mdates.date2num(df['timestamp'])

lows = df['low'].values
closes = df['close'].values
opens = df['open'].values
dates = df['dateNum'].values

# Prepare plot
fig, ax = plt.subplots(figsize=(14, 6))
barWidth = (dates[1] - dates[0]) * 0.4  # Width of each candlestick bar

for i in range(len(df)):
    color = 'green' if closes[i] >= opens[i] else 'red'
    ax.plot([dates[i], dates[i]], [df['low'][i], df['high'][i]], color=color, linewidth=1)
    ax.add_patch(plt.Rectangle(
        (dates[i] - barWidth / 2, min(opens[i], closes[i])),
        barWidth,
        abs(opens[i] - closes[i]),
        color=color,
        label='_nolegend_'
    ))

# Run detector
slope, intercept, score, supportLine, bases, allLines = findSupportLine(
    lows, closes, opens, tolerancePct, minCandlesSeparationToFindSupportLine, minTouches
)

# Get lowest low index
lowestIdx = int(np.argmin(lows))  # Index of the lowest low

# Filter: only lines with base point 1 at lowestIdx
validLines = [line for line in allLines if line['bases'][0] == lowestIdx]  # Only lines with first base at lowestIdx

# Pick best from valid lines
bestLine = None
for line in validLines:
    if not bestLine or (
        line['belowRatio'] < bestLine['belowRatio'] or
        (line['belowRatio'] == bestLine['belowRatio'] and line['touchCount'] > bestLine['touchCount']) or
        (line['belowRatio'] == bestLine['belowRatio'] and line['touchCount'] == bestLine['touchCount'] and line['slope'] > bestLine['slope'])
    ):
        bestLine = line

# Plot best
plottedElements = []
if bestLine:
    # Plot the best support line and its base points
    ax.plot(df['timestamp'], bestLine['lineExp'], color='brown', linewidth=2, label='Support Line')
    i, j = bestLine['bases']
    ax.plot(df['timestamp'][i], lows[i], 'o', color='brown', markersize=8)
    ax.plot(df['timestamp'][j], lows[j], 'o', color='brown', markersize=8)
    plottedElements.append('Support Line')

# Final touches
ax.set_title(fileName.upper())
ax.set_ylabel("Price")
ax.set_xlabel("Date")
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
ax.xaxis.set_major_locator(mticker.MaxNLocator(10))
plt.xticks(rotation=45)
plt.grid(True)
if plottedElements:
    ax.legend()
plt.tight_layout()
plt.show()
