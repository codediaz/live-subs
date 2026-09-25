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
| H4 | VAD automático por defecto, configurable con `realtime_input_config.automatic_activity_detection` (`end_of_speech_sensitivity`, `silence_duration_ms`); `audio_stream_end` vacía el audio en caché y fuerza la finalización, y después se puede seguir enviando audio | P0 usa VAD automático ajustado más corte forzado con `audio_stream_end` (R5, medido con `vad_probe.py`) |
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

### R2. Modelo del traductor: `gemini-3.8-flash` con `LOW` frente a `gemini-3.5-flash-lite` con `MINIMAL` — **cerrada**

- **Resultado (T0, 2026-09-24)**: `TRANSLATE_MODEL=gemini-3.5-flash-lite` con
  `TRANSLATE_THINKING_LEVEL=MINIMAL`. En T0 tuvo p50 de 638 ms frente a 1.533 ms de
  `gemini-3.8-flash` con `LOW`. La alternativa es `gemini-3.8-flash` con `LOW`: se cambia solo por
  configuración. Ver "Resultados de T0".
- **Decisión inicial**: arrancar con `TRANSLATE_MODEL=gemini-3.8-flash` y
  `TRANSLATE_THINKING_LEVEL=LOW` (valores de `AGENTS.md`). T0 compara ambos con las mismas frases.
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

### R4. Tiempos de cada frase (`start_ms`, `end_ms`) y latencia — **cerrada**

- **Resultado (T0, 2026-09-24)**: la Live API no entrega offsets. `input_transcription` e
  `interim_input_transcription` solo traen `text` (`utterance_offsets_found: false`). Se usa el reloj
  de audio con detección de voz por RMS. En T0, el fin de una racha de voz es el último bloque sobre
  el umbral seguido de al menos 300 ms de silencio. Eso evita tomar como fin el comienzo de la frase
  siguiente, y la implementación usa la misma regla.
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

### R5. Detección de voz: VAD automático del servidor, ajustado, con corte forzado — **actualizada 2026-09-25**

- **Decisión**: VAD automático con `END_SENSITIVITY_HIGH` (`VAD_END_SENSITIVITY`) y
  `silence_duration_ms=300` (`VAD_SILENCE_MS`); modo `VERBATIM`. Además, si una frase sigue abierta
  `MAX_SEGMENT_MS=8000` desde su primer parcial, se envía `audio_stream_end` sin cortar el envío de
  audio, y se repite si sigue abierta otros 8 s (variante d del probe).
- **Motivo**: con la configuración por defecto, la sala en español dio 1 final en 90 s y T038 falló
  (CE-004). La variante d es la que mejor combina espera máxima (9,4 s) y frases con puntuación de
  cierre (6 de 12). Ver § Resultados del probe de corte de frase.
- **Descartadas**:
  - VAD por defecto (variante a): 1 final en 90 s;
  - solo VAD ajustado (b): frases reales, pero hasta 62 s sin final;
  - `audio_stream_end` fijo cada 6 s (c): corta casi todas las frases a la mitad (4 de 14 con
    puntuación de cierre);
  - VAD manual (`activity_start` / `activity_end`) con detección propia: más código y más riesgo;
  - `SMART`: agrega formato de párrafos y listas que no sirve para subtítulos y es incompatible con
    tiempos (H3).
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

### R18. Últimas frases al conectarse: memoria del gateway — **2026-09-25**

- **Decisión**: el gateway guarda las últimas `RECENT_FINALS_N=5` frases finales de la ejecución
  actual por `(session_id, track)` en memoria. Las toma de la misma suscripción `subs:*` (R8) y las
  envía como mensajes `subtitle` al abrir el WebSocket, antes de los eventos en vivo. El cliente ya
  fusiona por clave y `revision` (R13), así que no hay que cambiar la vista.
- **Motivo**: RF-048 y CE-004. Una pista traducida solo recibe finales; sin estas frases, quien abre
  la vista espera a la próxima frase final.
- **Descartadas**:
  - historial en Redis (`hist:*`) con endpoint HTTP y fusión en el cliente: es P1 (§6.4.2) y suma
    escritura en el worker, una ruta nueva y cambios en la vista;
  - no guardar nada: incumple CE-004 cuando la pista no tiene una frase en curso.
- **Límite**: el buffer es acotado (principio 7). Cada gateway tiene su propia memoria; un gateway
  que recién arranca empieza vacío.

### R19. Traducción de fragmentos — **2026-09-25**

- **Decisión**: el prompt del traductor indica que el texto puede ser un fragmento de una frase más
  larga y pide traducirlo como fragmento, sin completarlo, apoyándose en las frases previas de
  contexto (RF-047).
- **Motivo**: el corte forzado (R5) cierra frases a la mitad. Sin la indicación, el modelo tiende a
  completarlas o a cerrarlas con punto.
- **Descartada**: unir el fragmento con el siguiente antes de traducir. Agrega espera y contradice
  el objetivo del corte.

## Dependencias (versiones fijadas)

Principio 13: cada dependencia tiene un motivo. Todas son directas y van fijadas con `==`.

| Paquete | Versión | Uso | Por qué no otra cosa |
| --- | --- | --- | --- |
| `fastapi` | 0.141.1 | HTTP y WebSocket del gateway | Stack de la constitución (principio 1) |
| `uvicorn` | 0.53.0 | Servidor ASGI del gateway | El servidor estándar de FastAPI; sin extras `[standard]` para no sumar `uvloop`, `httptools` ni `watchfiles` |
| `websockets` | 16.1.1 | Soporte WebSocket de uvicorn; su CLI (`python -m websockets`) sirve para verificar el WS | uvicorn necesita una biblioteca WS; esta es la de referencia. Se queda en 16.x porque `google-genai==2.25.0` exige `websockets<17.0` (detectado en T003) |
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
  corte forzado. *(2026-09-25: se verificó con `scripts/t0/vad_probe.py`, ver § Resultados del probe
  de corte de frase.)*
- **Salida**: tabla de resultados y decisión aplicada a R2 y R4 (y a R5 si se hizo la comparación
  opcional). Los datos crudos quedan en `scripts/t0/out/` (ignorado por git).

## Resultados de T0

**Ejecución**: 2026-09-24, ~18:49–18:56 (hora local), dentro del límite de 60 min.

- **Entrada**: `samples/local/nerdearla.mp3`, charla real de Nerdearla en inglés (local, no
  versionada). Se enviaron 118,4 s de audio a ritmo real en bloques de 100 ms (1.185 bloques; el
  envío tomó 123,7 s de reloj).
- **Datos crudos**: `scripts/t0/out/live_20260924-184905_verbatim_s1.*` (1 sesión) y
  `live_20260924-185404_verbatim_s2.*` (2 sesiones, 60 s).
- **Configuración**: `gemini-3.5-transcribe-live`, `language_codes=[en]`, modo `VERBATIM`, VAD
  automático, umbral RMS 500, silencio mínimo 300 ms.

### Transcripción (`gemini-3.5-transcribe-live`)

| Corrida | Parciales | Finales | Parcial p50 / p95 | Final p50 / p95 | Errores |
| --- | --- | --- | --- | --- | --- |
| 1 sesión, 118 s | 225 | 6 | 964 / 1.217 ms | 1.726 / 1.904 ms | 0 |
| 2 sesiones, 60 s — sesión 0 | 113 | 4 | 876 / 1.084 ms | 1.817 / 2.053 ms | 0 |
| 2 sesiones, 60 s — sesión 1 | 114 | 4 | 975 / 1.006 ms | 1.769 / 1.920 ms | 0 |

- Parcial = inicio de voz → primer parcial. Final = fin de la racha de voz → final.
- Contra los objetivos de §8: parcial p95 1,2 s (objetivo ≤ 1,5 s) y final p95 1,9 s (objetivo ≤ 3 s).
  Es una muestra chica (n = 6 frases).
- **Offsets por enunciado**: no hay. Los mensajes de transcripción no traen campos además de `text`
  (R4).
- **Dos sesiones simultáneas**: funcionan con la key, sin errores, y con latencias equivalentes a una
  sola sesión.
- **Frases finales muy largas**: 6 finales en 118 s, de 30, 18, 55, 2, 52 y 67 palabras, separadas
  por 13–32 s. El VAD automático corta en pausas largas y este speaker casi no las hace. La latencia
  "desde el fin de la frase" es buena, pero la pista traducida queda hasta ~30 s sin mostrar nada.

### Traducción (EN → ES, mismas frases)

Salieron 6 finales y 5 tenían ≥ 4 palabras, así que se tradujeron **5 frases**, no las 10 previstas.
Cada una llevó como contexto el título y las 3 frases anteriores.

| Modelo | `thinking_level` | p50 | p95 | Rango | Errores |
| --- | --- | --- | --- | --- | --- |
| `gemini-3.5-flash-lite` | `MINIMAL` | 638 ms | 911 ms | 566–911 ms | 0 |
| `gemini-3.8-flash` | `LOW` | 1.533 ms | 1.877 ms | 1.024–1.877 ms | 0 |

- Latencia estimada de la traducción en pantalla desde el fin de la frase (final p50 + traducción
  p50): ~2,4 s con Flash-Lite y ~3,3 s con 3.8 Flash. Las dos cumplen el objetivo de ≤ 5 s de §8.
- **Calidad**: las columnas `quality_1_5` y `term_errors` del CSV quedaron vacías. La elección de
  Flash-Lite la tomó el usuario revisando las traducciones, sin puntajes registrados. La regla de R2
  (calidad media ≥ 4/5) no quedó documentada con datos.
- **Opcional `SMART` / `VERBATIM`**: no se ejecutó. R5 queda en `VERBATIM`.

### Decisiones

- **R2 cerrada**: `TRANSLATE_MODEL=gemini-3.5-flash-lite`, `TRANSLATE_THINKING_LEVEL=MINIMAL`.
  Alternativa por configuración: `gemini-3.8-flash` con `LOW`.
- **R4 cerrada**: sin offsets de la API; reloj de audio con detección de voz por RMS (fin de racha =
  último bloque con voz seguido de ≥ 300 ms de silencio).

### Consecuencia para P1

*(2026-09-25: el corte forzado pasó a P0 por la falla de T038; ver § Resultados del probe de corte
de frase.)*

**El corte forzado (`MAX_SEGMENT_MS`, §6.2.4) es la primera prioridad de P1.** Con este tipo de
speaker hay pocas frases finales y muy largas (hasta 67 palabras y ~30 s). La traducción, que solo
procesa finales, llega tarde para la audiencia aunque su latencia desde el fin de la frase sea baja.
La verificación de `audio_stream_end` a mitad de frase (§14, punto 3) va junto con esa tarea.

## Resultados del probe de corte de frase

**Motivo**: T038 falló en CE-004 (`checklists/validation.md`). En 75 s, `sala2` publicó 133 parciales
y 0 finales, así que su pista `en` no mostraba nada. `sala1` publicaba un final cada ~20–25 s.

**Ejecución**: 2026-09-25, `scripts/t0/vad_probe.py` (descartable, como T0).

- **Entrada**: los primeros 90 s de `samples/audio/charla_es.ogg`, a ritmo real, bloques de 100 ms,
  seguidos de 2 s de silencio.
- **Método**: una sesión Live por variante, una después de otra, con `gemini-3.5-transcribe-live`,
  `language_codes=[es]` y `VERBATIM`.
- **Datos crudos**: `scripts/t0/out/vad_20260924-233936_*` (a, b, c) y
  `scripts/t0/out/vad_20260924-234935_*` (d). La corrida `vad_20260924-233926_*` falló por
  configuración local (`\r` en el nombre del modelo) y no cuenta.
- **Nombres de parámetros**: verificados en la guía oficial de la Live API y en los tipos de
  `google-genai==2.25.0`:
  - `LiveConnectConfig.realtime_input_config`;
  - `RealtimeInputConfig.automatic_activity_detection`;
  - `AutomaticActivityDetection.end_of_speech_sensitivity` (`EndSensitivity.END_SENSITIVITY_HIGH`);
  - `AutomaticActivityDetection.silence_duration_ms`;
  - `AsyncSession.send_realtime_input(audio_stream_end=True)`.

| Variante | Finales | Finales/min | Duración media de la frase | Palabras/final | Espera máxima entre finales | Finales con `.?!` | `audio_stream_end` enviados |
| --- | --- | --- | --- | --- | --- | --- | --- |
| (a) configuración actual (VAD por defecto) | 1 | 0,67 | 91,2 s | 218 | 92,0 s | 0 / 1 | 0 |
| (b) `END_SENSITIVITY_HIGH`, `silence_duration_ms=300` | 5 | 3,33 | 17,5 s | 43 | 61,9 s | 4 / 5 | 0 |
| (c) actual + `audio_stream_end` cada 6 s | 14 | 9,33 | 6,0 s | 15,1 | 12,2 s | 4 / 14 | 15 |
| **(d) b + `audio_stream_end` si la frase abierta supera 8 s** | 12 | 8,0 | 6,9 s | 17,8 | **9,4 s** | **6 / 12** | 7 |

- **Duración de la frase**: tiempo desde el primer parcial de la frase hasta su final. **Espera
  máxima**: mayor intervalo entre el inicio del envío y un final, o entre dos finales seguidos.
- **`audio_stream_end` a mitad de frase**: fuerza el final y la sesión sigue aceptando audio en la
  misma conexión (c y d, sin errores). Cierra el punto 3 de §14 de la arquitectura.
- **Conclusión**: se adopta d (R5). En d, 5 finales los cerró el VAD y 7 el corte. Los 6 finales sin
  puntuación de cierre son fragmentos cortados, por eso el traductor los trata como fragmentos (R19).
- **Límite de la muestra**: un clip TTS en español y 90 s por variante. Cada variante recibe el
  mismo audio, pero en una sesión distinta.
