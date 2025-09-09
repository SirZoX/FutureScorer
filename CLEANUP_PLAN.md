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
- [x] Eliminar: cleanClosedPositions() - COMPLETADO
- [x] Eliminar: _checkOrderStatusForClosure() - COMPLETADO
- [x] Eliminar: reconstructMissingPositions() calls - COMPLETADO
- [x] Eliminar: notifiedTracker imports y calls - COMPLETADO
- [x] Simplificar: updatePositions() - COMPLETADO
- [x] Crear: checkOrderStatus() - nueva función simple - COMPLETADO
- [x] Crear: cleanClosedPositions() - nueva versión simple - COMPLETADO

### helpers.py
- [x] Eliminar comandos: sync, cleanup, tracker, cleartracker - COMPLETADO
- [x] Mantener comandos esenciales - COMPLETADO

### bot.py
- [x] Eliminar imports de archivos eliminados - COMPLETADO
- [x] Eliminar positionSyncer scheduling - COMPLETADO
- [x] Agregar nuevo scheduling simple - COMPLETADO

### pairs.py
- [x] Eliminar referencias a tracker o sync - COMPLETADO
- [x] Limpiar lógica innecesaria - COMPLETADO

### Archivos adicionales limpiados:
- [x] initTracker.py - Marcado como obsoleto - COMPLETADO
- [x] apiOptimizer.py - Eliminado sistema de caché - COMPLETADO

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
