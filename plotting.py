
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from mplfinance.original_flavor import candlestick_ohlc
from datetime import datetime
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

    # Plot bounce bounds (lines ahead)
    bl = item.get('bounceLow')
    bh = item.get('bounceHigh')
    minPctBounceAllowed = item.get('minPctBounceAllowed')
    maxPctBounceAllowed = item.get('maxPctBounceAllowed')
    # English comment: Use new bounce fields for plot labels
    if bl is not None and minPctBounceAllowed is not None:
        ax.hlines(bl, *timeRange, linestyle='--', color='purple', linewidth=1, label=f'Min Bounce ({minPctBounceAllowed*100:.1f}%)')
    if bh is not None and maxPctBounceAllowed is not None:
        ax.hlines(bh, *timeRange, linestyle='--', color='purple', linewidth=1, label=f'Max Bounce ({maxPctBounceAllowed*100:.1f}%)')

    # Plot TP/SL
    tp = item.get('tpPrice')
    sl = item.get('slPrice')
    if tp is not None:
        ax.hlines(tp, *timeRange, linestyle='--', color='green', linewidth=1, label='Take Profit')
    if sl is not None:
        ax.hlines(sl, *timeRange, linestyle='--', color='red', linewidth=1, label='Stop Loss')

    # Determine legend location
    yMin, yMax     = ax.get_ylim()
    firstPrice     = (df['open'].iat[0] + df['close'].iat[0]) / 2
    topThreshold   = yMin + (yMax - yMin) * 0.66
    legendLoc      = 'lower left' if firstPrice > topThreshold else 'upper left'

    # Mark X only if previous candle touches support and last candle is green
    bounceIdx = None
    tolerancePct = item.get('tolerancePct', 0.015)
    if n >= 2:
        lowPrev = df['low'].iat[n-2]
        expPrev = supportLine[n-2]
        closeLast = df['close'].iat[n-1]
        # Generate filename with LONG_ or SHORT_ prefix and no date/time tag
        basePair = item['pair'].split('/')[0] if '/' in item['pair'] else item['pair']
        basePair = basePair.replace(':', '')
        prefix = 'LONG_' if item.get('type', 'long') == 'long' else 'SHORT_'
        plotPath = gvars.plotsFolder + f"/{prefix}{basePair}.png"
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
    # Compose a single label with colored texts using proxy artists
    handles = [supportLine, ma25Line, ma99Line]
    labels = [
        'Support',
        'MA25',
        'MA99'
    ]

    # Add scoring details to legend if available
    scoringKeys = ['momentum', 'distance', 'touches', 'volume', 'score']
    scoringValues = []
    for key in scoringKeys:
        val = item.get(key)
        if val is not None:
            scoringValues.append(f"{key.capitalize()}: {val:.3f}")
    if scoringValues:
        proxy = Line2D([0], [0], color='none', marker='', linestyle='')
        scoringLabel = "Scoring → " + ", ".join(scoringValues)
        handles.insert(0, proxy)
        labels.insert(0, scoringLabel)

    # Add last candle open date to legend (Europe/Madrid timezone)
    lastCandleDate = df['timestamp'].iloc[-1]
    lastCandleDateStr = lastCandleDate.strftime('%Y-%m-%d %H:%M') if hasattr(lastCandleDate, 'strftime') else str(lastCandleDate)
    proxyDate = Line2D([0], [0], color='none', marker='', linestyle='')
    dateLabel = f"Última vela abierta (Madrid): {lastCandleDateStr}"
    handles.insert(0, proxyDate)
    labels.insert(0, dateLabel)

    # Add bounce value and candle offset to legend
    if bl is not None and bounceIdx is not None:
        relPos      = bounceIdx - n  # negative index
        bounceLabel = f"BounceLow {bl:.6f} (candle {relPos})"
        handles.insert(0, handles.pop())  # move 'Bounce Ref Point' handle to front
        labels.insert(0, bounceLabel)

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

    # Generate filename
    timestampTag = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    # English comment: Remove everything after the first '/' and any ':' for plot filename
    basePair = item['pair'].split('/')[0] if '/' in item['pair'] else item['pair']
    basePair = basePair.replace(':', '')
    plotPath = gvars.plotsFolder + f"/{basePair}_{timestampTag}.png"

    # Save and close
    try:
        fig.savefig(plotPath)
        #messages(f"Plot saved: {plotPath}", console=0, log=1, telegram=0, pair=item.get('pair'))
    except Exception as e:
        messages(f"Error saving plot image: {e}", console=1, log=1, telegram=0, pair=item.get('pair'))
        raise
    finally:
        plt.close(fig)
    return plotPath
