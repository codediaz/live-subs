# Research: Live Subs MVP (P0)

**Feature**: `001-subs-mvp` | **Fecha**: 2026-09-24 | **Plan**: [plan.md](plan.md)

Fuentes consultadas el 2026-09-24: documentación de Gemini API (modelos, *thinking*, Live transcribe,
Live translate), tipos del SDK `google-genai==2.25.0` y PyPI / Docker Hub para versiones. El diseño
base es `docs/architecture.md`; acá solo se registra lo que el plan decide, confirma o cambia.

## Hallazgos de la documentación que afectan al diseño

| # | Hallazgo | Impacto |
| --- | --- | --- |
| H1 | `gemini-3.5-transcribe-live` es estable. Emite `server_content.interim_input_transcription` (parciales) e `input_transcription` (finales). Audio PCM 16 bits, 16 kHz, mono, `audio/pcm;rate=16000` | Confirma §6.2 y D1 de la arquitectura |
| H2 | Las sesiones de transcripción en vivo duran **hasta 10 minutos** | Con loop (RF-043), cada vuelta abre sesión nueva; los clips deben durar < 10 min |
| H3 | `AudioTranscriptionConfig` acepta `language_codes`, `custom_vocabulary` (hasta 1.000 frases), `mode` (`VERBATIM` / `SMART`) y `word_timestamp`. La Live API documenta tiempos por enunciado, no por palabra; el tipo `Transcription` solo trae `words[].start_offset/end_offset` | Los tiempos reales no están garantizados: se verifican en T0 (R4) |
| H4 | VAD automático por defecto; VAD híbrido con `audio_stream_end` fuerza la finalización | P0 usa VAD automático; el corte forzado (P1) ya tiene camino documentado |
| H5 | `gemini-3.5-live-translate-preview` (preview) solo produce **audio**; el texto llega como `output_transcription`, sin parciales, con **un idioma destino por sesión** | Pipeline B no da parciales del original (incumple RF-006) y cuesta una sesión de audio por idioma: se descarta sin probarlo (R1) |
| H6 | *Thinking* en Gemini 3.x se controla con `thinking_level` (`ThinkingConfig`). `gemini-3.8-flash`: mínimo `LOW` (por defecto `MEDIUM`). `gemini-3.5-flash-lite`: admite `MINIMAL` (por defecto). No hay valor "apagado"; `thinking_budget` no se usa desde 3.5 | Define la configuración del traductor (R3) |
| H7 | Modelos estables vigentes: `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-3.5-transcribe-live`, `gemini-3.8-flash-tts` | Los IDs exactos de `AGENTS.md` existen; nada de alias `-latest`. El modelo TTS genera los clips del repo (R17) |

## Decisiones

Cada decisión indica la alternativa descartada. Las marcadas **T0** son provisionales hasta la prueba
técnica.

### R1. Pipeline de traducción: A (transcribe-live + traducción de texto) — **cerrada**

- **Decisión**: pipeline A, como D2 de la arquitectura. Queda cerrada sin probar B en T0.
- **Motivo**:
  - A da parciales del original (RF-006) con una sola sesión de audio por escenario;
  - sumar un idioma cuesta una llamada de texto por frase;
  - el glosario (P1) exige A, porque se aplica en la transcripción y en la traducción.
- **Descartada**: pipeline B (`gemini-3.5-live-translate-preview`).
  - No da parciales, así que incumple RF-006.
  - Su salida es solo audio (H5) y necesita una sesión por idioma destino.
  - No admite glosario en la traducción y está en preview.

### R2. Modelo del traductor: `gemini-3.8-flash` con `LOW` frente a `gemini-3.5-flash-lite` con `MINIMAL` — **T0**

- **Decisión**: arrancar con `TRANSLATE_MODEL=gemini-3.8-flash` y `TRANSLATE_THINKING_LEVEL=LOW`
  (valores de `AGENTS.md`). T0 compara ambos con las mismas frases.
- **Regla de T0**: si `gemini-3.5-flash-lite` con `MINIMAL` tiene calidad media ≥ 4/5 y no más de
  1 error de término en las 10 frases evaluadas, y además es más rápido en p50, se cambia el valor por
  defecto en `.env.example`. Es un cambio de configuración, no de código.
- **Descartada**: elegir el modelo sin medir. §8 de la arquitectura exige validar con datos.

### R3. Razonamiento del traductor al mínimo

- **Decisión**: cada llamada de traducción envía `thinking_level` tomado de
  `TRANSLATE_THINKING_LEVEL`, con el menor valor que admite el modelo configurado (`LOW` para
  `gemini-3.8-flash`, `MINIMAL` para `gemini-3.5-flash-lite`). No se piden pensamientos en la
  respuesta (`include_thoughts` apagado). El prompt pide devolver solo la traducción, para una salida
  corta.
- **Motivo**: traducir una frase no necesita razonamiento; cada nivel extra suma latencia antes del
  primer token.
- **Descartada**: dejar el nivel por defecto (`MEDIUM` en 3.8 Flash), que es más lento. También se
  descarta `thinking_budget=0`: el SDK lo marca como no soportado desde los modelos 3.5.

### R4. Tiempos de cada frase (`start_ms`, `end_ms`) y latencia

- **Decisión**: la ingesta mantiene un reloj de audio (§6.1.5). Si T0 confirma que la Live API trae
  offsets por enunciado, se usan para `start_ms` y `end_ms`. Si no, `end_ms` es el último bloque de
  audio con voz antes del final, detectado por energía (RMS sobre un umbral configurable), y
  `start_ms` es el primer bloque con voz después del final anterior. La latencia sigue las
  definiciones de §8, contra la hora de envío de ese bloque.
- **Motivo**: si se usa la posición del audio al *recibir* el evento, la latencia sale casi 0 por
  construcción y no mide nada. Con la energía se aproxima el "fin de la frase" que usan los objetivos
  de §8 (principio 7).
- **Descartada**: la aproximación literal de §8 (posición al recibir el primer parcial y el final),
  porque subestima la latencia del modelo.

### R5. Detección de voz: VAD automático del servidor

- **Decisión**: VAD automático (valor por defecto); modo `VERBATIM`.
- **Motivo**: es lo más simple que cumple RF-006 y RF-007.
- **Descartadas**: VAD híbrido o manual, que se evalúan con el corte forzado (P1). También `SMART`:
  agrega formato de párrafos y listas que no sirve para subtítulos y es incompatible con tiempos (H3).
- **Opcional en T0**: si sobra tiempo dentro de los 60 min, se compara `SMART` con `VERBATIM` sobre
  las mismas 10 frases. Solo se pasa a `SMART` si mejora la calidad y T0 confirma que los tiempos de R4
  no dependen de los offsets de la Live API.

### R6. Ingesta: un proceso `ffmpeg` por vuelta; loop reiniciando el proceso

- **Decisión**: un subproceso `ffmpeg` asíncrono por escenario, con salida PCM s16le 16 kHz mono por
  `stdout`, leída en bloques de `AUDIO_CHUNK_MS`. Para archivos se usa `-re`; para streams no, porque
  ya llegan a ritmo real. Con loop activado, al terminar el proceso con código 0 se abre una
  ejecución nueva con un `ffmpeg` y una sesión Live nuevos (RF-043). Un código distinto de 0 es una
  falla (RF-025).
- **Descartada**: `-stream_loop -1` de ffmpeg. No marca el límite entre vueltas, y ese límite hace
  falta para abrir la ejecución y la sesión nuevas, lo que evita el tope de 10 minutos (H2).

### R7. Colas acotadas con descarte del más antiguo

- **Decisión**: una sola utilidad de cola acotada que, al llenarse, descarta el elemento más antiguo
  y cuenta el descarte. Se usa en tres lugares:
  - ingesta → transcriptor (`AUDIO_QUEUE_MAX_CHUNKS`): RF-004;
  - una cola por pista de traducción (`TRANSLATION_QUEUE_MAX`): RF-014;
  - una cola de salida por cliente WebSocket en el gateway (`WS_CLIENT_QUEUE_MAX`), para que un
    cliente lento no frene a los demás.
- **Descartadas**: colas sin límite (violan el principio 7) y contrapresión que bloquee al productor
  (la ingesta nunca se bloquea).

### R8. Distribución: una suscripción por patrón por gateway

- **Decisión**: el gateway abre **una** suscripción Redis por patrón (`subs:*`) y reparte en memoria
  a los clientes según `(session_id, track)`. Cumple §6.4.1: el costo en Redis no crece con los
  espectadores.
- **Descartada**: una suscripción por cliente. Es más simple de escribir, pero abre una conexión
  Redis por espectador y contradice §6.4.1.

### R9. Redis en P0: pub/sub, `run:{session_id}` y `status:{session_id}`

- **Decisión**: el publicador hace `PUBLISH` por pista, guarda `run_id` y el `SessionStatus` con
  expiración (§7.2, §7.5). La lista `hist:*` no se escribe en P0 (historial = P1).
- **Descartada**: Redis Streams. Da historial y relectura, pero eso es P1 y agrega complejidad.

### R10. Configuración sin dependencias extra

- **Decisión**: variables de entorno leídas y validadas con modelos Pydantic, más `sessions.yaml`
  con PyYAML. El worker y el gateway tienen modelos de configuración separados: el del gateway no
  conoce `GEMINI_API_KEY` (RF-031). En desarrollo local, el `.env` se carga con el shell
  (`set -a; . ./.env`).
- **Descartadas**: `pydantic-settings` y `python-dotenv`, una dependencia más cada una sin ganar
  nada que haga falta en P0 (principio 13).

### R11. Validación de `sessions.yaml`: todo o nada al arrancar

- **Decisión**: si algún escenario es inválido, el proceso termina con un mensaje que nombra el
  escenario y el campo (RF-029). `source.loop` solo se admite con `type: file`.
- **Descartada**: arrancar solo los escenarios válidos. Oculta errores del operador justo antes del
  evento; el aislamiento del principio 6 aplica a fallas en ejecución.

### R12. Aislamiento entre escenarios

- **Decisión**: el orquestador lanza una tarea supervisada por escenario. Cada supervisor captura sus
  excepciones, publica `error` con la causa y termina solo su escenario (RF-025).
- **Descartada**: un `asyncio.TaskGroup` común a todos los escenarios. Si una tarea falla, cancela a
  las demás y viola el principio 6.

### R13. Fusión de eventos en el cliente

- **Decisión**: la regla de fusión por `(run_id, track, segment_id)` + `revision` (RF-019 a RF-021)
  vive en JavaScript, en la vista de audiencia, porque en P0 ningún componente Python la usa. Se
  verifica con un script de repetición que publica en Redis una secuencia con eventos duplicados y
  desordenados (quickstart, escenario V6).
- **Descartada**: escribir una copia en Python solo para testearla con pytest. Sería código muerto
  en P0 que puede divergir del JS. Cuando el gateway fusione historial (P1), la función pasa a Python
  con su test. `AGENTS.md` (sección Testing) ya lo refleja.

### R14. Logs JSON con la biblioteca estándar

- **Decisión**: `logging` con un formateador JSON propio; `session_id` en cada registro. En `INFO`
  solo hay identificadores y métricas (RF-034).
- **Descartada**: `structlog` o `python-json-logger`, una dependencia más para unas 20 líneas.

### R15. Vista de audiencia: criterios verificables para RF-044

- **Decisión**:
  - contraste texto/fondo ≥ 4,5:1 (WCAG AA);
  - sin desplazamiento horizontal desde 360 px de ancho;
  - al menos 3 tamaños de letra que el espectador elige con botones A− / A+ (se recuerda en el
    navegador);
  - tema oscuro por defecto.
- **Descartada**: dejar "legible" sin métrica, porque no se podría verificar.

### R16. Imagen y servicios

- **Decisión**: una imagen `python:3.12.14-slim-trixie` con `ffmpeg` de Debian y dos servicios
  (worker, gateway) más `redis:8.10.2-alpine` sin persistencia (§11). El worker lee `.env` con
  `env_file`; el gateway recibe solo las variables que usa, por interpolación, sin la API key.
- **Descartadas**: una imagen por servicio (más piezas, contra D6) y compilar ffmpeg (innecesario).

### R17. Audio de prueba: charla real solo en local; clips del repo generados con TTS

- **Decisión**:
  - T0 usa una charla real de Nerdearla guardada en `samples/local/`, que está en `.gitignore` y
    nunca se sube.
  - Los clips del repo (`samples/audio/`) se generan con `gemini-3.8-flash-tts` a partir de un guion
    técnico con jerga (por ejemplo Kubernetes, pull request, deployment, observability), uno en
    inglés y otro en español, de 2 a 3 min cada uno.
  - Los guiones se guardan junto a los clips y sirven de transcript de referencia.
  - El origen de los clips (modelo, voz, fecha y guion) se documenta en `samples/audio/README.md`.
- **Motivo**: la charla real da latencia y calidad realistas en T0 sin problemas de licencia. Los
  clips TTS son redistribuibles bajo Apache 2.0, duran menos de 10 min (H2) y tienen jerga para
  probar el glosario en P1.
- **Descartadas**:
  - subir la charla real al repo: la licencia de redistribución no está clara;
  - grabar los clips a mano: lleva más tiempo y el resultado es menos reproducible.

## Dependencias (versiones fijadas)

Principio 13: cada dependencia tiene un motivo. Todas son directas y van fijadas con `==`.

| Paquete | Versión | Uso | Por qué no otra cosa |
| --- | --- | --- | --- |
| `fastapi` | 0.141.1 | HTTP y WebSocket del gateway | Stack de la constitución (principio 1) |
| `uvicorn` | 0.53.0 | Servidor ASGI del gateway | El servidor estándar de FastAPI; sin extras `[standard]` para no sumar `uvloop`, `httptools` ni `watchfiles` |
| `websockets` | 17.1 | Soporte WebSocket de uvicorn; su CLI (`python -m websockets`) sirve para verificar el WS | uvicorn necesita una biblioteca WS; esta es la de referencia |
| `pydantic` | 2.13.5 | `SubtitleEvent`, `SessionStatus` y validación de configuración | Stack de `AGENTS.md`; ya lo trae FastAPI, se fija porque se usa directo |
| `redis` | 8.1.0 | Cliente asyncio: pub/sub y claves | Cliente oficial; incluye asyncio |
| `google-genai` | 2.25.0 | Live API (transcripción) y traducción de texto | SDK oficial; tiene `interim_input_transcription` y `thinking_level` |
| `PyYAML` | 6.0.3 | `sessions.yaml` (y glosarios en P1) | Estándar de facto para YAML |
| `pytest` (dev) | 9.1.1 | Tests de funciones puras | Exigido por la constitución (principio 10) |

Imágenes: `python:3.12.14-slim-trixie` (con `ffmpeg` del repositorio de Debian) y
`redis:8.10.2-alpine`.

La generación de clips (R17) usa `google-genai` y `ffmpeg`, que ya están en la lista: no suma
dependencias.

Descartadas a propósito: `pytest-asyncio` (los tests son de funciones puras síncronas), `httpx` (no
hay tests HTTP en P0), `pydantic-settings`, `python-dotenv`, `structlog` y `numpy` (la energía RMS de
un bloque de 100 ms se calcula con la biblioteca estándar).

## T0. Prueba técnica (tarea previa, descartable)

- **Límite de tiempo**: 60 min. Si se agota, se cierra con lo medido y quedan los valores por
  defecto de R2 y R4.
- **Ubicación**: `scripts/t0/` (fuera de `src/`, sin tests, no entra a la imagen). Sus resultados se
  agregan a este archivo en "Resultados de T0".
- **Entrada**: 2–3 min de una charla real de Nerdearla en inglés, guardada en `samples/local/` (solo
  en local, R17). Se convierte con ffmpeg a PCM 16 kHz mono y se envía a ritmo real por la Live API
  con `gemini-3.5-transcribe-live` (pipeline A, R1 ya cerrada). Se arma a mano un transcript de
  referencia de 10 frases con tiempos aproximados.
- **Comparación de traductores**, con las mismas frases finales:
  - `gemini-3.8-flash` con `LOW`;
  - `gemini-3.5-flash-lite` con `MINIMAL`.
- **Métricas**:
  - latencia p50/p95 de parcial, de final y de traducción, desde el fin de frase de la referencia;
  - tiempo propio de traducción;
  - calidad 1–5 por frase, puntuada a mano sobre 10 frases;
  - errores de términos técnicos.
- **Verificaciones colaterales**:
  - si la Live API entrega offsets por enunciado (R4);
  - que dos sesiones Live simultáneas funcionan con la cuota de la key.
- **Opcional, si sobra tiempo**: `SMART` frente a `VERBATIM` sobre las mismas 10 frases (R5).
- **Fuera de T0**: la verificación de `audio_stream_end` para forzar el final pasa a P1, junto con el
  corte forzado.
- **Salida**: tabla de resultados y decisión aplicada a R2 y R4 (y a R5 si se hizo la comparación
  opcional). Los datos crudos quedan en `scripts/t0/out/` (ignorado por git).

## Resultados de T0

*Pendiente: se completa al ejecutar T0.*
