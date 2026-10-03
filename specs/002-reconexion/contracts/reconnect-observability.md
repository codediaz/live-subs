# Contrato: estado y logs de la reconexión (002)

Base: `docs/architecture.md` §7.2 (`SessionStatus`), §7.6 (`GET /api/status`) y §5 (logs JSON con
`session_id`). La forma de `SessionStatus` no cambia.

## `SessionStatus` en `/api/status`

| Campo | Durante y después de una reconexión |
| --- | --- |
| `state` | `reconnecting` desde el corte hasta que la conexión nueva queda lista, incluidas las esperas entre intentos (RF-017). Vuelve a `live` (RF-018). Pasa a `error` al agotar los intentos (RF-004) o a `stopped` si la fuente terminó durante la reconexión (RF-022) |
| `reconnects` | Reconexiones exitosas desde que el worker arrancó el escenario (RF-018). Las vueltas con loop no lo reinician |
| `errors` | +1 por cada intento fallido (RF-019) |
| `last_error` | Causa del último intento fallido, recortada a 300 caracteres como en el MVP; se conserva tras un éxito (RF-019) |

El estado se ve como mucho un `STATUS_INTERVAL_S` después del cambio (CE-005). Si el worker se detiene
durante una reconexión, la clave expira a los `STATUS_TTL_S` y el escenario nunca aparece `live`.

## Eventos de log

Todos en JSON, con `session_id`, en nivel INFO salvo que se indique otro. Ninguno lleva audio ni texto de
subtítulos (RF-020, principio 14).

| Evento | Nivel | Cuándo | Campos además de `session_id` |
| --- | --- | --- | --- |
| `reconnect_started` | INFO | Al detectar el cierre (RF-008) | `reason` (`closed` o `max_session`), `cause` (tipo y mensaje del cierre, si hubo), `cut_position_ms`, `discarded_open_segment` (bool) |
| `reconnect_attempt_failed` | WARNING | Por cada intento fallido | `attempt`, `cause`, `next_delay_ms` (nulo si no hay otro intento) |
| `reconnect_succeeded` | INFO | Cuando la conexión nueva queda lista | `attempts`, `gap_ms` (RF-010, CE-002), `duration_ms` (corte → lista), `reconnects` (total) |
| `reconnect_abandoned` | ERROR | Al agotar los intentos | `attempts`, `cause` (la del último fallo), `gap_ms` |
| `reconnect_cancelled` | INFO | La fuente terminó durante la reconexión (RF-022) | `attempts`, `gap_ms` |
| `live_go_away` | DEBUG | Si el servidor avisa que va a cerrar (R3) | `time_left` |

Reglas:

- CE-005: al final de una ejecución, `reconnects` en `/api/status` coincide con la cantidad de
  `reconnect_succeeded` del escenario.
- CE-008: con el servicio inaccesible para un escenario, hay exactamente `RECONNECT_MAX_ATTEMPTS`
  eventos `reconnect_attempt_failed`, sus `next_delay_ms` no decrecen, y después aparece un
  `reconnect_abandoned`.
- `cause` viene de la excepción o del código de cierre y no incluye la credencial. Como en el MVP, se
  recorta a 300 caracteres.
