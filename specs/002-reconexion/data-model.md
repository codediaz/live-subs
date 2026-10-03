# Modelo de datos: Reconexión de la transcripción

**Feature**: `002-reconexion` | **Plan**: [plan.md](plan.md) | **Investigación**: [research.md](research.md)

Los contratos base están en `docs/architecture.md` §7 y el modelo del MVP en
`specs/001-subs-mvp/data-model.md`. Acá solo se agrega lo que cambia; lo nuevo va marcado con **Δ**.
`SubtitleEvent` y `SessionStatus` **no cambian** de forma: `schema_version` sigue en 1.

## 1. Configuración del worker (Δ)

Variables, valores por defecto y rangos en [contracts/env.md](contracts/env.md). Las lee
`WorkerSettings` (§7.7) y se validan al arrancar (RF-006, RF-007; R13).

| Grupo | Campos | Reglas |
| --- | --- | --- |
| Reintentos | `reconnect_max_attempts`, `reconnect_backoff_initial_ms`, `reconnect_backoff_max_ms`, `reconnect_attempt_timeout_s` | Rangos de RF-006 y RF-007; `backoff_max ≥ backoff_initial`, con un error que nombra `RECONNECT_BACKOFF_MAX_MS` |
| Prueba | `live_session_max_s` | Vacío o no definido = sin cierre a propósito; con valor, entero ≥ 1 (RF-023, R13) |

## 2. Política de reintento (Δ, funciones puras)

Entradas y salidas de las dos reglas de R2. No guardan estado.

| Regla | Entradas | Salida |
| --- | --- | --- |
| Espera antes del intento | número de intento `n` (≥ 1), espera inicial, espera máxima | 0 si `n = 1`; si no, `min(inicial × 2^(n−2), máxima)` |
| Decisión tras un fallo | fallos consecutivos de esta reconexión, intentos máximos | `reintentar` si fallos < máximo; si no, `abandonar` |

Propiedades: la secuencia de esperas es no decreciente y nunca supera la máxima (CE-008). Con
`RECONNECT_MAX_ATTEMPTS = 1` se abandona tras el primer fallo.

## 3. Conexión de transcripción (Δ)

Una por cada apertura dentro de una ejecución. No se publica; vive en memoria del Transcriptor.

```text
abriendo ──(connect() entrega la sesión)──► lista ──(cierre detectado)──► cortada
    │                                          │
    └─(error o RECONNECT_ATTEMPT_TIMEOUT_S)──► fallida     (temporizador LIVE_SESSION_MAX_S → cortada)
```

| Atributo | Descripción |
| --- | --- |
| motivo del corte | `closed` (el servidor cerró o hubo una falla) o `max_session` (RF-023) |
| marca de corte | Se pone sin ceder el control al detectar el cierre; desde ahí se ignora todo resultado de esta conexión (RF-008, R4) |
| hora y posición del corte | Hora real y posición del reloj de audio en el instante de la marca |

## 4. Reconexión (Δ)

Va del corte de una conexión a la siguiente conexión lista, dentro de la misma ejecución.

| Atributo | Descripción |
| --- | --- |
| inicio | Hora y posición del corte (§3) |
| intentos | Contador de intentos de esta reconexión; vuelve a cero con cada éxito (RF-005) |
| hueco (`gap_ms`) | Suma de los bloques descartados × `AUDIO_CHUNK_MS`: los que había en la cola al cortar más los que llegaron hasta la conexión lista (RF-010, R5) |
| final | `exitosa` (conexión lista), `abandonada` (se agotaron los intentos) o `fuente terminada` (RF-022) |

Reglas:

- El primer intento no espera (RF-002). Antes de los siguientes se espera según §2 y cada intento tiene
  como límite `RECONNECT_ATTEMPT_TIMEOUT_S` (RF-007).
- Cada intento y cada espera compiten con el fin de la fuente; si la fuente termina primero, la
  reconexión termina como `fuente terminada` y nunca pasa a `error` (RF-022).
- Un cierre que llega cuando la fuente ya terminó y la cola está vacía no inicia una reconexión.
- Una conexión que se corta apenas lista es una reconexión exitosa seguida de otra reconexión; un cierre
  antes de quedar lista es un intento fallido (casos borde).

## 5. Reloj de audio (Δ)

Base: `specs/001-subs-mvp/data-model.md` §4.

| Operación | Efecto |
| --- | --- |
| registrar bloque (MVP) | Agrega un bloque con posición, hora de envío y marca de voz; la posición avanza `AUDIO_CHUNK_MS` |
| **Δ** saltar bloque | Avanza la posición `AUDIO_CHUNK_MS` sin agregar bloque: sin hora de envío ni marca de voz (RF-011, R6) |

Consecuencias: las posiciones saltadas no tienen hora de envío, así que no participan en la latencia
(RF-016) ni en la detección de voz o silencio.

## 6. Seguimiento de frases (`SegmentTracker`) (Δ)

Base: `specs/001-subs-mvp/data-model.md` §5. Se agrega un evento de entrada, el corte de conexión, que
recibe la hora y la posición del corte (R7).

| Estado al cortar | Salida | Efecto en la numeración |
| --- | --- | --- |
| Frase abierta (con parciales, sin final; incluye un corte forzado sin final todavía) | Final vacío (§7) | `segment_id` avanza; `sequence` toma el siguiente valor |
| Sin frase abierta | Nada | Sin cambios |

En los dos casos, el inicio de la próxima frase se ancla en el corte: empieza en el primer bloque con voz
**enviado después** del corte. Así `start_ms` nunca queda antes del hueco y la posición no retrocede
(CE-004). Los parciales siguientes abren una frase nueva con `revision` desde 0. `run_id` no cambia
(RF-012).

## 7. Final vacío (Δ, uso del contrato existente)

Es un `SubtitleEvent` normal de §7.1, con estos valores (RF-014):

| Campo | Valor |
| --- | --- |
| `kind` / `track` | `original` / `original` |
| `is_final` | `true` |
| `text` | `""` |
| `segment_id`, `start_ms` | Los de la frase descartada |
| `end_ms` | Posición del reloj de audio en el instante del corte |
| `revision` | Mayor que la del último parcial de esa frase |
| `latency_ms` | `null` |

Predicado único "es un final vacío" (`kind = original`, `is_final`, `text` vacío), definido en
`common/schema.py` (R8). Quién lo aplica:

| Consumidor | Regla |
| --- | --- |
| Worker | No lo agrega al contexto de traducción ni lo envía a los traductores |
| Gateway, `RecentFinals` | No lo guarda en las últimas frases |
| `index.html`, `overlay.html` | Lo guardan en la fusión por clave (así un parcial tardío no revive la frase) pero no lo dibujan |
| Historial y exportación (P1, todavía no existen) | No lo incluyen (regla escrita en §6.2.5) |

## 8. Estado del escenario (`ScenarioState` → `SessionStatus`) (Δ)

Base: `specs/001-subs-mvp/data-model.md` §7. Ahora se usa `reconnecting` y `reconnects` refleja valores
reales.

```text
starting ──► live ──(corte)──► reconnecting ──(conexión lista)──► live
                                    │
                                    ├──(intentos agotados)──► error   (final; RF-004)
                                    └──(fin de la fuente)───► stopped, o starting con loop (RF-022)
```

| Campo | Cambio |
| --- | --- |
| `state` | **Δ** `reconnecting` desde el corte hasta la conexión lista, incluidas las esperas (RF-017). La regla `starting → live` del snapshot no aplica mientras está en `reconnecting` |
| `reconnects` | **Δ** +1 por cada reconexión exitosa (RF-018). Acumula durante toda la vida del worker; las vueltas con loop no lo reinician |
| `errors` | **Δ** +1 por cada intento fallido (RF-019). El abandono no suma otro: su causa ya se contó |
| `last_error` | **Δ** Causa del último intento fallido; se conserva aunque después haya éxito (RF-019) |

## 9. Eventos de log (Δ)

Formato y campos en [contracts/reconnect-observability.md](contracts/reconnect-observability.md). Todos
llevan `session_id` y ninguno lleva audio ni texto de subtítulos (RF-020, principio 14).
