from logManager import messages

def notifyPositionClosure(symbol, closeReason, netProfitUsdt, profitPct, totalFees, detailsForDebug=None):
    """
    Unified function to send position closure notifications to Telegram and logs
    
    Args:
        symbol (str): Trading symbol (e.g., 'BTC/USDT:USDT')
        closeReason (str): Reason for closure ('TP', 'SL', 'SYNC', etc.)
        netProfitUsdt (float): Net profit/loss in USDT after fees
        profitPct (float): Profit percentage
        totalFees (float): Total fees paid
        detailsForDebug (dict, optional): Additional debug information
    """
    # Determine emoji based on profit/loss
    icon = "💰💰" if netProfitUsdt > 0 else "☠️☠️"
    
    # Format the main notification message
    if closeReason in ['TP', 'SL']:
        # Specific TP/SL closure
        mainMessage = f"{icon} {closeReason} for {symbol} — P/L: {netProfitUsdt:.4f} USDT ({profitPct:.2f}%) [Fees: {totalFees:.4f}]"
    else:
        # Generic closure (SYNC, manual, etc.)
        mainMessage = f"{icon} Position closed: {symbol} — P/L: {netProfitUsdt:.4f} USDT ({profitPct:.2f}%) [Fees: {totalFees:.4f}]"
    
    # Send main notification
    messages(mainMessage, pair=symbol, console=1, log=1, telegram=1)
    
    # Send debug information if provided
    if detailsForDebug:
        debugMessage = _formatDebugMessage(symbol, detailsForDebug)
        messages(debugMessage, pair=symbol, console=0, log=1, telegram=0)

def notifyPositionClosureSimple(symbol, reason="detected via exchange sync"):
    """
    Simple notification for when detailed P/L calculation is not available
    
    Args:
        symbol (str): Trading symbol
        reason (str): Reason description for the closure
    """
    simpleMessage = f"🔔 Position closed: {symbol} ({reason})"
    messages(simpleMessage, pair=symbol, console=1, log=1, telegram=1)

def _formatDebugMessage(symbol, details):
    """
    Format detailed debug information for logging
    
    Args:
        symbol (str): Trading symbol
        details (dict): Dictionary with debug information
    
    Returns:
        str: Formatted debug message
    """
    # Extract common debug fields
    buyPrice = details.get('buyPrice', 0)
    avgExitPrice = details.get('avgExitPrice', 0)
    quantity = details.get('quantity', 0)
    investmentUsdt = details.get('investmentUsdt', 0)
    totalCost = details.get('totalCost', 0)
    grossProfit = details.get('grossProfit', 0)
    totalFees = details.get('totalFees', 0)
    netProfit = details.get('netProfit', 0)
    profitPct = details.get('profitPct', 0)
    closeReason = details.get('closeReason', 'unknown')
    
    if 'avgSellPrice' in details and 'avgBuyPrice' in details:
        # Alternative format for sync-based calculations
        avgBuyPrice = details.get('avgBuyPrice', 0)
        avgSellPrice = details.get('avgSellPrice', 0)
        return f"[DEBUG] {symbol} P/L calculation: Gross={grossProfit:.4f}, Fees={totalFees:.4f}, Net={netProfit:.4f}, Buy={avgBuyPrice:.6f}, Sell={avgSellPrice:.6f}"
    else:
        # Detailed format for TP/SL calculations
        return f"[DEBUG] Closing position: {symbol} reason={closeReason} buyPrice={buyPrice:.6f} avgExitPrice={avgExitPrice:.6f} quantity={quantity:.6f} investmentUsdt={investmentUsdt:.4f} totalCost={totalCost:.4f} grossProfit={grossProfit:.4f} totalFees={totalFees:.4f} netP/L={netProfit:.4f} USDT ({profitPct:.2f}%)"
