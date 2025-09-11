import pandas as pd
import json
import os

def updateSelectionLogWithSpecificId():
    """Update selection log with specific ARKM entry ID"""
    
    selectionLogPath = "_files/logs/selectionLog.csv"
    openedPositionsPath = "_files/json/openedPositions.json"
    
    # Load opened positions
    with open(openedPositionsPath, 'r') as f:
        openedPositions = json.load(f)
    
    # Find ARKM position
    arkmPosition = openedPositions.get("ARKM/USDT:USDT")
    if not arkmPosition:
        print("ARKM position not found in openedPositions.json")
        return
    
    print(f"Found ARKM position:")
    print(f"  Timestamp: {arkmPosition['timestamp']}")
    print(f"  TP Order ID: {arkmPosition['tpOrderId1']}")
    print(f"  SL Order ID: {arkmPosition['slOrderId1']}")
    print(f"  Side: {arkmPosition['side']}")
    
    # Read selection log
    df = pd.read_csv(selectionLogPath, sep=';')
    
    # Look for the specific ID we found: 55c5179b
    targetId = "55c5179b"
    mask = df['id'] == targetId
    
    if not mask.any():
        print(f"Entry with ID {targetId} not found in selection log")
        return
    
    print(f"Found entry with ID {targetId}")
    
    # Update the IDs
    tpOrderId = arkmPosition['tpOrderId1']
    slOrderId = arkmPosition['slOrderId1']
    
    # Update tp_order_id and sl_order_id columns
    df.loc[mask, 'tp_order_id'] = tpOrderId
    df.loc[mask, 'sl_order_id'] = slOrderId
    
    print(f"Updating entry with:")
    print(f"  TP Order ID: {tpOrderId}")
    print(f"  SL Order ID: {slOrderId}")
    
    # Save the updated dataframe
    df.to_csv(selectionLogPath, sep=';', index=False)
    print(f"Selection log updated successfully!")
    
    # Verify the update
    df_verify = pd.read_csv(selectionLogPath, sep=';')
    updated_row = df_verify[df_verify['id'] == targetId]
    
    if not updated_row.empty:
        print(f"Verification - Updated row:")
        print(f"  ID: {updated_row.iloc[0]['id']}")
        print(f"  Pair: {updated_row.iloc[0]['pair']}")
        print(f"  Side: {updated_row.iloc[0]['side']}")
        print(f"  TP Order ID: {updated_row.iloc[0]['tp_order_id']}")
        print(f"  SL Order ID: {updated_row.iloc[0]['sl_order_id']}")

if __name__ == "__main__":
    updateSelectionLogWithSpecificId()
