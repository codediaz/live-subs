# Contrato: variables de entorno (P0)

Base: `docs/architecture.md` §7.7. Esta tabla agrega las variables nuevas (**Δ**), fija los valores
por defecto del P0 e indica qué servicio recibe cada variable.

| Variable | Por defecto | Servicio | Uso |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | — (obligatoria) | worker | Credencial. **El gateway no la recibe** (RF-031) |
| `REDIS_URL` | `redis://redis:6379/0` | ambos | Conexión a Redis |
| `TRANSCRIBE_MODEL` | `gemini-3.5-transcribe-live` | worker | Modelo de transcripción |
| `TRANSLATE_MODEL` | `gemini-3.5-flash-lite` | worker | Modelo de traducción (R2, cerrada en T0; alternativa: `gemini-3.8-flash`) |
| **Δ** `TRANSLATE_THINKING_LEVEL` | `MINIMAL` | worker | Nivel de razonamiento: el mínimo que admite el modelo (R3; `LOW` si se usa `gemini-3.8-flash`) |
| **Δ** `TRANSLATE_TIMEOUT_S` | `10` | worker | Límite por llamada de traducción (RF-015) |
| `TRANSLATION_CONTEXT_SEGMENTS` | `3` | worker | Frases previas como contexto (RF-012) |
| **Δ** `TRANSLATION_QUEUE_MAX` | `10` | worker | Frases pendientes por pista (RF-014) |
| `AUDIO_CHUNK_MS` | `100` | worker | Tamaño de bloque de audio |
| **Δ** `AUDIO_QUEUE_MAX_CHUNKS` | `50` | worker | Bloques pendientes antes de descartar (RF-004) |
| **Δ** `VOICE_RMS_THRESHOLD` | `500` | worker | Umbral de energía para detectar voz (R4) |
| **Δ** `AUDIO_CLOCK_WINDOW_S` | `120` | worker | Ventana del reloj de audio |
| **Δ** `SOURCE_END_GRACE_MS` | `3000` | worker | Espera del último final y de las traducciones al terminar la fuente |
| **Δ** `STATUS_INTERVAL_S` | `2` | worker | Periodo de publicación de `SessionStatus` (§7.2) |
| **Δ** `STATUS_TTL_S` | `15` | worker | Expiración de `SessionStatus` (§7.2) |
| **Δ** `VAD_END_SENSITIVITY` | `HIGH` | worker | Sensibilidad de fin de voz, `HIGH` o `LOW` (RF-045, R5) |
| **Δ** `VAD_SILENCE_MS` | `300` | worker | Silencio que cierra una frase (RF-045, R5) |
| `MAX_SEGMENT_MS` | `8000` | worker | Duración máxima de una frase abierta antes del corte forzado (RF-046, R5) |
| `SESSIONS_FILE` | `sessions.yaml` | ambos | Ruta de la configuración |
| `WORKER_SESSIONS` | vacío | worker | Escenarios de este worker (RF-027) |
| `GATEWAY_PORT` | `8000` | gateway | Puerto del gateway |
| **Δ** `WS_PING_S` | `20` | gateway | Ping del WebSocket (§7.6) |
| **Δ** `WS_CLIENT_QUEUE_MAX` | `100` | gateway | Eventos pendientes por cliente (R7) |
| **Δ** `RECENT_FINALS_N` | `5` | gateway | Últimas frases finales por pista enviadas al conectarse (RF-048, R18) |
| `LOG_LEVEL` | `INFO` | ambos | Nivel de logs |

`HISTORY_MAX_EVENTS` y `HISTORY_TTL_S` son P1: pueden estar en `.env.example` comentadas, pero en P0
no se leen.
