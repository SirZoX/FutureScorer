import json
import math
from decimal import Decimal, ROUND_DOWN
import ccxt
from binance.client import Client
from binance.enums import SIDE_SELL, TIME_IN_FORCE_GTC

# 1) Load configuration
CONFIG_PATH = '_files/config/config.json'
with open(CONFIG_PATH, encoding='utf-8') as f:
    cfg = json.load(f)
api_key = cfg.get('apiKey')
api_secret = cfg.get('apiSecret')

# 2) Initialize exchanges
ccxt_exch = ccxt.binance({'enableRateLimit': True})
binance_client = Client(api_key, api_secret)

# 3) Read base symbol from user
base = input("Enter base symbol (e.g. RAY): ").strip().upper()
symbol = f"{base}USDC"

# 4) Fetch current price and symbol filters from python-binance
ticker = binance_client.get_symbol_ticker(symbol=symbol)
price = Decimal(ticker['price'])
info = binance_client.get_symbol_info(symbol)

# Extract PRICE_FILTER and LOT_SIZE from filters
pf = next((f for f in info['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
ls = next((f for f in info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
if not pf or not ls:
    raise RuntimeError("Required filters not found for symbol " + symbol)

tick_size = Decimal(pf['tickSize'])
min_price = Decimal(pf['minPrice'])
step_size = Decimal(ls['stepSize'])
min_qty = Decimal(ls['minQty'])

print(f"Price={price}, tickSize={tick_size}, stepSize={step_size}")

# 5) Get user-defined quote amount and compute raw base amount
quote_qty = Decimal(input("Enter USDC amount to spend (e.g. 20): ").strip())
raw_amount = quote_qty / price

# 6) Quantize amount to step_size and ensure >= min_qty
# Use FLOOR division to respect step increments
amount = (raw_amount // step_size) * step_size
# Fallback: Decimal quantize if needed
if amount < min_qty:
    raise ValueError(f"Computed amount {amount} below minimum step {min_qty}")

# Normalize amount for API
amount_str = format(amount, f'f')

print(f"Buying {amount_str} @ {price}")

# 7) Execute market buy with correct step size
try:
    buy_resp = binance_client.order_market_buy(symbol=symbol, quantity=amount_str)
    print("Buy response:", buy_resp)
    filled_qty = Decimal(str(buy_resp.get('executedQty') or buy_resp.get('fills', [{}])[0].get('qty', 0)))
    open_price = price  # approximate; market order has no price in response
except Exception as e:
    print(f"❌ Error executing market buy (LOT_SIZE filter): {e}")
    raise


# tp_pct = Decimal(str(cfg.get('tpPercent', 0.02)))
# sl_pct = Decimal(str(cfg.get('slPercent', 0.01)))
tp_pct = Decimal(str(cfg.get('tp1', 0.02)))
sl_pct = Decimal(str(cfg.get('sl1', 0.01)))
raw_tp = open_price * (Decimal(1) + tp_pct)
raw_sp = open_price * (Decimal(1) - sl_pct)

# Quantize prices to tick_size
take_profit_price = (raw_tp // tick_size) * tick_size
stop_price = (raw_sp // tick_size) * tick_size
# Stop-limit price slightly below stop_price
stop_limit_price = ((stop_price * Decimal('0.995')) // tick_size) * tick_size

# Ensure prices respect minimum price
take_profit_price = max(take_profit_price, min_price)
stop_price = max(stop_price, min_price)
stop_limit_price = max(stop_limit_price, min_price)

tp_str = format(take_profit_price, f'f')
sp_str = format(stop_price, f'f')
lp_str = format(stop_limit_price, f'f')

print(f"Placing OCO: TP={tp_str}, Stop={sp_str}, StopLimit={lp_str}")
# Intento OCO sin aboveType/belowType
import requests
import time
import hmac
import hashlib

# Calcular los tipos correctos para aboveType y belowType
current_price = float(price)
tp_val = float(tp_str)
sp_val = float(sp_str)
# Para SELL, arriba es TP (LIMIT_MAKER), abajo es SL (STOP_LOSS_LIMIT)
above_type = 'LIMIT_MAKER'
below_type = 'STOP_LOSS_LIMIT'

# Parámetros obligatorios para el nuevo endpoint
endpoint = 'https://api.binance.com/api/v3/orderList/oco'
timestamp = int(time.time() * 1000)
params = {
    'symbol': symbol,
    'side': 'SELL',
    'quantity': amount_str,
    'aboveType': above_type,
    'abovePrice': tp_str,
    # Solo enviar aboveTimeInForce si el tipo lo requiere
    # 'aboveTimeInForce': 'GTC',
    'belowType': below_type,
    'belowPrice': lp_str,
    'belowStopPrice': sp_str,
    'belowTimeInForce': 'GTC',
    'timestamp': timestamp
}
# Agregar aboveTimeInForce solo si aboveType lo requiere
if above_type in ['STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT']:
    params['aboveTimeInForce'] = 'GTC'
# Construir la query string para la firma
query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
signature = hmac.new(api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
params['signature'] = signature

headers = {
    'X-MBX-APIKEY': api_key
}
print(f"[OCO-DEBUG] Llamada manual OCO: {params}")
try:
    response = requests.post(endpoint, params=params, headers=headers)
    print(f"OCO response status: {response.status_code}")
    print(f"OCO response: {response.text}")
    if response.status_code == 200:
        print("OCO placed correctamente usando el endpoint nuevo.")
    else:
        print("❌ Error placing OCO (manual endpoint):", response.text)
except Exception as e:
    print(f"❌ Error en la llamada manual OCO: {e}")
