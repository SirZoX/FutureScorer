
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from mplfinance.original_flavor import candlestick_ohlc
from datetime import datetime
import os
import gvars
from logManager import messages


def savePlot(item):
  
    """
    Generates and saves a candlestick + support plot.
    Marks the exact bounce reference point with a red 'X'.
    """
    # Load CSV data
    try:
        df = pd.read_csv(item['csvPath'], parse_dates=['timestamp'])
    except Exception as e:
        messages(f"Error loading CSV for plot: {e}", console=1, log=1, telegram=0, pair=item.get('pair'))
        raise
    # Convert all timestamps to Europe/Madrid timezone
    from zoneinfo import ZoneInfo
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC').dt.tz_convert('Europe/Madrid')
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert('Europe/Madrid')
    df['timestampNum'] = df['timestamp'].apply(mdates.date2num)


    # Compute moving averages
    df['ma25'] = df['close'].rolling(window=25).mean()
    df['ma99'] = df['close'].rolling(window=99).mean()

    # Compute support line
    slope       = item['slope']
    intercept   = item['intercept']
    n           = len(df)
    xIdx        = np.arange(n)
    supportLine = slope * xIdx + intercept

    # Prepare OHLC data
    ohlc = df[['timestampNum','open','high','low','close']].values

    # Time range: only up to last real candle
    timeRange = (df['timestampNum'].iat[0], df['timestampNum'].iat[-1])

    # Create figure & axes
    fig, ax = plt.subplots(figsize=(13, 5))

    # Plot candlesticks
    candlestick_ohlc(
        ax, ohlc,
        width=0.6 * (df['timestampNum'].diff().median()),
        colorup='green', colordown='red', alpha=0.8
    )

    # Plot support line
    ax.plot(df['timestampNum'], supportLine, color='orange', linewidth=2, label='Support Line')


    # Plot MA25
    ax.plot(df['timestampNum'], df['ma25'], color='magenta', linewidth=1, label='MA25')

    # Plot MA99 (always calculated locally)
    if df['ma99'].notna().sum() > 0:
        ax.plot(df['timestampNum'], df['ma99'], color='blue', linewidth=1, label='MA99')

    # Initialize bounceIdx and detect bounce point
    bounceIdx = None
    tolerancePct = item.get('tolerancePct', 0.015)
    if n >= 2:
        lowPrev = df['low'].iat[n-2]
        expPrev = supportLine[n-2]
        closeLast = df['close'].iat[n-1]
        openLast = df['open'].iat[n-1]
        
        # Check if previous candle touches support and last candle is green
        touchesSupport = abs(lowPrev - expPrev) <= abs(expPrev) * tolerancePct
        isGreen = closeLast > openLast
        
        if touchesSupport and isGreen:
            bounceIdx = n-2  # Index of the candle that touched support

    # Determine the start point for horizontal lines (3 candles before bounce)
    if bounceIdx is not None:
        # Start from 3 candles before bounce point (or from start if not enough candles)
        startIdx = max(0, bounceIdx - 3)
        lineStartTime = df['timestampNum'].iat[startIdx]
    else:
        # If no bounce detected, start from 3 candles before last
        startIdx = max(0, n - 4) if n >= 4 else 0
        lineStartTime = df['timestampNum'].iat[startIdx]
    
    # Extend lines 5 candles into the future (simulate 5 future candles)
    lastTime = df['timestampNum'].iat[-1]
    candleInterval = df['timestampNum'].iat[-1] - df['timestampNum'].iat[-2] if n >= 2 else 1/24/4  # Default 15min if can't calculate
    lineEndTime = lastTime + (candleInterval * 5)  # Extend 5 candles into future
    lineTimeRange = (lineStartTime, lineEndTime)
    
    # English comment: Bounce range lines removed as bounce validation no longer uses strict ranges
    # The bounce detection is now handled in supportDetector.py with touch + 2 consecutive candles logic
    
    # Plot TP/SL - only from bounce point onwards
    tp = item.get('tpPrice')
    sl = item.get('slPrice')
    if tp is not None:
        ax.hlines(tp, *lineTimeRange, linestyle='--', color='green', linewidth=1, label='Take Profit')
    if sl is not None:
        ax.hlines(sl, *lineTimeRange, linestyle='--', color='red', linewidth=1, label='Stop Loss') 

    # Determine legend location
    yMin, yMax     = ax.get_ylim()
    firstPrice     = (df['open'].iat[0] + df['close'].iat[0]) / 2
    topThreshold   = yMin + (yMax - yMin) * 0.66
    legendLoc      = 'lower left' if firstPrice > topThreshold else 'upper left'

    # Generate plot file name
    if n >= 2:
        # Normalizar nombre del par eliminando sufijos y barras
        basePair = item['pair']
        # Eliminar sufijos como :USDT, _USDT, _USDC, _BUSD, _USDT:USDT y cualquier barra
        basePair = basePair.split('/')[0].split(':')[0].replace('-', '_').replace(' ', '_')
        for suffix in ['_USDT', '_USDC', '_BUSD']:
            if basePair.endswith(suffix):
                basePair = basePair[:-len(suffix)]
        if item.get('type', '') == 'discard' or basePair.startswith('DISCARD_'):
            plotFile = f"DISCARD_{basePair}.png"
        else:
            prefix = 'LONG_' if item.get('type') == 'long' else 'SHORT_'
            plotFile = f"{prefix}{basePair}.png"
        plotPath = os.path.join(gvars.plotsFolder, plotFile)
        #print(f"[DEBUG][savePlot] plotFile generado: {plotFile}")
        #print(f"[DEBUG][savePlot] plotPath generado: {plotPath}")
    # Mark bounce point with red 'X'
    if bounceIdx is not None:
        xPoint = df['timestampNum'].iat[bounceIdx]
        yPoint = supportLine[bounceIdx]
        ax.plot(xPoint, yPoint, marker='x', color='red', markersize=10, label='Bounce Ref Point')  # English comment: mark reference




    # Build custom legend: Support - MA25 - MA99 (coloreado)
    from matplotlib.lines import Line2D
    supportLine = Line2D([0], [1], color='orange', linewidth=2)
    ma25Line = Line2D([0], [1], color='magenta', linewidth=1)
    ma99Line = Line2D([0], [1], color='blue', linewidth=1)
    handles = [supportLine, ma25Line, ma99Line]
    labels = ['Support', 'MA25', 'MA99']

    # Evaluación de criterios
    def ok(val): return '\u2714 OK'  # ✓
    def ko(val): return '\u2718 KO'  # ✗
    # Criterios principales
    slope = item.get('slope', 0)
    touchCount = item.get('touchesCount', item.get('touchCount', 0))  # Check both possible field names
    minTouches = 3
    
    # Debug logging
    messages(f"DEBUG PLOTTING - Symbol: {item.get('symbol', 'N/A')}, touchCount: {touchCount}, minTouches: {minTouches}, touchesOk: {touchCount >= minTouches}", console=0, log=1, telegram=0)
    # Para soporte: slope positivo, para resistencia: negativo
    isLong = item.get('type', 'long') == 'long'
    slopeOk = slope > 0 if isLong else slope < 0
    touchesOk = touchCount >= minTouches
    # Violaciones y rebote (solo si están en item)
    violationOk = True if item.get('violationOk', True) else False
    bounceOk = True if item.get('bounce', True) else False

    # Colores para leyenda
    def colorText(text, ok):
        return f"$\\bf{{{text}}}$" if ok else f"$\\bf{{{text}}}$"

    # Leyenda de criterios
    critLabels = [
        f"Slope: {slope:.4f} {'✓ OK' if slopeOk else '✗ KO'}",
        f"Touches: {touchCount} {'✓ OK' if touchesOk else '✗ KO'}",
        f"Violations: {'✓ OK' if violationOk else '✗ KO'}",
        f"Bounce: {'✓ OK' if bounceOk else '✗ KO'}"
    ]
    for cl in reversed(critLabels):
        proxy = Line2D([0], [0], color='none', marker='', linestyle='')
        labels.insert(0, cl)
        handles.insert(0, proxy)

    # Add last candle open date to legend (Europe/Madrid timezone)
    lastCandleDate = df['timestamp'].iloc[-1]
    lastCandleDateStr = lastCandleDate.strftime('%Y-%m-%d %H:%M') if hasattr(lastCandleDate, 'strftime') else str(lastCandleDate)
    proxyDate = Line2D([0], [0], color='none', marker='', linestyle='')
    dateLabel = f"Última vela abierta (Madrid): {lastCandleDateStr}"
    labels.insert(0, dateLabel)
    handles.insert(0, proxyDate)

    # Draw legend
    ax.legend(handles, labels, loc=legendLoc, fontsize='small', borderaxespad=0.5)

    # Format axes
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
    fig.autofmt_xdate()
    ax.set_title(item['pair'])
    ax.set_xlabel('Date')
    ax.set_ylabel('Price')
    ax.grid(True)
    fig.tight_layout()

    # El plotPath ya se ha generado correctamente arriba según el tipo

    # Save and close
    try:
        fig.savefig(plotPath)
    except Exception as e:
        messages(f"Error saving plot image: {e}", console=1, log=1, telegram=0, pair=item.get('pair'))
        raise
    finally:
        plt.close(fig)
    #print(f"[DEBUG][savePlot] return plotPath: {plotPath}")
    return plotPath
