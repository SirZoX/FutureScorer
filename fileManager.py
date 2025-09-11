
import glob
import os
import json
import pandas as pd
from zoneinfo import ZoneInfo
from datetime import datetime
import gvars
from logManager import messages # log_info, log_error





def clearLogFile(log_path):
    """
    Vacía el fichero de log indicado, dejándolo a 0 líneas.
    """
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            pass
        messages(f"Log file '{log_path}' cleared.", console=0, log=1, telegram=0)
    except Exception as e:
        messages(f"Could not clear log file '{log_path}': {e}", console=1, log=1, telegram=0)




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
                try:
                    os.remove(filePath)
                except PermissionError:
                    # File is in use by another process, skip it
                    from logManager import messages
                    messages(f"[FILE-MANAGER] Skipping file in use: {os.path.basename(filePath)}", console=0, log=1, telegram=0)
                    continue
                except Exception as e:
                    # Other file errors, log but continue
                    from logManager import messages
                    messages(f"[FILE-MANAGER] Error deleting {os.path.basename(filePath)}: {e}", console=0, log=1, telegram=0)
                    continue








def saveJson(data, filename):
    path = gvars.jsonFolder + f"/{filename}"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, default=str, indent=2)
    return path







def saveCsv(data, pair, tf, lim):
    # English comment: Remove everything after the first '/' and any ':', keep only the base symbol
    basePair = pair.split('/')[0] if '/' in pair else pair
    basePair = basePair.replace(':', '')
    filename = gvars.csvFolder + f"/{basePair}_{tf}_{lim}.csv"
    df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.to_csv(filename, index=False)
    return filename
