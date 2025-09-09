# PLAN DE LIMPIEZA Y SIMPLIFICACIÓN - FutureScorer

## OBJETIVO
Eliminar toda la complejidad innecesaria y crear un sistema simple basado en:
1. Campo "status" en JSON de posiciones
2. Verificación periódica de órdenes TP/SL por ID
3. Sistema de notificación simple
4. Limpieza automática de posiciones cerradas

## FASE 1: IDENTIFICACIÓN Y ELIMINACIÓN DE ARCHIVOS INNECESARIOS ✅
- [x] cacheManager.py - ELIMINADO
- [x] notificationManager.py - ELIMINADO  
- [x] notifiedTracker.py - ELIMINADO
- [x] positionMonitor.py - RECREADO con funciones esenciales
- [x] positionSyncer.py - ELIMINADO
- [x] supportDetector.py - CONSERVAR (detecta soportes)
- [x] tradesCleanup.py - ELIMINADO

## FASE 2: LIMPIEZA DE FUNCIONES EN ARCHIVOS PRINCIPALES
### orderManager.py
- [ ] Eliminar: cleanClosedPositions()
- [ ] Eliminar: _checkOrderStatusForClosure()
- [ ] Eliminar: reconstructMissingPositions() calls
- [ ] Eliminar: notifiedTracker imports y calls
- [ ] Simplificar: updatePositions()
- [ ] Crear: checkOrderStatus() - nueva función simple
- [ ] Crear: cleanClosedPositions() - nueva versión simple

### helpers.py
- [ ] Eliminar comandos: sync, cleanup, tracker, cleartracker
- [ ] Mantener comandos esenciales

### bot.py
- [ ] Eliminar imports de archivos eliminados
- [ ] Eliminar positionSyncer scheduling
- [ ] Agregar nuevo scheduling simple

### pairs.py
- [ ] Eliminar referencias a tracker o sync
- [ ] Limpiar lógica innecesaria

## FASE 3: IMPLEMENTACIÓN DEL NUEVO SISTEMA
### Estructura del JSON modificada:
```json
{
  "SYMBOL": {
    ...campos existentes...,
    "status": "open|closed",
    "notification_sent": false
  }
}
```

### Nuevas funciones simples:
1. `checkOrderStatusPeriodically()` - verifica IDs de órdenes
2. `notifyClosedPosition()` - notifica posición cerrada
3. `cleanNotifiedPositions()` - elimina posiciones notificadas y con status = closed

## FASE 4: TESTING Y VALIDACIÓN
- [ ] Verificar que no hay imports rotos
- [ ] Verificar que el bot inicia sin errores
- [ ] Probar apertura de posición
- [ ] Probar verificación de órdenes
- [ ] Probar notificación y limpieza

## PROGRESO ACTUAL
- Iniciando Fase 1: Eliminación de archivos innecesarios
