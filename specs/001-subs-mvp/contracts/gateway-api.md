# Contrato: API del gateway (P0)

Base: `docs/architecture.md` §7.6. El P0 implementa solo estas rutas:

| Método y ruta | P0 | Uso |
| --- | --- | --- |
| `GET /` | Sí | Vista de audiencia (RF-016 a RF-021, RF-044) |
| `GET /api/sessions` | Sí | Escenarios de `sessions.yaml`: `id`, `name`, `title`, `source_language` y `tracks` (`original` + destinos distintos del origen). **No expone `source`** (RF-022) |
| `GET /api/status` | Sí | `SessionStatus` de cada escenario (lo que haya en `status:*`). Si expiró, el escenario sale como `null` |
| `GET /healthz` | Sí | 200 si el gateway responde y Redis contesta `PING`; 503 si no |
| `WS /ws/{session_id}?tracks=original,es` | Sí | Eventos en vivo de las pistas pedidas |
| `GET /overlay.html`, `/panel.html`, `/api/sessions/{id}/history`, `/runs`, `/export` | No | P1 |

## WebSocket

- Mensajes del servidor, como en §7.6:
  - `{"type": "subtitle", "data": SubtitleEvent}`;
  - `{"type": "ping"}` cada `WS_PING_S`.
- Si `session_id` no existe o una pista no es válida para ese escenario, el servidor cierra con el
  código 1008 y un motivo.
- Los clientes no envían mensajes con efecto. Ningún parámetro acepta URLs ni rutas (RF-022).
- Si la cola de salida de un cliente se llena (`WS_CLIENT_QUEUE_MAX`), se descarta el evento más
  antiguo de ese cliente, sin afectar a los demás.
