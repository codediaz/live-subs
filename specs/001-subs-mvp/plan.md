# Plan de implementación: Live Subs MVP (P0)

**Rama**: `001-subs-mvp` | **Fecha**: 2026-09-24 | **Spec**: [spec.md](spec.md)

**Entrada**: especificación de `specs/001-subs-mvp/spec.md`. Diseño base: `docs/architecture.md`
(referenciado por sección, no copiado).

## Resumen

El P0 entrega subtítulos en vivo para dos o más escenarios en paralelo. Cada escenario lee audio de
un archivo (a ritmo real, con loop opcional) o de una URL de stream y lo transcribe en streaming con
`gemini-3.5-transcribe-live`. El original (parcial y final) se publica en Redis y cada frase final se
traduce con un modelo Flash con el razonamiento al mínimo. Un gateway FastAPI reparte los eventos por
WebSocket a una vista web legible en celular y escritorio.

Se sigue el diseño de §3 a §7 con los ajustes que pide la spec: loop por archivo, descarte en la cola
de traducción en lugar de agrupar frases, y medición de latencia desde P0. Antes de todo van dos
tareas previas: una prueba técnica (T0, máximo 60 min) que elige el modelo traductor y confirma los
tiempos por enunciado, y la generación de los clips de prueba con TTS (TC).

## Contexto técnico

**Lenguaje/versión**: Python 3.12 (imagen `python:3.12.14-slim-trixie`)

**Dependencias principales**: FastAPI 0.141.1, uvicorn 0.53.0, websockets 16.1.1, Pydantic 2.13.5,
redis-py 8.1.0, google-genai 2.25.0, PyYAML 6.0.3; ffmpeg del sistema. Justificación de cada una en
[research.md § Dependencias](research.md#dependencias-versiones-fijadas).

**Almacenamiento**: Redis 8.10.2 sin persistencia (pub/sub, `run:*` y `status:*`; §7.5)

**Tests**: pytest 9.1.1 para funciones puras; verificación de integración con `samples/audio/`
([quickstart.md](quickstart.md))

**Plataforma**: contenedores Linux con Docker Compose; navegadores móviles y de escritorio para la
vista

**Tipo de proyecto**: servicio web (un paquete Python, dos procesos: worker y gateway) con frontend
estático sin build

**Objetivos de rendimiento** (§8, se miden desde P0 y se validan en P1): parcial en pantalla ≤ 1,5 s;
final ≤ 3 s y traducción ≤ 5 s desde el fin de la frase

**Restricciones**:

- la ingesta nunca se bloquea y todas las colas son acotadas;
- sesiones de transcripción de hasta 10 min (se cubre con loop por clip);
- sin Node ni paso de build;
- audio solo por la Live API.

**Escala/alcance**: ≥ 2 escenarios por worker en P0. Escalado horizontal por `WORKER_SESSIONS`
(§10). Idiomas en P0: `en` y `es`.

No quedan puntos "NEEDS CLARIFICATION". Dos decisiones dependen de T0 (R2, R4) y ya tienen un valor
por defecto y una regla para cambiarlo. R1 está cerrada en el pipeline A.

## Constitution Check

*GATE: se revisa antes de la Fase 0 y de nuevo después de la Fase 1.*

| # | Principio | Cómo lo cumple el plan | Pre | Post |
| --- | --- | --- | --- | --- |
| 1 | Stack | Python 3.12, FastAPI, Redis y ffmpeg; vista en HTML + JS nativo servida por el gateway; sin Node | ✅ | ✅ |
| 2 | IA | Audio solo por `client.aio.live.connect` en streaming continuo (R6); la traducción es texto y recibe solo finales (RF-010) | ✅ | ✅ |
| 3 | Contrato | `SubtitleEvent` v1 de §7.1 sin cambios; las reglas de P0 solo precisan su uso ([contracts/events.md](contracts/events.md)) | ✅ | ✅ |
| 4 | Configuración | Modelos, timings, límites y rutas en `.env` y `sessions.yaml`; los valores que §7.2 y §7.6 fijaban (2 s, 15 s, 20 s) pasan a variables ([contracts/env.md](contracts/env.md)) | ✅ | ✅ |
| 5 | Secretos | `.env` ignorado por git; solo el worker usa `env_file`; `GatewaySettings` no tiene la key (R10, R16, V8) | ✅ | ✅ |
| 6 | Aislamiento | Un supervisor por escenario, sin `TaskGroup` común (R12); verificado en V4 | ✅ | ✅ |
| 7 | Latencia | Cola acotada con descarte del más antiguo en ingesta, traducción y clientes WS (R7); `latency_ms` en cada evento (R4) | ✅ | ✅ |
| 8 | Prioridad | El plan cubre solo P0; P1 y P2 quedan fuera según la spec | ✅ | ✅ |
| 9 | Spec primero | La spec ya incluye loop, descarte y RF-044; `docs/architecture.md` v0.4 está alineado. Si T0 cambia el modelo traductor, es solo configuración | ✅ | ✅ |
| 10 | Tests | Funciones puras con pytest (ver Estrategia de tests); integración con `samples/audio/` (quickstart). La fusión de eventos (JS) se verifica con `scripts/replay_events.py` en P0 y pasa a pytest en P1, según `AGENTS.md` (R13) | ✅ | ✅ |
| 11 | Suite verde | Cada tarea se cierra con `pytest -q` en verde | ✅ | ✅ |
| 12 | Despliegue | `docker compose up` con `sessions.yaml` y clips por defecto en el repo; healthcheck de Redis antes del worker y del gateway; validado en V1 | ✅ | ✅ |
| 13 | Simplicidad | 7 dependencias de ejecución y 1 de desarrollo, fijadas y justificadas; alternativas más pesadas descartadas en R10, R13, R14 | ✅ | ✅ |
| 14 | Logs | JSON con la biblioteca estándar y `session_id` (R14); en INFO, sin audio ni texto | ✅ | ✅ |
| 15 | Idioma | Código, commits y README en inglés; spec, plan y research en español | ✅ | ✅ |

**Resultado**: el gate pasa. No hay violaciones que justificar (Complexity Tracking vacío).

## Decisiones

El detalle y las alternativas descartadas están en [research.md](research.md#decisiones).

| # | Decisión | Alternativa descartada |
| --- | --- | --- |
| R1 | Pipeline A (transcribe-live + traducción de texto) — **cerrada, sin probar B** | B (`live-translate-preview`): sin parciales (incumple RF-006), sin glosario, solo audio, una sesión por idioma |
| R2 | Traductor `gemini-3.8-flash`; se compara con `gemini-3.5-flash-lite` — **T0** | Elegir sin medir |
| R3 | `thinking_level` al mínimo del modelo (`LOW` / `MINIMAL`), sin pensamientos en la respuesta, salida solo con la traducción | Nivel por defecto (`MEDIUM`); `thinking_budget=0` (no soportado desde 3.5) |
| R4 | Tiempos por offsets de la Live API si existen; si no, reloj de audio + detección de voz por energía — **T0** | Posición al recibir el evento (latencia ≈ 0 por construcción) |
| R5 | VAD automático, modo `VERBATIM` (comparación con `SMART` opcional en T0) | VAD híbrido o manual (P1); `SMART` |
| R6 | Un `ffmpeg` por vuelta; el loop reinicia proceso, ejecución y sesión | `-stream_loop -1` (sin límite entre vueltas) |
| R7 | Cola acotada con descarte del más antiguo (ingesta, traducción, WS) | Colas sin límite; contrapresión que bloquea |
| R8 | Una suscripción por patrón `subs:*` por gateway, reparto en memoria | Una suscripción por cliente |
| R9 | Redis pub/sub + `run:*` + `status:*` | Redis Streams (el historial es P1) |
| R10 | Pydantic + PyYAML; configuración separada por proceso | `pydantic-settings`, `python-dotenv` |
| R11 | `sessions.yaml` inválido detiene el arranque | Arrancar solo los escenarios válidos |
| R12 | Supervisor por escenario | `TaskGroup` común |
| R13 | Fusión de eventos en JS; verificación con script de repetición | Copia en Python solo para tests |
| R14 | Logs JSON con `logging` estándar | `structlog`, `python-json-logger` |
| R15 | RF-044: contraste ≥ 4,5:1, 360 px sin scroll horizontal, ≥ 3 tamaños | "Legible" sin métrica |
| R16 | Una imagen slim con ffmpeg de Debian; Redis alpine | Imagen por servicio; compilar ffmpeg |
| R17 | Charla real de Nerdearla solo en local (`samples/local/`, ignorada por git) para T0; clips del repo con `gemini-3.8-flash-tts` | Subir la charla real (licencia); grabar a mano (tiempo) |

## Tareas previas

Van antes de cualquier tarea de implementación y no dependen entre sí.

### T0: prueba técnica (máximo 60 min)

Es descartable, vive en `scripts/t0/`, no tiene tests y no entra a la imagen. Diseño, métricas y
reglas de decisión en [research.md § T0](research.md#t0-prueba-técnica-tarea-previa-descartable).

- **Entrada**: 2–3 min de una charla real de Nerdearla en inglés, en `samples/local/`. Esa carpeta
  está en `.gitignore` y nunca se sube (R17).
- **Pipeline**: solo A (`gemini-3.5-transcribe-live`); R1 está cerrada y B no se prueba.
- **Compara** traductores: `gemini-3.8-flash` (`LOW`) frente a `gemini-3.5-flash-lite` (`MINIMAL`).
- **Mide**:
  - latencia p50/p95 de parcial, final y traducción;
  - tiempo propio de traducción;
  - calidad 1–5 sobre 10 frases;
  - errores de términos.
- **Verifica también**:
  - si la Live API da offsets por enunciado (R4);
  - que dos sesiones Live simultáneas funcionan con la key.
- **Opcional**, si sobra tiempo: `SMART` frente a `VERBATIM` (R5).
- **No incluye** la verificación de `audio_stream_end` (pasa a P1 con el corte forzado).
- **Hecha cuando**: los resultados están en `research.md § Resultados de T0` y R2 y R4 quedan
  cerrados, o cuando se cumplen los 60 min; en ese caso quedan los valores por defecto.

### TC: clips de prueba del repositorio con TTS

- **Guiones**: uno en inglés y otro en español, de 2 a 3 min hablados (unas 300–450 palabras). Son
  técnicos y tienen jerga (Kubernetes, pull request, deployment, observability, etc.). Se guardan
  como `samples/audio/charla_en.txt` y `samples/audio/charla_es.txt` y sirven de transcript de
  referencia.
- **Generación**: con `gemini-3.8-flash-tts` y una voz por idioma, mediante un script de desarrollo
  en `scripts/make_clips.py` que no entra a la imagen. La salida se convierte con ffmpeg a
  `samples/audio/charla_en.ogg` y `samples/audio/charla_es.ogg` (Opus mono).
- **Documentación**: `samples/audio/README.md` registra el origen de cada clip (modelo, voz, fecha,
  guion usado), que el audio es sintético y su licencia (Apache 2.0, como el repo).
- **Hecha cuando**: los dos clips duran entre 2 y 3 min, `sessions.yaml` los usa (RF-040) y
  `samples/audio/README.md` existe.

## Estructura del proyecto

### Documentación (esta feature)

```text
specs/001-subs-mvp/
├── spec.md
├── plan.md              # este archivo
├── research.md          # Fase 0
├── data-model.md        # Fase 1
├── quickstart.md        # Fase 1
├── contracts/           # Fase 1: sessions-yaml.md, env.md, events.md, gateway-api.md
├── checklists/requirements.md
└── tasks.md             # Fase 2 (/speckit-tasks)
```

### Código (raíz del repositorio)

```text
Dockerfile                  # python:3.12.14-slim-trixie + ffmpeg; copia src/ y scripts/replay_events.py
docker-compose.yml          # redis, worker (env_file .env), gateway (sin la key)
pyproject.toml              # dependencias fijadas; extra [dev] con pytest
.env.example
sessions.yaml               # sala1 (EN→es) y sala2 (ES→en), ambas file + loop
README.md                   # en inglés (RF-041)
samples/
├── audio/                  # charla_{en,es}.ogg (TTS) + guiones .txt + README.md con su origen
└── local/                  # charla real de Nerdearla para T0 (en .gitignore, nunca se sube)
scripts/
├── t0/                     # prueba técnica (descartable, fuera de la imagen)
├── make_clips.py           # genera los clips con TTS (TC, fuera de la imagen)
└── replay_events.py        # publica una secuencia fija para verificar la vista (V6)
src/subs/
├── common/
│   ├── config.py           # WorkerSettings, GatewaySettings, carga y validación de sessions.yaml
│   ├── schema.py           # SubtitleEvent, SessionStatus (§7.1, §7.2)
│   ├── queues.py           # Δ cola acotada con descarte del más antiguo (R7)
│   └── logs.py             # Δ formateador JSON (R14)
├── worker/
│   ├── __main__.py         # python -m subs.worker
│   ├── main.py             # orquestador y supervisor por escenario, loop, estado
│   ├── ingest.py           # ffmpeg → bloques PCM + reloj de audio + detección de voz
│   ├── transcriber.py      # sesión Live + SegmentTracker
│   ├── translator.py       # colas por pista, prompt, llamada al modelo
│   └── publisher.py        # PUBLISH, run:*, status:*
└── gateway/
    ├── __main__.py         # python -m subs.gateway
    ├── main.py             # rutas, WebSocket, reparto desde subs:*
    └── static/index.html   # vista de audiencia (HTML + CSS + JS en un archivo)
tests/
├── test_schema.py
├── test_config.py
├── test_queues.py
├── test_audio_clock.py
├── test_segment_tracker.py
├── test_translator_pure.py
└── test_logs.py
```

**Decisión de estructura**: la de §13 y `AGENTS.md`, con dos módulos chicos en `common/`
(`queues.py` y `logs.py`, marcados Δ). Los usan el worker y el gateway, y ninguno cabe en la
responsabilidad de los módulos de §5. `overlay.html` y `panel.html` son P1 y no se crean.

## Cobertura de requisitos por módulo

| Módulo | RF que cubre |
| --- | --- |
| `common/config.py` | RF-012 (cantidad de contexto), RF-014 (tamaño de cola), RF-027, RF-028, RF-029, RF-030, RF-032, RF-043 (campo `loop`) |
| `common/schema.py` | RF-035, RF-036, RF-037, RF-038 (campos), RF-039; estados de RF-025 y RF-026 |
| `common/queues.py` | RF-004, RF-014 (mecanismo de descarte) |
| `common/logs.py` | RF-034 |
| `worker/main.py` | RF-023, RF-024, RF-025 (supervisor), RF-026, RF-027 (filtro), RF-043 (loop) |
| `worker/ingest.py` | RF-001, RF-002, RF-003, RF-004, RF-005 |
| `worker/transcriber.py` | RF-003 (envío continuo), RF-006, RF-007, RF-008, RF-025 (falla de la Live API) |
| `worker/translator.py` | RF-009, RF-010, RF-011, RF-012, RF-013, RF-014, RF-015 |
| `worker/publisher.py` | RF-024 (`run:*`), RF-025 y RF-026 (`status:*`), RF-036 (canal por pista), RF-038 (`emitted_at_ms`, `latency_ms`) |
| `gateway/main.py` | RF-016, RF-017, RF-022, RF-031 (no lee la key) |
| `gateway/static/index.html` | RF-016, RF-017, RF-018, RF-019, RF-020, RF-021, RF-044 |
| `Dockerfile`, `docker-compose.yml`, `.env.example` | RF-030, RF-031, RF-033 |
| `sessions.yaml`, `samples/audio/`, `scripts/make_clips.py` | RF-040 |
| `README.md` | RF-041 |
| `LICENSE` (ya existe, Apache 2.0) | RF-042 |

## Estrategia de tests

**Pytest: funciones puras, escritas antes de la implementación (principio 10).**

| Archivo | Qué prueba |
| --- | --- |
| `test_schema.py` | `SubtitleEvent` y `SessionStatus`: campos obligatorios, literales (`kind`, `state`), `schema_version = 1`, ida y vuelta a JSON, rechazo de `kind` inválido |
| `test_config.py` | `sessions.yaml`: `defaults`, cada regla de [contracts/sessions-yaml.md](contracts/sessions-yaml.md) con su mensaje (escenario + campo), `loop` con stream rechazado, destinos iguales al origen ignorados, filtro `WORKER_SESSIONS`; `GatewaySettings` sin la key |
| `test_queues.py` | La cola acotada descarta el más antiguo, cuenta los descartes y no bloquea al productor |
| `test_audio_clock.py` | Posición ↔ hora de envío, detección de voz por RMS, último y primer bloque con voz, cálculo de latencia según §8 |
| `test_segment_tracker.py` | Parciales → `revision` creciente; final con `revision` mayor; nuevo `segment_id` después del final; final sin parciales; parciales vacíos o repetidos ignorados; `sequence` monótona |
| `test_translator_pure.py` | Pistas destino (excluye el idioma de origen), armado del prompt (título + últimas N finales, sin parciales), limpieza de la respuesta |
| `test_logs.py` | El JSON incluye `session_id` y nivel; en INFO no aparece texto de subtítulos |

No se usan mocks de la API de Gemini para dar por buena una tarea (`AGENTS.md`).

**Integración: se verifica con `samples/audio/`**. Cada tarea que toca Gemini, ffmpeg o Redis tiene
su comando de "Hecha cuando", tomado de [quickstart.md](quickstart.md):

| Área | Comando / escenario |
| --- | --- |
| Ingesta + transcripción | `docker compose up worker redis` + `redis-cli PSUBSCRIBE 'subs:*'`: aparecen parciales y finales de `sala1` a ritmo real |
| Traducción | Mismo comando: aparecen eventos `subs:sala1:es` con el `segment_id` de su final |
| Gateway + WS | `python -m websockets ws://localhost:8000/ws/sala1?tracks=original,es` |
| Vista | V2, V3, V6, V9 |
| Aislamiento, configuración, secretos | V4, V7, V8 |
| Despliegue | V1 desde una carpeta nueva |

## Cambios incorporados a `docs/architecture.md` (v0.4)

Las introdujo la spec (por pedido del usuario) o este plan, y ya están en `docs/architecture.md`
v0.4.

| Sección | Diferencia | Origen |
| --- | --- | --- |
| §6.3.5 | No se agrupan frases pendientes (pasa a P1); en P0, cola acotada con descarte | Spec RF-014 |
| §6.5, §7.3 | `source.loop` en archivos; al terminar el clip, ejecución y sesión nuevas | Spec RF-043 |
| §7.7 | Variables nuevas (Δ en [contracts/env.md](contracts/env.md)) | Principio 4 y R3, R4, R7 |
| §8 | Aproximación de tiempos refinada con detección de voz | R4 |
| §4 (P1 "latencia registrada") | La latencia se mide desde P0 | Spec, constitución principio 7 |
| §5, §13 | `common/queues.py`, `common/logs.py`; `samples/local/`, `scripts/` | R7, R14, R17 |

La fusión de eventos se verifica con `scripts/replay_events.py` en P0 y pasa a pytest en P1
(`AGENTS.md`, sección Testing).

## Complexity Tracking

Sin violaciones de la constitución que justificar.
