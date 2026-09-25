---

description: "Lista de tareas de la feature 001-subs-mvp (P0)"
---

# Tareas: Live Subs MVP (P0)

**Entrada**: documentos de diseño en `specs/001-subs-mvp/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md)). Diseño base: `docs/architecture.md` v0.4.

**Tests**: primero, y solo para funciones puras (constitución, principio 10). La integración se
verifica con `samples/audio/` y los escenarios V0–V9 de [quickstart.md](quickstart.md). No se usan
mocks de Gemini para dar por buena una tarea.

**Organización**:

- Las fases siguen el orden por valor: T0 → setup → base → hito **"1 escenario"** → hito **"MVP P0"**
  → README y clon limpio → **Entrega**.
- Cada tarea dura como máximo 30 min (T0: 60 min) e indica sus RF y una línea **Hecho cuando**.

## Formato: `[ID] [P?] [Historia?] Descripción`

- **[P]**: paralelizable (otro archivo, sin dependencias pendientes); se puede delegar a Codex.
- **[US1]** espectador · **[US2]** operador · **[US3]** evaluador (historias de [spec.md](spec.md)).
- **[MANUAL]**: la hace el usuario; el agente **nunca** la ejecuta.
- Reglas de `AGENTS.md`:
  - una tarea por vez;
  - `pytest -q` en verde antes de marcar `[x]` (desde T008, cuando existen tests);
  - sin commits del agente: al terminar, propone un mensaje en Conventional Commits.

---

## Fase 0: Prueba técnica

**Propósito**: cerrar R2 (modelo traductor) y R4 (tiempos por enunciado) con datos reales antes de
escribir la aplicación. R1 ya está cerrada en el pipeline A.

- [ ] T000 [MANUAL] Dejar el material para T0:
  - 2–3 min de una charla real de Nerdearla en inglés en `samples/local/nerdearla_en.<ext>` (esa
    carpeta está en `.gitignore`);
  - `ffmpeg` instalado en la máquina (`sudo apt install ffmpeg`);
  - `GEMINI_API_KEY` exportada en la shell.
  - **RF**: — (prerrequisito de T001).
  - **Hecho cuando**: `ls samples/local/` muestra el clip y `ffmpeg -version` responde.
- [x] T001 T0 (máximo 60 min) en `scripts/t0/`. Es descartable, sin tests y fuera de la imagen.
  - `scripts/t0/live_probe.py`:
    - envía el clip a ritmo real (PCM 16 kHz mono, bloques de 100 ms) a `gemini-3.5-transcribe-live`
      por `client.aio.live.connect`;
    - registra la hora de cada `interim_input_transcription` e `input_transcription`;
    - revisa si llegan offsets por enunciado (`words[].start_offset/end_offset` u otro campo);
    - abre 2 sesiones simultáneas.
  - `scripts/t0/translate_probe.py` traduce las mismas 10 frases finales con:
    - `gemini-3.8-flash` y `thinking_level=LOW`;
    - `gemini-3.5-flash-lite` y `thinking_level=MINIMAL`.
  - Datos crudos en `scripts/t0/out/`.
  - Opcional, si sobra tiempo: `SMART` frente a `VERBATIM`.
  - No se prueba el pipeline B ni `audio_stream_end`.
  - **RF**: RF-006, RF-007, RF-009, RF-038 (insumos).
  - **Hecho cuando**:
    - `specs/001-subs-mvp/research.md § Resultados de T0` tiene la tabla de latencias p50/p95,
      la calidad 1–5 de 10 frases (el usuario valida las puntuaciones) y los errores de términos;
    - R2 y R4 están marcadas como cerradas, o pasaron los 60 min y quedan los valores por defecto.

---

## Fase 1: Setup

**Propósito**: imágenes, paquete, configuración de ejemplo y clips de prueba.

- [x] T002 Validar las imágenes fijadas en `research.md` (R16) con `docker pull`.
  - **RF**: RF-033.
  - **Hecho cuando**: `docker pull python:3.12.14-slim-trixie && docker pull redis:8.10.2-alpine`
    termina con código 0. Si falta un tag, se para y se pregunta.
- [x] T003 Crear el esqueleto del paquete:
  - `pyproject.toml` con las dependencias exactas de `research.md § Dependencias`
    (`fastapi==0.141.1`, `uvicorn==0.53.0`, `websockets==16.1.1`, `pydantic==2.13.5`, `redis==8.1.0`,
    `google-genai==2.25.0`, `PyYAML==6.0.3`) y el extra `[dev]` con `pytest==9.1.1`;
  - paquetes `src/subs/__init__.py`, `src/subs/common/__init__.py`, `src/subs/worker/__init__.py`,
    `src/subs/gateway/__init__.py`;
  - carpeta `tests/`;
  - `testpaths = ["tests"]` en `pyproject.toml`.
  - **RF**: —.
  - **Hecho cuando**: `pip install -e ".[dev]"` termina sin error y
    `python -c "import subs.common, subs.worker, subs.gateway"` no falla.
- [x] T004 [P] Crear `.env.example` con todas las variables de `contracts/env.md` y sus valores por
  defecto. Las P1 (`MAX_SEGMENT_MS`, `HISTORY_*`) van comentadas y `GEMINI_API_KEY` queda vacía.
  `TRANSLATE_MODEL` y `TRANSLATE_THINKING_LEVEL` toman la decisión de T001 (R2).
  - **RF**: RF-030.
  - **Hecho cuando**: cada variable de `contracts/env.md` aparece en `.env.example`, sin ningún
    valor de credencial (se revisa con `grep`).
- [x] T005 [P] Escribir los guiones de TC:
  - `samples/audio/charla_en.txt` y `samples/audio/charla_es.txt`;
  - cada uno de 300–450 palabras, en tono de charla técnica;
  - con jerga: Kubernetes, pull request, deployment, observability, open source, CI/CD, entre otras.
  - **RF**: RF-040.
  - **Hecho cuando**: `wc -w samples/audio/charla_*.txt` da entre 300 y 450 palabras en cada uno.
- [x] T006 TC: crear `scripts/make_clips.py`, generar los clips y documentarlos.
  - El script lee cada guion, genera el audio con `gemini-3.8-flash-tts` (una voz por idioma) y lo
    convierte con ffmpeg a `samples/audio/charla_en.ogg` y `samples/audio/charla_es.ogg` (Opus mono).
  - Si el guion es largo, lo genera por párrafos y los concatena.
  - `samples/audio/README.md` documenta modelo, voz, fecha, guion, que el audio es sintético y la
    licencia Apache 2.0.
  - **RF**: RF-040.
  - **Hecho cuando**: `ffprobe -v error -show_entries format=duration -of csv=p=0 samples/audio/charla_en.ogg`
    (y el mismo comando para `_es`) da entre 120 y 180 s, y existe `samples/audio/README.md`.

---

## Fase 2: Base (bloquea todas las historias)

**Propósito**: contrato, configuración, colas, logs e imagen. Tests primero en cada función pura.

- [x] T007 [P] Escribir `tests/test_schema.py` antes de la implementación.
  - `SubtitleEvent` según `docs/architecture.md` §7.1: `schema_version: Literal[1] = 1`,
    `kind: Literal["original", "translation"]`, `revision: int = 0`, `end_ms` y `latency_ms`
    opcionales.
  - `SessionStatus` según §7.2: `state: Literal["starting", "live", "reconnecting", "stopped", "error"]`.
  - Casos: ida y vuelta a JSON, rechazo de `kind` inválido y de `schema_version` distinto de 1.
  - **RF**: RF-035, RF-039.
  - **Hecho cuando**: `pytest -q tests/test_schema.py` falla por no encontrar el módulo o sus
    símbolos, y no por errores del test.
- [x] T008 Implementar `src/subs/common/schema.py` (`SubtitleEvent`, `SessionStatus`, más una función
  pura que arma el nombre de canal `subs:{session_id}:{track}`).
  - **RF**: RF-035, RF-036, RF-037, RF-038, RF-039.
  - **Hecho cuando**: `pytest -q` en verde.
- [x] T009 [P] Escribir `tests/test_config.py` antes de la implementación, con cada regla de
  `contracts/sessions-yaml.md`:
  - "`id` es obligatorio, único y sin espacios";
  - "`name`, `title` y `source_language` son obligatorios";
  - "`source.uri` es obligatorio para `file` y `stream`. Para `file`, el archivo tiene que existir";
  - "`loop: true` con `type: stream` es un error";
  - `target_languages` heredado de `defaults`;
  - "Cada id de `WORKER_SESSIONS` tiene que existir en el archivo";
  - se rechazan `microphone`, `auto` y `pt`;
  - los destinos iguales al origen se ignoran;
  - el mensaje de error nombra el escenario y el campo;
  - `GatewaySettings` no tiene `GEMINI_API_KEY`.
  - **RF**: RF-027, RF-028, RF-029, RF-030, RF-031, RF-043.
  - **Hecho cuando**: `pytest -q tests/test_config.py` falla solo por la implementación faltante.
- [x] T010 Implementar `src/subs/common/config.py`:
  - `WorkerSettings` y `GatewaySettings` (Pydantic, leídos de `os.environ`, con los valores por
    defecto de `contracts/env.md`);
  - `load_sessions(path, worker_sessions)`, que lanza un error con escenario y campo.
  - **RF**: RF-012, RF-014, RF-027, RF-028, RF-029, RF-030, RF-031, RF-032, RF-043.
  - **Hecho cuando**: `pytest -q` en verde.
- [x] T011 [P] Escribir `tests/test_queues.py` antes de la implementación. La cola acotada:
  - al llenarse descarta el elemento **más antiguo**;
  - cuenta los descartes;
  - `put` nunca bloquea;
  - `get` devuelve en orden.
  - **RF**: RF-004, RF-014.
  - **Hecho cuando**: `pytest -q tests/test_queues.py` falla solo por la implementación faltante.
- [x] T012 Implementar `src/subs/common/queues.py` (cola asyncio acotada con descarte del más antiguo
  y contador).
  - **RF**: RF-004, RF-014.
  - **Hecho cuando**: `pytest -q` en verde.
- [x] T013 [P] Escribir `tests/test_logs.py` antes de la implementación:
  - cada registro es JSON con `level`, `msg` y `session_id`;
  - en INFO, un campo `text` o `audio` pasado por error no aparece en la salida.
  - **RF**: RF-034.
  - **Hecho cuando**: `pytest -q tests/test_logs.py` falla solo por la implementación faltante.
- [x] T014 Implementar `src/subs/common/logs.py` (formateador JSON con `logging` estándar y
  `setup_logging(level)`).
  - **RF**: RF-034.
  - **Hecho cuando**: `pytest -q` en verde.
- [x] T015 Crear `sessions.yaml` por defecto según `contracts/sessions-yaml.md`:
  - `sala1`: `samples/audio/charla_en.ogg`, `source_language: en`, `target_languages: [es]`,
    `loop: true`;
  - `sala2`: `samples/audio/charla_es.ogg`, `source_language: es`, `target_languages: [en]`,
    `loop: true`.
  - **RF**: RF-028, RF-040.
  - **Hecho cuando**:
    `python -c "from subs.common.config import load_sessions; print([s.id for s in load_sessions('sessions.yaml', '')])"`
    imprime `['sala1', 'sala2']`.
- [x] T016 Crear la imagen y los servicios:
  - `Dockerfile` desde `python:3.12.14-slim-trixie`, con `ffmpeg` por apt, que copia `src/`,
    `pyproject.toml`, `sessions.yaml`, `samples/audio/` y `scripts/replay_events.py`;
  - `.dockerignore` que excluye `scripts/t0/`, `samples/local/` y `.env`;
  - `docker-compose.yml` con:
    - `redis:8.10.2-alpine` sin persistencia y con healthcheck;
    - `worker` con `env_file: .env`;
    - `gateway` solo con `REDIS_URL`, `SESSIONS_FILE`, `GATEWAY_PORT`, `WS_PING_S`,
      `WS_CLIENT_QUEUE_MAX` y `LOG_LEVEL` por interpolación, **sin `GEMINI_API_KEY`**;
    - puerto `${GATEWAY_PORT:-8000}` publicado;
    - `depends_on` con `condition: service_healthy`.
  - **RF**: RF-031, RF-033.
  - **Hecho cuando**: `docker compose build` termina sin error y
    `docker compose run --rm worker ffmpeg -version` imprime la versión.

**Checkpoint**: contrato, configuración e imagen listos; `pytest -q` en verde.

---

## Fase 3: Hito "1 escenario" — [US1] de punta a punta con la pista original

**Objetivo**: `sala1` se ve en vivo en la vista web, con parciales que se reemplazan y finales que se
consolidan.

**Prueba independiente**: `WORKER_SESSIONS=sala1 docker compose up`; en `http://localhost:8000/`
elegir `sala1` → `original` y ver parciales y finales (quickstart V2, paso 1).

- [x] T017 [P] [US1] Escribir `tests/test_audio_clock.py` antes de la implementación (reloj de audio
  de `data-model.md` §4):
  - posición n → `n × AUDIO_CHUNK_MS`;
  - `sent_at(position_ms)`;
  - RMS de un bloque PCM s16le y `voiced` según `VOICE_RMS_THRESHOLD`;
  - último bloque con voz antes de t y primer bloque con voz después de t;
  - ventana de `AUDIO_CLOCK_WINDOW_S`;
  - latencia final según §8 (`emitted_at − sent_at(end_ms)`).
  - **RF**: RF-005, RF-038.
  - **Hecho cuando**: `pytest -q tests/test_audio_clock.py` falla solo por la implementación faltante.
- [x] T018 [US1] Implementar la parte pura de `src/subs/worker/ingest.py`: `AudioClock` y el cálculo
  RMS con la biblioteca estándar (sin numpy). Si T001 confirmó offsets de la Live API, `AudioClock`
  igual se usa para `sent_at`.
  - **RF**: RF-005, RF-038.
  - **Hecho cuando**: `pytest -q` en verde.
- [x] T019 [US1] Implementar la ingesta en `src/subs/worker/ingest.py`:
  - subproceso asíncrono `ffmpeg` que convierte a PCM s16le 16 kHz mono por `stdout`, con `-re` solo
    para `file`;
  - lectura en bloques de `AUDIO_CHUNK_MS`;
  - envío a la cola acotada (`AUDIO_QUEUE_MAX_CHUNKS`) con registro de descartes;
  - código de salida 0 = fin y distinto de 0 = falla;
  - diagnóstico `python -m subs.worker.ingest <uri> --seconds N` que imprime la cantidad de bloques.
  - **RF**: RF-001, RF-002, RF-003, RF-004.
  - **Hecho cuando**:
    `docker compose run --rm worker python -m subs.worker.ingest samples/audio/charla_en.ogg --seconds 5`
    imprime unos 50 bloques y tarda unos 5 s (ritmo real).
- [x] T020 [P] [US1] Escribir `tests/test_segment_tracker.py` antes de la implementación (máquina de
  `data-model.md` §5):
  - parciales con `revision` creciente en la misma frase;
  - un final con `revision` mayor que cualquier parcial de su frase;
  - un final sin parciales tiene `revision` 0;
  - el siguiente parcial abre `segment_id + 1`;
  - los parciales vacíos o iguales al anterior no se emiten;
  - `sequence` es monótona;
  - `start_ms`, `end_ms` y `latency_ms` salen de `AudioClock`.
  - **RF**: RF-006, RF-007, RF-037.
  - **Hecho cuando**: `pytest -q tests/test_segment_tracker.py` falla solo por la implementación faltante.
- [x] T021 [US1] Implementar `SegmentTracker` en `src/subs/worker/transcriber.py`.
  - **RF**: RF-006, RF-007, RF-037, RF-038.
  - **Hecho cuando**: `pytest -q` en verde.
- [ ] T022 [US1] Implementar la sesión Live en `src/subs/worker/transcriber.py`:
  - `client.aio.live.connect` con `TRANSCRIBE_MODEL`;
  - `input_audio_transcription` con `language_codes=[source_language]` y modo `VERBATIM` (o el que
    haya definido T001);
  - una tarea que envía bloques de la cola con `send_realtime_input` (`audio/pcm;rate=16000`);
  - una tarea que recibe `interim_input_transcription` e `input_transcription` y los pasa a
    `SegmentTracker`;
  - una excepción de la sesión se propaga al supervisor.
  - **RF**: RF-003, RF-006, RF-007, RF-008, RF-025.
  - **Hecho cuando**: se verifica junto con T024 (la sesión sola no tiene salida observable).
- [x] T023 [P] [US1] Implementar `src/subs/worker/publisher.py`:
  - `PUBLISH` a `subs:{session_id}:{track}` con el JSON de `SubtitleEvent`;
  - `SET run:{session_id}`;
  - `SessionStatus` en `status:{session_id}` con expiración `STATUS_TTL_S`, publicado cada
    `STATUS_INTERVAL_S`;
  - `emitted_at_ms` se completa al publicar.
  - **RF**: RF-024, RF-025, RF-026, RF-036, RF-038.
  - **Hecho cuando**: se verifica en T024.
- [ ] T024 [US1] Implementar `src/subs/worker/main.py` y `src/subs/worker/__main__.py`:
  - supervisor de **un** escenario: `run_id` = epoch ms, ingesta → transcriptor → publicador;
  - estados `starting → live → stopped | error` (`data-model.md` §7);
  - `load_sessions` al arrancar: si falla, sale con código ≠ 0;
  - `setup_logging`.
  - **RF**: RF-024, RF-025, RF-026, RF-029, RF-034.
  - **Hecho cuando**: con `WORKER_SESSIONS=sala1 docker compose up redis worker`,
    `docker compose exec redis redis-cli PSUBSCRIBE 'subs:*'` muestra en `subs:sala1:original`
    parciales con `revision` creciente y finales con `is_final: true` y `latency_ms`, a ritmo real.
- [ ] T025 [US1] Implementar la parte HTTP de `src/subs/gateway/main.py` y `src/subs/gateway/__main__.py`
  según `contracts/gateway-api.md`:
  - `GET /healthz` (200 si Redis responde a `PING`, si no 503);
  - `GET /api/sessions` (`id`, `name`, `title`, `source_language`, `tracks`; **sin `source`**);
  - `GET /api/status`;
  - `GET /` sirve `static/index.html`;
  - uvicorn en `GATEWAY_PORT`.
  - **RF**: RF-016, RF-022, RF-031.
  - **Hecho cuando**: con el stack arriba, `curl -s localhost:8000/healthz` da 200 y
    `curl -s localhost:8000/api/sessions` lista `sala1` y `sala2` sin el campo `source`.
- [ ] T026 [US1] Implementar el WebSocket en `src/subs/gateway/main.py`:
  - `WS /ws/{session_id}?tracks=`, con cierre 1008 si la sesión o la pista son inválidas;
  - **una** suscripción `PSUBSCRIBE subs:*` por gateway con reparto en memoria por
    `(session_id, track)` (R8);
  - una cola acotada por cliente (`WS_CLIENT_QUEUE_MAX`, descarte del más antiguo);
  - `{"type": "ping"}` cada `WS_PING_S`.
  - **RF**: RF-017, RF-022.
  - **Hecho cuando**: `python -m websockets "ws://localhost:8000/ws/sala1?tracks=original"` muestra
    mensajes `{"type": "subtitle", ...}` y pings.
- [ ] T027 [US1] Crear la vista `src/subs/gateway/static/index.html` (HTML + CSS + JS nativo, sin build):
  - selector de escenario y pista desde `/api/sessions`;
  - WebSocket a la pista elegida;
  - mapa por `(run_id, track, segment_id)` donde gana la `revision` mayor y un final reemplaza a un
    parcial;
  - al cambiar de `run_id`, se limpia la pantalla;
  - al cambiar de selección, se cierra el WS anterior.
  - **RF**: RF-016, RF-017, RF-018, RF-019, RF-020, RF-021.
  - **Hecho cuando** (quickstart V2, paso 1): en `http://localhost:8000/`, con `sala1` → `original`,
    el texto de la frase en curso se actualiza y queda fijo al terminar, sin parciales viejos.
- [ ] T028 [P] [US1] Crear `scripts/replay_events.py --session <id>`. Publica en
  `subs:<id>:original` una secuencia fija de `SubtitleEvent`:
  - parciales duplicados;
  - revisiones desordenadas;
  - un final antes de su último parcial;
  - un cambio de `run_id`.

  Usa un escenario real (`sala1`) con el worker detenido, porque el WebSocket rechaza sesiones que
  no están en `sessions.yaml` (`contracts/gateway-api.md`).
  - **RF**: RF-019, RF-020, RF-021.
  - **Hecho cuando** (quickstart V6): con `docker compose stop worker` y la vista abierta en
    `sala1` → `original`, `docker compose run --rm worker python scripts/replay_events.py --session sala1`
    deja una línea por frase con el texto de mayor revisión, el final no se pisa y la pantalla se
    limpia al cambiar de `run_id`.

**Checkpoint — hito "1 escenario"**: `sala1` original se ve de punta a punta en la vista; `pytest -q`
en verde.

---

## Fase 4: Hito "MVP P0" — dos escenarios con traducción ([US1] + [US2])

**Objetivo**: `sala1` (EN → `es`) y `sala2` (ES → `en`) en paralelo, en loop, aislados entre sí, con
traducciones vinculadas a su frase y la vista legible en celular.

**Prueba independiente**: quickstart V2, V3, V4, V5, V7, V8 y V9.

- [ ] T029 [P] [US1] Escribir `tests/test_translator_pure.py` antes de la implementación:
  - pistas destino = `target_languages` menos el idioma de origen;
  - el prompt incluye el `title` y las últimas `TRANSLATION_CONTEXT_SEGMENTS` frases **finales**,
    nunca parciales, y pide devolver solo la traducción;
  - limpieza de la respuesta (espacios, comillas);
  - el evento de traducción copia `run_id`, `segment_id`, `start_ms` y `end_ms`, con `revision` 0,
    `kind` `translation` e `is_final` true.
  - **RF**: RF-009, RF-010, RF-011, RF-012.
  - **Hecho cuando**: `pytest -q tests/test_translator_pure.py` falla solo por la implementación faltante.
- [ ] T030 [US1] Implementar las funciones puras de `src/subs/worker/translator.py`.
  - **RF**: RF-009, RF-010, RF-011, RF-012.
  - **Hecho cuando**: `pytest -q` en verde.
- [ ] T031 [US1] Implementar la parte en ejecución de `src/subs/worker/translator.py` y conectarla en
  `src/subs/worker/main.py`:
  - una cola acotada (`TRANSLATION_QUEUE_MAX`, descarte del más antiguo con registro) y una tarea por
    pista, en orden dentro de cada pista;
  - `client.aio.models.generate_content` con `TRANSLATE_MODEL` y
    `ThinkingConfig(thinking_level=TRANSLATE_THINKING_LEVEL, include_thoughts=False)`;
  - timeout `TRANSLATE_TIMEOUT_S`; si falla, se registra y sigue con la frase siguiente;
  - la publicación del original nunca espera a la traducción.
  - **RF**: RF-009, RF-010, RF-013, RF-014, RF-015, RF-038.
  - **Hecho cuando**: con `PSUBSCRIBE 'subs:*'` aparecen eventos `subs:sala1:es` con el `segment_id`
    de un final de `subs:sala1:original` y con `latency_ms`; en `http://localhost:8000/`,
    `sala1` → `es` muestra frases en español.
- [ ] T032 [US2] Varios escenarios aislados en `src/subs/worker/main.py`:
  - un supervisor por escenario de `load_sessions(..., WORKER_SESSIONS)`, **sin** `TaskGroup` común
    (R12);
  - cada supervisor captura su excepción, publica `error` con `last_error` y termina solo su escenario.
  - **RF**: RF-023, RF-025, RF-027.
  - **Hecho cuando** (quickstart V4): tras matar el ffmpeg de `charla_es`,
    `curl -s localhost:8000/api/status` muestra `sala2` en `error` y `sala1` en `live`, y la vista de
    `sala1` no se interrumpe.
- [ ] T033 [US2] Loop y fin de fuente en `src/subs/worker/main.py`:
  - con `loop: true` y código de salida 0: se espera `SOURCE_END_GRACE_MS`, se cierra la sesión Live
    y empieza una ejecución nueva (nuevo `run_id`, `ffmpeg` y sesión Live);
  - sin loop: estado `stopped`.
  - **RF**: RF-026, RF-043.
  - **Hecho cuando** (quickstart V3): `docker compose exec redis redis-cli GET run:sala1` cambia
    después de cada vuelta del clip; la vista limpia la pantalla y sigue.
- [ ] T034 [US2] Verificar la fuente de stream con un `sessions.stream.yaml` temporal (no se versiona)
  y la URL de una radio o HLS pública, y corregir `ingest.py` si hace falta.
  - **RF**: RF-002, RF-025.
  - **Hecho cuando** (quickstart V5): con `SESSIONS_FILE=sessions.stream.yaml`, ese escenario produce
    subtítulos en vivo; con una URL inaccesible queda en `error` y los demás siguen.
- [ ] T035 [US2] Verificar la configuración inválida y los secretos, y corregir lo que falle.
  - **RF**: RF-029, RF-031, RF-034.
  - **Hecho cuando**:
    - V7: con un `id` repetido, el worker sale con código ≠ 0 y el mensaje nombra escenario y campo;
    - V8: `docker compose exec gateway env | grep -c GEMINI_API_KEY` da `0`;
    - `docker compose logs worker` muestra JSON con `session_id` y sin texto de subtítulos.
- [ ] T036 [P] [US1] Hacer legible `src/subs/gateway/static/index.html` (R15):
  - tema oscuro con contraste texto/fondo ≥ 4,5:1;
  - sin scroll horizontal desde 360 px;
  - botones A− / A+ con al menos 3 tamaños, guardados en `localStorage` con try/catch.
  - **RF**: RF-044.
  - **Hecho cuando** (quickstart V9): en las devtools a 360 px no hay scroll horizontal, el contraste
    medido es ≥ 4,5:1 y el tamaño elegido se mantiene al recargar.

**Checkpoint — hito "MVP P0"**:

- V2 completo: CE-001, CE-002 y CE-003;
- V4: CE-007;
- todos los eventos con `latency_ms`: CE-008;
- `pytest -q` en verde.

---

## Fase 5: README y validación desde un clon limpio — [US3]

**Objetivo**: un evaluador levanta el sistema con solo su API key siguiendo el README.

**Prueba independiente**: quickstart V1 en una carpeta nueva.

- [ ] T037 [US3] Escribir `README.md` en inglés:
  - qué es;
  - requisitos;
  - quickstart (`cp .env.example .env`, poner `GEMINI_API_KEY`, `docker compose up --build`, abrir
    `http://localhost:8000/`);
  - credencial y dónde va;
  - modelos (`TRANSCRIBE_MODEL`, `TRANSLATE_MODEL`, `TRANSLATE_THINKING_LEVEL`) y cómo cambiarlos;
  - cómo editar `sessions.yaml` (incluye `loop`);
  - cómo escalar según `docs/architecture.md` §10 (unidad = escenario, `WORKER_SESSIONS`, varios
    gateways, costo por idioma, cuotas);
  - origen de los clips;
  - licencia Apache 2.0.
  - **RF**: RF-041, RF-042.
  - **Hecho cuando** (CE-006): leyendo solo el README se responde qué credencial hace falta, qué
    modelos se usan y cómo pasar de 2 a 100 escenarios.
- [ ] T038 [US3] Validar desde un clon limpio (quickstart V1) en una carpeta nueva, siguiendo solo el
  README y cronometrando.
  - Requiere que el usuario haya commiteado el estado actual.
  - El agente no lee la key: copia el archivo `.env` existente.
  - **RF**: RF-033, RF-040; CE-004, CE-005.
  - **Hecho cuando**: desde `git clone` hasta ver subtítulos pasan menos de 10 min, y desde abrir la
    vista hasta leer la pista elegida menos de 30 s. Los tiempos quedan en
    `specs/001-subs-mvp/checklists/validation.md`.
- [ ] T039 [US3] Pasar el quickstart completo (V0–V9) y registrar el resultado de cada escenario y
  cada CE-001 a CE-008 en `specs/001-subs-mvp/checklists/validation.md`.
  - **RF**: todos (validación).
  - **Hecho cuando**: `validation.md` tiene V0–V9 y CE-001–CE-008 en OK, o con la falla y la tarea
    de corrección anotadas.

**Checkpoint**: P0 validado de punta a punta (§15 de la arquitectura, bloque P0).

---

## Fase 6: Entrega

**Propósito**: material para el jurado. Plazo: **2026-09-25 15:00 UTC**.

- [ ] T040 Agregar al `README.md` el diagrama de arquitectura (bloque de texto o Mermaid, que GitHub
  muestra sin build), basado en `docs/architecture.md` §3, y una sección de demo con el lugar para el
  link del video.
  - **RF**: RF-041.
  - **Hecho cuando**: el README muestra el diagrama en la vista previa de GitHub (o en un visor
    Markdown local).
- [ ] T041 [P] Escribir el guion del video en inglés en `docs/delivery/video-script.md`, de 1 a 2 min:
  - problema;
  - demo de dos salas con subtítulos y traducción;
  - overlay / vista en celular;
  - cómo escalar;
  - cierre.

  Tiene que incluir audio real de Nerdearla subtitulado por el sistema (§15, Entrega).
  - **RF**: —.
  - **Hecho cuando**: el guion tiene tiempos por bloque que suman entre 60 y 120 s.
- [ ] T042 [P] Escribir el texto para Devpost en inglés en `docs/delivery/devpost.md`:
  - inspiración;
  - qué hace;
  - cómo se construyó (Gemini Live + Flash, Redis, FastAPI);
  - desafíos;
  - logros;
  - qué sigue (P1/P2);
  - stack.
  - **RF**: —.
  - **Hecho cuando**: `docs/delivery/devpost.md` tiene todas esas secciones y los links al repo y al
    video (el del video queda como marcador hasta T043).
- [ ] T043 [MANUAL] Grabar el video de 1 a 2 min siguiendo `docs/delivery/video-script.md` y subirlo
  a YouTube.
  - **RF**: —.
  - **Hecho cuando**: el video es público o no listado en YouTube y el link está en el README y en
    `docs/delivery/devpost.md`.
- [ ] T044 [MANUAL] Hacer público el repositorio y enviar el proyecto a Devpost antes de
  **2026-09-25 15:00 UTC**.
  - **RF**: RF-042.
  - **Hecho cuando**: Devpost muestra el envío confirmado.

---

## Dependencias y orden de ejecución

### Fases

| Fase | Depende de | Bloquea |
| --- | --- | --- |
| 0 — T0 | T000 [MANUAL] | T004 (valores de R2), T018/T022 (R4, modo) |
| 1 — Setup | T002 no depende de nada; T006 depende de T005 y de ffmpeg local (T000) | Fase 2 |
| 2 — Base | T003 | Fases 3 y 4 |
| 3 — Hito "1 escenario" | Fase 2 | Fase 4 |
| 4 — Hito "MVP P0" | Fase 3 | Fase 5 |
| 5 — README y clon limpio | Fase 4 | Fase 6 |
| 6 — Entrega | Fase 5 (T043 necesita T041; T044 necesita T042 y T043) | — |

### Dentro de cada fase

- Test antes que implementación: T007→T008, T009→T010, T011→T012, T013→T014, T017→T018,
  T020→T021, T029→T030.
- Worker: T018→T019; T021→T022; T019 + T022 + T023 → T024.
- Gateway y vista: T025→T026→T027; T027→T036.
- Traducción y escenarios: T024→T031→T032→T033→(T034, T035).
- Datos y configuración: T005→T006; T010 + T006 → T015 (`sessions.yaml`) → T016 (imagen, que copia
  `sessions.yaml` y `samples/audio/`).

### Historias

- **US1 (espectador)**: hito "1 escenario" (original) y, en el hito "MVP P0", traducción (T029–T031)
  y legibilidad (T036).
- **US2 (operador)**: depende de US1 hasta T024 (worker de un escenario); agrega varios escenarios,
  loop, stream, validación y secretos (T032–T035).
- **US3 (evaluador)**: depende de US1 y US2 completas (T037–T039).

---

## Paralelismo (delegable a Codex)

Las tareas [P] tocan archivos distintos y no dependen de tareas pendientes de su grupo.

```text
# Fase 1, después de T003:
T004 .env.example   |   T005 guiones samples/audio/*.txt

# Fase 2, tests de funciones puras en paralelo:
T007 tests/test_schema.py | T009 tests/test_config.py | T011 tests/test_queues.py | T013 tests/test_logs.py

# Fase 3:
T017 tests/test_audio_clock.py | T020 tests/test_segment_tracker.py | T023 worker/publisher.py | T028 scripts/replay_events.py

# Fase 4:
T029 tests/test_translator_pure.py | T036 legibilidad de static/index.html

# Fase 6:
T041 docs/delivery/video-script.md | T042 docs/delivery/devpost.md
```

---

## Estrategia de implementación

1. **T0 primero** (máximo 60 min): cierra R2 y R4 con una charla real. Si se pasa del tiempo, se
   cierra con los valores por defecto.
2. **Setup + base**: imágenes validadas, contrato, configuración, colas, logs, imagen y clips.
3. **Hito "1 escenario"**: parar y validar `sala1` original en la vista antes de sumar traducción.
   Ya es una demo mínima.
4. **Hito "MVP P0"**: traducción, dos escenarios, loop, aislamiento y legibilidad. Cumple los
   requisitos eliminatorios.
5. **README + clon limpio**: lo que el jurado va a repetir.
6. **Entrega**: diagrama, guion y Devpost por el agente; video y envío a cargo del usuario.

Si el tiempo aprieta, el orden de recorte es:

- primero, T034 (stream) y T036 (legibilidad) se reducen a lo mínimo verificable;
- después, T039 se acota a V1, V2 y V4;
- nunca se recorta la Fase 6.

---

## Notas

- Cada tarea termina con `pytest -q` en verde (desde T008), `[x]` en esta lista y un mensaje de
  commit propuesto en Conventional Commits. El agente no ejecuta `git commit`, `git push` ni
  `git reset`.
- Si algo contradice la spec, el plan o `docs/architecture.md`, se para y se pregunta.
- Las tareas [MANUAL] (T000, T043, T044) nunca las ejecuta el agente.
