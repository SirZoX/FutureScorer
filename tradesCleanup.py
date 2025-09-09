"""
Utilidad para limpiar duplicados del archivo trades.csv
"""

import csv
import os
from logManager import messages
from gvars import tradesLogFile

def removeDuplicateTradesFromCSV():
    """
    Remueve duplicados del archivo trades.csv basándose en:
    - symbol
    - open_date
    - investment_usdt
    - net_profit_usdt
    
    Mantiene solo el primer registro de cada duplicado
    """
    try:
        if not os.path.exists(tradesLogFile):
            messages("[CLEANUP] trades.csv file does not exist", console=0, log=1, telegram=0)
            return 0
        
        # Read all trades
        trades = []
        with open(tradesLogFile, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            trades = list(reader)
        
        if not trades:
            messages("[CLEANUP] No trades found in trades.csv", console=0, log=1, telegram=0)
            return 0
        
        # Create backup
        backupFile = tradesLogFile.replace('.csv', '_backup_cleanup.csv')
        with open(backupFile, 'w', encoding='utf-8', newline='') as f:
            if trades:
                fieldnames = trades[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
                writer.writeheader()
                writer.writerows(trades)
        
        # Find and remove duplicates
        seen = set()
        uniqueTrades = []
        duplicatesFound = 0
        
        for trade in trades:
            # Create unique key from important fields
            key = (
                trade.get('symbol', ''),
                trade.get('open_date', ''),
                trade.get('investment_usdt', ''),
                trade.get('net_profit_usdt', '')
            )
            
            if key in seen:
                duplicatesFound += 1
                messages(f"[CLEANUP] Duplicate found: {trade.get('symbol')} at {trade.get('open_date')} with profit {trade.get('net_profit_usdt')}", console=0, log=1, telegram=0)
            else:
                seen.add(key)
                uniqueTrades.append(trade)
        
        if duplicatesFound > 0:
            # Write cleaned data back
            with open(tradesLogFile, 'w', encoding='utf-8', newline='') as f:
                if uniqueTrades:
                    fieldnames = uniqueTrades[0].keys()
                    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
                    writer.writeheader()
                    writer.writerows(uniqueTrades)
            
            messages(f"[CLEANUP] Removed {duplicatesFound} duplicate trades from trades.csv. Backup saved to {backupFile}", console=1, log=1, telegram=0)
        else:
            # Remove backup if no duplicates found
            os.remove(backupFile)
            messages("[CLEANUP] No duplicate trades found in trades.csv", console=1, log=1, telegram=0)
        
        return duplicatesFound
        
    except Exception as e:
        messages(f"[ERROR] Failed to clean duplicate trades: {e}", console=1, log=1, telegram=0)
        return 0

def analyzeTradesDuplicates():
    """
    Analiza el archivo trades.csv para encontrar posibles duplicados sin eliminarlos
    """
    try:
        if not os.path.exists(tradesLogFile):
            return []
        
        trades = []
        with open(tradesLogFile, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            trades = list(reader)
        
        # Group by potential duplicate keys
        groups = {}
        for i, trade in enumerate(trades):
            key = (
                trade.get('symbol', ''),
                trade.get('investment_usdt', ''),
                trade.get('net_profit_usdt', '')
            )
            
            if key not in groups:
                groups[key] = []
            groups[key].append((i, trade))
        
        # Find groups with multiple entries
        duplicateGroups = []
        for key, tradeGroup in groups.items():
            if len(tradeGroup) > 1:
                duplicateGroups.append({
                    'symbol': key[0],
                    'investment': key[1],
                    'profit': key[2],
                    'count': len(tradeGroup),
                    'trades': tradeGroup
                })
        
        return duplicateGroups
        
    except Exception as e:
        messages(f"[ERROR] Failed to analyze duplicate trades: {e}", console=1, log=1, telegram=0)
        return []
