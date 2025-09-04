print ("\r\n\r\n")
import threading
# import positionMonitor  # Disabled - removed from main flow
# from positionMonitor import monitorActive  # Disabled - removed from main flow
import os
import sys
import schedule
from datetime import datetime

# Import messages early so it's available from the start
from logManager import messages

# def startPositionMonitor():  # Disabled - position monitoring removed
#     t = threading.Thread(target=positionMonitor.monitorPositions, daemon=True)
#     t.start()

# bot.py
import time
start = time.time()
messages("Loading modules", console=1, log=1, telegram=0)


# Argument control via args.py
import args
isSandbox = args.isSandbox or ('-test' in sys.argv)
isForce = args.isForce
if isSandbox:
    messages('>>> SANDBOX activated: Using VST instead USDT', console=1, log=1, telegram=0)



import fileManager
import orderManager
import gvars
import helpers
import pairs

from configManager import configManager
from validators import validateConfigStructure

end = time.time()
messages(f"Loading modules time: {(end - start):.2f}s", console=1, log=1, telegram=0)




update_lock = threading.Lock()
def safeUpdatePositions():
    if update_lock.locked():
        messages("Skipping updatePositions: still running previous invocation", console=1, log=1, telegram=0)
        return
    with update_lock:
        orderManager.updatePositions()


orderManager = orderManager.OrderManager(isSandbox=isSandbox)

# Validate configuration
configData = configManager.config
isValid, errors = validateConfigStructure(configData)
if not isValid:
    messages(f"Configuration validation failed | errors={errors}", console=1, log=1, telegram=0)
    print(f"❌ Configuration errors: {errors}")
    sys.exit(1)

messages("Configuration validated successfully", console=1, log=1, telegram=0)

# topPercent   = configData.get('topPercent', 10)
# limit        = configData.get('limit', 150)
# tpPercent    = configData.get('tpPercent', 0.01)
# slPercent    = configData.get('slPercent', 0.035)
# bouncePct    = configData.get('bouncePct', 0.002)
# maxBounceAllowed= configData.get('maxBounceAllowed', 0.002)
# minSeparation= configData.get('minSeparation', 36)
# minVolume    = configData.get('minVolume', 500000)
topCoinsPctAnalyzed = configManager.get('topCoinsPctAnalyzed', 10)
requestedCandles    = configManager.get('requestedCandles', 150)
tp1                 = configManager.get('tp1', 0.01)
sl1                 = configManager.get('sl1', 0.035)
minPctBounceAllowed = configManager.get('minPctBounceAllowed', 0.002)
maxPctBounceAllowed = configManager.get('maxPctBounceAllowed', 0.002)
minCandlesSeparationToFindSupportLine = configManager.get('minCandlesSeparationToFindSupportLine', 36)
lastCandleMinUSDVolume = configManager.get('lastCandleMinUSDVolume', 500000)
timeframe    = configManager.get('timeframe', '1d')
tolerancePct = configManager.get('tolerancePct', 0.015)
minTouches   = configManager.get('minTouches', 3)

# Scoring configuration
scoringWeights = configManager.get('scoringWeights', {
    'distance': 0.3, #default value if value is not in config.json
    'volume':   0.3, #default value if value is not in config.json
    'momentum': 0.10, #default value if value is not in config.json
    'touches':  0.15 #default value if value is not in config.json
})
scoreThreshold = configManager.get('scoreThreshold', 0.0)






# Prepare selection logging
os.makedirs(os.path.dirname(gvars.selectionLogFile), exist_ok=True)
if not os.path.isfile(gvars.selectionLogFile):
    with open(gvars.selectionLogFile, 'w', encoding='utf-8') as f:
        f.write(
            "id;"
            "timestamp_iso;"
            "timestamp_unix;"
            "pair;"
            "distancePct;"
            "volumeRatio;"
            "momentum;"
            "touchesCount;"
            "score;"
            "accepted;"
            "tolerancePct;"
            "minTouches;"
            "slope;"
            "intercept;"
            "entryPrice;"
            "tpPrice;"
            "slPrice;"
            "bounceLow;"
            "bounceHigh;"
            "ma25Prev;"
            "filter1Passed;"
            "filter2Passed;"
            "weight_distance;"
            "weight_volume;"
            "weight_momentum;"
            "weight_touches\n"
        )






# Display timeframe summary
def timeframeScheduled(tf:str,lim:int):
    unit=tf[-1]; num=int(tf[:-1])
    if unit=='d':
        hours=num*24; days,hrs=divmod(hours,24)
        messages(f"Requested {lim} candles of '{tf}' -> {hours}h ({days}d {hrs}h)",console=1,log=1,telegram=0)
    elif unit=='h':
        hours=num; days,hrs=divmod(hours*lim,24)
        messages(f"Requested {lim} candles of '{tf}' -> {hours*lim}h ({days}d {hrs}h)",console=1,log=1,telegram=0)
    elif unit=='m':
        mins=num*lim; hrs,mins_rem=divmod(mins,60)
        days,hrs_rem=divmod(hrs,24)
        messages(f"Requested {lim} candles of '{tf}' -> {mins}m ({days}d {hrs_rem}h {mins_rem}m)",console=1,log=1,telegram=0)
    else:
        messages(f"Unsupported timeframe: {tf}",console=1,log=1,telegram=0)











# Schedule tasks based on timeframe
def setupSchedules(tf: str):
    """
    Schedules pairs.updatePairs and pairs.analyzePairs aligned to the timeframe:
      - 'Nm' with N divisor of 60: every hour at minutes 0, N, 2N, ...
      - 'Nh' with N divisor of 24: every day at hours 0, N, 2N, ...
      - 'Nd': every N days at midnight
    """

    try:
        period = int(tf[:-1])
        unit = tf[-1]
    except ValueError:
        messages(f"[ERROR] Invalid timeframe {tf}", console=1, log=1, telegram=1)
        sys.exit(1)

    # Clear any previous jobs to avoid duplicates
    schedule.clear()

    if unit == 'm' and 60 % period == 0:
        # every hour at minute multiples
        for mm in range(0, 60, period):
            atStr = f":{mm:02d}"
            schedule.every().hour.at(atStr).do(pairs.updatePairs)
            schedule.every().hour.at(atStr).do(pairs.analyzePairs)
        unit_desc = f"each {period} minutes aligned"

    elif unit == 'h' and 24 % period == 0:
        # every day at hour multiples
        for hh in range(0, 24, period):
            atStr = f"{hh:02d}:00"
            schedule.every().day.at(atStr).do(pairs.updatePairs)
            schedule.every().day.at(atStr).do(pairs.analyzePairs)
        unit_desc = f"every {period} hour(s) aligned"

    elif unit == 'd':
        # every N days at midnight
        atStr = "00:00"
        schedule.every(period).days.at(atStr).do(pairs.updatePairs)
        schedule.every(period).days.at(atStr).do(pairs.analyzePairs)
        unit_desc = f"every {period} day(s) at {atStr}"

    else:
        # fallback to simple interval scheduling
        if unit == 'm':
            schedule.every(period).minutes.do(pairs.updatePairs)
            schedule.every(period).minutes.do(pairs.analyzePairs)
            unit_desc = f"every {period} minute(s) (unaligned)"
        elif unit == 'h':
            schedule.every(period).hours.do(pairs.updatePairs)
            schedule.every(period).hours.do(pairs.analyzePairs)
            unit_desc = f"every {period} hour(s) (unaligned)"
        else:
            messages(f"[ERROR] Unknown timeframe unit: '{unit}'", console=1, log=1, telegram=1)
            sys.exit(1)

    messages(f"Scheduled pairs.updatePairs/pairs.analyzePairs {unit_desc}", console=0, log=1, telegram=0)













if __name__ == "__main__":


    fileManager.ensureDirectories()

    # --- Soporte para -newlog: vaciar log del día actual ---
    if '-newlog' in sys.argv:
        # Log principal del día: logs/YYYY_MM/DDMMYYYY.csv
        today = datetime.now().strftime('%d%m%Y')
        month = datetime.now().strftime('%Y_%m')
        log_path = os.path.join(gvars.logsFolder, month, f"{today}.csv")
        fileManager.clearLogFile(log_path)
        messages(f"Log file {log_path} cleared by -newlog argument.", console=0, log=1, telegram=0)


    
    orderManager.updateDailyBalance()




    print(f"\n\nStarting bot v.{gvars.version}\n")
    messages(f"{gvars._line_}", console=1, log=1, telegram=0)
    messages("Bot started", console=1, log=1, telegram=0)
    messages("-----------------------------------", console=1, log=1, telegram=0)

    messages("Trading & Risk", 1, 1, 0)
    messages(f"  • maxOpenPositions = {configManager.get('maxOpenPositions','')}", 1, 1, 0)
    messages(f"  • usdcInvestment = {configManager.get('usdcInvestment','')}", 1, 1, 0)
    messages(f"  • tp1 = {helpers.formatNum(tp1*100)}%", 1, 1, 0)
    messages(f"  • tp2 = {helpers.formatNum(configManager.get('tp2',0)*100)}%", 1, 1, 0)
    messages(f"  • sl1 = {helpers.formatNum(sl1*100)}%", 1, 1, 0)
    messages("",1,0,0)
    
    messages("Market Selection", 1, 1, 0)
    messages(f"  • topCoinsPctAnalyzed = {helpers.formatNum(topCoinsPctAnalyzed)}%", 1, 1, 0)
    messages(f"  • lastCandleMinUSDVolume = {helpers.formatNum(lastCandleMinUSDVolume)} USDC", 1, 1, 0)
    messages("",1,0,0)

    messages("Support Detection", 1, 1, 0)
    messages(f"  • minPctBounceAllowed = {helpers.formatNum(minPctBounceAllowed*100)}%", 1, 1, 0)
    messages(f"  • maxPctBounceAllowed = {helpers.formatNum(maxPctBounceAllowed*100)}%", 1, 1, 0)
    messages(f"  • minCandlesSeparationToFindSupportLine = {minCandlesSeparationToFindSupportLine}", 1, 1, 0)
    messages(f"  • minTouches = {helpers.formatNum(minTouches)}", 1, 1, 0)
    messages(f"  • tolerancePct = {helpers.formatNum(tolerancePct*100)}%", 1, 1, 0)
    messages("",1,0,0)

    messages("Timeframe & Candles", 1, 1, 0)
    messages(f"  • timeframe = {timeframe}", 1, 1, 0)
    messages(f"  • requestedCandles = {requestedCandles}", 1, 1, 0)
    messages("",1,0,0)

    messages("Scoring", 1, 1, 0)
    weights = configManager.get('scoringWeights', {})
    messages(f"  • scoringWeights: distance={weights.get('distance','')}, volume={weights.get('volume','')}, momentum={weights.get('momentum','')}, touches={weights.get('touches','')}", 1, 1, 0)
    messages(f"  • scoreThreshold = {configManager.get('scoreThreshold','')}", 1, 1, 0)

    messages(f"{gvars._line_}", console=1, log=1, telegram=0)



    # timeframeScheduled(timeframe, limit)
    timeframeScheduled(timeframe, requestedCandles)


    # check for "-force" in command-line args
    forceRun = '-force' in sys.argv

    if forceRun:
        messages("Force flag detected: running initial update & analysis", console=1, log=1, telegram=0)
        pairs.updatePairs()
        # monitorActive.clear()  # Disabled - position monitor removed
        pairs.analyzePairs()
        # monitorActive.set()    # Disabled - position monitor removed
        # positionMonitor.printPositionsTable()  # Disabled - position monitor removed
        # startPositionMonitor()  # Disabled - position monitor removed
    else:
        messages("Skipping initial update & analysis (use -force to override)", console=1, log=1, telegram=0)
        # Arrancar monitor de posiciones en hilo solo después de cargar todo
        # startPositionMonitor()  # Disabled - position monitor removed

    setupSchedules(timeframe)
    schedule.every(3).minutes.do(safeUpdatePositions)
    schedule.every().day.at("00:00").do(orderManager.updateDailyBalance)
    schedule.every(10).seconds.do(helpers.checkTelegram)
    
    # Schedule position synchronization every 5 minutes
    from positionSyncer import schedulePositionSync
    positionSyncFunction = schedulePositionSync(orderManager, intervalMinutes=5)
    schedule.every(5).minutes.do(positionSyncFunction)
    
    # Set orderManager reference for telegram commands
    import helpers
    helpers.setOrderManagerReference(orderManager)

    while True:
        schedule.run_pending()
        time.sleep(1)

