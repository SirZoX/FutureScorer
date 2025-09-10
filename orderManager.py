import ccxt
from connector import bingxConnector
import json
import os
import csv
import time
import threading
from datetime import datetime

from logManager import messages
from gvars import configFile, positionsFile, dailyBalanceFile, clientPrefix, marketsFile, selectionLogFile, csvFolder, tradesLogFile
from plotting import savePlot
from configManager import configManager
from logManager import messages
from validators import validateTradingParameters, validateSymbol, sanitizeSymbol
from exceptions import OrderExecutionError, InsufficientBalanceError, DataValidationError

from datetime import datetime
from decimal import Decimal, ROUND_DOWN
## Eliminada dependencia de python-binance, ahora se usa BingX
from zoneinfo import ZoneInfo


class OrderManager:
    def __init__(self, isSandbox=False):
        # Initialize thread locks for file operations
        self.positions_lock = threading.Lock()
        self.file_lock = threading.Lock()
        
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
        Get currently open positions from the exchange
        Returns a set of symbols with open positions
        """
        try:
            # Direct call to exchange without caching for simplicity
            positions = self.exchange.fetch_positions()
            
            openSymbols = set()
            messages(f"[DEBUG] Exchange returned {len(positions)} positions", console=0, log=1, telegram=0)
            
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
            
            messages(f"[DEBUG] Final open symbols: {openSymbols} (cached)", console=0, log=1, telegram=0)
            return openSymbols
            
        except Exception as e:
            # Fallback to direct API call with retry logic if caching fails
            messages(f"[WARNING] Cached positions failed, falling back to direct API: {e}", console=0, log=1, telegram=0)
            return self._getExchangeOpenPositionsDirectly(maxRetries, retryDelay)
    
    def _getExchangeOpenPositionsDirectly(self, maxRetries=3, retryDelay=2):
        """
        Fallback method for direct API calls with retry logic
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
        SIMPLIFIED: Call external function to clean notified positions
        """
        try:
            from positionMonitor import cleanNotifiedPositions
            cleanNotifiedPositions()
        except Exception as e:
            messages(f"[ERROR] Error cleaning positions: {e}", console=1, log=1, telegram=0)

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
        with self.file_lock:
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
            
            # Ensure all positions have 'side' field and remove duplicate orderIds
            if isinstance(data, dict):
                needs_save = False
                for symbol, position in data.items():
                    # Add side field if missing
                    if 'side' not in position:
                        # Infer side from amount (positive = LONG, negative = SHORT)
                        amount = position.get('amount', 0)
                        position['side'] = 'LONG' if amount >= 0 else 'SHORT'
                        needs_save = True
                    
                    # Remove duplicate orderIds (without numbers) if they exist
                    if 'tpOrderId' in position and 'tpOrderId1' in position:
                        position.pop('tpOrderId', None)
                        needs_save = True
                    if 'slOrderId' in position and 'slOrderId1' in position:
                        position.pop('slOrderId', None)
                        needs_save = True
                
                # Save the cleaned data if any changes were made
                if needs_save:
                    self.savePositionsDict(data)
        
        return data if isinstance(data, dict) else {}

    def savePositions(self):
        """
        Guarda self.positions (dict) en el archivo JSON.
        """
        with self.file_lock:
            try:
                with open(positionsFile, 'w', encoding='utf-8') as f:
                    json.dump(self.positions, f, indent=2, default=str)
            except Exception as e:
                messages(f"Error saving positions: {e}", console=1, log=1, telegram=0)

    def savePositionsDict(self, positions_dict):
        """
        Guarda un dict de posiciones en el archivo JSON.
        """
        with self.file_lock:
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
        messages(f"[DEBUG] annotateSelectionLog called with orderIdentifier='{orderIdentifier}'", console=0, log=1, telegram=0)
        
        # ...existing code...
        rows = []
        updated = False
        with open(selectionLogFile, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            fieldnames = reader.fieldnames or []
            rows = list(reader)

        messages(f"[DEBUG] Read {len(rows)} rows from selectionLog", console=0, log=1, telegram=0)

        extras = ['profitQuote', 'profitPct', 'close_ts_iso', 'close_ts_unix', 'time_to_close_s']
        for key in extras:
            if key not in fieldnames:
                fieldnames.append(key)

        closeTsUnix = int(time.time())
        closeTsIso  = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H-%M-%S")
        try:
            # Handle the timestamp format used in position records: "2025-09-04 00-19-10"
            if tsOpenIso:
                # Convert from "2025-09-04 00-19-10" to "2025-09-04 00:19:10" for ISO parsing
                tsOpenIsoFormatted = tsOpenIso.replace('-', ':', 2).replace('-', ':', 1)
                dtOpen = datetime.fromisoformat(tsOpenIsoFormatted)
                openTsUnix = int(dtOpen.timestamp())
            else:
                openTsUnix = closeTsUnix
        except Exception as e:
            messages(f"[DEBUG] Failed to parse timestamp '{tsOpenIso}': {e}", console=0, log=1, telegram=0)
            openTsUnix = closeTsUnix
        elapsed = closeTsUnix - openTsUnix

        for row in rows:
            row_id = (row.get('id') or '').strip()
            if row_id == orderIdentifier:
                messages(f"[DEBUG] Found matching row for id='{orderIdentifier}', updating close data", console=0, log=1, telegram=0)
                row['profitQuote']     = f"{profitQuote:.6f}"
                row['profitPct']       = f"{profitPct:.2f}"
                row['close_ts_iso']    = closeTsIso
                row['close_ts_unix']   = str(closeTsUnix)
                row['time_to_close_s'] = str(elapsed)
                updated = True
                break

        if updated:
            messages(f"[DEBUG] Writing updated selectionLog with close data for id='{orderIdentifier}'", console=0, log=1, telegram=0)
            with open(selectionLogFile, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
                writer.writeheader()
                writer.writerows(rows)
        else:
            # Log first few row IDs for debugging
            sample_ids = [row.get('id', 'NO_ID') for row in rows[:5]]
            messages(f"[ERROR] No se encontró la línea con id='{orderIdentifier}' para actualizar cierre en selectionLog.csv. Sample IDs: {sample_ids}", console=1, log=1, telegram=1)

    def logTrade(self, symbol: str, openDate: str, closeDate: str, elapsed: str, investmentUsdt: float, leverage: int, netProfitUsdt: float, side: str = "UNKNOWN"):
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
                'net_profit_usdt': f"{netProfitUsdt:.4f}",
                'side': side
            }
            
            # Check if file exists and has header
            fileExists = os.path.exists(tradesFile)
            
            # Append the trade record
            with open(tradesFile, 'a', encoding='utf-8', newline='') as f:
                fieldnames = ['symbol', 'open_date', 'close_date', 'elapsed', 'investment_usdt', 'leverage', 'net_profit_usdt', 'side']
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
                
                # Write header if file is new or empty
                if not fileExists or os.path.getsize(tradesFile) == 0:
                    writer.writeheader()
                
                writer.writerow(tradeRecord)
            
            messages(f"[DEBUG] Trade logged: {symbol} {side} P/L={netProfitUsdt:.4f} USDT", pair=symbol, console=0, log=1, telegram=0)
            
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
            leverage = int(position.get('leverage', 10))  # Get leverage from position or default 10
            side = position.get('side', 'UNKNOWN')  # Get side (LONG/SHORT) from position
            
            # Calculate investment (amount * price / leverage)
            investmentUsdt = (amount * openPrice) / leverage
            
            # Format dates with consistent format using colons for time
            currentTime = datetime.now()
            
            if openDateIso:
                try:
                    # Parse from "2025-08-26 16-30-59" format
                    openDateObj = datetime.strptime(openDateIso, '%Y-%m-%d %H-%M-%S')
                    openDateHuman = openDateObj.strftime('%Y-%m-%d %H:%M:%S')  # Use colons for consistency
                except Exception as parse_error:
                    messages(f"[DEBUG] Date parse error for {symbol}: {parse_error}, using raw date", pair=symbol, console=0, log=1, telegram=0)
                    openDateHuman = openDateIso
                    openDateObj = None
            else:
                openDateHuman = "Unknown"
                openDateObj = None
            
            # Current time as close date with colons
            closeDateHuman = currentTime.strftime('%Y-%m-%d %H:%M:%S')
            
            # Calculate elapsed time
            if openDateObj:
                try:
                    elapsed = currentTime - openDateObj
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
                except Exception as elapsed_error:
                    messages(f"[DEBUG] Elapsed calculation error for {symbol}: {elapsed_error}", pair=symbol, console=0, log=1, telegram=0)
                    elapsedHuman = "Unknown"
            else:
                elapsedHuman = "Unknown"
            
            messages(f"[DEBUG] Logging trade for {symbol}: side={side}, open={openDateHuman}, close={closeDateHuman}, elapsed={elapsedHuman}, investment={investmentUsdt:.4f}, profit={netProfitUsdt:.4f}", pair=symbol, console=0, log=1, telegram=0)
            
            # Log the trade
            self.logTrade(
                symbol=symbol,
                openDate=openDateHuman,
                closeDate=closeDateHuman,
                elapsed=elapsedHuman,
                investmentUsdt=investmentUsdt,
                leverage=leverage,
                netProfitUsdt=netProfitUsdt,
                side=side
            )
            
        except Exception as e:
            messages(f"[ERROR] Failed to extract trade data for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)





    def updatePositions(self):
        """
        SIMPLIFIED: Check order status, notify closed positions, and clean notified ones
        """
        try:
            # Load positions if not already loaded
            if not hasattr(self, '_positions_loaded') or not self.positions:
                self.positions = self.loadPositions()
                self._positions_loaded = True
            
            # Step 1: Check order status and mark closed positions
            from positionMonitor import checkOrderStatusPeriodically
            checkOrderStatusPeriodically()
            
            # Step 2: Notify closed positions
            from positionMonitor import notifyClosedPositions
            notifyClosedPositions()
            
            # Step 3: Clean notified positions
            self.cleanClosedPositions()
            
            # Reload positions after changes
            self.positions = self.loadPositions()
            
        except Exception as e:
            messages(f"[ERROR] Error in updatePositions: {e}", console=1, log=1, telegram=0)









    def openPosition(self, symbol, slope=None, intercept=None, investmentPct=1.0, side='long'):
        """
        Market buy with CCXT, then place OCO sell (TP + SL) with python-binance.
        Never open more than one trade for the same symbol per run.
        """
        messages(f"[DEBUG] symbol recibido: {symbol}", console=0, log=1, telegram=0)
        
        # Thread-safe check for duplicate positions
        with self.positions_lock:
            # 0) If we've already flagged insufficient balance, skip
            if self.hadInsufficientBalance:
                binSym = symbol.replace('/', '')
                return None

        # 1) Refresh and reconcile open positions (outside lock to avoid deadlock)
        messages(f"[DEBUG] About to call updatePositions() for {symbol}", console=0, log=1, telegram=0)
        self.updatePositions()
        messages(f"[DEBUG] Successfully completed updatePositions() for {symbol}", console=0, log=1, telegram=0)
        
        # Re-acquire lock for position checks and reservation
        with self.positions_lock:
            if symbol in self.positions:
                messages(f"Skipping openPosition for {symbol}: position already open", console=1, log=1, telegram=0, pair=symbol)
                return None

            # 1.2) Skip if we've hit the maxOpen limit
            if len(self.positions) >= self.maxOpen:
                messages(f"Skipping openPosition for {symbol}: max open positions reached ({self.maxOpen})", console=1, log=1, telegram=0, pair=symbol)
                return None
            
            # CRITICAL: Double-check if position exists on exchange to prevent duplicates
            try:
                exchangePositions = self.exchange.fetch_positions([symbol])
                for pos in exchangePositions:
                    if pos.get('symbol') == symbol and float(pos.get('contracts', 0)) > 0:
                        messages(f"[CRITICAL] Skipping {symbol}: position already exists on exchange with {pos.get('contracts')} contracts", console=1, log=1, telegram=0, pair=symbol)
                        return None
                messages(f"[DEBUG] Verified no existing position for {symbol} on exchange", console=0, log=1, telegram=0, pair=symbol)
            except Exception as e:
                messages(f"[WARNING] Could not verify exchange position for {symbol}: {e}", console=0, log=1, telegram=0, pair=symbol)
            
            # Reserve the symbol to prevent other threads from opening the same position
            self.positions[symbol] = {'status': 'opening', 'timestamp': datetime.now().isoformat()}
        
        # 2) Check free balance in baseAsset (e.g. USDC)
        messages(f"[DEBUG] Fetching free balance for {symbol}...", console=0, log=1, telegram=0)
        free = self.exchange.fetch_free_balance()
        messages(f"[DEBUG] Successfully fetched balance for {symbol}", console=0, log=1, telegram=0)
        availableUSDC = float(free.get(self.baseAsset, 0) or 0)
        baseInvestment = float(self.config.get('usdcInvestment', 0))
        
        # NEW LOGIC: Apply leverage FIRST, then score percentage
        leverage = int(self.config.get('leverage', 20))
        basePositionUSDT = baseInvestment * leverage  # 100 * 20 = 2000 USDT position
        finalPositionUSDT = basePositionUSDT * investmentPct  # 2000 * 0.7 = 1400 USDT
        investUSDC = finalPositionUSDT / leverage  # 1400 / 20 = 70 USDT margin required
        
        messages(f"[DEBUG] Leverage calculation for {symbol}: base={baseInvestment}, leverage={leverage}, score%={investmentPct}, final_position={finalPositionUSDT}, margin_required={investUSDC}", console=0, log=1, telegram=0)
        if availableUSDC < investUSDC:
            if investmentPct == 1.0 and availableUSDC > 0:
                messages(f"[EXCEPCIÓN] No hay saldo suficiente para 100% de inversión, usando todo el saldo disponible: {availableUSDC:.6f} USDC", console=1, log=1, telegram=0, pair=symbol)
                investUSDC = availableUSDC
            else:
                self.hadInsufficientBalance = True
                messages(f"Skipping openPosition for {symbol}: insufficient balance {availableUSDC:.6f} USDC, need {investUSDC:.6f} USDC", console=1, log=1, telegram=0, pair=symbol )
                # Clean up reservation
                with self.positions_lock:
                    self.positions.pop(symbol, None)
                return None

        # 3) Fetch current market price
        messages(f"[DEBUG] Fetching ticker for {symbol}...", console=0, log=1, telegram=0)
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price = Decimal(str(ticker.get('last') or 0))
            if price <= 0:
                raise ValueError(f"Invalid price for {symbol}: {price}")
            messages(f"[DEBUG] Successfully fetched price for {symbol}: {price}", console=0, log=1, telegram=0)
        except Exception as e:
            messages(f"Error fetching price for {symbol}: {e}", console=1, log=1, telegram=0, pair=symbol)
            # Clean up reservation
            with self.positions_lock:
                self.positions.pop(symbol, None)
            return None

        # 4) Compute how much base asset to buy (based on total position value, not margin)
        # For futures with leverage, amount should be for the full position value
        positionValueDecimal = Decimal(str(finalPositionUSDT))
        rawAmt = positionValueDecimal / price
        messages(f"[DEBUG] Amount calculation: position_value={finalPositionUSDT} / price={price} = {rawAmt}", console=0, log=1, telegram=0)
        normSymbol = symbol.replace(':USDT', '') if symbol.endswith(':USDT') else symbol
        messages(f"[DEBUG] normSymbol usado para markets: {normSymbol}", console=0, log=1, telegram=0)
        messages(f"[DEBUG] Fetching market info for {normSymbol}...", console=0, log=1, telegram=0)
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
        # Si la cantidad calculada es menor que el mínimo, usar el mínimo permitido y recalcular posición
        if minQty and amtDec < minQty:
            messages(f"[DEBUG] Amount {amtDec} below minimum lot size {minQty}, ajustando a mínimo", console=0, log=1, telegram=0, pair=symbol)
            amtDec = minQty
            # Recalcular los valores basados en la cantidad mínima
            actualPositionValue = float(minQty) * float(price)
            investUSDC = actualPositionValue / leverage
            finalPositionUSDT = actualPositionValue
            messages(f"[DEBUG] Recalculated due to min qty: position_value={actualPositionValue}, margin_required={investUSDC}", console=0, log=1, telegram=0)
        amount = float(amtDec)
        messages(f"[DEBUG] Opening {symbol}: price={price}, amount={amtDec} (position_amount), margin_required={investUSDC}, position_value={finalPositionUSDT}", pair=symbol, console=0, log=1, telegram=0)

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
            # Clean up reservation
            with self.positions_lock:
                self.positions.pop(symbol, None)
            return None

        # 6) Calculate TP/SL teniendo en cuenta el leverage y side
        tpPct = Decimal(str(self.config.get('tp1', 0.02)))
        slPct = Decimal(str(self.config.get('sl1', 0.01)))
        leverage = int(self.config.get('leverage', 10))
        tpPctPrice = tpPct / Decimal(leverage)
        slPctPrice = slPct / Decimal(leverage)
        
        # For LONG: TP above entry, SL below entry
        # For SHORT: TP below entry, SL above entry
        if side == 'long':
            rawTp = openPrice * (Decimal('1') + tpPctPrice)
            rawSp = openPrice * (Decimal('1') - slPctPrice)
        else:  # short
            rawTp = openPrice * (Decimal('1') - tpPctPrice)
            rawSp = openPrice * (Decimal('1') + slPctPrice)
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
            'position_value_usdt': finalPositionUSDT,  # Add the full position value
            'side': side.upper(),  # Add side information (LONG/SHORT)
            'status': 'open',  # NEW: Set initial status
            'notification_sent': False  # NEW: Flag for notification tracking
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

    def _checkOrderStatusForClosure(self, symbol, tpOrderId, slOrderId):
        """
        Check if TP or SL orders have been executed by checking their status directly
        Uses BingX API status 'FILLED' or 'closed' to determine actual execution
        Returns True if any order is executed, False if none are executed, None if API issues
        """
        try:
            if not tpOrderId and not slOrderId:
                messages(f"[DEBUG] No TP/SL order IDs found for {symbol}, using fallback method", pair=symbol, console=0, log=1, telegram=0)
                return self._checkForClosingTradesFallback(symbol)
            
            tpOrder = None
            slOrder = None
            tpAccessible = True
            slAccessible = True
            
            # Fetch both orders first to get complete information
            if tpOrderId:
                try:
                    tpOrder = self.exchange.fetch_order(tpOrderId, symbol)
                    tpStatus = tpOrder.get('status', 'unknown')
                    messages(f"[DEBUG] TP order {tpOrderId} status: {tpStatus}", pair=symbol, console=0, log=1, telegram=0)
                except Exception as e:
                    error_msg = str(e).lower()
                    if "order not exist" in error_msg or "80016" in error_msg:
                        messages(f"[DEBUG] TP order {tpOrderId} not found for {symbol} - order may have been executed or cancelled: {e}", pair=symbol, console=0, log=1, telegram=0)
                    else:
                        messages(f"[DEBUG] Could not fetch TP order {tpOrderId} for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)
                    tpAccessible = False
            
            if slOrderId:
                try:
                    slOrder = self.exchange.fetch_order(slOrderId, symbol)
                    slStatus = slOrder.get('status', 'unknown')
                    messages(f"[DEBUG] SL order {slOrderId} status: {slStatus}", pair=symbol, console=0, log=1, telegram=0)
                except Exception as e:
                    error_msg = str(e).lower()
                    if "order not exist" in error_msg or "80016" in error_msg:
                        messages(f"[DEBUG] SL order {slOrderId} not found for {symbol} - order may have been executed or cancelled: {e}", pair=symbol, console=0, log=1, telegram=0)
                    else:
                        messages(f"[DEBUG] Could not fetch SL order {slOrderId} for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)
                    slAccessible = False
            
            # If we couldn't access either order due to API issues, return None (undetermined)
            if not tpAccessible and not slAccessible:
                messages(f"[DEBUG] Cannot access any orders for {symbol} due to API issues - status undetermined", pair=symbol, console=0, log=1, telegram=0)
                return None
            
            # Check which order was actually filled (executed) - accept both BingX statuses
            tpFilled = tpOrder and tpOrder.get('status') in ['FILLED', 'closed']
            slFilled = slOrder and slOrder.get('status') in ['FILLED', 'closed']
            
            # Determine which order was executed and save closing details
            if tpFilled and not slFilled:
                # Take Profit was executed
                messages(f"[INFO] Take Profit order executed for {symbol}", pair=symbol, console=0, log=1, telegram=0)
                position = self.positions.get(symbol, {})
                
                # Get the actual execution price
                actualPrice = tpOrder.get('average') or tpOrder.get('price')
                if actualPrice is None:
                    actualPrice = position.get('tpPrice')
                
                position['closingOrder'] = {
                    'type': 'TP',
                    'orderId': tpOrderId,
                    'price': actualPrice,
                    'amount': tpOrder.get('filled') or tpOrder.get('amount'),
                    'fee': tpOrder.get('fee', {}),
                    'timestamp': tpOrder.get('timestamp') or int(time.time() * 1000)
                }
                self.positions[symbol] = position
                messages(f"[DEBUG] Saved TP closing order details for {symbol}: {position['closingOrder']}", pair=symbol, console=0, log=1, telegram=0)
                return True
                
            elif slFilled and not tpFilled:
                # Stop Loss was executed
                messages(f"[INFO] Stop Loss order executed for {symbol}", pair=symbol, console=0, log=1, telegram=0)
                position = self.positions.get(symbol, {})
                
                # Get the actual execution price
                actualPrice = slOrder.get('average') or slOrder.get('price')
                if actualPrice is None:
                    actualPrice = position.get('slPrice')
                
                position['closingOrder'] = {
                    'type': 'SL',
                    'orderId': slOrderId,
                    'price': actualPrice,
                    'amount': slOrder.get('filled') or slOrder.get('amount'),
                    'fee': slOrder.get('fee', {}),
                    'timestamp': slOrder.get('timestamp') or int(time.time() * 1000)
                }
                self.positions[symbol] = position
                messages(f"[DEBUG] Saved SL closing order details for {symbol}: {position['closingOrder']}", pair=symbol, console=0, log=1, telegram=0)
                return True
                
            elif tpFilled and slFilled:
                # Both orders filled - this shouldn't happen, but prioritize the one with most recent timestamp
                messages(f"[WARNING] Both TP and SL orders appear filled for {symbol} - using most recent", pair=symbol, console=0, log=1, telegram=0)
                tpTimestamp = tpOrder.get('timestamp', 0)
                slTimestamp = slOrder.get('timestamp', 0)
                
                if tpTimestamp >= slTimestamp:
                    # Use TP
                    position = self.positions.get(symbol, {})
                    actualPrice = tpOrder.get('average') or tpOrder.get('price') or position.get('tpPrice')
                    position['closingOrder'] = {
                        'type': 'TP',
                        'orderId': tpOrderId,
                        'price': actualPrice,
                        'amount': tpOrder.get('filled') or tpOrder.get('amount'),
                        'fee': tpOrder.get('fee', {}),
                        'timestamp': tpTimestamp
                    }
                else:
                    # Use SL
                    position = self.positions.get(symbol, {})
                    actualPrice = slOrder.get('average') or slOrder.get('price') or position.get('slPrice')
                    position['closingOrder'] = {
                        'type': 'SL',
                        'orderId': slOrderId,
                        'price': actualPrice,
                        'amount': slOrder.get('filled') or slOrder.get('amount'),
                        'fee': slOrder.get('fee', {}),
                        'timestamp': slTimestamp
                    }
                
                self.positions[symbol] = position
                messages(f"[DEBUG] Saved closing order details for {symbol}: {position['closingOrder']}", pair=symbol, console=0, log=1, telegram=0)
                return True
            
            else:
                # Neither order is filled - position still open
                messages(f"[DEBUG] No closing orders executed for {symbol} (TP: {tpOrder.get('status') if tpOrder else 'N/A'}, SL: {slOrder.get('status') if slOrder else 'N/A'})", pair=symbol, console=0, log=1, telegram=0)
                return False
                
        except Exception as e:
            messages(f"[ERROR] Could not check closing orders for {symbol}: {e}", pair=symbol, console=0, log=1, telegram=0)
            return None

    def checkForClosingTrade(self, symbol):
        """
        Check if TP or SL orders have been executed to confirm position closure
        Uses specific order IDs from the position data for precise verification
        Falls back to trade search if order IDs are not available
        Returns True if any closing order is executed, False if confirmed open, None if undetermined
        """
        position = self.positions.get(symbol, {})
        tpOrderId = position.get('tpOrderId1')
        slOrderId = position.get('slOrderId1')
        
        # If we have order IDs, use the precise method
        if tpOrderId or slOrderId:
            return self._checkOrderStatusForClosure(symbol, tpOrderId, slOrderId)
        else:
            # No order IDs available (likely failed to create TP/SL), use fallback
            messages(f"[DEBUG] No TP/SL order IDs found for {symbol}, using fallback method", pair=symbol, console=0, log=1, telegram=0)
            return self._checkForClosingTradesFallback(symbol)
    
    def _checkForClosingTradesFallback(self, symbol):
        """
        Fallback method to check for closing trades when order IDs are not available
        Uses the original trade search method with improved logic for both longs and shorts
        """
        try:
            position = self.positions.get(symbol, {})
            openTsUnix = position.get('open_ts_unix', 0)
            positionSide = position.get('side', 'LONG').upper()
            
            # For LONG positions, closing trades are SELL
            # For SHORT positions, closing trades are BUY
            expectedClosingSide = 'sell' if positionSide == 'LONG' else 'buy'
            
            allTrades = self.exchange.fetch_my_trades(symbol)
            relevantTrades = [
                t for t in allTrades
                if t.get('side') == expectedClosingSide and t.get('timestamp', 0) >= openTsUnix * 1000
            ]
            
            if relevantTrades:
                messages(f"[DEBUG] Found {len(relevantTrades)} closing trades for {symbol} (fallback method, side={expectedClosingSide})", pair=symbol, console=0, log=1, telegram=0)
                return True
            else:
                messages(f"[DEBUG] No closing trades found for {symbol} (fallback method, side={expectedClosingSide})", pair=symbol, console=0, log=1, telegram=0)
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
            if position.get('notified', False) or position.get('notification_sent', False):
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
                with self.positions_lock:
                    position['notified'] = True
                    position['notification_sent'] = True
                    position.pop('processing_notification', None)
                    self.positions[symbol] = position
                return
            
            # Check if we have closing order details saved
            closingOrder = position.get('closingOrder')
            messages(f"[DEBUG] Checking closingOrder for {symbol}: {closingOrder}", pair=symbol, console=0, log=1, telegram=0)
            
            if closingOrder:
                # Use saved closing order details for P/L calculation
                rawPrice = closingOrder.get('price')
                messages(f"[DEBUG] Raw price from closingOrder: {rawPrice} (type: {type(rawPrice)})", pair=symbol, console=0, log=1, telegram=0)
                
                closePrice = float(rawPrice) if rawPrice is not None else 0
                closedAmount = float(closingOrder.get('amount', 0))
                orderType = closingOrder.get('type', 'Unknown')
                
                messages(f"[DEBUG] Processed values - closePrice: {closePrice}, amount: {closedAmount}, type: {orderType}", pair=symbol, console=0, log=1, telegram=0)
                
                # If we don't have closePrice from order, try to use the target price from position
                if not closePrice:
                    if orderType == 'TP':
                        closePrice = float(position.get('tpPrice', 0))
                        messages(f"[DEBUG] Using TP price as fallback: {closePrice}", pair=symbol, console=0, log=1, telegram=0)
                    elif orderType == 'SL':
                        closePrice = float(position.get('slPrice', 0))
                        messages(f"[DEBUG] Using SL price as fallback: {closePrice}", pair=symbol, console=0, log=1, telegram=0)
                
                if closePrice and closedAmount:
                    # Calculate P/L
                    side = position.get('side', 'LONG')
                    if side.upper() == 'LONG':
                        pnlUsdt = (closePrice - openPrice) * closedAmount
                    else:
                        pnlUsdt = (openPrice - closePrice) * closedAmount
                    
                    pnlPct = (pnlUsdt / (openPrice * closedAmount)) * 100
                    investment = float(position.get('investment_usdt', 0))
                    leverage = int(position.get('leverage', 1))
                    pnlOnInvestment = pnlPct * leverage
                    
                    # Format message
                    cleanSymbol = symbol.replace('/USDT:USDT', '').replace('/', '_')
                    pnlSign = "💰💰" if pnlUsdt >= 0 else "❌"
                    
                    message = (f"{pnlSign} {side} {cleanSymbol} - P/L: {pnlUsdt:.2f} USDT ({pnlOnInvestment:.2f}%) - Investment: {investment} ({leverage}x)")
                    
                    messages(message, pair=symbol, console=1, log=1, telegram=1)
                    
                    # Log the trade to trades.csv
                    self.logTradeFromPosition(symbol, position, orderType, pnlUsdt)
                    
                    # Update selectionLog with close data
                    try:
                        # Construct recordId from position TP/SL order IDs
                        tpOrderId1 = position.get('tpOrderId1', '')
                        tpOrderId2 = position.get('tpOrderId2', '')
                        slOrderId1 = position.get('slOrderId1', '')
                        slOrderId2 = position.get('slOrderId2', '')
                        activeTpOrderId = tpOrderId2 if tpOrderId2 else tpOrderId1
                        activeSlOrderId = slOrderId2 if slOrderId2 else slOrderId1
                        recordId = f"{activeTpOrderId or ''}-{activeSlOrderId or ''}"
                        tsOpenIso = position.get('timestamp', '')
                        
                        messages(f"[DEBUG] Attempting to annotate selectionLog for {symbol} (closingOrder): recordId='{recordId}', profit={pnlUsdt:.4f}, pct={pnlOnInvestment:.2f}", pair=symbol, console=0, log=1, telegram=0)
                        self.annotateSelectionLog(recordId, pnlUsdt, pnlOnInvestment, tsOpenIso)
                    except Exception as annotate_error:
                        messages(f"[ERROR] Failed to annotate selectionLog for {symbol}: {annotate_error}", pair=symbol, console=0, log=1, telegram=0)
                    
                    with self.positions_lock:
                        position['notified'] = True
                        position['notification_sent'] = True
                        position.pop('processing_notification', None)
                        self.positions[symbol] = position
                    return
                else:
                    messages(f"[DEBUG] Missing price data for {symbol}: closePrice={closePrice}, amount={closedAmount}", pair=symbol, console=0, log=1, telegram=0)
            
            # Fallback: try to get trades from exchange
            try:
                allTrades = self.exchange.fetch_my_trades(symbol)
                relevantTrades = [
                    t for t in allTrades
                    if t.get('timestamp', 0) >= openTsUnix * 1000
                ]
                
                buyTrades = [t for t in relevantTrades if t.get('side') == 'buy']
                sellTrades = [t for t in relevantTrades if t.get('side') == 'sell']
                
                if not sellTrades:
                    # No sell trades found, send notification without P/L details
                    cleanSymbol = symbol.replace('/USDT:USDT', '').replace('/', '_')
                    simpleMessage = f"Position closed: {cleanSymbol} (detected via exchange sync - no sell trades found)"
                    messages(simpleMessage, pair=symbol, console=1, log=1, telegram=1)
                    with self.positions_lock:
                        position['notified'] = True
                        position['notification_sent'] = True
                        position.pop('processing_notification', None)
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
                
                # Log position sync closure
                messages(f"[SYNC] Position {symbol} closed - Profit: {netProfitQuote:.4f} USDT ({netProfitPct:.2f}%)", console=1, log=1, telegram=0)
                
                # Log the trade to trades.csv
                self.logTradeFromPosition(symbol, position, "SYNC", netProfitQuote)
                
                # Update selectionLog with close data
                try:
                    # Construct recordId from position TP/SL order IDs
                    tpOrderId1 = position.get('tpOrderId1', '')
                    tpOrderId2 = position.get('tpOrderId2', '')
                    slOrderId1 = position.get('slOrderId1', '')
                    slOrderId2 = position.get('slOrderId2', '')
                    activeTpOrderId = tpOrderId2 if tpOrderId2 else tpOrderId1
                    activeSlOrderId = slOrderId2 if slOrderId2 else slOrderId1
                    recordId = f"{activeTpOrderId or ''}-{activeSlOrderId or ''}"
                    tsOpenIso = position.get('timestamp', '')
                    
                    # Calculate profit percentage on investment (leverage-adjusted)
                    leverage = position.get('leverage', 10)
                    profitPctOnInvestment = netProfitPct * leverage
                    
                    messages(f"[DEBUG] Attempting to annotate selectionLog for {symbol} (trades): recordId='{recordId}', profit={netProfitQuote:.4f}, pct={profitPctOnInvestment:.2f}", pair=symbol, console=0, log=1, telegram=0)
                    self.annotateSelectionLog(recordId, netProfitQuote, profitPctOnInvestment, tsOpenIso)
                except Exception as annotate_error:
                    messages(f"[ERROR] Failed to annotate selectionLog for {symbol}: {annotate_error}", pair=symbol, console=0, log=1, telegram=0)
                
            except Exception as trade_error:
                messages(f"[ERROR] Could not calculate P/L for {symbol}: {trade_error}", pair=symbol, console=0, log=1, telegram=0)
                # Fallback to simple notification
                cleanSymbol = symbol.replace('/USDT:USDT', '').replace('/', '_')
                simpleMessage = f"Position closed: {cleanSymbol} (detected via exchange sync - P/L calculation failed)"
                messages(simpleMessage, pair=symbol, console=1, log=1, telegram=1)
            
            # Mark as notified
            with self.positions_lock:
                position['notified'] = True
                position['notification_sent'] = True
                position.pop('processing_notification', None)
                self.positions[symbol] = position
            
        except Exception as e:
            messages(f"[ERROR] Failed to notify closure for {symbol}: {e}", pair=symbol, console=1, log=1, telegram=0)

        # ...existing code...


