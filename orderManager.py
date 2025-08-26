import ccxt
from connector import bingxConnector
import json
import os
import csv
import time

from logManager import messages
from gvars import configFile, positionsFile, dailyBalanceFile, clientPrefix, marketsFile, selectionLogFile, csvFolder
from plotting import savePlot
from configManager import configManager
from logManager import messages
from validators import validateTradingParameters, validateSymbol, sanitizeSymbol
from exceptions import OrderExecutionError, InsufficientBalanceError, DataValidationError
from cacheManager import cachedCall

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
            return migrated
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





    def updatePositions(self):
        """
        Sincroniza el estado con el exchange y elimina solo el nodo del símbolo cerrado.
        """
        #messages("Analyzing positions", console=1, log=1, telegram=0)
        # Cargar siempre desde disco para evitar inconsistencias
        self.positions = self.loadPositions()
        symbols_to_remove = []
        for symbol, position in self.positions.items():
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
            try:
                if activeTpOrderId:
                    tpInfo = self.exchange.fetch_order(activeTpOrderId, symbol)
                    tpStatus = str(tpInfo.get('status', '')).lower()
                if activeSlOrderId:
                    slInfo = self.exchange.fetch_order(activeSlOrderId, symbol)
                    slStatus = str(slInfo.get('status', '')).lower()
            except Exception as e:
                # If order doesn't exist, it was likely executed - check for trades to determine closure
                error_msg = str(e).lower()
                if "order not exist" in error_msg or "80016" in error_msg:
                    messages(f"[DEBUG] Order not found for {symbol} (likely executed), checking trades", pair=symbol, console=0, log=1, telegram=0)
                    # Set status as filled for processing
                    if activeTpOrderId and not tpStatus:
                        tpStatus = 'filled'
                    if activeSlOrderId and not slStatus:
                        slStatus = 'filled'
                else:
                    messages(f"[ERROR] fetch_order failed for {symbol}: {e}", pair=symbol, console=1, log=1, telegram=0)
                    continue

            close_reason = None
            if tpStatus in ('filled', 'canceled', 'closed'):
                close_reason = 'TP' 
            elif slStatus in ('filled', 'canceled', 'closed'):
                close_reason = 'SL'

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
            for trade in relevantTrades:
                amt  = float(trade.get('amount', 0))
                cost = float(trade.get('cost',   0))
                if totalQuantity + amt > buyQuantity:
                    needed       = buyQuantity - totalQuantity
                    totalCost   += cost * (needed / amt)
                    totalQuantity = buyQuantity
                    break
                totalQuantity += amt
                totalCost     += cost

            avgExitPrice = totalCost / totalQuantity if totalQuantity else 0
            profitQuote  = totalQuantity * (avgExitPrice - buyPrice)
            profitPct    = ((avgExitPrice / buyPrice - 1) * 100) if buyPrice else 0

            icon = "💰💰" if profitQuote > 0 else "☠️☠️"
            messages(f"[DEBUG] Closing position: {symbol} reason={close_reason} P/L={profitQuote:.4f} USDC ({profitPct:.2f}%)", pair=symbol, console=0, log=1, telegram=0)
            try:
                messages(
                    f"{icon} {close_reason} for {symbol} — P/L: {profitQuote:.4f} USDC ({profitPct:.2f}%)",
                    pair=symbol, console=1, log=1, telegram=1
                )
                # Comentar el uso antiguo y dejar nota
                # recordId = f"{tpOrderId or ''}-{slOrderId or ''}"
                recordId = f"{activeTpOrderId or ''}-{activeSlOrderId or ''}"
                self.annotateSelectionLog(recordId, profitQuote, profitPct, tsOpenIso)
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
            tpId = tpOrder.get('id')
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
            slId = slOrder.get('id')
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
            'slPercent': float(slPct) * 100
        }
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
        # ...existing code...


