# Modelo de datos: Live Subs MVP (P0)

**Feature**: `001-subs-mvp` | **Plan**: [plan.md](plan.md)

Los contratos base están en `docs/architecture.md` §7. Acá solo se agregan los campos, reglas y
estados que el P0 necesita. Los cambios frente a la arquitectura van marcados con **Δ**.

## 1. Configuración de escenarios (`sessions.yaml`)

Base: §7.3. Formato completo en [contracts/sessions-yaml.md](contracts/sessions-yaml.md).

| Entidad | Campos | Reglas de validación (RF-029) |
| --- | --- | --- |
| `Defaults` | `target_languages`, `glossary` (P1: se lee pero no se usa) | Idiomas dentro de los soportados |
| `SessionConfig` | `id`, `name`, `title`, `source`, `source_language`, `target_languages`, `glossary` | `id` único y sin espacios; `source_language` ∈ {`en`, `es`} (`auto` es P2); cada destino ∈ idiomas soportados |
| `SourceConfig` | `type` ∈ {`file`, `stream`}, `uri`, **Δ `loop`** (bool, por defecto `false`) | `uri` obligatorio; `loop: true` solo con `type: file`; `microphone` se rechaza en P0 |

- Los destinos iguales al idioma de origen se ignoran: no se crea esa pista (spec, casos borde).
- `WORKER_SESSIONS` filtra por `id`. Si nombra un `id` inexistente, es un error de validación.

## 2. Configuración del entorno

Base: §7.7. Variables nuevas y reparto por servicio en [contracts/env.md](contracts/env.md).

| Modelo | Lo usa | Contiene |
| --- | --- | --- |
| `WorkerSettings` | worker | Credencial, modelos, parámetros de audio, colas, traducción, estado y Redis |
| `GatewaySettings` | gateway | Redis, puerto, `SESSIONS_FILE`, parámetros de WebSocket. **No tiene `GEMINI_API_KEY`** (RF-031) |

## 3. Ejecución (run)

- `run_id`: epoch ms del inicio de la vuelta. Se guarda en `run:{session_id}` (§7.5).
- Empieza cuando arranca un escenario y **Δ** en cada vuelta de un archivo con loop (RF-043).
- Dentro de una ejecución se cuentan `sequence`, `segment_id` y `start_ms`, todos desde 0.

## 4. Reloj de audio

| Campo | Descripción |
| --- | --- |
| `position_ms` | Posición del bloque en la ejecución (bloque n → n × `AUDIO_CHUNK_MS`) |
| `sent_at_ms` | Hora real (epoch ms) en que el bloque se envió a la Live API |
| `voiced` | Si la energía RMS del bloque supera `VOICE_RMS_THRESHOLD` (R4) |

- Se guardan solo los últimos `AUDIO_CLOCK_WINDOW_S` segundos, en un buffer circular.
- Funciones puras sobre el reloj:
  - `sent_at(position_ms)`;
  - último bloque con voz antes de t;
  - primer bloque con voz después de t.

## 5. Estado de frase en el transcriptor (`SegmentTracker`)

Es una máquina pura: recibe parciales y finales de la Live API y devuelve `SubtitleEvent` de la pista
`original`.

```text
(sin frase abierta) ──parcial──► ABIERTA(segment_id=n, revision=0)
ABIERTA ──parcial──► ABIERTA(revision+1)
ABIERTA ──final──► CERRADA(revision = última+1, is_final=true) ──► (sin frase abierta, próximo n+1)
(sin frase abierta) ──final sin parciales──► CERRADA(segment_id=n, revision=0)
```

- `sequence` sube en cada evento emitido del escenario, incluidas las traducciones.
- El final lleva una `revision` mayor que cualquier parcial de su frase, así también gana por
  revisión (§7.1).
- Parciales con texto vacío o igual al anterior no se publican.

## 6. `SubtitleEvent`

Base: §7.1, sin cambios (`schema_version = 1`). Las reglas de P0 están en
[contracts/events.md](contracts/events.md).

| Tipo | `track` | `kind` | `is_final` | `end_ms` | `latency_ms` |
| --- | --- | --- | --- | --- | --- |
| Parcial | `original` | `original` | `false` | `null` | Parcial (§8, R4) |
| Final | `original` | `original` | `true` | fin de frase | Final (§8, R4) |
| Traducción | idioma destino | `translation` | `true` | = el del original | Traducción (§8) |

## 7. `SessionStatus`

Base: §7.2, sin cambios. En P0 se usan los estados `starting`, `live`, `stopped` y `error`
(`reconnecting` es P1).

```text
starting ──primer bloque enviado──► live
live ──fuente termina (código 0) y sin loop──► stopped
live ──fuente termina (código 0) y con loop──► starting (nueva ejecución)
starting | live ──falla de fuente, Live API o configuración en ejecución──► error (last_error = causa)
```

- Se publica cada `STATUS_INTERVAL_S` con expiración `STATUS_TTL_S` (§7.2: 2 s y 15 s).
- `last_error` es un texto corto de la causa, sin audio ni subtítulos.

## 8. Pista de traducción

- Hay una por cada idioma destino distinto del de origen.
- Tiene una cola acotada de frases finales pendientes (`TRANSLATION_QUEUE_MAX`). Si se llena, se
  descarta la más antigua y se registra (RF-014).
- Contexto: las últimas `TRANSLATION_CONTEXT_SEGMENTS` frases finales originales de la ejecución,
  más el `title` del escenario (RF-012).
- Si una traducción falla o supera `TRANSLATE_TIMEOUT_S`, se registra el error y se sigue con la
  siguiente frase (RF-015).

## 9. Vista de audiencia (estado en el navegador)

- Mapa `clave (run_id, track, segment_id) → evento`. Gana la `revision` mayor y un final reemplaza a
  un parcial (RF-019, RF-020).
- Si llega un `run_id` distinto al actual, se vacía el mapa (RF-021).
- Preferencias del espectador: tamaño de letra (RF-044), guardado en el navegador.
