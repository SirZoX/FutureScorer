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
threadPoolMaxWorkers = 5                    # default max threads for analysis


clientPrefix = "SCBot_"
_line_ = "*"*120
