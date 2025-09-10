#!/usr/bin/env python3
"""
Script para probar fetch_open_orders con parámetros específicos
"""

import sys
from connector import bingxConnector

def testFetchOpenOrders(symbol=None, since=None, limit=None):
    """
    Prueba fetch_open_orders con parámetros específicos
    """
    try:
        # Detect sandbox mode
        isSandboxMode = '-test' in sys.argv or '--sandbox' in sys.argv
        
        print(f"Conectando a BingX...")
        print(f"Modo: {'SANDBOX' if isSandboxMode else 'PRODUCCIÓN'}")
        exchange = bingxConnector(isSandbox=isSandboxMode)
        print(f"Conectado exitosamente\n")
        
        print(f"Probando fetch_open_orders con:")
        print(f"  Symbol: {symbol if symbol else 'None (todas las órdenes)'}")
        print(f"  Since: {since if since else 'None (sin filtro de fecha)'}")
        print(f"  Limit: {limit if limit else 'None (sin límite)'}")
        print("-" * 50)
        
        try:
            # Preparar parámetros
            params = {}
            if since:
                params['since'] = since
            if limit:
                params['limit'] = limit
            
            # Llamar al método
            if symbol:
                if params:
                    result = exchange.fetch_open_orders(symbol, **params)
                else:
                    result = exchange.fetch_open_orders(symbol)
            else:
                if params:
                    result = exchange.fetch_open_orders(**params)
                else:
                    result = exchange.fetch_open_orders()
                
            print(f"✅ ÉXITO - fetch_open_orders respondió:")
            print(f"Tipo de respuesta: {type(result)}")
            print(f"Número de órdenes: {len(result) if isinstance(result, list) else 'No es lista'}")
            
            if isinstance(result, list) and len(result) > 0:
                print(f"\nPrimera orden (ejemplo):")
                first_order = result[0]
                print(f"  ID: {first_order.get('id', 'N/A')}")
                print(f"  Symbol: {first_order.get('symbol', 'N/A')}")
                print(f"  Type: {first_order.get('type', 'N/A')}")
                print(f"  Side: {first_order.get('side', 'N/A')}")
                print(f"  Status: {first_order.get('status', 'N/A')}")
                print(f"  Amount: {first_order.get('amount', 'N/A')}")
                print(f"  Price: {first_order.get('price', 'N/A')}")
                print(f"  Client Order ID: {first_order.get('clientOrderId', 'N/A')}")
                
                if len(result) > 1:
                    print(f"\nTotal de {len(result)} órdenes encontradas")
                    
                    # Buscar órdenes con IDs personalizados
                    custom_orders = [o for o in result if o.get('clientOrderId', '').startswith('FUTSCO_')]
                    if custom_orders:
                        print(f"\n🎯 Órdenes con IDs personalizados encontradas: {len(custom_orders)}")
                        for order in custom_orders:
                            print(f"  - {order.get('clientOrderId')} ({order.get('symbol')}) - Status: {order.get('status')}")
                    else:
                        print(f"\n⚠️  No se encontraron órdenes con IDs personalizados (FUTSCO_)")
                        
            elif isinstance(result, list) and len(result) == 0:
                print(f"\n📭 No hay órdenes abiertas")
            else:
                print(f"\nContenido completo: {result}")
                
        except Exception as api_error:
            print(f"❌ ERROR en fetch_open_orders:")
            print(f"Tipo de error: {type(api_error).__name__}")
            print(f"Mensaje: {str(api_error)}")
        
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("=== TEST DE fetch_open_orders ===")
    print("Este método puede aceptar los siguientes parámetros:")
    print("  - symbol: Par específico (ej: WIF/USDT:USDT) o None para todas")
    print("  - since: Timestamp desde cuando buscar (opcional)")
    print("  - limit: Número máximo de órdenes (opcional)")
    print()
    
    # Obtener parámetros del usuario
    if len(sys.argv) > 1:
        # Usar parámetros de línea de comandos
        symbol = sys.argv[1] if sys.argv[1].lower() != 'none' else None
        since = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].lower() != 'none' else None
        limit = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].lower() != 'none' else None
    else:
        # Modo interactivo
        print("Introduce los parámetros (presiona Enter para None):")
        
        symbol_input = input("Symbol (ej: WIF/USDT:USDT): ").strip()
        symbol = symbol_input if symbol_input else None
        
        since_input = input("Since timestamp (ej: 1757536000): ").strip()
        since = int(since_input) if since_input else None
        
        limit_input = input("Limit (ej: 50): ").strip()
        limit = int(limit_input) if limit_input else None
        
        print()
    
    testFetchOpenOrders(symbol, since, limit)

if __name__ == "__main__":
    main()
