# Quickstart de validación: Reconexión de la transcripción

**Feature**: `002-reconexion` | **Plan**: [plan.md](plan.md)

Escenarios ejecutables que prueban la feature de punta a punta. Los contratos están en
[contracts/](contracts/) y el modelo en [data-model.md](data-model.md); acá solo van los pasos y los
resultados esperados. La base es el quickstart del MVP (`specs/001-subs-mvp/quickstart.md`).

## Requisitos previos

- Los mismos del MVP: Docker con Compose, `.env` con `GEMINI_API_KEY`, `pytest` local
  (`pip install -e ".[dev]"`).
- `redis-cli` (o `docker compose exec redis redis-cli`) y `curl`.
- Para R7: una fuente de ≥ 30 min en `samples/local/` (ignorada por git). Puede ser audio real o el clip
  del repo repetido con ffmpeg sin recodificar (`-stream_loop 13 … -c copy`, unos 31 min).

## R0. Suite y configuración

| Paso | Resultado esperado |
| --- | --- |
| `pytest -q` | Verde, con los tests nuevos del [plan](plan.md#estrategia-de-tests) |
| Arrancar el worker con cada valor inválido de [contracts/env.md](contracts/env.md) (por ejemplo, `RECONNECT_MAX_ATTEMPTS=0`, `RECONNECT_BACKOFF_MAX_MS=200` con inicial 500, `RECONNECT_ATTEMPT_TIMEOUT_S=121`, `LIVE_SESSION_MAX_S=0`) | El worker no arranca (código 2) y `invalid_configuration` nombra la variable (RF-006, RF-007) |

## R1. Reconexiones forzadas con `LIVE_SESSION_MAX_S=60`

**Preparación**: `LIVE_SESSION_MAX_S=60` en `.env`, `docker compose up --build`, con el
`sessions.yaml` del repo (`sala1` y `sala2` con clips de unos 135 s y loop). Cada vuelta tiene 2
reconexiones, a los ~60 s y a los ~120 s. Dejar correr 5 min.

| Observación | Resultado esperado |
| --- | --- |
| Logs del worker (`docker compose logs worker`) | Por escenario y vuelta: 2 `reconnect_started` con `reason=max_session` y 2 `reconnect_succeeded` con `attempts=1` y `gap_ms < 2000` (RF-001, RF-002, CE-002). Ningún `run_failed` |
| `redis-cli PSUBSCRIBE 'subs:sala1:*'` durante una reconexión | El `run_id` no cambia en la vuelta; `sequence` estrictamente creciente; el `segment_id` sigue desde el último (RF-012, CE-004) |
| Mismo canal, si el corte cae a mitad de una frase | Un final de `original` con `text` vacío, `latency_ms` nulo y `revision` mayor que la de su último parcial; ningún evento `es` con ese `segment_id` (RF-013, RF-014) |
| Mismo canal, finales previos al corte | Sus traducciones `es` aparecen aunque la reconexión siga en curso (RF-015, CE-003) |
| `start_ms` de la primera frase después del corte | Mayor o igual que la posición del corte (`cut_position_ms` del log) más el hueco (RF-011) |
| `latency_ms` de los finales posteriores | Dentro de los objetivos de §8 desde la primera frase (RF-016, CE-006) |
| Logs en nivel INFO | Ningún texto de subtítulos en los eventos `reconnect_*` (RF-020) |

## R2. Estado visible

Con R1 corriendo, consultar `curl -s localhost:8000/api/status` una vez por segundo durante una
reconexión.

| Observación | Resultado esperado |
| --- | --- |
| Durante la reconexión | El escenario en `reconnecting` como mucho un `STATUS_INTERVAL_S` después del `reconnect_started` (RF-017, CE-005) |
| Después | `live` como mucho un periodo después del `reconnect_succeeded`, con `reconnects` +1 (RF-018) |
| Tras varias vueltas | `reconnects` igual a la cantidad de `reconnect_succeeded` del escenario en los logs; no vuelve a 0 con el loop (CE-005) |

## R3. Vista de audiencia y overlay

| Paso | Resultado esperado |
| --- | --- |
| `python scripts/replay_events.py` con el caso de reconexión (frase abierta → final vacío → frase nueva con el mismo `run_id`) y la vista abierta | La pantalla no se limpia; el parcial de la frase descartada desaparece al llegar el final vacío; la frase nueva aparece a continuación (CE-009). Lo mismo en `/overlay.html` |
| Con R1 corriendo, mirar `/` en `original` y en `es` durante dos reconexiones | No se limpia la pantalla ni hay que recargar; ninguna frase descartada queda visible como frase en curso (historia 1, CE-009) |
| Abrir una pestaña nueva justo después de un final vacío | Las últimas frases que llegan al conectarse no incluyen el final vacío (RF-014) |

## R4. Aislamiento entre escenarios (harness)

`python scripts/reconnect_check.py isolation` con Redis arriba (`docker compose up redis gateway`). El
escenario A corre con `LIVE_SESSION_MAX_S=60` y el B sin él, en el mismo proceso (R15).

| Observación | Resultado esperado |
| --- | --- |
| Resumen de A | ≥ 2 reconexiones exitosas |
| Resumen de B | 0 eventos de reconexión, 0 bloques descartados, siempre `live`, y ninguna espera entre finales mayor a `MAX_SEGMENT_MS` + 2 s mientras hay voz (RF-021, CE-007) |

## R5. Reintentos y abandono (harness)

`python scripts/reconnect_check.py failure` con `RECONNECT_MAX_ATTEMPTS=3`,
`RECONNECT_BACKOFF_INITIAL_MS=500` y `RECONNECT_BACKOFF_MAX_MS=1000`. A corre con
`LIVE_SESSION_MAX_S=60` para provocar el primer corte; desde ahí abre cada conexión con una credencial
inválida y el servicio real la rechaza (R15).

| Observación | Resultado esperado |
| --- | --- |
| Logs de A | Exactamente 3 `reconnect_attempt_failed` con `next_delay_ms` 500, 1000 y nulo, y después `reconnect_abandoned` (RF-003, RF-004, CE-008) |
| `/api/status` de A | `error` con la causa en `last_error` y `errors` = 3; sigue visible mientras el worker vive (RF-004, RF-019) |
| A tras el abandono | Su `ffmpeg` terminó: no hay más bloques de A |
| B | Sigue `live` y publicando finales (RF-021, CE-008) |

## R6. Fin de la fuente durante la reconexión (harness)

`python scripts/reconnect_check.py source-end`: A sin loop, con un clip que termina mientras A espera
entre intentos (credencial inválida como en R5 y `RECONNECT_BACKOFF_MAX_MS` alto).

| Observación | Resultado esperado |
| --- | --- |
| A sin loop | `reconnect_cancelled` en los logs y estado `stopped`, nunca `error` (RF-022) |
| Variante con loop | Empieza una ejecución nueva (`run_id` nuevo), como en el MVP; nunca `error` (RF-022) |

## R7. Charla de 30 minutos con cierres reales

**Preparación**: `LIVE_SESSION_MAX_S` vacío; `sessions.local.yaml` con un escenario cuya fuente es el
archivo largo de `samples/local/`, **sin loop**, y un `docker-compose.override.yml` que monta
`samples/local/` y apunta `SESSIONS_FILE` a ese archivo (los dos están en `.gitignore`).

| Observación | Resultado esperado |
| --- | --- |
| Toda la charla, una sola ejecución | `run_id` único; ≥ 2 `reconnect_succeeded` por cierres reales (`reason=closed`); 0 `run_failed` ni estado `error` (CE-001) |
| Fin de la fuente | La última frase final de `original` y de cada traducción termina (`end_ms`) a menos de 15 s del fin del audio; estado `stopped` (CE-001) |
| Huecos | Cada reconexión con `attempts=1` tiene `gap_ms < 2000` (CE-002) |
| Eventos de toda la charla (`PSUBSCRIBE` guardado a un archivo) | `sequence` estrictamente creciente, `segment_id` sin repetir entre frases, `start_ms` sin retroceder (CE-004) |
| Latencia | Las frases que siguen a cada reconexión cumplen §8 (CE-006) |

## R8. Worker detenido durante una reconexión

Con R1 corriendo, ejecutar `docker compose stop worker` justo después de un `reconnect_started`.

| Observación | Resultado esperado |
| --- | --- |
| `/api/status` | El escenario nunca vuelve a `live`; la clave expira a los `STATUS_TTL_S` (caso borde de la spec) |

## R9. Clon limpio

Desde un clon nuevo, siguiendo solo el README: `cp .env.example .env`, completar la key y
`docker compose up --build`. El stack arranca con los valores por defecto (sin `LIVE_SESSION_MAX_S`), y
el README menciona que las charlas pueden durar más de 10 minutos y dónde están las variables de
reconexión.
