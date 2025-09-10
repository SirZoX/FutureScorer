# gvars.py
"""
Global static variables for scoringbot.
"""
version = "0.1.0"  # Bot version

# Base folders
baseFolder = "_files"                       # main storage folder
configFolder = f"{baseFolder}/config"       # config files folder
jsonFolder = f"{baseFolder}/json"           # JSON dumps
csvFolder = f"{baseFolder}/csv"             # CSV dumps
plotsFolder = f"{baseFolder}/plots"         # saved plots
logsFolder = f"{baseFolder}/logs"           # log files


# Config filenames
configFile = f"{configFolder}/config.json"          # main bot config
ignorePairsFile = f"{configFolder}/ignore_pairs.json"  # pairs to ignore
selectionLogFile = f"{logsFolder}/selectionLog.csv"  # master selection log
tradesLogFile = f"{logsFolder}/trades.csv"          # trades log
marketsFile = f"{jsonFolder}/markets.json"
positionsFile = f"{jsonFolder}/openedPositions.json"
dailyBalanceFile = f"{jsonFolder}/dailyBalance.json"
topSelectionFile = f"{jsonFolder}/topSelection.json"  # top selection pairs


# Rate limiter defaults
rateLimiterMaxCalls = 20                    # max API calls per period
rateLimiterPeriodSeconds = 1.0              # period length in seconds

# Concurrency
threadPoolMaxWorkers = 6                   # thread pool size for parallel processing
pairAnalysisSleepTime = 0.05               # Reduced from 0.12 to 0.05 for better performance (50ms)


_line_ = "*"*120

# Position monitor table column widths
columnWidthHour = 19           # Hour column width
columnWidthPair = 20           # Pair column width  
columnWidthSide = 6            # Side column width (L/S)
columnWidthTpPercent = 10      # TP% column width
columnWidthSlPercent = 10      # SL% column width
columnWidthPnlPercent = 12     # PNL% column width
columnWidthInvestment = 12     # Investment column width
columnWidthEntryPrice = 10     # Entry price column width
columnWidthTpPrice = 10        # TP price column width
columnWidthSlPrice = 10        # SL price column width
columnWidthLiveFor = 12        # Live for column width
