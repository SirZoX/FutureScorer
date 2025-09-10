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
            print(f"Contenido completo: {result}")
            
            # Si es un dict, mostrar campos importantes de forma estructurada
            if isinstance(result, dict):
                print(f"\n📋 CAMPOS IMPORTANTES:")
                important_fields = ['id', 'clientOrderId', 'symbol', 'type', 'side', 'status', 
                                   'amount', 'price', 'cost', 'filled', 'remaining', 'average',
                                   'stopPrice', 'triggerPrice', 'takeProfitPrice', 'stopLossPrice',
                                   'timestamp', 'datetime', 'lastTradeTimestamp']
                
                for field in important_fields:
                    if field in result:
                        print(f"  {field}: {result[field]}")
                        
                print(f"\n🔍 TODOS LOS CAMPOS DISPONIBLES:")
                for key, value in result.items():
                    print(f"  {key}: {value}")
            
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
                print(f"Tipo de respuesta: {type(result2)}")
                print(f"Resultado completo: {result2}")
                
                # Si es un dict, mostrar campos importantes
                if isinstance(result2, dict):
                    print(f"\n📋 CAMPOS IMPORTANTES:")
                    important_fields = ['id', 'clientOrderId', 'symbol', 'type', 'side', 'status', 
                                       'amount', 'price', 'cost', 'filled', 'remaining', 'average',
                                       'stopPrice', 'triggerPrice', 'takeProfitPrice', 'stopLossPrice',
                                       'timestamp', 'datetime', 'lastTradeTimestamp']
                    
                    for field in important_fields:
                        if field in result2:
                            print(f"  {field}: {result2[field]}")
                
            except Exception as api_error2:
                print(f"❌ fetch_order también falló:")
                print(f"Error: {str(api_error2)}")
        
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        import traceback
        traceback.print_exc()

def main():
    # Filter out sandbox/test flags from arguments
    realArgs = [arg for arg in sys.argv[1:] if arg not in ['-test', '--sandbox']]
    
    if len(realArgs) < 1:
        print("Uso: python test_order_status.py [-test] <ORDER_ID> [SYMBOL]")
        print("Ejemplos:")
        print("  python test_order_status.py 1965876339668508672")
        print("  python test_order_status.py 1965876339668508672 WIF/USDT:USDT")
        print("  python test_order_status.py -test 1965876339668508672")
        print("  python test_order_status.py -test 1965876339668508672 WIF/USDT:USDT")
        sys.exit(1)
    
    orderId = realArgs[0]
    symbol = realArgs[1] if len(realArgs) > 1 else None
    
    testFetchOrderStatus(orderId, symbol)

if __name__ == "__main__":
    main()
