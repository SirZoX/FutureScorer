from connector import bingxConnector

exchange = bingxConnector()

print('=== Test fetchPositions ===')
try:
    positions = exchange.fetch_positions()
    print(f'Total positions: {len(positions)}')
    open_positions = [p for p in positions if p.get('contracts', 0) > 0]
    print(f'Open positions: {len(open_positions)}')
    
    if open_positions:
        for pos in open_positions:
            print(f"Symbol: {pos.get('symbol')}, Size: {pos.get('contracts')}, Side: {pos.get('side')}")
    else:
        print('No hay posiciones abiertas')
        
except Exception as e:
    print(f'Error fetchPositions: {e}')
