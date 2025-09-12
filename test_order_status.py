#!/usr/bin/env python3
"""
Script interactivo para verificar el estado de órdenes en BingX
"""

import sys
from connector import bingxConnector

def getUserInput():
    """
    Solicita al usuario los datos necesarios de forma interactiva
    """
    print("=" * 60)
    print("VERIFICADOR DE ESTADO DE ÓRDENES - BingX")
    print("=" * 60)
    
    # Solicitar modo
    while True:
        print("\nSelecciona el modo:")
        print("1) Modo TEST (Sandbox)")
        print("2) Modo REAL (Producción)")
        mode = input("\nIngresa tu opción (1 o 2): ").strip()
        
        if mode == "1":
            isSandboxMode = True
            print("✅ Modo TEST seleccionado")
            break
        elif mode == "2":
            isSandboxMode = False
            print("✅ Modo REAL seleccionado")
            break
        else:
            print("❌ Opción inválida. Ingresa 1 o 2.")
    
    # Solicitar ID de orden
    while True:
        orderId = input("\nIngresa el ID de la orden: ").strip()
        if orderId:
            break
        else:
            print("❌ El ID de orden no puede estar vacío.")
    
    # Solicitar par (opcional)
    print("\nIngresa el par (opcional, presiona Enter para omitir):")
    print("Ejemplos: BTC, ETH, WIF, BONK, SUI")
    pair = input("Par: ").strip().upper()
    
    # Construir symbol si se proporcionó el par
    symbol = None
    if pair:
        # Formato estándar para futuros: PAR/USDT:USDT
        symbol = f"{pair}/USDT:USDT"
        print(f"✅ Symbol construido: {symbol}")
    else:
        print("✅ Sin symbol especificado")
    
    return isSandboxMode, orderId, symbol, pair

def testOrderStatus(isSandboxMode, orderId, symbol, pair):
    """
    Prueba el estado de la orden con los parámetros proporcionados
    """
    try:
        print(f"\n{'='*60}")
        print(f"CONECTANDO A BINGX...")
        print(f"Modo: {'SANDBOX' if isSandboxMode else 'PRODUCCIÓN'}")
        exchange = bingxConnector(isSandbox=isSandboxMode)
        print(f"✅ Conectado exitosamente")
        
        print(f"\n{'='*60}")
        print(f"VERIFICANDO ESTADO DE ORDEN:")
        print(f"  Order ID: {orderId}")
        print(f"  Pair: {pair if pair else 'No especificado'}")
        print(f"  Symbol: {symbol if symbol else 'No especificado'}")
        print(f"{'='*60}")
        
        # Método 1: fetchOrderStatus
        print(f"\n🔍 Método 1: fetchOrderStatus")
        try:
            if symbol:
                result1 = exchange.fetchOrderStatus(orderId, symbol)
            else:
                result1 = exchange.fetchOrderStatus(orderId)
                
            print(f"✅ fetchOrderStatus ÉXITO:")
            print(f"   Estado: {result1}")
            
        except Exception as e1:
            print(f"❌ fetchOrderStatus FALLÓ:")
            print(f"   Error: {str(e1)}")
            result1 = None
        
        # Método 2: fetch_order
        print(f"\n🔍 Método 2: fetch_order")
        try:
            if symbol:
                result2 = exchange.fetch_order(orderId, symbol)
            else:
                result2 = exchange.fetch_order(orderId)
                
            print(f"✅ fetch_order ÉXITO:")
            print(f"   Tipo: {type(result2)}")
            
            if isinstance(result2, dict):
                print(f"\n📋 INFORMACIÓN DE LA ORDEN:")
                importantFields = {
                    'id': 'ID de Orden',
                    'clientOrderId': 'Client Order ID', 
                    'symbol': 'Symbol',
                    'type': 'Tipo',
                    'side': 'Side',
                    'status': 'Estado',
                    'amount': 'Cantidad',
                    'price': 'Precio',
                    'cost': 'Costo',
                    'filled': 'Ejecutado',
                    'remaining': 'Restante',
                    'average': 'Precio Promedio',
                    'stopPrice': 'Stop Price',
                    'triggerPrice': 'Trigger Price',
                    'takeProfitPrice': 'Take Profit',
                    'stopLossPrice': 'Stop Loss',
                    'timestamp': 'Timestamp',
                    'datetime': 'Fecha/Hora'
                }
                
                for field, description in importantFields.items():
                    if field in result2 and result2[field] is not None:
                        print(f"   {description}: {result2[field]}")
                        
                print(f"\n🔍 TODOS LOS CAMPOS:")
                for key, value in result2.items():
                    print(f"   {key}: {value}")
            else:
                print(f"   Resultado: {result2}")
                
        except Exception as e2:
            print(f"❌ fetch_order FALLÓ:")
            print(f"   Error: {str(e2)}")
            result2 = None
        
        # Método 3: fetchOrders (todas las órdenes del symbol)
        if symbol:
            print(f"\n� Método 3: fetchOrders (todas las órdenes de {symbol})")
            try:
                result3 = exchange.fetchOrders(symbol=symbol, limit=50)
                print(f"✅ fetchOrders ÉXITO:")
                print(f"   Total órdenes encontradas: {len(result3) if result3 else 0}")
                
                if result3:
                    # Buscar nuestra orden específica
                    targetOrder = None
                    for order in result3:
                        if str(order.get('id')) == str(orderId):
                            targetOrder = order
                            break
                    
                    if targetOrder:
                        print(f"   🎯 ORDEN ENCONTRADA en la lista:")
                        print(f"      Estado: {targetOrder.get('status')}")
                        print(f"      Side: {targetOrder.get('side')}")
                        print(f"      Cantidad: {targetOrder.get('amount')}")
                        print(f"      Precio: {targetOrder.get('price')}")
                        print(f"      Ejecutado: {targetOrder.get('filled')}")
                    else:
                        print(f"   ⚠️  Orden {orderId} NO encontrada en la lista de órdenes")
                        
            except Exception as e3:
                print(f"❌ fetchOrders FALLÓ:")
                print(f"   Error: {str(e3)}")
        
        return result1, result2
        
    except Exception as e:
        print(f"❌ ERROR DE CONEXIÓN: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def main():
    """
    Función principal interactiva
    """
    try:
        # Obtener datos del usuario
        isSandboxMode, orderId, symbol, pair = getUserInput()
        
        # Ejecutar verificación
        result1, result2 = testOrderStatus(isSandboxMode, orderId, symbol, pair)
        
        # Preguntar si quiere verificar otra orden
        print(f"\n{'='*60}")
        while True:
            continuar = input("¿Quieres verificar otra orden? (s/n): ").strip().lower()
            if continuar in ['s', 'si', 'y', 'yes']:
                print("\n" + "="*60)
                isSandboxMode, orderId, symbol, pair = getUserInput()
                result1, result2 = testOrderStatus(isSandboxMode, orderId, symbol, pair)
                print(f"\n{'='*60}")
            elif continuar in ['n', 'no']:
                print("👋 ¡Hasta luego!")
                break
            else:
                print("❌ Respuesta inválida. Ingresa 's' para sí o 'n' para no.")
        
    except KeyboardInterrupt:
        print("\n\n👋 Script interrumpido por el usuario. ¡Hasta luego!")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")

if __name__ == "__main__":
    main()
