
import os
import json
import ccxt
from connector import bingxConnector
import time
from gvars import configFile, configFolder, marketsFile
from connector import loadConfig

config = loadConfig()
exchange = bingxConnector()



print ("Loading markets")
start = time.time()

markets = exchange.load_markets(True)
os.makedirs(configFolder, exist_ok=True)

with open(marketsFile, "w", encoding="utf-8") as f:
    json.dump(markets, f, default=str, indent=2)

end = time.time()
print(f"Loading markets time: {(end - start):.2f}s")
