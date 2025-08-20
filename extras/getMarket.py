import json
import ccxt
from connector import bingxConnector


def fetch_market_info():
    # Load API credentials from config.json
    with open('_files/config/config.json', 'r') as cfg:
        config = json.load(cfg)

    api_key = config.get('apikey') or config.get('apiKey')
    api_secret = config.get('apisecret') or config.get('apiSecret')

    # Initialize BingX Futures exchange
    exchange = bingxConnector()
    base = input("Introduce el símbolo base (p.ej. 'ray'): ")
    symbol = f"{base.strip().upper()}/USDC"

    try:
        # Ensure markets are loaded
        exchange.load_markets()
        # Fetch ticker information
        ticker = exchange.fetch_ticker(symbol)
        # Print the JSON node for the requested pair
        print(json.dumps({symbol: ticker}, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error al obtener información para {symbol}: {e}")


if __name__ == '__main__':
    fetch_market_info()
