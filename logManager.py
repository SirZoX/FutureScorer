
import os
import json
import requests
import inspect
from datetime import datetime
from zoneinfo import ZoneInfo
from gvars import configFile, logsFolder
from connector import loadConfig

# ——— Configuración de Telegram ———



# with open(configFile, encoding='utf-8') as f:
#     _cfg = json.load(f)
# _telegramToken = _cfg.get('telegramTextToken')
# _telegramChatId = _cfg.get('telegramChatId')
# _telegramPlotsToken = _cfg.get('telegramPlotsToken', _telegramToken)
_cfg = loadConfig()
_telegramToken = _cfg.get('telegramToken')
_telegramChatId = _cfg.get('telegramChatId')
_telegramPlotsToken = _cfg.get('telegramPlotsToken', _telegramToken)



# ——— Configuración de logs CSV ———
tz_madrid = ZoneInfo("Europe/Madrid")
def get_log_csv_path():
    now = datetime.now(tz_madrid)
    year_month = now.strftime("%Y_%m")
    day = now.strftime("%d%m%Y")
    folder = os.path.join(logsFolder, year_month)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{day}.csv")

def ensure_csv_header(path):
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
        print(f"[DEBUG][sendTelegramMessage] plotPaths recibidos: {plotPaths}")
        apiUrl = f"https://api.telegram.org/bot{token}/sendPhoto"
        for path in plotPaths:
            norm_path = path.replace('\\', '/').replace('//', '/')
            print(f"[DEBUG][sendTelegramMessage] norm_path usado: {norm_path}")
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
            except Exception as e:
                messages(f"Exception sending photo {norm_path}: {e}", console=1, log=1, telegram=0)
        print(f"[DEBUG][sendTelegramMessage] Plots enviados: {plotPaths}")
        messages(f"Plots sent: {plotPaths}", console=0, log=1, telegram=0)
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
        log_path = get_log_csv_path()
        ensure_csv_header(log_path)
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
