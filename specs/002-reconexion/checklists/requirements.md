# Checklist de calidad de la especificación: Reconexión de la transcripción

**Propósito**: validar que la especificación está completa y tiene calidad antes de planificar
**Creado**: 2026-10-02
**Feature**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Sin detalles de implementación (lenguajes, frameworks, APIs)
- [x] Centrada en el valor para el usuario y el negocio
- [x] Escrita para personas no técnicas
- [x] Todas las secciones obligatorias completas

## Completitud de los requisitos

- [x] No quedan marcadores [NEEDS CLARIFICATION]
- [x] Los requisitos son verificables y no ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito no dependen de la tecnología
- [x] Todos los escenarios de aceptación están definidos
- [x] Los casos borde están identificados
- [x] El alcance está claramente acotado
- [x] Dependencias y supuestos identificados

## Preparación de la feature

- [x] Todos los requisitos funcionales tienen criterios de aceptación claros
- [x] Los escenarios de usuario cubren los flujos principales
- [x] La feature cumple los resultados medibles definidos en los criterios de éxito
- [x] No se filtran detalles de implementación en la especificación

## Notas

- Se nombran `SubtitleEvent` (`sequence`, `segment_id`, `run_id`, `start_ms`, `revision`), `SessionStatus`
  (`reconnecting`, `reconnects`, `last_error`) y `/api/status` porque son interfaces del producto ya
  definidas en `docs/architecture.md` §7 y pedidas por el usuario, no decisiones de implementación. La
  spec lo aclara al inicio. Tras una ronda de revisión de QA se nombran también variables de entorno
  nuevas (`RECONNECT_MAX_ATTEMPTS`, `RECONNECT_BACKOFF_INITIAL_MS`, `RECONNECT_BACKOFF_MAX_MS`,
  `RECONNECT_ATTEMPT_TIMEOUT_S`, `LIVE_SESSION_MAX_S`) con sus rangos y valores por defecto: el usuario
  pidió fijarlos en la spec en lugar de dejarlos para el plan, siguiendo el patrón ya usado en el MVP
  (`docs/architecture.md` §7.7) de no dejar valores sin nombre ni default documentado. No se nombran el
  SDK ni mensajes del protocolo Live: quedan para el plan.
- "Hueco de reconexión" se define en Entidades clave y Supuestos para que CE-002 sea medible; la frase
  abierta descartada se mide aparte (CE-003, CE-009). CE-002 distingue, por pedido de QA, el hueco de una
  reconexión exitosa al primer intento (límite de 2 s) del hueco de una reconexión con reintentos (sin
  límite exigido, solo registro en logs).
- RF-014 (antes RF-012 en el primer borrador; la frase descartada se publica como final vacío y no queda
  en pantalla como "en curso") surge de revisar el MVP: hoy la vista de audiencia conserva el parcial de
  un `segment_id` que nunca recibe final. La ronda de QA definió el final vacío con `revision` mayor que
  la del último parcial y mismo `start_ms`, y lo excluyó explícitamente de RF-048 del MVP (últimas
  finales en memoria), del historial y de la exportación, para que no aparezca donde solo se esperan
  frases con texto. No cambia el contrato `SubtitleEvent`.
- RF-008 fija que el corte es el instante en que se detecta el cierre, no cuando termina de procesarse:
  evita ambigüedad en qué resultados de la conexión vieja se ignoran y en qué momento exacto se mide el
  hueco de CE-002.
- Puntos que ya estaban decididos con un valor razonable y la ronda de QA confirmó o precisó: el error
  por agotar intentos es final hasta reiniciar el worker; el contador de reconexiones no se reinicia con
  las vueltas del loop; la primera conexión al arrancar queda fuera de alcance; y ahora además los
  valores y límites de cada variable de reconexión, la prioridad del fin de la fuente sobre un error de
  reconexión (RF-022), y los nombres de los eventos de log que debe emitir el sistema (RF-020).
- Validación hecha en 2 iteraciones (borrador inicial + ronda de revisión de QA); sin pendientes que
  bloqueen `/speckit-clarify` o `/speckit-plan`.
