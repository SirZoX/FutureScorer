#!/usr/bin/env python3
"""
Script para probar fetchOrderStatus con un ID de orden específico
"""

import sys
from connector import bingxConnector

def testFetchOrderStatus(orderId, symbol=None):
    """
    Prueba fetchOrderStatus con un ID de orden específico
    """
    try:
        # Detect sandbox mode
        isSandboxMode = '-test' in sys.argv or '--sandbox' in sys.argv
        
        print(f"Conectando a BingX...")
        print(f"Modo: {'SANDBOX' if isSandboxMode else 'PRODUCCIÓN'}")
        exchange = bingxConnector(isSandbox=isSandboxMode)
        print(f"Conectado exitosamente\n")
        
        print(f"Probando fetchOrderStatus con:")
        print(f"  Order ID: {orderId}")
        print(f"  Symbol: {symbol if symbol else 'No especificado'}")
        print("-" * 50)
        
        try:
            if symbol:
                # Usar symbol si se proporciona
                result = exchange.fetchOrderStatus(orderId, symbol)
            else:
                # Solo con ID
                result = exchange.fetchOrderStatus(orderId)
                
            print(f"✅ ÉXITO - fetchOrderStatus respondió:")
            print(f"Tipo de respuesta: {type(result)}")
            print(f"Contenido: {result}")
            
        except Exception as api_error:
            print(f"❌ ERROR en fetchOrderStatus:")
            print(f"Tipo de error: {type(api_error).__name__}")
            print(f"Mensaje: {str(api_error)}")
            
            # Intentar también con fetch_order para comparar
            print(f"\n🔄 Probando fetch_order para comparar...")
            try:
                if symbol:
                    result2 = exchange.fetch_order(orderId, symbol)
                else:
                    result2 = exchange.fetch_order(orderId)
                    
                print(f"✅ fetch_order funcionó:")
                print(f"Resultado: {result2}")
                
            except Exception as api_error2:
                print(f"❌ fetch_order también falló:")
                print(f"Error: {str(api_error2)}")
        
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        import traceback
        traceback.print_exc()

def main():
    if len(sys.argv) < 2:
        print("Uso: python test_order_status.py <ORDER_ID> [SYMBOL]")
        print("Ejemplos:")
        print("  python test_order_status.py 1965876339668508672")
        print("  python test_order_status.py 1965876339668508672 WIF/USDT:USDT")
        sys.exit(1)
    
    orderId = sys.argv[1]
    symbol = sys.argv[2] if len(sys.argv) > 2 else None
    
    testFetchOrderStatus(orderId, symbol)

if __name__ == "__main__":
    main()
