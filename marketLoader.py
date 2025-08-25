
import os
import json
import ccxt
from connector import bingxConnector
import time
from gvars import configFile, configFolder, marketsFile
from configManager import configManager
from logManager import messages # log_info

config = configManager.config
exchange = bingxConnector()

messages("Loading markets", console=1, log=1, telegram=0)
start = time.time()

markets = exchange.load_markets(True)
os.makedirs(configFolder, exist_ok=True)

with open(marketsFile, "w", encoding="utf-8") as f:
    json.dump(markets, f, default=str, indent=2)

end = time.time()
messages(f"Loading markets time: {(end - start):.2f}s", console=1, log=1, telegram=0)
