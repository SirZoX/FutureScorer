
import os
import json
import ccxt
import time
from gvars import configFile, configFolder, marketsFile

# Load API credentials and initialize exchange
with open(configFile, "r", encoding="utf-8") as f:
    config = json.load(f)


api_key = config.get('apikey') or config.get('apiKey')
api_secret = config.get('apisecret') or config.get('apiSecret')
exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})



print ("Loading markets")
start = time.time()

markets = exchange.load_markets(True)
os.makedirs(configFolder, exist_ok=True)

with open(marketsFile, "w", encoding="utf-8") as f:
    json.dump(markets, f, default=str, indent=2)

end = time.time()
print(f"Loading markets time: {(end - start):.2f}s")
