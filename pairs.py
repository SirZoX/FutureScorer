import threading
import os
import json
import time
import uuid
import ccxt
from connector import bingxConnector
from configManager import configManager
from validators import validateSymbol, validateOhlcvData, sanitizeSymbol
from logManager import messages
from exceptions import DataValidationError, ExchangeConnectionError
# from cacheManager import cachedCall, cacheManager  # REMOVED - no longer needed
import pandas as pd
import args  # Import command line arguments


from datetime import datetime, UTC
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo


import gvars
import plotting
import orderManager
import args
import fileManager
import helpers

from logManager import messages
from supportDetector import findPossibleResistancesAndSupports
from marketLoader import markets





# ——— Rate limiter para no pasar de 20 calls/s ———
class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            # Limpiamos llamadas fuera de la ventana
            while self.calls and self.calls[0] <= now - self.period:
                self.calls.pop(0)
            # if we have space, add a new call
            if len(self.calls) >= self.max_calls:
                to_sleep = self.period - (now - self.calls[0])
                time.sleep(to_sleep)
            self.calls.append(time.time())






# Initialize managers
orderManager = orderManager.OrderManager(isSandbox=args.isSandbox)
exchange = bingxConnector()
rate_limiter = RateLimiter(max_calls=gvars.rateLimiterMaxCalls, period=gvars.rateLimiterPeriodSeconds)

# Filtrar solo los pares de futuros perpetuos (swap) de BingX
def getFuturesPairs():
    # Usar markets.json para filtrar solo futuros perpetuos activos y operables
    with open(gvars.marketsFile, encoding='utf-8') as f:
        markets = json.load(f)
    return [
        info['symbol'] for info in markets.values()
        if info.get('type') == 'swap'
        and info.get('active', False)
        and info.get('symbol', '').endswith('USDT:USDT')
        and info.get('info', {}).get('status') == '1'
        and info.get('info', {}).get('apiStateOpen') == 'true'
        and info.get('info', {}).get('apiStateClose') == 'true'
    ]








def filterSignals(df):
    """
    1) Elimina los outliers extremos de 'low' (percentil 1–99)
    2) (Opcional) aquí podrías añadir más filtros globales
    """
    q_low, q_high = df['low'].quantile(0.01), df['low'].quantile(0.99)
    df = df[(df['low'] >= q_low) & (df['low'] <= q_high)]
    return df.reset_index(drop=True)








def executeOpportunitiesSequentially(approvedOpportunities, configData):
    """
    Execute all approved opportunities sequentially.
    This includes position opening with automatic adjustment for position limits (error 101209)
    Returns dict with 'opened' and 'failed' counts.
    """
    results = {'opened': 0, 'failed': 0}
    
    if not approvedOpportunities:
        return results
    
    for i, opportunity in enumerate(approvedOpportunities, 1):
        try:
            pair = opportunity['pair']
            messages(f"[{i}/{len(approvedOpportunities)}] Processing {pair}...", console=0, log=1, telegram=0, pair=pair)
            
            # Check if we've reached max positions
            orderManager.updatePositions()
            currentOpenPositions = len(orderManager.positions)
            maxOpenPositions = configData.get('maxOpenPositions', 8)
            
            if currentOpenPositions >= maxOpenPositions:
                messages(f"Max positions reached ({currentOpenPositions}/{maxOpenPositions}). Stopping execution.", console=0, log=1, telegram=0)
                break
            
            # Execute position opening with automatic retry logic for position limits
            record = orderManager.openPosition(
                opportunity['pair'], 
                slope=opportunity['slope'], 
                intercept=opportunity['intercept'], 
                investmentPct=opportunity['investmentPct'], 
                side=opportunity['side']
            )
            
            if record:
                results['opened'] += 1
                messages(f"[{i}/{len(approvedOpportunities)}] {pair} position opened successfully", console=0, log=1, telegram=0, pair=pair)
                # Update selectionLog with real order IDs from successful execution
                updateSelectionLogWithRealOrderIds(opportunity.get('opportunityId'), pair, record)
            else:
                results['failed'] += 1
                messages(f"[{i}/{len(approvedOpportunities)}] {pair} position opening failed", console=0, log=1, telegram=0, pair=pair)
                # Update selectionLog to mark as execution failed
                updateSelectionLogForExecutionFailure(opportunity.get('opportunityId'), pair)
                
        except Exception as e:
            results['failed'] += 1
            messages(f"[{i}/{len(approvedOpportunities)}] Error processing {opportunity['pair']}: {e}", console=0, log=1, telegram=0, pair=opportunity['pair'])
            # Update selectionLog to mark as execution failed
            updateSelectionLogForExecutionFailure(opportunity.get('opportunityId'), opportunity['pair'])
    
    return results


def updateSelectionLogWithRealOrderIds(opportunityId, pair, record):
    """
    Update selectionLog.csv with real order IDs from successful execution
    """
    if not record:
        return
        
    try:
        import csv
        import gvars
        
        # Extract real order IDs
        tpId = record.get("tpOrderId2") or record.get("tpOrderId1", "")
        slId = record.get("slOrderId2") or record.get("slOrderId1", "")
        
        if not tpId and not slId:
            messages(f"[SELECTION-LOG] No real order IDs found for {pair}", console=0, log=1, telegram=0)
            return
        
        # Normalize pair name to match selectionLog format (SYMBOL_USDT)
        normalizedPair = pair.replace('/USDT:USDT', '_USDT').replace('/USDT', '_USDT')
        
        # Read current selectionLog
        rows = []
        with open(gvars.selectionLogFile, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=';')
            header = next(reader)
            rows = [header]
            
            # Find column indices
            idIdx = header.index('id') if 'id' in header else -1
            pairIdx = header.index('pair') if 'pair' in header else -1
            tpOrderIdx = header.index('tp_order_id') if 'tp_order_id' in header else -1
            slOrderIdx = header.index('sl_order_id') if 'sl_order_id' in header else -1
            
            if idIdx == -1 or pairIdx == -1:
                messages(f"[SELECTION-LOG] Required columns not found in selectionLog", console=0, log=1, telegram=0)
                return
                
            # Update the row with matching opportunityId or most recent matching pair
            updated = False
            matchingRows = []
            
            for row in reader:
                # First try to match by opportunityId (exact match)
                if len(row) > idIdx and row[idIdx] == opportunityId:
                    if tpOrderIdx >= 0 and len(row) > tpOrderIdx:
                        row[tpOrderIdx] = tpId
                    if slOrderIdx >= 0 and len(row) > slOrderIdx:
                        row[slOrderIdx] = slId
                    messages(f"[SELECTION-LOG] Updated {normalizedPair} (ID: {opportunityId}) with TP: {tpId}, SL: {slId}", console=0, log=1, telegram=0)
                    updated = True
                # If no exact ID match, collect matching pairs for fallback
                elif len(row) > pairIdx and row[pairIdx] == normalizedPair:
                    matchingRows.append((len(rows), row))
                
                rows.append(row)
            
            # If no exact ID match, update the most recent matching pair (last 2 minutes)
            if not updated and matchingRows:
                try:
                    currentTimestamp = int(time.time())
                    for rowIdx, row in reversed(matchingRows):  # Start from most recent
                        rowTimestamp = int(row[2]) if len(row) > 2 else 0
                        # If within last 2 minutes, assume it's our opportunity
                        if abs(currentTimestamp - rowTimestamp) < 120:
                            if tpOrderIdx >= 0 and len(row) > tpOrderIdx:
                                rows[rowIdx][tpOrderIdx] = tpId
                            if slOrderIdx >= 0 and len(row) > slOrderIdx:
                                rows[rowIdx][slOrderIdx] = slId
                            messages(f"[SELECTION-LOG] Updated recent {normalizedPair} entry with TP: {tpId}, SL: {slId}", console=0, log=1, telegram=0)
                            updated = True
                            break
                except Exception as te:
                    messages(f"[SELECTION-LOG] Error parsing timestamp for {normalizedPair}: {te}", console=0, log=1, telegram=0)
        
        if not updated:
            messages(f"[SELECTION-LOG] No matching entry found for {normalizedPair} (ID: {opportunityId}) to update with order IDs", console=0, log=1, telegram=0)
        
        # Write back updated selectionLog
        with open(gvars.selectionLogFile, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerows(rows)
            
    except Exception as e:
        messages(f"[ERROR] Failed to update selectionLog with real order IDs for {pair}: {e}", console=0, log=1, telegram=0)


def updateSelectionLogForExecutionFailure(opportunityId, pair):
    """
    Update selectionLog.csv to mark an opportunity as execution failed (accepted=0)
    """
    if not opportunityId:
        return
        
    try:
        import csv
        import gvars
        
        # Read current selectionLog
        rows = []
        with open(gvars.selectionLogFile, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=';')
            header = next(reader)
            rows = [header]
            
            # Find accepted column index
            acceptedIdx = header.index('accepted') if 'accepted' in header else -1
            if acceptedIdx == -1:
                return
                
            # Update the row with matching timestamp+pair or opportunityId
            for row in reader:
                if len(row) > 3 and row[3] == pair:
                    # Check if this is recent (last few entries) by looking at timestamp
                    try:
                        rowTimestamp = int(row[2]) if len(row) > 2 else 0
                        currentTimestamp = int(time.time())
                        # If within last 5 minutes, assume it's our opportunity
                        if abs(currentTimestamp - rowTimestamp) < 300:
                            row[acceptedIdx] = '0'  # Mark as execution failed
                            messages(f"[SELECTION-LOG] Updated {pair} execution status to failed", console=0, log=1, telegram=0)
                            break
                    except:
                        pass
                rows.append(row)
        
        # Write back updated selectionLog
        with open(gvars.selectionLogFile, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerows(rows)
            
    except Exception as e:
        messages(f"[ERROR] Failed to update selectionLog for execution failure {pair}: {e}", console=0, log=1, telegram=0)


def analyzePairs():
    """
    1) Load daily selection
    2) For each pair: fetch OHLCV, filter, detect support, calculate metrics
    3) Sort by score
    4) Pre-compute bounceLow/bounceHigh and previous MA25
    5) Collect approved opportunities in a list (analysis phase)
    6) Process all opportunities sequentially (execution phase)
       • generate and send msg+image via messages()
    7) Log everything in selectionLog.csv; plots are not deleted
    """

    # ——— 0) Limpiar carpeta de plots ———
    fileManager.deleteOldFiles(json=False, csv=True, plots=True)
    
    # Initialize plot data storage for delayed generation
    analyzePairs._plotData = []
    
    # Initialize list for approved opportunities to execute
    approvedOpportunities = []
    
    # from positionMonitor import monitorActive  # Disabled - position monitor removed
    import time
    startTime = time.time()
    analysisStartTime = time.time()
    messages("Starting analysis", console=1, log=1, telegram=0)
    # monitorActive.clear()  # Disabled - position monitor removed
    dateTag = datetime.utcnow().date().isoformat()

    # Leer config en caliente
    configData = configManager.config

    # ——— Control de posiciones máximas ———
    # Check current opened positions before starting analysis
    maxOpenPositions = configData.get('maxOpenPositions', 8)
    try:
        with open(gvars.positionsFile, encoding="utf-8") as f:
            currentPositions = json.load(f)
        
        # Support both formats: old list or new dict
        if isinstance(currentPositions, dict):
            currentPositionsCount = len(currentPositions)
        elif isinstance(currentPositions, list):
            currentPositionsCount = len([p for p in currentPositions if isinstance(p, dict) and p.get("symbol")])
        else:
            currentPositionsCount = 0
    except Exception as e:
        currentPositionsCount = 0
        messages(f"Error reading openedPositions.json: {e}", console=0, log=1, telegram=0)

    if currentPositionsCount >= maxOpenPositions:
        messages(f"⚠️  Maximum positions reached ({currentPositionsCount}/{maxOpenPositions}). Skipping analysis to save resources.", console=0, log=1, telegram=0)
        messages("Analysis cancelled - all position slots are occupied", console=0, log=1, telegram=0)
        # monitorActive.set()  # Disabled - position monitor removed
        return []  # Return empty list to indicate no analysis was performed

    messages(f"Current positions: {currentPositionsCount}/{maxOpenPositions}. Starting analysis...", console=1, log=1, telegram=0)

    # Core parameters
    # topPercent   = configData.get('topPercent', 10)
    # limit        = configData.get('limit', 150)
    # tpPercent    = configData.get('tpPercent', 0.01)
    # slPercent    = configData.get('slPercent', 0.035)
    # bouncePct    = configData.get('bouncePct', 0.002)
    # maxBounceAllowed= configData.get('maxBounceAllowed', 0.002)
    # minSeparation= configData.get('minSeparation', 36)
    # minVolume    = configData.get('minVolume', 500000)
    topCoinsPctAnalyzed = configData.get('topCoinsPctAnalyzed', 10)
    requestedCandles    = configData.get('requestedCandles', 150)
    tp1                 = configData.get('tp1', 0.01)
    sl1                 = configData.get('sl1', 0.035)
    minPctBounceAllowed = configData.get('minPctBounceAllowed', 0.002)
    maxPctBounceAllowed = configData.get('maxPctBounceAllowed', 0.002)
    minCandlesSeparationToFindSupportLine = configData.get('minCandlesSeparationToFindSupportLine', 36)
    lastCandleMinUSDVolume = configData.get('lastCandleMinUSDVolume', 500000)
    timeframe    = configData.get('timeframe', '1d')
    tolerancePct = configData.get('tolerancePct', 0.015)
    minTouches   = configData.get('minTouches', 3)

    # Scoring configuration
    scoringWeights = configData.get('scoringWeights', {
        'distance': 0.3,
        'volume':   0.3,
        'momentum': 0.10,
        'touches':  0.15
    })
    scoreThreshold = configData.get('scoreThreshold', 0.0)

    # 1) Load today's selection file
    try:
        with open(gvars.topSelectionFile, encoding="utf-8") as f:
            pairs = json.load(f)
    except FileNotFoundError:
        messages("No selection file found", console=1, log=1, telegram=0)
        return

    # Always update positions from disk and exchange before counting open positions
    orderManager.updatePositions()
    posicionesYaAbiertas = len(orderManager.positions)
    opportunities = []

    # Filtrar pares que ya tienen posición abierta antes de lanzar los hilos
    pairsToAnalyze = [p for p in pairs if p not in orderManager.positions]

    # 2) Esperar 5 segundos antes de lanzar los hilos para obtener las velas
    time.sleep(5)
    # 2) Generate opportunities in parallel
    def processPair(pair):
        import time
        # Reduced sleep time for better performance - BingX can handle more requests
        time.sleep(gvars.pairAnalysisSleepTime)  # Centralized sleep time configuration
        rate_limiter.acquire()
        try:
            # Use cached OHLCV data to reduce API calls
            cache_key = f"ohlcv_{pair}_{timeframe}_{requestedCandles}"
            ohlcv = exchange.fetch_ohlcv(pair, timeframe, None, requestedCandles)  # Direct call without cache
        except Exception as e:
            return {"pair": pair, "reason": f"OHLCV error: {e}"}

        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        # Discard the most recent candle if it's too close to now
        if len(df) > 0:
            now = datetime.now(UTC)
            lastCandleTime = df["timestamp"].iloc[-1]
            if lastCandleTime.tzinfo is None:
                lastCandleTime = lastCandleTime.replace(tzinfo=UTC)
            tfStr = str(timeframe)
            if tfStr.endswith('m'):
                tfSeconds = int(tfStr[:-1]) * 60
            elif tfStr.endswith('h'):
                tfSeconds = int(tfStr[:-1]) * 3600
            elif tfStr.endswith('d'):
                tfSeconds = int(tfStr[:-1]) * 86400
            else:
                tfSeconds = 0
            diffSeconds = (now - lastCandleTime).total_seconds()
            if diffSeconds < tfSeconds:
                df = df.iloc[:-1]

        df = filterSignals(df)
        # Detectar oportunidades long y short
        opps = findPossibleResistancesAndSupports(
            df["low"].values,
            df["high"].values,
            df["close"].values,
            df["open"].values,
            tolerancePct=tolerancePct,
            minSeparation=minCandlesSeparationToFindSupportLine,
            minTouches=minTouches,
            closeViolationPct=0.02
        )
        results = []
        for opp in opps:
            # The bounce validation is already done in supportDetector.py
            # We only need to validate the final criteria here
            last, prev, prev2 = len(df)-1, len(df)-2, len(df)-3
            lineExp = opp['lineExp']
            
            # Calculate MA25 and MA99 for logging and pattern analysis
            # Re-enabled for data collection and pattern analysis
            ma25Series = df["close"].rolling(window=25).mean()
            ma99Series = df["close"].rolling(window=99).mean()
            ma25Prev = ma25Series.iloc[prev] if len(ma25Series) > prev and not pd.isna(ma25Series.iloc[prev]) else None
            ma99Prev = ma99Series.iloc[prev] if len(ma99Series) > prev and not pd.isna(ma99Series.iloc[prev]) else None
            
            # Calcular score y otros datos igual que antes
            avgVol   = df["volume"].mean() or 1
            volTouch = df["volume"].iat[last]
            closeLast = df["close"].iat[last]
            volUsdc = volTouch * closeLast
            if volUsdc < lastCandleMinUSDVolume:
                continue
            distance = abs(df["low"].iat[last] - lineExp[last]) if opp['type']=='long' else abs(df["high"].iat[last] - lineExp[last])
            distancePct = distance / lineExp[last] if lineExp[last] else 0
            volumeRatio = volTouch / avgVol
            momentum    = (df["close"].iat[last] - df["close"].iat[prev]) / df["close"].iat[prev] if df["close"].iat[prev] else 0
            # For LONG positions, positive momentum is good (price going up)
            # For SHORT positions, negative momentum is good (price going down)
            momentumScore = momentum if opp['type'] == 'long' else -momentum
            score = (
                scoringWeights["distance"] * (1 - distancePct) +
                scoringWeights["volume"]   * min(volumeRatio, 2) +
                scoringWeights["momentum"] * max(momentumScore, 0) +
                scoringWeights["touches"]  * min(opp['touchCount'] / minTouches, 1)
            )
            results.append({
                "pair": pair,
                "type": opp['type'],
                "slope": opp['slope'],
                "intercept": opp['intercept'],
                "touchesCount": opp['touchCount'],
                "score": score,
                "distancePct": distancePct,
                "volumeRatio": volumeRatio,
                "momentum": momentum,
                "entryPrice": closeLast,
                "bases": opp['bases'],
                "csvPath": fileManager.saveCsv(ohlcv, pair, timeframe, requestedCandles) if ohlcv and len(ohlcv) > 0 else "",
                "minPctBounceAllowed": minPctBounceAllowed,
                "maxPctBounceAllowed": maxPctBounceAllowed,
                "bounceLow": lineExp[last] * (1 - maxPctBounceAllowed) if opp['type'] == 'short' else lineExp[last] * (1 + minPctBounceAllowed),
                "bounceHigh": lineExp[last] * (1 - minPctBounceAllowed) if opp['type'] == 'short' else lineExp[last] * (1 + maxPctBounceAllowed),
                "ma25Prev": ma25Prev,
                "ma99Prev": ma99Prev,
                # Add candle data to avoid CSV re-reading
                "candleData": {
                    "close_n1": df["close"].iat[last],
                    "open_n1": df["open"].iat[last], 
                    "low_n1": df["low"].iat[last],
                    "high_n1": df["high"].iat[last],  # Add high_n1 for SHORT validation
                    "close_n2": df["close"].iat[prev],
                    "open_n2": df["open"].iat[prev],
                    "candleCount": len(df)
                }
            })
        return results

    messages(f"[DEBUG] Starting parallel processing of {len(pairsToAnalyze)} pairs with {gvars.threadPoolMaxWorkers} workers", console=0, log=1, telegram=0)
    
    # Progress counter
    processed_count = 0
    total_pairs = len(pairsToAnalyze)
    
    with ThreadPoolExecutor(max_workers=gvars.threadPoolMaxWorkers) as executor:
        futures = {executor.submit(processPair, p): p for p in pairsToAnalyze}
        for fut in as_completed(futures):
            processed_count += 1
            
            # Log progress every 25 pairs
            if processed_count % 25 == 0 or processed_count == total_pairs:
                messages(f"Progress: {processed_count}/{total_pairs} pairs analyzed", console=0, log=1, telegram=0)
            
            res = fut.result()
            if res:
                # Si es oportunidad válida, añadir a opportunities
                if isinstance(res, list):
                    for r in res:
                        if 'score' in r:
                            opportunities.append(r)
                        elif 'reason' in r:
                            messages(f"{r['pair']} descartada: {r['reason']}", console=0, log=1, telegram=0, pair=r['pair'])
                            # Guardar plot de descarte si hay datos
                            if 'csvPath' in r and r['csvPath']:
                                item = {
                                    'pair': f"DISCARD_{r['pair']}",
                                    'csvPath': r['csvPath'],
                                    'slope': r.get('slope', 0),
                                    'intercept': r.get('intercept', 0),
                                    'type': 'discard'
                                }
                                # Skip plot generation during analysis - will be generated asynchronously later
                                # try:
                                #     plotting.savePlot(item)
                                # except Exception as e:
                                #     messages(f"Error saving plot for {r['pair']}: {e}", console=0, log=1, telegram=0, pair=r['pair'])
                else:
                    if 'score' in res:
                        opportunities.append(res)
                    elif 'reason' in res:
                        messages(f"{res['pair']} descartada: {res['reason']}", console=0, log=1, telegram=0, pair=res['pair'])
                        # Guardar plot de descarte si hay datos
                        if 'csvPath' in res and res['csvPath']:
                            item = {
                                'pair': f"DISCARD_{res['pair']}",
                                'csvPath': res['csvPath'],
                                'slope': res.get('slope', 0),
                                'intercept': res.get('intercept', 0),
                                'type': 'discard'
                            }
                            # Skip plot generation during analysis - will be generated asynchronously later  
                            # try:
                            #     plotting.savePlot(item)
                            # except Exception as e:
                            #     messages(f"Error saving plot for {res['pair']}: {e}", console=0, log=1, telegram=0, pair=res['pair'])

    messages(f"[DEBUG] Parallel processing completed, found {len(opportunities)} total opportunities", console=0, log=1, telegram=0)
    # 3) Sort by score descending
    ordered = sorted(opportunities, key=lambda o: o["score"], reverse=True)
    # Filtrar solo la mejor oportunidad por cada par
    bestByPair = {}
    for o in ordered:
        if o['pair'] not in bestByPair:
            bestByPair[o['pair']] = o
    bestOrdered = list(bestByPair.values())
    messages(f"Ordered (pair,score,side): {[ (o['pair'], round(float(o['score']), 6), o.get('type','')) for o in bestOrdered ]}", 0, 1, 0)

    # 4) Pre-calculate bounce bounds & MA25 (si lo necesitas, pero ya lo haces en processPair)
    #    (puedes omitir este paso si confías en los valores ya retornados)

    # 5) Analyze opportunities and collect approved ones for execution
    approvedCount = 0
    # Exclusión para evitar procesamiento duplicado de símbolos
    import threading
    if not hasattr(analyzePairs, "processingSymbols"):
        analyzePairs.processingSymbols = set()
        analyzePairs.processingLock = threading.Lock()
    processingSymbols = analyzePairs.processingSymbols
    processingLock = analyzePairs.processingLock

    # Filtrar oportunidades para que cada símbolo solo se procese una vez
    seenSymbols = set()
    for opp in ordered:
        if opp["pair"] in seenSymbols:
            continue
        seenSymbols.add(opp["pair"])
        record = None
        accepted = 0

        # Normalizar el símbolo para plots y Telegram
        symbolNorm = opp["pair"].replace(":USDT", "").replace("/", "_")
        plotType = opp.get("type", "LONG").upper()
        import os
        plotFileName = f"{plotType}_{symbolNorm}.png"
        plotPath = os.path.join(gvars.plotsFolder, plotFileName)

        # Exclusión rápida: si el símbolo está siendo procesado por otro hilo, saltar
        with processingLock:
            if opp["pair"] in processingSymbols:
                messages(f"Skipping openPosition for {opp['pair']}: already being processed by another thread", console=1, log=1, telegram=0, pair=opp['pair'])
                continue
            processingSymbols.add(opp["pair"])

        try:
            # Evitar duplicados: no abrir posición si ya está abierta
            if opp["pair"] in orderManager.positions:
                messages(f"Skipping openPosition for {opp['pair']}: position already open", console=1, log=1, telegram=0, pair=opp['pair'])
                continue
            # ...existing code...
            # Cuando se genere el plot, usar plotPath para la ruta
            # ...existing code...
        finally:
            # Al terminar, eliminar el símbolo del set de procesamiento
            with processingLock:
                processingSymbols.discard(opp["pair"])

        # Investment percentage logic based on score
        score = opp["score"]
        if score > 0.85:
            investmentPct = 1.0
        elif score > 0.65:
            investmentPct = 0.7
        else:
            investmentPct = 0.5

        # Validar cantidad mínima antes de abrir la orden
        # Obtener mínimo desde markets.json si existe
        minAmount = 0.0
        try:
            with open(gvars.marketsFile, encoding='utf-8') as f:
                marketsData = json.load(f)
            marketInfo = next((m for m in marketsData.values() if m['symbol'] == opp['pair']), None)
            if marketInfo:
                minAmount = float(marketInfo.get('info', {}).get('minAmount', 0.0))
        except Exception:
            minAmount = 0.0

        # Calcular cantidad a invertir
        entryPrice = opp["entryPrice"]
        usdcInvestment = configData["usdcInvestment"] * investmentPct
        amountToOpen = usdcInvestment / entryPrice if entryPrice else 0
        # Si la cantidad calculada es menor que la mínima, usar la mínima requerida
        if minAmount > 0 and amountToOpen < minAmount:
            messages(f"Cantidad calculada para {opp['pair']} ({amountToOpen:.4f}) es menor que el mínimo permitido ({minAmount}), usando el mínimo.", console=1, log=1, telegram=0, pair=opp['pair'])
            amountToOpen = minAmount

        # Calculate filter results for logging
        filter1Passed = False  # Basic technical criteria
        filter2Passed = False  # Entry-specific criteria
        filter1Passed = (opp["score"] >= scoreThreshold and posicionesYaAbiertas < configData["maxOpenPositions"])

        # Attempt to analyze opportunity according to filters
        rejected = False
        totalValidations = 5  # Updated: Total number of validation steps (restored RANGE validation)
        currentValidation = 1
        
        if opp["score"] < scoreThreshold:
            messages(f"  ⚠️  {opp['pair']} rejected by SCORE ({currentValidation}/{totalValidations}): {opp['score']:.4f} < threshold {scoreThreshold:.4f}", console=0, log=1, telegram=0, pair=opp['pair'])
            rejected = True
        elif posicionesYaAbiertas >= configData["maxOpenPositions"]:
            currentValidation = 2
            totalOpen = posicionesYaAbiertas
            messages(f"  ⚠️  {opp['pair']} rejected by OPENED POSITIONS ({currentValidation}/{totalValidations}): {totalOpen}/{configData['maxOpenPositions']}", console=0, log=1, telegram=0, pair=opp['pair'])
            rejected = True
        else:
            try:
                # Use pre-calculated candle data instead of reading CSV again
                candleData = opp.get("candleData", {})
                if not candleData:
                    # Fallback to CSV if candleData is missing (shouldn't happen)
                    df = pd.read_csv(opp["csvPath"])
                    close_n1 = df["close"].iloc[-1]
                    open_n1 = df["open"].iloc[-1]
                    low_n1 = df["low"].iloc[-1]
                    high_n1 = df["high"].iloc[-1]  # Add high_n1 for SHORT validation
                    close_n2 = df["close"].iloc[-2]
                    open_n2 = df["open"].iloc[-2]
                    candleCount = len(df)
                else:
                    # Use pre-calculated data for better performance
                    close_n1 = candleData["close_n1"]
                    open_n1 = candleData["open_n1"]
                    low_n1 = candleData["low_n1"]
                    high_n1 = candleData["high_n1"]  # Add high_n1 for SHORT validation
                    close_n2 = candleData["close_n2"]
                    open_n2 = candleData["open_n2"]
                    candleCount = candleData["candleCount"]
                
                # Calculate support line for N-1 candle
                idx_n1 = -1  # Most recent candle
                soporte_n1 = opp["slope"] * (candleCount + idx_n1) + opp["intercept"]
                
                # Both last candles (N-1 and N-2) must be same color: both green OR both red
                currentValidation = 3
                
                isN1Green = close_n1 > open_n1
                isN2Green = close_n2 > open_n2
                
                # Check if both candles are the same color
                if not ((isN1Green and isN2Green) or (not isN1Green and not isN2Green)):
                    color_n1 = "green" if isN1Green else "red"
                    color_n2 = "green" if isN2Green else "red"
                    messages(f"  ⚠️  {opp['pair']} rejected by CANDLE SEQUENCE ({currentValidation}/{totalValidations}): N-1={color_n1}, N-2={color_n2} (must be same color)", console=0, log=1, telegram=0, pair=opp['pair'])
                    rejected = True
                # N-1 must touch or pierce the support/resistance line based on position type
                if not rejected:
                    currentValidation = 4
                    
                    if opp['type'] == 'long':
                        # LONG: Check if low touches or pierces support line
                        if low_n1 < soporte_n1:
                            # If it pierces, allow tolerance
                            if abs(low_n1 - soporte_n1) > abs(soporte_n1) * tolerancePct:
                                messages(f"  ⚠️  {opp['pair']} rejected by SUPPORT TOUCH ({currentValidation}/{totalValidations}): N-1 pierces but out of tolerance", console=0, log=1, telegram=0, pair=opp['pair'])
                                rejected = True
                        elif low_n1 > soporte_n1:
                            # If it does not touch, reject
                            messages(f"  ⚠️  {opp['pair']} rejected by SUPPORT TOUCH ({currentValidation}/{totalValidations}): N-1 does not touch the support line", console=0, log=1, telegram=0, pair=opp['pair'])
                            rejected = True
                    
                    elif opp['type'] == 'short':
                        # SHORT: Check if high touches or pierces resistance line
                        if high_n1 > soporte_n1:
                            # If it pierces, allow tolerance
                            if abs(high_n1 - soporte_n1) > abs(soporte_n1) * tolerancePct:
                                messages(f"  ⚠️  {opp['pair']} rejected by RESISTANCE TOUCH ({currentValidation}/{totalValidations}): N-1 pierces but out of tolerance", console=0, log=1, telegram=0, pair=opp['pair'])
                                rejected = True
                        elif high_n1 < soporte_n1:
                            # If it does not touch, reject
                            messages(f"  ⚠️  {opp['pair']} rejected by RESISTANCE TOUCH ({currentValidation}/{totalValidations}): N-1 does not touch the resistance line", console=0, log=1, telegram=0, pair=opp['pair'])
                            rejected = True
            except Exception as e:
                currentValidation = 3  # Error in candle sequence check
                messages(f"  ⚠️  {opp['pair']} rejected by CANDLE SEQUENCE ({currentValidation}/{totalValidations}) check error: {e}", console=0, log=1, telegram=0, pair=opp['pair'])
                rejected = True

        # After basic filters, check entry-specific criteria for filter2
        filter2Passed = filter1Passed and not rejected

        # RANGE validation: Check if current price is within allowed bounce range
        if not rejected:
            currentValidation = 5
            try:
                currentPrice = opp.get("entryPrice", 0)
                bounceLow = opp.get("bounceLow", 0)
                bounceHigh = opp.get("bounceHigh", 0)
                
                if currentPrice < bounceLow or currentPrice > bounceHigh:
                    messages(f"  ⚠️  {opp['pair']} rejected by BOUNCE RANGE ({currentValidation}/{totalValidations}): price {currentPrice:.6f} not in range [{bounceLow:.6f}, {bounceHigh:.6f}]", console=0, log=1, telegram=0, pair=opp['pair'])
                    rejected = True
                else:
                    messages(f"  ✅  {opp['pair']} passed BOUNCE RANGE ({currentValidation}/{totalValidations}): price {currentPrice:.6f} in range [{bounceLow:.6f}, {bounceHigh:.6f}]", console=0, log=1, telegram=0, pair=opp['pair'])
            except Exception as e:
                messages(f"  ⚠️  {opp['pair']} rejected by BOUNCE RANGE ({currentValidation}/{totalValidations}) check error: {e}", console=0, log=1, telegram=0, pair=opp['pair'])
                rejected = True

        # Note: Restored RANGE validation (bounceLow/bounceHigh) to filter extreme bounces
        # The basic bounce validation is handled in supportDetector.py
        
        record = None
        accepted = 0
        if not rejected:
            # 5e) Instead of opening position immediately, add to approved opportunities list
            # Preparar para quitar ReduceOnly en modo Hedge (debe hacerse en orderManager/connector)
            side = opp.get("type", "long")  # Get side from opportunity type (long/short)
            
            # Store all necessary data for position opening
            # Generate unique opportunity ID for tracking
            opportunityId = str(uuid.uuid4())[:8]  # Short UUID for tracking
            
            opportunityToExecute = {
                'pair': opp["pair"],
                'slope': opp.get("slope"),
                'intercept': opp.get("intercept"),
                'investmentPct': investmentPct,
                'side': side,
                'opp': opp,  # Keep full opportunity data for plotting and logging
                'symbolNorm': symbolNorm,
                'plotFileName': plotFileName,
                'usdcInvestment': usdcInvestment,
                'opportunityId': opportunityId  # Add unique ID for tracking
            }
            
            approvedOpportunities.append(opportunityToExecute)
            messages(f"  ✅  {opp['pair']} approved for execution (score: {opp['score']:.4f})", console=0, log=1, telegram=0, pair=opp['pair'])
            
            # Count as accepted for logging purposes
            accepted = 1
        itemAll = {
            **opp,
            "tpPrice":            (record or {}).get("tpPrice"),
            "slPrice":            (record or {}).get("slPrice"),
            # Only use new bounce fields for plotting
            "minPctBounceAllowed": opp["minPctBounceAllowed"],
            "maxPctBounceAllowed": opp["maxPctBounceAllowed"],
            "ma99":               opp.get("ma99"),
            "momentum":           opp.get("momentum"),
            "distance":           opp.get("distancePct"),
            "touches":            opp.get("touchesCount"),
            "volume":             opp.get("volumeRatio"),
            "score":              opp.get("score")
        }
        if record:
            itemAll.update({
                "tpPrice": record["tpPrice"],
                "slPrice": record["slPrice"]
                # Do not add bouncePct or maxBounceAllowed, only the new fields
            })
        
        # Store data for post-analysis plot generation (for all opportunities)
        # All plots will be generated asynchronously at the end to avoid slowing down execution
        if not hasattr(analyzePairs, '_plotData'):
            analyzePairs._plotData = []
        analyzePairs._plotData.append(itemAll)

        # ——— 7) Loguear en selectionLog.csv ———
        tpId = (record or {}).get("tpOrderId2") or (record or {}).get("tpOrderId1", "")
        slId = (record or {}).get("slOrderId2") or (record or {}).get("slOrderId1", "")
        # Use unique opportunity ID for tracking
        uniqueId = str(uuid.uuid4())[:8]
        oppId = f"{tpId}-{slId}" if (tpId or slId) else uniqueId
        tsIso = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H-%M-%S")
        tsUnix = int(datetime.utcnow().timestamp())
        w = scoringWeights

        # Add filter status to opportunity for logging
        opp["filter1Passed"] = filter1Passed
        opp["filter2Passed"] = filter2Passed
        line = ";".join([
            oppId,
            tsIso,
            str(tsUnix),
            symbolNorm,
            opp.get("type", "long"),  # Add position type for better tracking
            helpers.fmt(opp["distancePct"], 6),
            helpers.fmt(opp["volumeRatio"], 6),
            helpers.fmt(opp["momentum"], 6),
            str(opp["touchesCount"]),
            helpers.fmt(opp["score"], 6),
            str(accepted),
            helpers.fmt(tolerancePct, 6),
            str(minTouches),
            helpers.fmt(opp["slope"], 6),
            helpers.fmt(opp["intercept"], 6),
            helpers.fmt(opp["entryPrice"], 6),
            helpers.fmt((record or {}).get("tpPrice", 0), 6),
            helpers.fmt((record or {}).get("slPrice", 0), 6),
            helpers.fmt(opp["bounceLow"], 6),
            helpers.fmt(opp["bounceHigh"], 6),
            helpers.fmt(opp.get("ma25Prev") or 0, 6),  # MA25 value for pattern analysis
            helpers.fmt(opp.get("ma99Prev") or 0, 6),  # MA99 value for pattern analysis
            str(int(opp["filter1Passed"])),
            str(int(opp["filter2Passed"])),
            helpers.fmt(w["distance"], 3),
            helpers.fmt(w["volume"], 3),
            helpers.fmt(w["momentum"], 3),
            helpers.fmt(w["touches"], 3),
            helpers.fmt((record or {}).get("tpPercent", 0), 1),
            helpers.fmt((record or {}).get("slPercent", 0), 1),
            str((record or {}).get("leverage", 0)),
            helpers.fmt((record or {}).get("investment_usdt", 0), 4),
            # Config variables from usdcInvestment downwards
            str(configData.get("usdcInvestment", 0)),
            str(configData.get("maxOpenPositions", 0)),
            str(configData.get("timeframe", "")),
            str(configData.get("requestedCandles", 0)),
            helpers.fmt(configData.get("tp1", 0), 2),
            helpers.fmt(configData.get("tp2", 0), 2),
            helpers.fmt(configData.get("sl1", 0), 2),
            str(configData.get("topCoinsPctAnalyzed", 0)),
            helpers.fmt(configData.get("minPctBounceAllowed", 0), 6),
            helpers.fmt(configData.get("maxPctBounceAllowed", 0), 6),
            str(configData.get("minCandlesSeparationToFindSupportLine", 0)),
            helpers.fmt(configData.get("scoreThreshold", 0), 3),
            str(configData.get("lastCandleMinUSDVolume", 0)),
            str(configData.get("last24hrsPairVolume", 0)),
            "",  # profitQuote - to be filled when position closes
            "",  # profitPct - to be filled when position closes
            "",  # close_ts_iso - to be filled when position closes
            "",  # close_ts_unix - to be filled when position closes
            ""   # time_to_close_s - to be filled when position closes
        ]) + "\n"

        with open(gvars.selectionLogFile, "a", encoding="utf-8") as f:
            f.write(line)


    # 8) Finish main processing
    analysisEndTime = time.time()
    analysisElapsed = analysisEndTime - analysisStartTime
    messages(f"Analysis phase completed. Elapsed: {analysisElapsed:.2f}s", console=1, log=1, telegram=0)
    
    # 9) Generate plots for all opportunities asynchronously (non-blocking)
    if args.generatePlots and hasattr(analyzePairs, '_plotData') and analyzePairs._plotData:
        def generatePlotsAsync():
            import threading
            plotCount = len(analyzePairs._plotData)
            messages(f"Starting asynchronous plot generation for {plotCount} opportunities", console=0, log=1, telegram=0)
            plotStart = time.time()
            
            for plotData in analyzePairs._plotData:
                try:
                    plotting.savePlot(plotData)
                except Exception as e:
                    messages(f"Error generating delayed plot for {plotData.get('pair', 'unknown')}: {e}", console=0, log=1, telegram=0)
            
            plotElapsed = time.time() - plotStart
            messages(f"Plot generation completed. {plotCount} plots generated in {plotElapsed:.2f}s", console=1, log=1, telegram=0)
            # Clear plot data after generation
            analyzePairs._plotData = []
        
        # Start plot generation in background thread
        plotThread = threading.Thread(target=generatePlotsAsync, daemon=True)
        plotThread.start()
        messages("Plot generation started in background thread", console=0, log=1, telegram=0)
    elif not args.generatePlots and hasattr(analyzePairs, '_plotData') and analyzePairs._plotData:
        # Clear plot data if plots are disabled
        analyzePairs._plotData = []
        messages("Plot generation disabled by -plots argument", console=0, log=1, telegram=0)
    
    # ——— NEW: EXECUTION PHASE - Process approved opportunities sequentially ———
    if approvedOpportunities:
        executionStartTime = time.time()
        messages(f"Starting execution phase: {len(approvedOpportunities)} opportunities to process", console=1, log=1, telegram=0)
        executionResults = executeOpportunitiesSequentially(approvedOpportunities, configData)
        executionEndTime = time.time()
        executionElapsed = executionEndTime - executionStartTime
        messages(f"Execution phase completed: {executionResults['opened']} positions opened, {executionResults['failed']} failed in {executionElapsed:.2f}s", console=1, log=1, telegram=0)
    else:
        messages("No opportunities approved for execution", console=1, log=1, telegram=0)
    
    # Calculate total elapsed time
    totalEndTime = time.time()
    totalElapsed = totalEndTime - startTime
    messages(f"Total processing time: {totalElapsed:.2f}s", console=1, log=1, telegram=0)
    
    # Show the separator line AFTER all messages
    messages(gvars._line_, console=1, log=1, telegram=0)
    
    # monitorActive.set()  # Disabled - position monitor removed

    # Log of pairs found in openedPositions.json (log only)
    try:
        with open(gvars.positionsFile, encoding="utf-8") as f:
            bot_positions = json.load(f)
        # Soporta ambos formatos: lista antigua o dict nuevo
        if isinstance(bot_positions, dict):
            pairs_json = list(bot_positions.keys())
        elif isinstance(bot_positions, list):
            pairs_json = [p.get("symbol") for p in bot_positions if isinstance(p, dict) and p.get("symbol")]
        else:
            pairs_json = []
    except Exception as e:
        pairs_json = []
        messages(f"Error loading openedPositions.json: {e}", console=0, log=1, telegram=0)

    messages(f"pairs found in openedpositions.json: {pairs_json}", console=0, log=1, telegram=0)









# Fetch and save top selection
def updatePairs():

    messages("Fetching all pairs data", console=1, log=1, telegram=0)

    # Cargar lista de pares a ignorar
    try:
        with open(gvars.ignorePairsFile, encoding='utf-8') as f:
            ignorePairs = json.load(f)
    except Exception:
        ignorePairs = []

    # Leer config en caliente para topCoinsPctAnalyzed
    topCoinsPctAnalyzed = configManager.get('topCoinsPctAnalyzed', 10)

    # Selección de pares de futuros perpetuos USDT
    futuresPairs = getFuturesPairs()
    # Validar y filtrar pares
    validated_pairs = []
    for symbol in futuresPairs:
        try:
            if validateSymbol(symbol) and symbol not in ignorePairs:
                validated_pairs.append(symbol)
        except DataValidationError:
            messages(f"Invalid symbol detected: {symbol}", console=1, log=1, telegram=0)
    
    filtered = validated_pairs
    total = len(filtered)

    # Obtener volúmenes de todos los pares filtrados usando cache
    try:
        tickers = exchange.fetch_tickers()  # Direct call without cache
        messages(f"Tickers fetched: {len(tickers)}", console=0, log=1, telegram=0, pair="")
    except Exception as e:
        messages(f"Error fetching tickers: {e}", console=1, log=1, telegram=0)
        messages(f"Error fetching tickers: {e}", console=1, log=1, telegram=0)
        tickers = {}



    # Leer volumen mínimo de config
    minVolume = configManager.get('last24hrsPairVolume', 0)

    # Calcular volumen en USDT para cada par y filtrar por mínimo
    volumes_usdt = {}
    for s in filtered:
        ticker = tickers.get(s, {})
        baseVol = ticker.get('baseVolume', 0) or 0
        price = ticker.get('last', 0) or 0
        vol_usdt = baseVol * price
        if vol_usdt >= minVolume:
            volumes_usdt[s] = vol_usdt

    # Ordenar por volumen USDT descendente
    sortedPairs = sorted(volumes_usdt, key=lambda x: volumes_usdt[x], reverse=True)
    numSelect = max(1, int(len(sortedPairs) * topCoinsPctAnalyzed / 100))
    selected = sortedPairs[:numSelect]

    messages(f"  >> Total USDT perpetual futures pairs with volume >= {minVolume}: {len(sortedPairs)}. Top {topCoinsPctAnalyzed}% seleccionados: {numSelect}", console=0, log=1, telegram=0, pair="")

    # ...existing code...
    # Justo antes de iniciar el análisis, imprimir los pares seleccionados ordenados por volumen

    # Mensaje informativo antes de analizar
    numHilos = gvars.threadPoolMaxWorkers
    sleepSeg = gvars.pairAnalysisSleepTime
    messages(f"  >> Using {numHilos} threads with {sleepSeg}s sleeping between each one", console=0, log=1, telegram=0, pair="")

    # Guardar selección
    fileManager.saveJson(selected, gvars.topSelectionFile.split('/')[-1])

    return selected
