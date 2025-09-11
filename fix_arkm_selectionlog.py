#!/usr/bin/env python3
"""
Script to manually update selectionLog with real order IDs for ARKM
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pairs import updateSelectionLogWithRealOrderIds

# Simulate the record data for ARKM position
record = {
    "tpOrderId1": "1966256037007286272",
    "slOrderId1": "1966256038022307840"
}

# Update the selectionLog for ARKM
print("Updating selectionLog for ARKM/USDT:USDT...")
updateSelectionLogWithRealOrderIds(None, "ARKM/USDT:USDT", record)
print("Done!")
