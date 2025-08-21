import threading
import json
import time
import ccxt
from connector import bingxConnector, loadConfig
import pandas as pd


from datetime import datetime, UTC
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo


import gvars
import plotting
import orderManager
import fileManager
import helpers

from logManager import messages
from supportDetector import findSupportLine
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
orderManager = orderManager.OrderManager()
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








def filter_signals(df):
    """
    1) Elimina los outliers extremos de 'low' (percentil 1–99)
    2) (Opcional) aquí podrías añadir más filtros globales
    """
    q_low, q_high = df['low'].quantile(0.01), df['low'].quantile(0.99)
    df = df[(df['low'] >= q_low) & (df['low'] <= q_high)]
    return df.reset_index(drop=True)








def analyzePairs():
    """
    1) Load daily selection
    2) For each pair: fetch OHLCV, filter, detect support, calculate metrics
    3) Sort by score
    4) Pre-compute bounceLow/bounceHigh and previous MA25
    5) Open positions up to maxOpenPositions, and for each:
       • generate and send msg+image via messages()
    6) Log everything in selectionLog.csv; plots are not deleted
    """


    # ——— 0) Limpiar carpeta de plots ———
    fileManager.deleteOldFiles(json=False, csv=True, plots=True)
    from positionMonitor import monitorActive
    messages("Starting analysis", console=1, log=1, telegram=0)
    monitorActive.clear()  # Pausa el monitor
    dateTag = datetime.utcnow().date().isoformat()

    # Leer config en caliente
    configData = loadConfig()

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

    # 2) Esperar 5 segundos antes de lanzar los hilos para obtener las velas
    time.sleep(5)
    # 2) Generate opportunities in parallel
    def processPair(pair):
        rate_limiter.acquire()
        try:
            # ohlcv = exchange.fetch_ohlcv(pair, timeframe, None, limit)
            ohlcv = exchange.fetch_ohlcv(pair, timeframe, None, requestedCandles)
        except Exception as e:
            messages(f"OHLCV error {pair}: {e}", console=1, log=1, telegram=0, pair=pair)
            return None
        except Exception as e:
            messages(f"OHLCV error {pair}: {e}", console=1, log=1, telegram=0, pair=pair)
            return None

        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        # Discard the most recent candle if it's too close to now
        if len(df) > 0:
            # English comment: use timezone-aware UTC datetime to avoid deprecation warning
            now = datetime.now(UTC)
            lastCandleTime = df["timestamp"].iloc[-1]
            # English comment: ensure lastCandleTime is tz-aware in UTC for subtraction
            if lastCandleTime.tzinfo is None:
                lastCandleTime = lastCandleTime.replace(tzinfo=UTC)
            # Convert timeframe to seconds
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
                # Remove the last candle
                df = df.iloc[:-1]

        df = filter_signals(df)

        # slope, intercept, touchesCount, lineExp, bases = findSupportLine(
        #     df["low"].values,
        #     df["close"].values,
        #     df["open"].values,
        #     tolerancePct=tolerancePct,
        #     minSeparation=minSeparation,
        #     minTouches=minTouches
        # )
        slope, intercept, touchesCount, lineExp, bases = findSupportLine(
            df["low"].values,
            df["close"].values,
            df["open"].values,
            tolerancePct=tolerancePct,
            minSeparation=minCandlesSeparationToFindSupportLine,
            minTouches=minTouches
        )
        if len(bases) != 2:
            return None

        last, prev = len(df)-1, len(df)-2
        lowLast, expLast     = df["low"].iat[last],   lineExp[last]
        lowPrev, expPrev     = df["low"].iat[prev],   lineExp[prev]
        closeLast, openLast  = df["close"].iat[last], df["open"].iat[last]
        closePrev, openPrev  = df["close"].iat[prev], df["open"].iat[prev]
        tolerance = tolerancePct if 'tolerancePct' in locals() else 0.015
        # English comment: Only consider opportunity if previous candle touches support and last candle is green
        touchesSupport = abs(lowPrev - expPrev) <= abs(expPrev) * tolerance
        isGreen = closeLast > openLast
        if not (touchesSupport and isGreen):
            return None
        avgVol   = df["volume"].mean() or 1
        volTouch = df["volume"].iat[last]
        closeLast = df["close"].iat[last]
        # Calcular volumen en USDC de la última vela
        volUsdc = volTouch * closeLast
        # if volUsdc < minVolume:
        #     messages(f"  ⚠️  {pair} ignorado por volumen USDC bajo: {volUsdc:.2f} < minVolume {minVolume}", console=1, log=1, telegram=0, pair=pair)
        #     return None
        if volUsdc < lastCandleMinUSDVolume:
            messages(f"  ⚠️  {pair} ignorado por volumen USDC bajo: {volUsdc:.2f} < lastCandleMinUSDVolume {lastCandleMinUSDVolume}", console=1, log=1, telegram=0, pair=pair)
            return None
        distance = abs(lowLast - expLast)
        distancePct = distance / expLast if expLast else 0
        volumeRatio = volTouch / avgVol
        momentum    = (closeLast - closePrev) / closePrev if closePrev else 0

        score = (
            scoringWeights["distance"] * (1 - distancePct) +
            scoringWeights["volume"]   * min(volumeRatio, 2) +
            scoringWeights["momentum"] * max(momentum, 0) +
            scoringWeights["touches"]  * min(touchesCount / minTouches, 1)
        )

        # csvPath = fileManager.saveCsv(ohlcv, pair, timeframe, limit)
        csvPath = fileManager.saveCsv(ohlcv, pair, timeframe, requestedCandles)

        # calcular MA25prev y bounce bounds
        ma25 = df["close"].rolling(25).mean()
        ma25Prev = float(ma25.iat[-2]) if len(ma25) >= 2 else None
        ma99 = df["close"].rolling(99).mean()
        ma99Prev = float(ma99.iat[-2]) if len(ma99) >= 2 else None
        # bounceLow  = expLast * (1 + bouncePct)
        # bounceHigh = expLast * (1 + maxBounceAllowed)
        bounceLow  = expLast * (1 + minPctBounceAllowed)
        bounceHigh = expLast * (1 + maxPctBounceAllowed)
        filter1 = bounceLow <= closeLast <= bounceHigh
        filter2 = (ma25Prev is not None and closeLast > ma25Prev)
        filter3 = (ma99Prev is not None and closeLast > ma99Prev)

        return {
            "pair":             pair,
            "csvPath":          csvPath,
            "slope":            slope,
            "intercept":        intercept,
            "touchesCount":     touchesCount,
            "score":            score,
            "distancePct":      distancePct,
            "volumeRatio":      volumeRatio,
            "momentum":         momentum,
            "entryPrice":       closeLast,
            "bases":            bases,
            "bounceLow":        bounceLow,
            "bounceHigh":       bounceHigh,
            "ma25Prev":         ma25Prev,
            "ma99Prev":         ma99Prev,
            "ma99":             list(ma99) if ma99 is not None else None,
            "filter1Passed":    filter1,
            "filter2Passed":    filter2,
            "filter3Passed":    filter3,
            # "bouncePct":        bouncePct,
            # "maxBounceAllowed": maxBounceAllowed
            "minPctBounceAllowed": minPctBounceAllowed,
            "maxPctBounceAllowed": maxPctBounceAllowed
        }

    with ThreadPoolExecutor(max_workers=gvars.threadPoolMaxWorkers) as executor:
        futures = {executor.submit(processPair, p): p for p in pairs}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                opportunities.append(res)

    # 3) Sort by score descending
    ordered = sorted(opportunities, key=lambda o: o["score"], reverse=True)
    messages(f"Ordered (pair,score): {[ (o['pair'], round(float(o['score']), 4)) for o in ordered ]}", 0, 1, 0)

    # 4) Pre-calculate bounce bounds & MA25 (si lo necesitas, pero ya lo haces en processPair)
    #    (puedes omitir este paso si confías en los valores ya retornados)

    # 5) Open positions AND generar plot para todas
    nuevasAbiertas = 0
    # ...existing code...
    for opp in ordered:
        record = None
        accepted = 0

        # Investment percentage logic based on score
        score = opp["score"]
        if score > 0.85:
            investmentPct = 1.0
        elif score > 0.65:
            investmentPct = 0.7
        else:
            investmentPct = 0.5

        # Attempt to open position according to filters
        rejected = False
        if opp["score"] < scoreThreshold:
            messages(f"  ⚠️  {opp['pair']} rejected by SCORE: {opp['score']:.4f} < threshold {scoreThreshold:.4f}", console=0, log=1, telegram=0, pair=opp['pair'])
            rejected = True
        elif posicionesYaAbiertas + nuevasAbiertas >= configData["maxOpenPositions"]:
            totalOpen = posicionesYaAbiertas + nuevasAbiertas
            messages(f"  ⚠️  {opp['pair']} rejected by OPENED POSITIONS: {totalOpen}/{configData['maxOpenPositions']}", console=0, log=1, telegram=0, pair=opp['pair'])
            rejected = True
        else:
            try:
                df = pd.read_csv(opp["csvPath"])
                idx_n1 = -2
                close_n1 = df["close"].iloc[idx_n1]
                open_n1 = df["open"].iloc[idx_n1]
                low_n1 = df["low"].iloc[idx_n1]
                soporte_n1 = opp["slope"] * (len(df) + idx_n1) + opp["intercept"]
                # Only the last candle (N-1) must be green
                if not (close_n1 > open_n1):
                    messages(f"  ⚠️  {opp['pair']} rejected by CANDLE SEQUENCE: N-1 not green", console=0, log=1, telegram=0, pair=opp['pair'])
                    rejected = True
                # N-1 must touch or pierce the support line
                if low_n1 < soporte_n1:
                    # If it pierces, allow tolerance
                    if abs(low_n1 - soporte_n1) > abs(soporte_n1) * tolerancePct:
                        messages(f"  ⚠️  {opp['pair']} rejected by SUPPORT TOUCH: N-1 pierces but out of tolerance", console=0, log=1, telegram=0, pair=opp['pair'])
                        rejected = True
                elif low_n1 > soporte_n1:
                    # If it does not touch, do not allow tolerance
                    messages(f"  ⚠️  {opp['pair']} rejected by SUPPORT TOUCH: N-1 does not touch the support line", console=0, log=1, telegram=0, pair=opp['pair'])
                    rejected = True
            except Exception as e:
                messages(f"  ⚠️  {opp['pair']} rejected by CANDLE SEQUENCE check error: {e}", console=0, log=1, telegram=0, pair=opp['pair'])
                rejected = True
        if not rejected:
            if not (opp["bounceLow"] <= opp["entryPrice"] <= opp["bounceHigh"]):
                bl, bh, ep = opp["bounceLow"], opp["bounceHigh"], opp["entryPrice"]
                if ep < bl:
                    diff_pct = 100 * (bl - ep) / bl if bl != 0 else 0
                    messages(f"  ⚠️  {opp['pair']} rejected by RANGE (BELOW): entryPrice {ep:.6f} < min {bl:.6f} ({diff_pct:.2f}% under)", console=0, log=1, telegram=0, pair=opp['pair'])
                elif ep > bh:
                    diff_pct = 100 * (ep - bh) / bh if bh != 0 else 0
                    messages(f"  ⚠️  {opp['pair']} rejected by RANGE (ABOVE): entryPrice {ep:.6f} > max {bh:.6f} ({diff_pct:.2f}% over)", console=0, log=1, telegram=0, pair=opp['pair'])
                else:
                    messages(f"  ⚠️  {opp['pair']} rejected by RANGE: entryPrice {ep:.6f} not in [{bl:.6f}, {bh:.6f}]", console=0, log=1, telegram=0, pair=opp['pair'])
                rejected = True
            elif opp.get("ma25Prev") is None or opp.get("ma99Prev") is None:
                messages(f"  ⚠️  {opp['pair']} rejected: MA25prev or MA99prev is None", console=0, log=1, telegram=0, pair=opp['pair'])
                rejected = True
            elif opp["entryPrice"] <= opp["ma25Prev"]:
                ep, mp = opp["entryPrice"], opp["ma25Prev"]
                messages(f"  ⚠️  {opp['pair']} rejected by PRICE UNDER MA25: entryPrice {ep:.6f} <= MA25prev {mp:.6f}", console=0, log=1, telegram=0, pair=opp['pair'])
                rejected = True
            elif opp["entryPrice"] <= opp["ma99Prev"]:
                ep, mp = opp["entryPrice"], opp["ma99Prev"]
                messages(f"  ⚠️  {opp['pair']} rejected by PRICE UNDER MA99: entryPrice {ep:.6f} <= MA99prev {mp:.6f}", console=0, log=1, telegram=0, pair=opp['pair'])
                rejected = True
        record = None
        accepted = 0
        if not rejected:
            # 5e) Open position with investmentPct
            record = orderManager.openPosition(opp["pair"], slope=opp.get("slope"), intercept=opp.get("intercept"), investmentPct=investmentPct)
            if record:
                nuevasAbiertas += 1
                accepted = 1
                item = {
                    **opp,
                    "tpPrice": record["tpPrice"],
                    "slPrice": record["slPrice"],
                    "ma99": opp.get("ma99"),
                    "momentum": opp.get("momentum"),
                    "distance": opp.get("distancePct"),
                    "touches": opp.get("touchesCount"),
                    "volume": opp.get("volumeRatio"),
                    "score": opp.get("score")
                }
                try:
                    plotPath = plotting.savePlot(item)
                    caption = (
                        f"{record['symbol']}\n"
                        f"Investment: {configData['usdcInvestment']} USDC ({investmentPct*100:.0f}%)\n"
                        f"Entry Price: {record['openPrice']}\n"
                        f"TP: {record['tpPrice']}\n"
                        f"SL: {record['slPrice']}"
                    )
                    messages([plotPath], console=0, log=1, telegram=2, caption=caption)
                except Exception as e:
                    messages(f"Error generating plot for {opp['pair']}: {e}", console=1, log=1, telegram=0, pair=opp['pair'])
            else:
                messages(f"{opp['pair']} openPosition returned None", console=0, log=0, telegram=0, pair=opp['pair'])

        # ——— 6) Generar plot para TODOS los pares de `ordered` ———
        # Incluir bouncePct y maxBounceAllowed para plotting.savePlot
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
        try:
            plotting.savePlot(itemAll)
        except Exception as e:
            messages(f"Error saving plot for {opp['pair']}: {e}", console=1, log=1, telegram=0, pair=opp['pair'])

        # ——— 7) Loguear en selectionLog.csv ———
        # Uso antiguo de campos, ahora comentado
        # tpId = (record or {}).get("tpOrderId", "")
        # slId = (record or {}).get("slOrderId", "")
        tpId = (record or {}).get("tpOrderId2") or (record or {}).get("tpOrderId1", "")
        slId = (record or {}).get("slOrderId2") or (record or {}).get("slOrderId1", "")
        oppId = f"{tpId}-{slId}"
        tsIso = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H-%M-%S")
        tsUnix = int(datetime.utcnow().timestamp())
        w = scoringWeights

        line = ";".join([
            oppId,
            tsIso,
            str(tsUnix),
            opp["pair"],
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
            helpers.fmt(opp.get("ma25Prev", 0), 6),
            str(int(opp["filter1Passed"])),
            str(int(opp["filter2Passed"])),
            helpers.fmt(w["distance"], 3),
            helpers.fmt(w["volume"], 3),
            helpers.fmt(w["momentum"], 3),
            helpers.fmt(w["touches"], 3)
        ]) + "\n"

        with open(gvars.selectionLogFile, "a", encoding="utf-8") as f:
            f.write(line)


    # 8) Finish without deleting plots
    messages("End processing", console=1, log=1, telegram=0)
    messages(gvars._line_, console=1, log=1, telegram=0)
    monitorActive.set()  # Reactiva el monitor

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
    with open(gvars.configFile, encoding='utf-8') as f:
        configData = json.load(f)
    topCoinsPctAnalyzed = configData.get('topCoinsPctAnalyzed', 10)

    # Selección de pares de futuros perpetuos USDT
    futuresPairs = getFuturesPairs()
    filtered = [s for s in futuresPairs if s not in ignorePairs]
    total = len(filtered)
    numSelect = max(1, int(total * topCoinsPctAnalyzed / 100))

    messages(f"Total USDT perpetual futures pairs: {total}. Selecting top {topCoinsPctAnalyzed}% -> {numSelect} pairs", console=1, log=1, telegram=0)
    import sys; sys.exit("Interrupción: solo mostrando cantidad de pares, análisis detenido para evitar baneo.")

    # Obtener volúmenes    
    try:
        tickers = exchange.fetch_tickers()
    except Exception as e:
        messages(f"Error fetching tickers: {e}", console=1, log=1, telegram=0)
        tickers = {}

    volumes = {s: tickers.get(s, {}).get('quoteVolume', 0) for s in filtered}
    selected = sorted(volumes, key=lambda x: volumes[x], reverse=True)[:numSelect]

    #messages(f"Selected pairs: {selected}", console=0, log=1, telegram=0)

    # Guardar selección
    fileManager.saveJson(selected, gvars.topSelectionFile.split('/')[-1])

    return selected
