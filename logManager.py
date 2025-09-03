
import os
import json
import requests
import inspect
from datetime import datetime
from zoneinfo import ZoneInfo
from gvars import configFile, logsFolder
from configManager import configManager
from exceptions import ConfigurationError

# Aliases for compatibility with new logger system
def log_info(message, **kwargs):
    messages(message, console=1, log=1, telegram=0)

def log_error(message, error=None, **kwargs):
    if error:
        messages(f"{message}: {error}", console=1, log=1, telegram=0)
    else:
        messages(message, console=1, log=1, telegram=0)

def log_debug(message, **kwargs):
    messages(message, console=0, log=1, telegram=0)

def log_warning(message, **kwargs):
    messages(message, console=1, log=1, telegram=0)

def log_trade(message, **kwargs):
    messages(message, console=1, log=1, telegram=1)

# Función de diagnóstico temporal
def diagnosticTelegram():
    """Diagnostic function to test Telegram configuration"""
    print(f"[DIAGNOSTIC] Telegram Token present: {bool(_telegramToken)}")
    print(f"[DIAGNOSTIC] Telegram Chat ID present: {bool(_telegramChatId)}")
    if _telegramToken and _telegramChatId:
        print(f"[DIAGNOSTIC] Token starts with: {_telegramToken[:10]}...")
        print(f"[DIAGNOSTIC] Chat ID: {_telegramChatId}")
        # Test message
        try:
            messages("🔧 Test message from FutureScorer diagnostics", console=1, log=1, telegram=1)
            print("[DIAGNOSTIC] Test message sent successfully")
        except Exception as e:
            print(f"[DIAGNOSTIC] Error sending test message: {e}")
    else:
        print("[DIAGNOSTIC] Missing Telegram credentials")

# ——— Configuración de Telegram ———
try:
    _cfg = configManager.config
    _telegramToken = _cfg.get('telegramToken')
    _telegramChatId = _cfg.get('telegramChatId')
    _telegramPlotsToken = _cfg.get('telegramPlotsToken', _telegramToken)
except Exception as e:
    print(f"Error loading config: {e}")  # Use print to avoid circular reference
    _telegramToken = None
    _telegramChatId = None
    _telegramPlotsToken = None



# ——— Configuración de logs CSV ———
tz_madrid = ZoneInfo("Europe/Madrid")
def getLogCsvPath():
    now = datetime.now(tz_madrid)
    year_month = now.strftime("%Y_%m")
    day = now.strftime("%d%m%Y")
    folder = os.path.join(logsFolder, year_month)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{day}.csv")

def ensureCsvHeader(path):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        with open(path, 'a', encoding='utf-8-sig') as f:
            f.write("fecha,hora,funcion,par,mensaje\n")








def sendTelegramMessage(text=None, plotPaths=None, caption=None, token=None, chatId=None):
    """
    Unified function to send text or photo messages via Telegram.
    If plotPaths is provided, sends images; otherwise sends text.
    Allows custom token and chatId per message.
    """
    token = token or _telegramToken
    chatId = chatId or _telegramChatId
    if not token or not chatId:
        messages("Telegram credentials missing; skipping Telegram send.", console=1, log=1, telegram=0)
        return
    if plotPaths:
        apiUrl = f"https://api.telegram.org/bot{token}/sendPhoto"
        successful_sends = []
        for path in plotPaths:
            norm_path = path.replace('\\', '/').replace('//', '/').replace("_USDT", "")
            # Verificar que el archivo existe antes de enviarlo
            if not os.path.exists(norm_path):
                messages(f"Plot file not found, skipping: {norm_path}", console=1, log=1, telegram=0)
                continue
            try:
                with open(norm_path, 'rb') as img:
                    files = {'photo': img}
                    data = {
                        'chat_id': chatId,
                        'parse_mode': 'HTML'
                    }
                    if caption:
                        data['caption'] = caption
                    resp = requests.post(apiUrl, files=files, data=data)
                    if resp.status_code != 200:
                        messages(f"Error sending photo {norm_path}: {resp.text}", console=1, log=1, telegram=0)
                    else:
                        successful_sends.append(norm_path)
            except Exception as e:
                messages(f"Exception sending photo {norm_path}: {e}", console=1, log=1, telegram=0)
        if successful_sends:
            messages(f"Plots sent successfully: {len(successful_sends)} files", console=0, log=1, telegram=0)
    elif text:
        apiUrl = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            'chat_id': chatId,
            'text': text,
            'parse_mode': 'HTML'
        }
        try:
            resp = requests.post(apiUrl, data=data)
            if resp.status_code != 200:
                messages(f"Error sending text to Telegram: {resp.text}", console=1, log=1, telegram=0)
        except Exception as e:
            messages(f"Exception sending text to Telegram: {e}", console=1, log=1, telegram=0)









def sendPlotsByTelegram(plotPaths, caption=None):
    """
    Wrapper to send plots using the plots token.
    """
    sendTelegramMessage(plotPaths=plotPaths, caption=caption, token=_telegramPlotsToken, chatId=_telegramChatId)








def messages(text, console=1, log=1, telegram=0, caption=None, pair=None):
    """
    Centraliza la emisión de mensajes:
      • console=1 → print con timestamp local (Madrid dd/mm/yyyy hh:mm:ss)
      • log=1     → logger.info(text)
      • telegram=1→ texto o fotos según el tipo de "text"
    """
    if console:
        ts = datetime.now(tz_madrid).strftime("%d/%m/%Y %H:%M:%S")
        print(f"{ts} | {text}")
    if log:
        now = datetime.now(tz_madrid)
        fecha = now.strftime("%d/%m/%Y")
        hora = now.strftime("%H:%M:%S")
        # Obtener nombre de la función llamadora
        stack = inspect.stack()
        funcion = stack[1].function if len(stack) > 1 else "main"
        # Usar el argumento pair si se pasa, si no intentar buscarlo en el scope local
        par = pair
        if par is None:
            # Buscar en el frame llamador
            caller_locals = stack[1].frame.f_locals
            if 'pair' in caller_locals:
                par = caller_locals['pair']
            elif 'symbol' in caller_locals:
                par = caller_locals['symbol']
            else:
                par = ""
        # Limpiar comas del mensaje para no romper el CSV
        msg_clean = str(text).replace(',', ';')
        funcion_clean = funcion.replace(',', ';')
        par_clean = str(par).replace(',', ';') if par else ""
        logline = f"{fecha},{hora},{funcion_clean},{par_clean},{msg_clean}\n"
        log_path = getLogCsvPath()
        ensureCsvHeader(log_path)
        with open(log_path, 'a', encoding='utf-8-sig') as f:
            f.write(logline)
    if telegram:
        '''
        0: no envía nada por Telegram
        1: usa el bot de texto (infoalertsbot) para texto o imágenes
        2: usa el bot de gráficos (graphbot) para texto o imágenes
        3: usa el bot de gráficos solo para texto
        '''
        if telegram == 1:
            if isinstance(text, list):
                sendTelegramMessage(plotPaths=text, caption=caption, token=_telegramToken, chatId=_telegramChatId)
            else:
                sendTelegramMessage(text=text, token=_telegramToken, chatId=_telegramChatId)
        elif telegram == 2:
            # Usar bot de gráficos para plots o texto
            if isinstance(text, list):
                sendTelegramMessage(plotPaths=text, caption=caption, token=_telegramPlotsToken, chatId=_telegramChatId)
            else:
                sendTelegramMessage(text=text, token=_telegramPlotsToken, chatId=_telegramChatId)
        elif telegram == 3:
            # Solo texto, usando bot de gráficos
            sendTelegramMessage(text=text, token=_telegramPlotsToken, chatId=_telegramChatId)
        # telegram==0: no enviar nada por Telegram
