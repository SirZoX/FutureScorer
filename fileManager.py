
import glob
import os
import json
import pandas as pd
from zoneinfo import ZoneInfo
from datetime import datetime
import gvars
from logManager import messages





def clearLogFile(log_path):
    """
    Vacía el fichero de log indicado, dejándolo a 0 líneas.
    """
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            pass
        messages(f"Log file '{log_path}' cleared.", console=0, log=1, telegram=0)
    except Exception as e:
        messages(f"[ERROR] Could not clear log file '{log_path}': {e}", console=1, log=1, telegram=0)




# Helper functions
def ensureDirectories():
    for folder in [
        gvars.jsonFolder, gvars.csvFolder, gvars.plotsFolder, gvars.logsFolder
    ]:
        os.makedirs(folder, exist_ok=True)





def deleteOldFiles(json, csv, plots):

    folderList = []
    folderList.append(gvars.jsonFolder) if json else None
    folderList.append(gvars.csvFolder) if csv else None
    folderList.append(gvars.plotsFolder) if plots else None
    
    for folder in folderList:
        fileList = glob.glob(os.path.join(folder, '**', '*'), recursive=True)
        for filePath in fileList:
            if os.path.isfile(filePath):
                os.remove(filePath)








def saveJson(data, filename):
    path = gvars.jsonFolder + f"/{filename}"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, default=str, indent=2)
    return path







def saveCsv(data, pair, tf, lim):
    safePair = pair.replace('/', '_')
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    nowTag = now.strftime("%Y-%m-%d %H-%M-%S")
    filename = gvars.csvFolder + f"/{safePair}_{tf}_{lim}_{nowTag}.csv"
    df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.to_csv(filename, index=False)
    return filename