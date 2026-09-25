# Contrato: API del gateway (P0)

Base: `docs/architecture.md` §7.6. El P0 implementa solo estas rutas:

| Método y ruta | P0 | Uso |
| --- | --- | --- |
| `GET /` | Sí | Vista de audiencia (RF-016 a RF-021, RF-044) |
| `GET /api/sessions` | Sí | Escenarios de `sessions.yaml`: `id`, `name`, `title`, `source_language` y `tracks` (`original` + destinos distintos del origen). **No expone `source`** (RF-022) |
| `GET /api/status` | Sí | `SessionStatus` de cada escenario (lo que haya en `status:*`). Si expiró, el escenario sale como `null` |
| `GET /healthz` | Sí | 200 si el gateway responde y Redis contesta `PING`; 503 si no |
| `WS /ws/{session_id}?tracks=original,es` | Sí | Eventos en vivo de las pistas pedidas |
| `GET /overlay.html?session=sala2&track=en&size=42&position=bottom&partials=true` | Sí | Overlay para OBS/vMix (RF-049): fondo transparente, máximo 2 líneas, sin controles. `size` en px (por defecto 42), `position` `bottom` o `top`, `partials` `true` o `false`. Usa el mismo WebSocket y se reconecta cada 2 s |
| `GET /panel.html`, `/api/sessions/{id}/history`, `/runs`, `/export` | No | P1 |

## WebSocket

- Mensajes del servidor, como en §7.6:
  - `{"type": "subtitle", "data": SubtitleEvent}`;
  - `{"type": "ping"}` cada `WS_PING_S`.
- Al conectarse a una o más pistas, el cliente recibe primero las últimas `RECENT_FINALS_N` frases
  finales de la ejecución actual de cada pista pedida, en orden de llegada, como mensajes `subtitle`.
  Después recibe los eventos en vivo. El gateway guarda estas frases solo en su memoria; cada
  instancia nueva comienza sin frases guardadas. Con `RECENT_FINALS_N=0` no envía frases previas.
- Si `session_id` no existe o una pista no es válida para ese escenario, el servidor cierra con el
  código 1008 y un motivo.
- Los clientes no envían mensajes con efecto. Ningún parámetro acepta URLs ni rutas (RF-022).
- Si la cola de salida de un cliente se llena (`WS_CLIENT_QUEUE_MAX`), se descarta el evento más
  antiguo de ese cliente, sin afectar a los demás.
