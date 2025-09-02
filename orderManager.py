import ccxt
from connector import bingxConnector
import json
import os
import csv
import time
from datetime import datetime

from logManager import messages
from gvars import configFile, positionsFile, dailyBalanceFile, clientPrefix, marketsFile, selectionLogFile, csvFolder, tradesLogFile
from plotting import savePlot
from configManager import configManager
from logManager import messages
from validators import validateTradingParameters, validateSymbol, sanitizeSymbol
from exceptions import OrderExecutionError, InsufficientBalanceError, DataValidationError
from cacheManager import cachedCall
from notificationManager import notifyPositionClosure, notifyPositionClosureSimple

from datetime import datetime
from decimal import Decimal, ROUND_DOWN
## Eliminada dependencia de python-binance, ahora se usa BingX
from zoneinfo import ZoneInfo



class OrderManager:
    def __init__(self, isSandbox=False):
        # Load config and credentials
        try:
            self.config = configManager.config
        except Exception as e:
            messages(f"Error loading config: {e}", console=1, log=1, telegram=0)
            self.config = {}

        # Set base asset for balance checks (VST en sandbox, USDC en real)
        if isSandbox:
            self.baseAsset = "VST"
        else:
            self.baseAsset = self.config.get("baseAsset", "USDC")  # English comment: define the asset used for funding

        # Initialize CCXT exchange
        try:
            self.exchange = bingxConnector(isSandbox=isSandbox)
        except Exception as e:
            messages(f"Error initializing BingX connector: {e}", console=1, log=1, telegram=0)
            self.exchange = None

        # Load markets data once
        try:
            with open(marketsFile, encoding='utf-8') as f:
                self.markets = json.load(f)
        except Exception:
            try:
                self.markets = self.exchange.load_markets()
                os.makedirs(os.path.dirname(marketsFile), exist_ok=True)
                with open(marketsFile, 'w', encoding='utf-8') as mf:
                    json.dump(self.markets, mf, default=str, indent=2)
            except Exception as e:
                messages(f"Error saving markets data: {e}", console=1, log=1, telegram=0)
                self.markets = {}

        self.maxOpen = self.config.get("maxOpenPositions", 8)
        self.minVolume = self.config.get("lastCandleMinUSDVolume", 500000)
        self.hadInsufficientBalance = False

        # Ensure state files exist
        os.makedirs(os.path.dirname(positionsFile), exist_ok=True)
        for path in (positionsFile, dailyBalanceFile):
            if not os.path.isfile(path):
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump([], f)

        # Load persisted state
        self.positions = self.loadPositions()
        self.dailyBalance = self.loadDailyBalance()

        # Reconcile local JSON with exchange state
        self.updatePositions()

    def fetchOrderWithRetry(self, orderId, symbol, maxRetries=3, delay=2):
        """
        Fetch order with retry logic for rate limiting errors (100410)
        Returns None if max retries reached for rate limit errors
        """
        for attempt in range(maxRetries):
            try:
                return self.exchange.fetch_order(orderId, symbol)
            except Exception as e:
                error_msg = str(e).lower()
                if "100410" in error_msg or "please try again later" in error_msg:
                    if attempt < maxRetries - 1:
                        messages(f"Rate limit hit for {symbol}, retrying in {delay}s (attempt {attempt + 1}/{maxRetries})", pair=symbol, console=0, log=1, telegram=0)
                        time.sleep(delay)
                        delay *= 1.5  # Exponential backoff
                        continue
                    else:
                        messages(f"Max retries reached for {symbol} order {orderId}, will check trades instead", pair=symbol, console=0, log=1, telegram=0)
                        return None  # Return None instead of raising exception
                else:
                    # Not a rate limit error, re-raise immediately
                    raise e
        
        return None

    def getExchangeOpenPositions(self, maxRetries=3, retryDelay=2):
        """
        Get currently open positions from the exchange with enhanced retry logic
        Returns a set of symbols with open positions
        """
        consecutiveZeroResults = 0
        
        for attempt in range(maxRetries):
            try:
                positions = self.exchange.fetch_positions()
                openSymbols = set()
                messages(f"[DEBUG] Exchange returned {len(positions)} positions (attempt {attempt + 1}/{maxRetries})", console=0, log=1, telegram=0)
                
                for pos in positions:
                    symbol = pos.get('symbol', '')
                    contracts = float(pos.get('contracts', 0))
                    side = pos.get('side', '')
                    notional = pos.get('notional', 0)
                    unrealizedPnl = pos.get('unrealizedPnl', 0)
                    
                    messages(f"[DEBUG] Position: {symbol} contracts={contracts} side={side} notional={notional} pnl={unrealizedPnl}", console=0, log=1, telegram=0)
                    
                    if contracts > 0:  # Position has contracts
                        openSymbols.add(symbol)
                        messages(f"[DEBUG] Added {symbol} to open positions", console=0, log=1, telegram=0)
                
                messages(f"[DEBUG] Final open symbols: {openSymbols} (attempt {attempt + 1})", console=0, log=1, telegram=0)
                
                # Track consecutive zero results to detect API issues
                if len(positions) == 0:
                    consecutiveZeroResults += 1
                    if consecutiveZeroResults >= 2 and attempt < maxRetries - 1:
                        messages(f"[WARNING] Exchange returned 0 positions {consecutiveZeroResults} times consecutively, possible API issue. Retrying in {retryDelay}s", console=0, log=1, telegram=0)
                        time.sleep(retryDelay)
                        continue
                else:
                    consecutiveZeroResults = 0  # Reset counter
                
                # If we got any positions, return immediately (successful result)
                if len(positions) > 0 or attempt == maxRetries - 1:
                    return openSymbols
                    
                # If we got 0 positions and it's not the last attempt, retry
                if len(positions) == 0 and attempt < maxRetries - 1:
                    messages(f"[WARNING] Exchange returned 0 positions, retrying in {retryDelay}s", console=0, log=1, telegram=0)
                    time.sleep(retryDelay)
                    continue
                    
                return openSymbols
                
            except Exception as e:
                if attempt < maxRetries - 1:
                    messages(f"[ERROR] Could not fetch exchange positions (attempt {attempt + 1}): {e}, retrying", console=0, log=1, telegram=0)
                    time.sleep(retryDelay)
                    continue
                else:
                    messages(f"[ERROR] Could not fetch exchange positions after {maxRetries} attempts: {e}", console=1, log=1, telegram=0)
                    return set()
        
        return set()

    def cleanClosedPositions(self):
        """
        Clean positions that are no longer open on the exchange
        Added enhanced safety mechanism to avoid false deletions due to API inconsistency
        """
        try:
            exchangeOpenSymbols = self.getExchangeOpenPositions()
            localSymbols = set(self.positions.keys())
            
            messages(f"[DEBUG] Local positions: {localSymbols}", console=0, log=1, telegram=0)
            messages(f"[DEBUG] Exchange open positions: {exchangeOpenSymbols}", console=0, log=1, telegram=0)
            
            # Find positions that are in local file but not on exchange
            potentialClosedSymbols = localSymbols - exchangeOpenSymbols
            
            if potentialClosedSymbols:
                messages(f"[DEBUG] Potentially closed positions detected: {potentialClosedSymbols}", console=0, log=1, telegram=0)
                
                # Enhanced safety check: only remove positions with confirmed closing trades
                currentTime = time.time()
                symbolsToRemove = []
                symbolsToNotify = []
                
                for symbol in potentialClosedSymbols:
                    position = self.positions.get(symbol, {})
                    openTime = position.get('open_ts_unix', currentTime)
                    timeSinceOpen = currentTime - openTime
                    
                    # Skip if already notified to avoid duplicate notifications
                    if position.get('notified', False):
                        messages(f"[DEBUG] Position {symbol} already notified, skipping notification", console=0, log=1, telegram=0)
                        symbolsToRemove.append(symbol)
                        continue
                    
                    # Check for closing trades to confirm the position is actually closed
                    hasClosingTrade = self.checkForClosingTrade(symbol)
                    
                    # Also allow cleanup for old positions (more than 24 hours) even without closing trades
                    # This prevents old positions from staying forever due to API limitations
                    isOldPosition = timeSinceOpen > 86400  # 24 hours in seconds
                    
                    if hasClosingTrade:
                        # Only remove if we have confirmed closing trades and not yet notified
                        symbolsToRemove.append(symbol)
                        symbolsToNotify.append(symbol)
                        messages(f"[DEBUG] Position {symbol} confirmed closed via trades, safe to remove", console=0, log=1, telegram=0)
                    elif isOldPosition:
                        # Remove old positions that are not on exchange (likely closed but trades not accessible)
                        symbolsToRemove.append(symbol)
                        symbolsToNotify.append(symbol)
                        messages(f"[DEBUG] Position {symbol} is old ({timeSinceOpen/3600:.1f}h) and not on exchange, removing", console=0, log=1, telegram=0)
                    else:
                        messages(f"[DEBUG] Position {symbol} not found on exchange but no closing trades found, keeping for safety", console=0, log=1, telegram=0)
                
                # Send notifications for closed positions before removing them
                for symbol in symbolsToNotify:
                    self.notifyPositionClosed(symbol)
                
                if symbolsToRemove:
                    messages(f"Found {len(symbolsToRemove)} positions to clean: {', '.join(symbolsToRemove)}", console=0, log=1, telegram=0)
                    for symbol in symbolsToRemove:
                        messages(f"Removing closed position {symbol} from local file", pair=symbol, console=0, log=1, telegram=0)
                        self.positions.pop(symbol, None)
                    
                    self.savePositions()
                    messages(f"Cleaned {len(symbolsToRemove)} closed positions from local file", console=0, log=1, telegram=0)
                else:
                    messages("No positions old enough to be safely removed", console=0, log=1, telegram=0)
            else:
                messages("No closed positions found to clean", console=0, log=1, telegram=0)
                
        except Exception as e:
            messages(f"[ERROR] Error cleaning closed positions: {e}", console=1, log=1, telegram=0)

    def calculateOrderSize(self, symbol):
        """
        English comment: calculate how much baseAsset is needed
        to invest the configured usdcInvestment at current price.
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price  = float(ticker.get('last') or ticker.get('close') or 0)
            usdcInvest = float(self.config.get('usdcInvestment', 0))
            return usdcInvest / price if price else 0
        except Exception as e:
            messages(f"Error calculating order size for {symbol}: {e}", console=1, log=1, telegram=0, pair=symbol)
            return 0




    def loadPositions(self):
        """
        Carga las posiciones abiertas desde el JSON como dict {symbol: {...}}.
        Si el archivo está en formato antiguo (lista), lo migra automáticamente.
        Añade el campo 'side' si no existe.
        """
        try:
            with open(positionsFile, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            messages(f"Error loading positions: {e}", console=1, log=1, telegram=0)
            data = {}
        
        # Si es lista (formato antiguo), migrar a dict
        if isinstance(data, list):
            migrated = {item['symbol']: item for item in data if 'symbol' in item}
            self.savePositionsDict(migrated)
            data = migrated
        
        # Ensure all positions have 'side' field
        if isinstance(data, dict):
            for symbol, position in data.items():
                if 'side' not in position:
                    # Infer side from amount (positive = LONG, negative = SHORT)
                    amount = position.get('amount', 0)
                    position['side'] = 'LONG' if amount >= 0 else 'SHORT'
        
        return data if isinstance(data, dict) else {}

    def savePositions(self):
        """
        Guarda self.positions (dict) en el archivo JSON.
        """
        try:
            with open(positionsFile, 'w', encoding='utf-8') as f:
                json.dump(self.positions, f, indent=2, default=str)
        except Exception as e:
            messages(f"Error saving positions: {e}", console=1, log=1, telegram=0)

    def savePositionsDict(self, positions_dict):
        """
        Guarda un dict de posiciones en el archivo JSON.
        """
        try:
            with open(positionsFile, 'w', encoding='utf-8') as f:
                json.dump(positions_dict, f, indent=2, default=str)
        except Exception as e:
            messages(f"Error saving positions: {e}", console=1, log=1, telegram=0)

    def loadDailyBalance(self):
        today = datetime.utcnow().date().isoformat()
        try:
            with open(dailyBalanceFile, encoding='utf-8') as f:
                data = json.load(f) or {}
        except Exception as e:
            messages(f"Error loading daily balance: {e}", console=0, log=1, telegram=0)
            data = {}
        return data if data.get('date') == today else self.updateDailyBalance()

    def updateDailyBalance(self):
        freeUsdc = 0
        try:
            bal = self.exchange.fetch_balance()
            freeUsdc = float(bal.get('USDC', {}).get('free', 0) or 0)
        except Exception as e:
            messages(f"Error fetching balance: {e}", console=1, log=1, telegram=0, pair="USDC")
        record = {'date': datetime.utcnow().date().isoformat(), 'balance': freeUsdc}
        try:
            with open(dailyBalanceFile, 'w', encoding='utf-8') as f:
                json.dump(record, f, indent=2)
        except Exception as e:
            messages(f"Error saving daily balance: {e}", console=1, log=1, telegram=0)
        messages(f"Daily balance updated: {freeUsdc} USDC on {record['date']}", console=0, log=1, telegram=0, pair="USDC")
        return record
    

    def annotateSelectionLog(self, orderIdentifier: str, profitQuote: float, profitPct: float, tsOpenIso: str):
        """
        Busca la línea con coincidencia exacta de id y actualiza los campos de cierre.
        Si no la encuentra, lo loguea. Solo reescribe si se actualizó.
        """
        # ...existing code...
        rows = []
        updated = False
        with open(selectionLogFile, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            fieldnames = reader.fieldnames or []
            rows = list(reader)

        extras = ['profitQuote', 'profitPct', 'close_ts_iso', 'close_ts_unix', 'time_to_close_s']
        for key in extras:
            if key not in fieldnames:
                fieldnames.append(key)

        closeTsUnix = int(time.time())
        closeTsIso  = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H-%M-%S")
        try:
            dtOpen = datetime.fromisoformat(tsOpenIso)
            openTsUnix = int(dtOpen.timestamp())
        except:
            openTsUnix = closeTsUnix
        elapsed = closeTsUnix - openTsUnix

        for row in rows:
            row_id = (row.get('id') or '').strip()
            if row_id == orderIdentifier:
                row['profitQuote']     = f"{profitQuote:.6f}"
                row['profitPct']       = f"{profitPct:.2f}"
                row['close_ts_iso']    = closeTsIso
                row['close_ts_unix']   = str(closeTsUnix)
                row['time_to_close_s'] = str(elapsed)
                updated = True
                break

        if updated:
            with open(selectionLogFile, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
                writer.writeheader()
                writer.writerows(rows)
        else:
            messages(f"[ERROR] No se encontró la línea con id={orderIdentifier} para actualizar cierre en selectionLog.csv", console=1, log=1, telegram=1)

    def logTrade(self, symbol: str, openDate: str, closeDate: str, elapsed: str, investmentUsdt: float, leverage: int, netProfitUsdt: float):
        """
        Log a completed trade to trades.csv
        """
        try:
            import os
            
            tradesFile = tradesLogFile
            
            # Prepare the trade record
            tradeRecord = {
                'symbol': symbol,
                'open_date': openDate,
                'close_date': closeDate,
                'elapsed': elapsed,
                'investment_usdt': f"{investmentUsdt:.4f}",
                'leverage': str(leverage),
                'net_profit_usdt': f"{netProfitUsdt:.4f}"
            }
            
            # Check if file exists and has header
            fileExists = os.path.exists(tradesFile)
            
            # Append the trade record
            with open(tradesFile, 'a', encoding='utf-8', newline='') as f:
                fieldnames = ['symbol', 'open_date', 'close_date', 'elapsed', 'investment_usdt', 'leverage', 'net_profit_usdt']
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
                
                # Write header if file is new or empty
                if not fileExists or os.path.getsize(tradesFile) == 0:
                    writer.writeheader()
                
                writer.writerow(tradeRecord)
            
            messages(f"[DEBUG] Trade logged: {symbol} P/L={netProfitUsdt:.4f} USDT", pair=symbol, console=0, log=1, telegram=0)
            
        except Exception as e:
            messages(f"[ERROR] Failed to log trade for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)

    def logTradeFromPosition(self, symbol: str, position: dict, closeReason: str, netProfitUsdt: float):
        """
        Extract trade data from position and log it to trades.csv
        """
        try:
            # Extract position data
            openDateIso = position.get('timestamp', '')  # Format: "2025-08-26 16-30-59"
            openPrice = float(position.get('openPrice', 0))
            amount = float(position.get('amount', 0))
            
            # Calculate investment (amount * price / leverage)
            # Assuming leverage 10 (could be extracted from position if stored)
            leverage = 10  # Default, could be made configurable
            investmentUsdt = (amount * openPrice) / leverage
            
            # Format dates
            if openDateIso:
                try:
                    # Convert from "2025-08-26 16-30-59" format to proper format
                    openDateFormatted = openDateIso.replace('-', ':', 2).replace('-', '/')
                    openDateObj = datetime.strptime(openDateFormatted, '%Y/%m/%d %H:%M:%S')
                    openDateHuman = openDateObj.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    openDateHuman = openDateIso
            else:
                openDateHuman = "Unknown"
            
            # Current time as close date
            closeDateHuman = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Calculate elapsed time
            try:
                if openDateIso:
                    openDateFormatted = openDateIso.replace('-', ':', 2).replace('-', '/')
                    openDateObj = datetime.strptime(openDateFormatted, '%Y/%m/%d %H:%M:%S')
                    closeeDateObj = datetime.now()
                    elapsed = closeeDateObj - openDateObj
                    
                    # Format elapsed time as human readable
                    totalSeconds = int(elapsed.total_seconds())
                    hours = totalSeconds // 3600
                    minutes = (totalSeconds % 3600) // 60
                    seconds = totalSeconds % 60
                    
                    if hours > 0:
                        elapsedHuman = f"{hours}h {minutes}m {seconds}s"
                    elif minutes > 0:
                        elapsedHuman = f"{minutes}m {seconds}s"
                    else:
                        elapsedHuman = f"{seconds}s"
                else:
                    elapsedHuman = "Unknown"
            except:
                elapsedHuman = "Unknown"
            
            # Log the trade
            self.logTrade(
                symbol=symbol,
                openDate=openDateHuman,
                closeDate=closeDateHuman,
                elapsed=elapsedHuman,
                investmentUsdt=investmentUsdt,
                leverage=leverage,
                netProfitUsdt=netProfitUsdt
            )
            
        except Exception as e:
            messages(f"[ERROR] Failed to extract trade data for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)





    def updatePositions(self):
        """
        Sincroniza el estado con el exchange y elimina solo el nodo del símbolo cerrado.
        """
        #messages("Analyzing positions", console=1, log=1, telegram=0)
        # Cargar desde disco solo si el dict está vacío o no se ha cargado
        if not hasattr(self, '_positions_loaded') or not self.positions:
            self.positions = self.loadPositions()
            self._positions_loaded = True
        
        # First, clean positions that are no longer open on the exchange
        self.cleanClosedPositions()
        
        symbols_to_remove = []
        for symbol, position in self.positions.items():
            # Skip if already notified to prevent duplicate notifications
            if position.get('notified', False):
                symbols_to_remove.append(symbol)
                continue
                
            buyQuantity  = float(position.get('amount', 0))
            buyPrice     = float(position.get('openPrice', 0))
            tsOpenIso    = position.get('timestamp')  # ISO string
            openTsUnix   = position.get('open_ts_unix') or int(datetime.fromisoformat(tsOpenIso).timestamp())
            # Usar los nuevos campos explícitos para TP/SL activos
            tpOrderId2 = position.get('tpOrderId2')
            slOrderId2 = position.get('slOrderId2')
            tpOrderId1 = position.get('tpOrderId1')
            slOrderId1 = position.get('slOrderId1')
            # Comentar los campos antiguos (deprecados)
            # tpOrderId    = position.get('tpOrderId')
            # slOrderId    = position.get('slOrderId')
            notified     = position.get('notified', False)
            tpStatus = slStatus = None
            tpInfo = slInfo = None
            # Usar el TP/SL activo (2 si existe, si no el 1)
            activeTpOrderId = tpOrderId2 if tpOrderId2 else tpOrderId1
            activeSlOrderId = slOrderId2 if slOrderId2 else slOrderId1
            
            # Use the improved order checking logic
            hasClosingOrder = self._checkOrderStatusForClosure(symbol, activeTpOrderId, activeSlOrderId)
            
            if not hasClosingOrder:
                continue  # Position still active, skip to next
                
            # If we reach here, a closing order was executed
            # Determine close reason by checking which order was executed
            close_reason = 'UNKNOWN'
            if activeTpOrderId:
                try:
                    tpOrder = self.exchange.fetch_order(activeTpOrderId, symbol)
                    if tpOrder.get('status') in ['closed', 'filled', 'executed']:
                        close_reason = 'TP'
                except:
                    pass
            
            if close_reason == 'UNKNOWN' and activeSlOrderId:
                try:
                    slOrder = self.exchange.fetch_order(activeSlOrderId, symbol)
                    if slOrder.get('status') in ['closed', 'filled', 'executed']:
                        close_reason = 'SL'
                except:
                    pass
            
            # Process the closed position
            try:
                allTrades = self.exchange.fetch_my_trades(symbol)
                
                # Filter for sell trades after position open
                sellTrades = [
                    t for t in allTrades
                    if t.get('side') == 'sell' and t.get('timestamp', 0) >= openTsUnix * 1000
                ]
                
                if not sellTrades:
                    messages(f"No sell trades found for {symbol} despite closed orders, skipping", pair=symbol, console=1, log=1, telegram=0)
                    continue
                
                # Calculate totals from sell trades
                totalQuantity = sum(float(t.get('amount', 0)) for t in sellTrades)
                totalCost = sum(float(t.get('cost', 0)) for t in sellTrades)
                totalFees = sum(float(t.get('fee', {}).get('cost', 0)) for t in sellTrades)
                
                # Calculate average exit price
                avgExitPrice = totalCost / totalQuantity if totalQuantity > 0 else 0
                
                # Calculate investment and profit
                actualInvestmentUsdt = buyQuantity * buyPrice
                grossProfitQuote = totalCost - actualInvestmentUsdt
                totalFeesComplete = totalFees
                profitQuote = grossProfitQuote - totalFeesComplete
                profitPct = (profitQuote / actualInvestmentUsdt) * 100 if actualInvestmentUsdt > 0 else 0
            
            except Exception as e:
                messages(f"[ERROR] Could not process trades for {symbol}: {e}", pair=symbol, console=1, log=1, telegram=0)
                continue

            if not close_reason:
                continue

            if notified:
                continue

            try:
                allTrades = self.exchange.fetch_my_trades(symbol)
            except Exception as e:
                allTrades = []
                messages(f"[DEBUG] Failed to get {symbol} trades: {e}", pair=symbol, console=1, log=1, telegram=0)

            relevantTrades = [
                t for t in allTrades
                if t.get('side') == 'sell' and t.get('timestamp', 0) >= openTsUnix * 1000
            ]

            totalQuantity = 0.0
            totalCost     = 0.0
            totalFees     = 0.0
            for trade in relevantTrades:
                amt  = float(trade.get('amount', 0))
                cost = float(trade.get('cost',   0))
                fee  = float(trade.get('fee', {}).get('cost', 0))
                if totalQuantity + amt > buyQuantity:
                    needed       = buyQuantity - totalQuantity
                    proportionalCost = cost * (needed / amt)
                    proportionalFee = fee * (needed / amt)
                    totalCost   += proportionalCost
                    totalFees   += proportionalFee
                    totalQuantity = buyQuantity
                    break
                totalQuantity += amt
                totalCost     += cost
                totalFees     += fee

            avgExitPrice = totalCost / totalQuantity if totalQuantity else 0
            profitPct    = ((avgExitPrice / buyPrice - 1) * 100) if buyPrice else 0
            
            # Calculate profit in USDT for futures with leverage
            # Get the actual investment and leverage from the position
            actualInvestmentUsdt = float(position.get('investment_usdt', 0))
            leverage = float(position.get('leverage', 10))
            
            # If investment_usdt is not available (old positions), estimate it
            if not actualInvestmentUsdt:
                # For old positions, estimate: notional_value / leverage
                notionalValue = buyQuantity * buyPrice
                actualInvestmentUsdt = notionalValue / leverage
            
            # For futures: profit = investment × (price_change_%) × leverage
            priceChangePct = profitPct / 100  # Convert percentage to decimal
            grossProfitQuote = actualInvestmentUsdt * priceChangePct * leverage
            
            # Get buy fees from position opening (estimate based on investment and typical fee rate)
            # For BingX futures, typical fee is 0.05% (0.0005)
            estimatedBuyFees = actualInvestmentUsdt * 0.0005  # Estimate buy fees
            totalFeesComplete = totalFees + estimatedBuyFees  # Total fees (buy + sell)
            
            # Net profit after all fees
            profitQuote = grossProfitQuote - totalFeesComplete
            
            # Alternative calculation (should give same result): profitQuote = investmentUsdt * (profitPct / 100)
            
            # Prepare debug details for unified notification
            debugDetails = {
                'buyPrice': buyPrice,
                'avgExitPrice': avgExitPrice,
                'quantity': totalQuantity,
                'investmentUsdt': actualInvestmentUsdt,
                'totalCost': totalCost,
                'grossProfit': grossProfitQuote,
                'totalFees': totalFeesComplete,
                'netProfit': profitQuote,
                'profitPct': profitPct,
                'closeReason': close_reason
            }
            
            try:
                # Use unified notification function
                notifyPositionClosure(symbol, close_reason, profitQuote, profitPct, totalFeesComplete, debugDetails)
                
                # Comentar el uso antiguo y dejar nota
                # recordId = f"{tpOrderId or ''}-{slOrderId or ''}"
                recordId = f"{activeTpOrderId or ''}-{activeSlOrderId or ''}"
                self.annotateSelectionLog(recordId, profitQuote, profitPct, tsOpenIso)
                
                # Log the trade to trades.csv
                self.logTradeFromPosition(symbol, position, close_reason, profitQuote)
                
                position['notified'] = True
                # Marcar para eliminar del dict
                symbols_to_remove.append(symbol)
                continue
            except Exception as e:
                messages(f"[ERROR] Telegram/log failed for {symbol}: {e}", pair=symbol, console=1, log=1, telegram=0)
                position['notified'] = False
                self.positions[symbol] = position
                continue
        # Eliminar solo los símbolos cerrados
        for symbol in symbols_to_remove:
            self.positions.pop(symbol, None)
        self.savePositions()









    def openPosition(self, symbol, slope=None, intercept=None, investmentPct=1.0, side='long'):
        """
        Market buy with CCXT, then place OCO sell (TP + SL) with python-binance.
        Never open more than one trade for the same symbol per run.
        """
        messages(f"[DEBUG] symbol recibido: {symbol}", console=0, log=1, telegram=0)
        # 0) If we've already flagged insufficient balance, skip
        if self.hadInsufficientBalance:
            binSym = symbol.replace('/', '')
            return None

        # 1) Refresh and reconcile open positions
        self.updatePositions()
        if symbol in self.positions:
            #messages(f"Skipping openPosition for {symbol}: position already open", console=1, log=1, telegram=0, pair=symbol)
            return None

        # 1.2) Skip if we've hit the maxOpen limit
        if len(self.positions) >= self.maxOpen:
            messages(f"Skipping openPosition for {symbol}: max open positions reached ({self.maxOpen})", console=1, log=1, telegram=0, pair=symbol)
            return None

        # 2) Check free balance in baseAsset (e.g. USDC)
        free = self.exchange.fetch_free_balance()
        availableUSDC = float(free.get(self.baseAsset, 0) or 0)
        baseInvestment = float(self.config.get('usdcInvestment', 0))
        investUSDC = baseInvestment * investmentPct
        if availableUSDC < investUSDC:
            if investmentPct == 1.0 and availableUSDC > 0:
                messages(f"[EXCEPCIÓN] No hay saldo suficiente para 100% de inversión, usando todo el saldo disponible: {availableUSDC:.6f} USDC", console=1, log=1, telegram=0, pair=symbol)
                investUSDC = availableUSDC
            else:
                self.hadInsufficientBalance = True
                messages(f"Skipping openPosition for {symbol}: insufficient balance {availableUSDC:.6f} USDC, need {investUSDC:.6f} USDC", console=1, log=1, telegram=0, pair=symbol )
                return None

        # 3) Fetch current market price
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price = Decimal(str(ticker.get('last') or 0))
            if price <= 0:
                raise ValueError(f"Invalid price for {symbol}: {price}")
        except Exception as e:
            messages(f"Error fetching price for {symbol}: {e}", console=1, log=1, telegram=0, pair=symbol)
            return None

        # 4) Compute how much base asset to buy
        quoteQty = Decimal(str(investUSDC))
        rawAmt = quoteQty / price
        normSymbol = symbol.replace(':USDT', '') if symbol.endswith(':USDT') else symbol
        messages(f"[DEBUG] normSymbol usado para markets: {normSymbol}", console=0, log=1, telegram=0)
        info = self.markets.get(normSymbol, {}).get('info', {})
        messages(f"[DEBUG] info markets: {json.dumps(info)}", console=0, log=1, telegram=0)
        pf = next((f for f in info.get('filters', []) if f.get('filterType') == 'PRICE_FILTER'), {})
        ls = next((f for f in info.get('filters', []) if f.get('filterType') == 'LOT_SIZE'), {})
        tickSize = Decimal(pf.get('tickSize', info.get('tickSize', '0'))) or None
        stepSize = Decimal(ls.get('stepSize', info.get('stepSize', '0'))) or None
        minQty   = Decimal(ls.get('minQty', info.get('minQty', '0'))) or None
        messages(f"[DEBUG] minQty: {minQty}, stepSize: {stepSize}, tickSize: {tickSize}", console=0, log=1, telegram=0)
        messages(f"[DEBUG] rawAmt calculado: {rawAmt}", console=0, log=1, telegram=0)
        amtDec = rawAmt.quantize(stepSize, rounding=ROUND_DOWN) if stepSize else rawAmt
        messages(f"[DEBUG] amtDec tras quantize: {amtDec}", console=0, log=1, telegram=0)
        # Si la cantidad calculada es menor que el mínimo, usar el mínimo permitido y recalcular inversión
        if minQty and amtDec < minQty:
            messages(f"[DEBUG] Amount {amtDec} below minimum lot size {minQty}, ajustando a mínimo", console=0, log=1, telegram=0, pair=symbol)
            amtDec = minQty
            investUSDC = float(minQty) * float(price)
        amount = float(amtDec)
        messages(f"[DEBUG] Opening {symbol}: price={price}, amount={amtDec}, usdc={investUSDC}", pair=symbol, console=0, log=1, telegram=0)

        # 5) Place futures order (long/short)
        clientId = f"{clientPrefix}{symbol.replace('/','')}_{int(datetime.utcnow().timestamp())}"
        leverage = int(self.config.get('leverage', 10))
        orderSide = 'buy' if side == 'long' else 'sell'
        positionSide = 'LONG' if side == 'long' else 'SHORT'
        try:
            hedgeSide = positionSide if positionSide in ['LONG', 'SHORT'] else 'BOTH'
            self.exchange.set_leverage(leverage, symbol, params={'side': hedgeSide})
            orderResp = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=orderSide,
                amount=amount,
                params={
                    'positionSide': positionSide,
                    'newClientOrderId': clientId
                }
            )
            # Log complete order response
            messages(f"[DEBUG] Complete order response for {symbol}: {orderResp}", pair=symbol, console=0, log=1, telegram=0)
            
            filled    = Decimal(str(orderResp.get('filled') or orderResp.get('amount') or 0))
            openPrice = Decimal(str(orderResp.get('price') or price))
            messages(f"  ➡️   Futures order executed for {symbol}: side={side}, filled={filled}, price={openPrice}, leverage={leverage}", pair=symbol, console=1, log=1, telegram=0)
        except Exception as e:
            messages(f"Error executing futures order for {symbol}: {e}", console=1, log=1, telegram=0, pair=symbol)
            return None

        # 6) Calculate TP/SL teniendo en cuenta el leverage
        tpPct = Decimal(str(self.config.get('tp1', 0.02)))
        slPct = Decimal(str(self.config.get('sl1', 0.01)))
        leverage = int(self.config.get('leverage', 10))
        tpPctPrice = tpPct / Decimal(leverage)
        slPctPrice = slPct / Decimal(leverage)
        rawTp = openPrice * (Decimal('1') + tpPctPrice)
        rawSp = openPrice * (Decimal('1') - slPctPrice)
        tpPrice = (rawTp // tickSize) * tickSize if tickSize else rawTp
        slPrice = (rawSp // tickSize) * tickSize if tickSize else rawSp
        minPrice = Decimal(pf.get('minPrice','0'))
        if tickSize:
            tpPrice = max(tpPrice, minPrice)
            slPrice = max(slPrice, minPrice)

        # 7) Place TP and SL orders (no OCO)
        tpId, slId = None, None
        try:
            tpOrder = self.exchange.create_order(
                symbol=symbol,
                type='TAKE_PROFIT_MARKET',
                side='sell' if side == 'long' else 'buy',
                amount=float(filled),
                params={
                    'stopPrice': float(tpPrice),
                    'positionSide': positionSide
                }
            )
            # Log complete TP order response
            messages(f"[DEBUG] Complete TP order response for {symbol}: {tpOrder}", pair=symbol, console=0, log=1, telegram=0)
            tpId = tpOrder.get('id')
            messages(f"[DEBUG] TP order ID extracted: {tpId}", pair=symbol, console=0, log=1, telegram=0)
            # Solo mostrar mensaje si hay error
        except Exception as e:
            messages(f"[ERROR] Error creando TP: {e}", log=1)
        try:
            slOrder = self.exchange.create_order(
                symbol=symbol,
                type='STOP_MARKET',
                side='sell' if side == 'long' else 'buy',
                amount=float(filled),
                params={
                    'stopPrice': float(slPrice),
                    'positionSide': positionSide
                }
            )
            # Log complete SL order response
            messages(f"[DEBUG] Complete SL order response for {symbol}: {slOrder}", pair=symbol, console=0, log=1, telegram=0)
            slId = slOrder.get('id')
            messages(f"[DEBUG] SL order ID extracted: {slId}", pair=symbol, console=0, log=1, telegram=0)
            # Solo mostrar mensaje si hay error
        except Exception as e:
            messages(f"[ERROR] Error creando SL: {e}", log=1)

        # 8) Persist and return
        record = {
            'symbol':    symbol,
            'openPrice': float(openPrice),
            'amount':    float(filled),
            'tpPrice':   float(tpPrice),
            'slPrice':   float(slPrice),
            'tpOrderId1': tpId,
            'slOrderId1': slId,
            'timestamp': datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H-%M-%S"),
            'open_ts_unix': int(time.time()),
            'slope': slope if slope is not None else 0,
            'intercept': intercept if intercept is not None else 0,
            'tpPercent': float(tpPct) * 100,
            'slPercent': float(slPct) * 100,
            'leverage': leverage,
            'investment_usdt': investUSDC,
            'side': side.upper()  # Add side information (LONG/SHORT)
        }
        # Log the complete position record being saved
        messages(f"[DEBUG] Saving position record for {symbol}: {record}", pair=symbol, console=0, log=1, telegram=0)
        
        self.positions[symbol] = record
        self.savePositions()
        # Enviar plot por Telegram tras abrir posición
        try:
            import glob
            import os
            csv_path = None
            # Extraer ticker base
            base_ticker = symbol.split('/')[0] if '/' in symbol else symbol.split('_')[0]
            # Obtener timeframe y número de velas desde config
            timeframe = str(self.config.get('timeframe', '15m'))
            requested_candles = str(self.config.get('requestedCandles', 180))
            # Construir nombre de archivo CSV
            csv_filename = f"{base_ticker}_{timeframe}_{requested_candles}.csv"
            csv_path = os.path.join(csvFolder, csv_filename)
            if not os.path.isfile(csv_path):
                raise Exception(f"No CSV found for {symbol} as {csv_filename} in {csvFolder}")
            slope = record.get('slope', 0)
            intercept = record.get('intercept', 0)
            oppData = record.get('opp', {}) if 'opp' in record else {}
            item = {
                'csvPath': csv_path,
                'pair': base_ticker,
                'slope': slope,
                'intercept': intercept,
                'minPctBounceAllowed': float(self.config.get('minPctBounceAllowed', 0.003)),
                'maxPctBounceAllowed': float(self.config.get('maxPctBounceAllowed', 0.09)),
                'tpPrice': record.get('tpPrice'),
                'slPrice': record.get('slPrice'),
                'ma99': oppData.get('ma99'),
                'momentum': oppData.get('momentum'),
                'distance': oppData.get('distancePct'),
                'touches': oppData.get('touchesCount'),
                'volume': oppData.get('volumeRatio'),
                'score': oppData.get('score')
            }
            plot_path = savePlot(item)
            # Plot will be sent by pairs.py, no need to send it here again
            messages(f"Plot generated for {symbol}: {plot_path}", pair=symbol, console=0, log=1, telegram=0)
        except Exception as e:
            messages(f"[ERROR] No se pudo generar el plot para {symbol}: {e}", pair=symbol, console=1, log=1, telegram=0)
        self.savePositions()
        return record

        # 5) Place stop loss and take profit orders (futuros BingX)
        # Solo si la orden principal se ejecutó correctamente
        if order and order.get('status') == 'closed':
            # Calcula precios de SL y TP según lógica del bot
            stopLossPrice = round(price * (1 - stopLossPerc/100), 5) if side == 'long' else round(price * (1 + stopLossPerc/100), 5)
            takeProfitPrice = round(price * (1 + takeProfitPerc/100), 5) if side == 'long' else round(price * (1 - takeProfitPerc/100), 5)
            # Orden STOP_MARKET (stop loss)
            try:
                slOrder = self.connector.createOrder(
                    symbol=symbol,
                    type='STOP_MARKET',
                    side='sell' if side == 'long' else 'buy',
                    amount=amount,
                    price=stopLossPrice,
                    params={'stopPrice': stopLossPrice, 'reduceOnly': True}
                )
                messages(f"[INFO] Stop loss order creada: {slOrder}", log=1)
            except Exception as e:
                messages(f"[ERROR] Error creando stop loss: {e}", log=1)
            # Orden TAKE_PROFIT_MARKET (take profit)
            try:
                tpOrder = self.connector.createOrder(
                    symbol=symbol,
                    type='TAKE_PROFIT_MARKET',
                    side='sell' if side == 'long' else 'buy',
                    amount=amount,
                    price=takeProfitPrice,
                    params={'stopPrice': takeProfitPrice, 'reduceOnly': True}
                )
                messages(f"[INFO] Take profit order creada: {tpOrder}", log=1)
            except Exception as e:
                messages(f"[ERROR] Error creando take profit: {e}", log=1)

    def _checkOrderStatusForClosure(self, symbol, tpOrderId, slOrderId):
        """
        Helper method to check if TP or SL orders have been executed
        Uses the same logic as checkForClosingTrade but returns boolean
        Returns True if any closing order is executed, False otherwise
        """
        try:
            if not tpOrderId and not slOrderId:
                messages(f"[DEBUG] No TP/SL order IDs found for {symbol}, using fallback method", pair=symbol, console=0, log=1, telegram=0)
                return self._checkForClosingTradesFallback(symbol)
            
            # Check Take Profit order status
            if tpOrderId:
                try:
                    tpOrder = self.exchange.fetch_order(tpOrderId, symbol)
                    tpStatus = tpOrder.get('status', 'unknown')
                    messages(f"[DEBUG] TP order {tpOrderId} status: {tpStatus}", pair=symbol, console=0, log=1, telegram=0)
                    
                    if tpStatus in ['closed', 'filled', 'executed']:
                        messages(f"[INFO] Take Profit order executed for {symbol}", pair=symbol, console=0, log=1, telegram=0)
                        return True
                except Exception as e:
                    messages(f"[DEBUG] Could not fetch TP order {tpOrderId} for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)
            
            # Check Stop Loss order status
            if slOrderId:
                try:
                    slOrder = self.exchange.fetch_order(slOrderId, symbol)
                    slStatus = slOrder.get('status', 'unknown')
                    messages(f"[DEBUG] SL order {slOrderId} status: {slStatus}", pair=symbol, console=0, log=1, telegram=0)
                    
                    if slStatus in ['closed', 'filled', 'executed']:
                        messages(f"[INFO] Stop Loss order executed for {symbol}", pair=symbol, console=0, log=1, telegram=0)
                        return True
                except Exception as e:
                    messages(f"[DEBUG] Could not fetch SL order {slOrderId} for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)
            
            messages(f"[DEBUG] No closing orders executed for {symbol}", pair=symbol, console=0, log=1, telegram=0)
            return False
                
        except Exception as e:
            messages(f"[ERROR] Could not check closing orders for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)
            return False

    def checkForClosingTrade(self, symbol):
        """
        Check if TP or SL orders have been executed to confirm position closure
        Uses specific order IDs from the position data for precise verification
        Returns True if any closing order is executed, False otherwise
        """
        position = self.positions.get(symbol, {})
        tpOrderId = position.get('tpOrderId1')
        slOrderId = position.get('slOrderId1')
        
        return self._checkOrderStatusForClosure(symbol, tpOrderId, slOrderId)
    
    def _checkForClosingTradesFallback(self, symbol):
        """
        Fallback method to check for closing trades when order IDs are not available
        Uses the original trade search method
        """
        try:
            position = self.positions.get(symbol, {})
            openTsUnix = position.get('open_ts_unix', 0)
            
            allTrades = self.exchange.fetch_my_trades(symbol)
            relevantTrades = [
                t for t in allTrades
                if t.get('side') == 'sell' and t.get('timestamp', 0) >= openTsUnix * 1000
            ]
            
            if relevantTrades:
                messages(f"[DEBUG] Found {len(relevantTrades)} closing trades for {symbol} (fallback method)", pair=symbol, console=0, log=1, telegram=0)
                return True
            else:
                messages(f"[DEBUG] No closing trades found for {symbol} (fallback method)", pair=symbol, console=0, log=1, telegram=0)
                return False
                
        except Exception as e:
            messages(f"[ERROR] Could not check closing trades for {symbol} (fallback): {e}", pair=symbol, console=0, log=1, telegram=0)
            return False

    def notifyPositionClosed(self, symbol):
        """
        Send notification for a closed position with detailed P/L calculation including fees
        Used when position is detected as closed but detailed info is not available
        """
        try:
            position = self.positions.get(symbol, {})
            if position.get('notified', False):
                return  # Already notified
                
            # Get position data
            openPrice = float(position.get('openPrice', 0))
            amount = float(position.get('amount', 0))
            openTsUnix = position.get('open_ts_unix', 0)
            
            if not openPrice or not amount or not openTsUnix:
                # Fallback to simple notification if data is missing
                cleanSymbol = symbol.replace('/USDT:USDT', '').replace('/', '_')
                simpleMessage = f"Position closed: {cleanSymbol} (detected via exchange sync)"
                messages(simpleMessage, pair=symbol, console=1, log=1, telegram=1)
                position['notified'] = True
                self.positions[symbol] = position
                return
            
            # Get all trades for this symbol since position opened
            try:
                allTrades = self.exchange.fetch_my_trades(symbol)
                relevantTrades = [
                    t for t in allTrades
                    if t.get('timestamp', 0) >= openTsUnix * 1000
                ]
                
                buyTrades = [t for t in relevantTrades if t.get('side') == 'buy']
                sellTrades = [t for t in relevantTrades if t.get('side') == 'sell']
                
                if not sellTrades:
                    # No sell trades found, send notification without bells
                    cleanSymbol = symbol.replace('/USDT:USDT', '').replace('/', '_')
                    simpleMessage = f"Position closed: {cleanSymbol} (detected via exchange sync - no sell trades found)"
                    messages(simpleMessage, pair=symbol, console=1, log=1, telegram=1)
                    position['notified'] = True
                    self.positions[symbol] = position
                    return
                
                # Calculate average buy and sell prices
                totalBuyAmount = sum(float(t.get('amount', 0)) for t in buyTrades)
                totalBuyValue = sum(float(t.get('amount', 0)) * float(t.get('price', 0)) for t in buyTrades)
                avgBuyPrice = totalBuyValue / totalBuyAmount if totalBuyAmount > 0 else openPrice
                
                totalSellAmount = sum(float(t.get('amount', 0)) for t in sellTrades)
                totalSellValue = sum(float(t.get('amount', 0)) * float(t.get('price', 0)) for t in sellTrades)
                avgSellPrice = totalSellValue / totalSellAmount if totalSellAmount > 0 else 0
                
                # Calculate gross P/L for futures contracts
                # For futures: P/L = (Exit_Price - Entry_Price) × Amount ÷ Leverage
                # The correct calculation for futures considers the actual investment amount
                
                # Get the original position investment amount (if available)
                originalInvestmentUsdt = position.get('investment_usdt') or (amount * avgBuyPrice / 10)  # Default leverage 10
                leverage = position.get('leverage', 10)  # Get leverage from position or default to 10
                
                # Calculate P/L percentage
                priceChangePct = ((avgSellPrice - avgBuyPrice) / avgBuyPrice) if avgBuyPrice > 0 else 0
                
                # For futures, the actual profit in USDT = investment × price_change_% × leverage
                grossProfitQuote = originalInvestmentUsdt * priceChangePct * leverage
                
                # Debug logging for troubleshooting
                messages(f"[DEBUG] P/L calculation for {symbol}: totalBuyAmount={totalBuyAmount:.6f}, totalBuyValue={totalBuyValue:.6f}, avgBuyPrice={avgBuyPrice:.6f}", pair=symbol, console=0, log=1, telegram=0)
                messages(f"[DEBUG] P/L calculation for {symbol}: totalSellAmount={totalSellAmount:.6f}, totalSellValue={totalSellValue:.6f}, avgSellPrice={avgSellPrice:.6f}", pair=symbol, console=0, log=1, telegram=0)
                messages(f"[DEBUG] P/L calculation for {symbol}: grossProfitQuote=(avgSellPrice-avgBuyPrice)*totalSellAmount=({avgSellPrice:.6f}-{avgBuyPrice:.6f})*{totalSellAmount:.6f}={grossProfitQuote:.6f}", pair=symbol, console=0, log=1, telegram=0)
                
                # Calculate fees (assume same fee rate for buy and sell, multiply by 2)
                # Get fee from the most recent trade (buy or sell)
                recentTrade = max(relevantTrades, key=lambda t: t.get('timestamp', 0))
                feeRate = 0
                if recentTrade.get('fee') and recentTrade.get('fee', {}).get('rate'):
                    feeRate = float(recentTrade.get('fee', {}).get('rate', 0))
                elif recentTrade.get('fee') and recentTrade.get('fee', {}).get('cost'):
                    # Calculate fee rate from cost and value
                    feeCost = float(recentTrade.get('fee', {}).get('cost', 0))
                    tradeValue = float(recentTrade.get('amount', 0)) * float(recentTrade.get('price', 0))
                    feeRate = feeCost / tradeValue if tradeValue > 0 else 0
                
                # Estimate total fees (buy fee + sell fee)
                totalFees = (totalBuyValue * feeRate) + (totalSellValue * feeRate)
                
                # Calculate net P/L
                netProfitQuote = grossProfitQuote - totalFees
                netProfitPct = ((avgSellPrice / avgBuyPrice - 1) * 100) if avgBuyPrice > 0 else 0
                
                # Prepare debug details for unified notification
                debugDetails = {
                    'grossProfit': grossProfitQuote,
                    'totalFees': totalFees,
                    'netProfit': netProfitQuote,
                    'avgBuyPrice': avgBuyPrice,
                    'avgSellPrice': avgSellPrice,
                    'profitPct': netProfitPct
                }
                
                # Use unified notification function
                notifyPositionClosure(symbol, "SYNC", netProfitQuote, netProfitPct, totalFees, debugDetails)
                
                # Log the trade to trades.csv
                self.logTradeFromPosition(symbol, position, "SYNC", netProfitQuote)
                
            except Exception as trade_error:
                messages(f"[ERROR] Could not calculate P/L for {symbol}: {trade_error}", pair=symbol, console=0, log=1, telegram=0)
                # Fallback to simple notification
                cleanSymbol = symbol.replace('/USDT:USDT', '').replace('/', '_')
                simpleMessage = f"Position closed: {cleanSymbol} (detected via exchange sync - P/L calculation failed)"
                messages(simpleMessage, pair=symbol, console=1, log=1, telegram=1)
            
            # Mark as notified
            position['notified'] = True
            self.positions[symbol] = position
            
        except Exception as e:
            messages(f"[ERROR] Failed to notify closure for {symbol}: {e}", pair=symbol, console=1, log=1, telegram=0)

        # ...existing code...


