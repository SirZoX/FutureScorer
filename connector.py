"""
Connector module for BingX Futures using ccxt.
Reads configuration from config.json and establishes connection.
All function and variable names use camelCase. Comments are in English.
"""
import ccxt
import json
import os
from configManager import configManager

configFilePath = os.path.join(os.path.dirname(__file__), '_files', 'config', 'config.json')

def loadConfig():
    """Load configuration from config.json file."""
    return configManager.config


def bingxConnector(isSandbox=False):
    """Create and return a BingX Futures connection using ccxt and config data. If isSandbox=True, use BingX sandbox."""
    apiKey = configManager.get('apikey') or configManager.get('apiKey')
    secret = configManager.get('apisecret') or configManager.get('apiSecret')
    #password = configManager.get('bingxPassword')
    if not apiKey or not secret:
        raise Exception('API key or secret missing in config.json')
    options = {
        'defaultType': 'swap',  # For BingX Futures
    }
    if isSandbox:
        options['sandboxMode'] = True
    exchange = ccxt.bingx({
        'apiKey': apiKey,
        'secret': secret,
        #'password': password,
        'options': options
    })
    if isSandbox:
        exchange.set_sandbox_mode(True)
    return exchange

# Example usage (commented out)
# connector = bingxConnector()
# print(connector.fetch_balance())
