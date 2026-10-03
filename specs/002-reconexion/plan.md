# Plan de implementación: Reconexión de la transcripción

**Rama**: `002-reconexion` (trabajo actual en `feat/transcription-reconnection-spec`) | **Fecha**: 2026-10-02 |
**Spec**: [spec.md](spec.md)

**Entrada**: especificación de `specs/002-reconexion/spec.md`. Diseño base: `docs/architecture.md`
(referenciado por sección, no copiado), en particular §5, §6.1.6, §6.2, §7.1, §7.2, §7.7, §8 y §9.

## Resumen

Hoy cada escenario abre **una** conexión Live, y cuando esa conexión se cierra (a los ~10 min o por una
falla) el escenario queda en `error` (§9). Esta feature hace que el Transcriptor reconecte dentro de la
misma ejecución:

- la ingesta, los traductores y el `run_id` no se enteran del cambio de conexión (R1);
- mientras dura la reconexión, el audio que llega se descarta y el reloj de audio sigue avanzando, como
  ya prevé §6.1.6 (R5, R6);
- si había una frase abierta, se cierra con un final vacío que los clientes ocultan, sin cambiar el
  contrato (R7, R8);
- los reintentos usan una espera exponencial con tope, calculada por funciones puras (R2), y terminan en
  `error` tras `RECONNECT_MAX_ATTEMPTS` intentos;
- el estado `reconnecting` y el contador `reconnects`, que ya existen en `SessionStatus`, pasan a
  reflejar valores reales (R11).

Antes de implementar se ejecuta un probe descartable (T0R) que mide cuánto tarda en abrirse una conexión
Live y confirma que un corte provocado desde el cliente, como el que hará `LIVE_SESSION_MAX_S`, produce
un relevo real con un clip corto. La feature termina actualizando `docs/architecture.md` §6.2.5, §7.7 y
§9.

## Contexto técnico

**Lenguaje/versión**: Python 3.12 (sin cambios)

**Dependencias principales**: las del MVP, sin agregar ninguna: FastAPI, uvicorn, Pydantic v2,
redis-py (asyncio), `google-genai` 2.25.0, PyYAML; ffmpeg del sistema (R18).

**Almacenamiento**: Redis, sin claves nuevas (`run:*`, `status:*` y `subs:*`; §7.5).

**Tests**: pytest para las funciones puras; integración con `samples/audio/` y
`LIVE_SESSION_MAX_S=60`; harness de desarrollo para aislamiento y falla (R15); validación de 30 min con
cierres reales (R16).

**Plataforma**: contenedores Linux con Docker Compose (sin cambios).

**Tipo de proyecto**: servicio web; un paquete Python con dos procesos (worker y gateway) y frontend
estático sin build.

**Objetivos de rendimiento**:

- hueco < 2 s por reconexión exitosa al primer intento (CE-002);
- latencias de §8 desde la primera frase después de reconectar (CE-006);
- `reconnecting` visible en `/api/status` en ≤ 1 `STATUS_INTERVAL_S` (CE-005).

**Restricciones**:

- la ingesta nunca se bloquea ni se reinicia (principio 7);
- el audio va solo por la Live API y el descartado nunca se reenvía (principio 2, RF-010);
- `SubtitleEvent` sin cambios (principio 3);
- reanudación de sesión y pre-apertura quedan fuera (P2).

**Escala/alcance**: cada escenario se reconecta por su cuenta; nada se comparte entre escenarios
durante una reconexión (RF-021). Sin cambios en el escalado de §10.

No quedan puntos "NEEDS CLARIFICATION". Dos supuestos dependen del probe T0R (tiempo de apertura y
relevo desde el cliente); tienen valor por defecto y regla de decisión en
[research.md § T0R](research.md#t0r-probe-previo-de-reconexión-descartable).

## Constitution Check

*GATE: se revisa antes de la Fase 0 y de nuevo después de la Fase 1.*

| # | Principio | Cómo lo cumple el plan | Pre | Post |
| --- | --- | --- | --- | --- |
| 1 | Stack | Solo Python, asyncio y el SDK existente; los cambios del frontend son JS nativo en `index.html` y `overlay.html`; sin Node | ✅ | ✅ |
| 2 | IA | La conexión nueva es otra sesión Live en streaming (R1). El audio descartado no se guarda ni se reenvía por ningún canal (R5). El final vacío no se traduce: se traducen solo finales con texto (R8) | ✅ | ✅ |
| 3 | Contrato | `SubtitleEvent` y `SessionStatus` no cambian de forma; el final vacío usa el contrato actual (`text=""`, `is_final=true`) y `reconnecting`/`reconnects` ya existen (R8; [contracts/events.md](contracts/events.md)) | ✅ | ✅ |
| 4 | Configuración | Intentos, esperas, tiempo límite y cierre de prueba en `.env` con valores por defecto y validación ([contracts/env.md](contracts/env.md)); ningún tiempo fijo en el código (R2, R13) | ✅ | ✅ |
| 5 | Secretos | Las variables nuevas no son secretas. La credencial inválida del harness es un valor de prueba armado en tiempo de ejecución, no se guarda en el repo. `cause` en logs y estado no incluye la key | ✅ | ✅ |
| 6 | Aislamiento | La reconexión vive en el Transcriptor de cada escenario, sin estado compartido; un abandono sigue el camino de error del supervisor por escenario (R1, R11). Se verifica en un mismo proceso con el harness (R15, CE-007) | ✅ | ✅ |
| 7 | Latencia | La ingesta sigue sin cambios y sin bloqueo; el audio de la reconexión se descarta en lugar de acumularse (R5); el hueco se mide (`gap_ms`) y la latencia no se infla con el tramo descartado (R6) | ✅ | ✅ |
| 8 | Prioridad | La reconexión simple es P1 (§4) y el P0 está validado (§15, todos los criterios P0 marcados). Reanudación de sesión y pre-apertura (P2) quedan fuera | ✅ | ✅ |
| 9 | Spec primero | La spec cubre el comportamiento. Dos precisiones nuevas del plan (rango de `LIVE_SESSION_MAX_S` y dos eventos de log extra) pasan a la spec en la tarea S0, antes del código | ✅ | ✅ |
| 10 | Tests | Funciones puras con pytest escritas primero (política de reintento, esperas, configuración, final vacío, reloj, estado). Integración con `samples/audio/` y `LIVE_SESSION_MAX_S=60`. La fusión en JS se verifica con `scripts/replay_events.py`, según `AGENTS.md` | ✅ | ✅ |
| 11 | Suite verde | Cada tarea se cierra con `pytest -q` en verde | ✅ | ✅ |
| 12 | Despliegue | Sin cambios en `Dockerfile` ni en Compose; las variables nuevas tienen valores por defecto y `LIVE_SESSION_MAX_S` va vacío en `.env.example`. Se valida con un clon limpio (quickstart R9) | ✅ | ✅ |
| 13 | Simplicidad | Sin dependencias nuevas (R18) ni módulos nuevos en `src/` (R2). Se descartan el jitter, las variables de prueba por escenario y el drenaje en el abandono (R2, R15, R17) | ✅ | ✅ |
| 14 | Logs | Seis eventos `reconnect_*`/`live_go_away` en JSON con `session_id`, sin audio ni texto de subtítulos ([contracts/reconnect-observability.md](contracts/reconnect-observability.md)) | ✅ | ✅ |
| 15 | Idioma | Código, comentarios y README en inglés; spec, plan, research y contratos en español | ✅ | ✅ |

**Resultado**: el gate pasa, antes y después del diseño. No hay violaciones que justificar (Complexity
Tracking vacío).

## Decisiones

El detalle de cada una está en [research.md](research.md#decisiones).

| # | Decisión | Alternativa descartada (motivo) |
| --- | --- | --- |
| R1 | La reconexión vive dentro de `transcribe()`: un bucle de conexiones Live sobre la misma ejecución | El supervisor relanza `_run_once()` (`run_id` y `ffmpeg` nuevos; la pantalla se limpia; incumple RF-009 y RF-012) |
| R2 | Política pura en `transcriber.py`: primer intento sin espera, luego `min(inicial × 2^(n−2), máx.)`; abandonar al llegar a `RECONNECT_MAX_ATTEMPTS` | Jitter (esperas que pueden decrecer, contra CE-008, y tests no deterministas); módulo nuevo `reconnect.py` (cambiaría §5 y §13 por dos funciones) |
| R3 | Cualquier cierre o falla de la conexión con la fuente activa inicia la reconexión; la cancelación no. `go_away` solo se registra | Reaccionar a `go_away` (es pre-apertura, P2); reconectar solo ante cierres limpios (una caída de red terminaría en `error`) |
| R4 | Marca de corte por conexión, puesta sin ceder el control; el receptor la consulta antes de entregar resultados | Solo cancelar las tareas (carrera con un resultado ya leído que espera a Redis) |
| R5 | Un descartador vacía la cola durante toda la reconexión, avanza el reloj y mide `gap_ms` | Dejar que la cola acotada descarte sola (manda hasta 5 s de audio viejo, retrasa todo y no avanza el reloj); guardar y reenviar (fuera de alcance) |
| R6 | `AudioClock` salta bloques: avanza la posición sin registrar envío ni voz | Registrarlos como bloques sin voz (falsea silencios y horas de envío); no avanzar el reloj (incumple RF-011) |
| R7 | Corte en `SegmentTracker`: final vacío si hay frase abierta y ancla del próximo inicio en el corte | No publicar nada (el parcial queda visible, CE-009); publicar el último parcial como final (rescate, fuera de alcance) |
| R8 | Un predicado único de "final vacío" en `common/schema.py`; los clientes JS aplican la misma regla | Campo nuevo en el evento (cambio de contrato); expirar parciales en el cliente (timeout arbitrario) |
| R9 | Lista = `connect()` entregó la sesión (incluye `setup_complete`, verificado en el SDK); el tiempo límite cubre solo la apertura | Esperar el primer parcial (en silencio nunca llega) |
| R10 | Cada intento y cada espera compiten con el fin de la fuente | Terminar el intento y revisar después (podría pasar a `error`, contra RF-022) |
| R11 | Callbacks del Transcriptor a `ScenarioState`; `errors` = intentos fallidos; el abandono no suma otro | Escribir el estado en Redis desde el Transcriptor (rompe §5); contar el abandono como un error más (N + 1) |
| R12 | `LIVE_SESSION_MAX_S` como temporizador por conexión que usa el mismo camino de cierre | Cerrar desde el supervisor (segundo camino); cortes de red (no reproducibles) |
| R13 | Validación al arrancar en `WorkerSettings`; la regla cruzada nombra `RECONNECT_BACKOFF_MAX_MS` | Validar al usar (arranca con configuración inválida) |
| R14 | `contracts/env.md` de 002 con solo las variables nuevas; el test lee los dos contratos | Editar el contrato de 001 (feature cerrada) |
| R15 | Harness `scripts/reconnect_check.py` con el código real del worker para aislamiento, falla y fin de fuente | Variables de prueba por escenario en el producto; dos workers (solo prueba el aislamiento entre procesos) |
| R16 | CE-001 con una fuente de ≥ 30 min en `samples/local/` y cierres reales | Solo `LIVE_SESSION_MAX_S` (no ejercita el cierre real a los ~10 min) |
| R17 | El abandono cancela las traducciones pendientes, como cualquier error del MVP | Drenarlas antes de pasar a `error` (otro camino de espera que la spec no pide) |
| R18 | Sin dependencias nuevas | — |

## Tareas previas

Van antes de cualquier tarea de implementación.

### S0: precisiones de la spec (principio 9)

Se agregan a `spec.md` dos precisiones que surgieron del plan. Se muestra el diff antes de seguir
(`AGENTS.md`):

- RF-023: rango de `LIVE_SESSION_MAX_S` (vacío o entero ≥ 1; si no, el worker no arranca, como RF-006)
  (R13);
- RF-020: los eventos opcionales `reconnect_cancelled` (la fuente terminó durante la reconexión) y
  `live_go_away` (DEBUG), que no cambian el comportamiento
  ([contracts/reconnect-observability.md](contracts/reconnect-observability.md)).

### T0R: probe de reconexión (descartable, máximo 30 min)

Vive en `scripts/t0/reconnect_probe.py`. No tiene tests, no entra en la imagen y escribe su salida en
`scripts/t0/out/` (ignorada por git). Diseño, medidas y reglas de decisión en
[research.md § T0R](research.md#t0r-probe-previo-de-reconexión-descartable).

- **Mide** cuánto tarda en abrirse una conexión Live nueva, de la llamada a `connect()` a la sesión
  lista: p50, p95 y máximo sobre 10 aperturas.
- **Verifica** que cerrar la conexión desde el cliente a los 60 s, lo que hará `LIVE_SESSION_MAX_S=60`,
  produce relevos reales con `samples/audio/charla_en.ogg` (135 s, 2 relevos). Para cada relevo
  registra la conexión nueva lista, el audio descartado, el primer parcial y el primer final, y si
  llegan resultados tardíos de la conexión cortada.
- **Decide**:
  - si p95 ≤ 1500 ms, se mantienen RF-002 y los valores por defecto;
  - si p95 > 1500 ms, o si el relevo falla, se detiene y se consulta antes de implementar.
- **Hecha cuando**: [research.md § Resultados del probe](research.md#resultados-del-probe) tiene los
  números y la decisión de cada regla.

## Estructura del proyecto

### Documentación (esta feature)

```text
specs/002-reconexion/
├── spec.md
├── plan.md                 # este archivo
├── research.md             # Fase 0: decisiones R1–R18 y probe T0R
├── data-model.md           # Fase 1
├── quickstart.md           # Fase 1: escenarios R0–R9
├── contracts/
│   ├── env.md              # variables nuevas
│   ├── events.md           # reglas de eventos ante una reconexión (contrato sin cambios)
│   └── reconnect-observability.md   # SessionStatus y eventos de log
├── checklists/requirements.md
└── tasks.md                # Fase 2 (/speckit-tasks)
```

### Código (raíz del repositorio)

Solo archivos existentes, salvo los dos scripts de desarrollo y los tests nuevos (marcados **+**).

```text
.env.example                     # variables RECONNECT_* y LIVE_SESSION_MAX_S (vacía, solo pruebas)
README.md                        # charlas de cualquier duración; dónde están las variables de reconexión
docs/architecture.md             # §6.2.5, §7.7, §9
scripts/
├── t0/reconnect_probe.py        # + probe T0R (descartable, fuera de la imagen)
├── reconnect_check.py           # + harness de aislamiento, falla y fin de fuente (fuera de la imagen)
└── replay_events.py             # caso nuevo: frase abierta → final vacío → frase nueva, mismo run_id
src/subs/
├── common/
│   ├── config.py                # WorkerSettings: campos y validación nuevos
│   └── schema.py                # predicado "final vacío" (sin cambios en los modelos)
├── worker/
│   ├── ingest.py                # AudioClock: saltar bloque
│   ├── transcriber.py           # bucle de conexiones, política de reintento, corte en SegmentTracker
│   └── main.py                  # ScenarioState (reconnecting, contadores), supervisor, filtro de finales vacíos
└── gateway/
    ├── main.py                  # RecentFinals ignora finales vacíos
    └── static/
        ├── index.html           # no dibuja finales vacíos
        └── overlay.html         # ídem
tests/
├── test_reconnect_policy.py     # + espera antes de cada intento y decisión tras un fallo
├── test_scenario_state.py       # + estado y contadores de la reconexión
├── test_config.py               # variables nuevas
├── test_segment_tracker.py      # corte de conexión y final vacío
├── test_audio_clock.py          # saltar bloque
├── test_schema.py               # predicado "final vacío"
├── test_recent_finals.py        # no guarda finales vacíos
└── test_env_example.py          # unión de los contratos de 001 y 002
```

`worker/translator.py`, `worker/publisher.py`, `Dockerfile`, `docker-compose.yml` y `pyproject.toml` no
cambian.

**Decisión de estructura**: la de §5 y §13, sin módulos nuevos en `src/`. Las reglas puras de la
reconexión quedan en `transcriber.py`, junto a `should_force_cut`, porque mantener la sesión Live ya es
responsabilidad del Transcriptor (R2). Los dos scripts nuevos siguen el patrón de `scripts/t0/` y
`scripts/replay_events.py`: herramientas de desarrollo fuera de la imagen.

## Cobertura de requisitos por módulo

| Módulo | RF que cubre |
| --- | --- |
| `common/config.py` | RF-006, RF-007 (lectura, valores por defecto y validación al arrancar); RF-023 (`LIVE_SESSION_MAX_S`) |
| `common/schema.py` | RF-014 (predicado "final vacío" compartido por worker y gateway) |
| `worker/transcriber.py`, bucle de conexiones | RF-001, RF-002, RF-003 y RF-004 (lanza el abandono), RF-005, RF-007 (límite por intento), RF-008 (marca de corte), RF-010 (descartador y `gap_ms`), RF-016 (latencia solo con bloques enviados), RF-020 (eventos de log), RF-022 (compite con el fin de la fuente), RF-023 (temporizador) |
| `worker/transcriber.py`, política pura | RF-002, RF-003, RF-004, RF-005, RF-006 (cálculo con los valores configurados) |
| `worker/transcriber.py`, `SegmentTracker` | RF-012 (numeración continua), RF-013, RF-014 (final vacío y ancla del inicio) |
| `worker/ingest.py` (`AudioClock`) | RF-011 (saltar bloque); RF-009 se cumple sin cambios: la ingesta no se entera de la reconexión |
| `worker/main.py` | RF-004 (supervisor: `error` sin sumar otro error; el `TaskGroup` cancela la ingesta), RF-012 (no crea ejecución), RF-014 y RF-015 (no envía el final vacío a los traductores; las colas no se tocan), RF-017, RF-018, RF-019 (`ScenarioState`), RF-021 (estado por escenario), RF-022 (`stopped` o vuelta nueva) |
| `gateway/main.py` | RF-014 (`RecentFinals` no guarda finales vacíos) |
| `gateway/static/index.html`, `overlay.html` | RF-014 (no dibujan el final vacío), RF-012 (la pantalla no se limpia con el mismo `run_id`); CE-009 |
| `.env.example`, `tests/test_env_example.py` | RF-006, RF-007, RF-023 (plantilla del operador) |
| `scripts/replay_events.py` | Verificación de RF-012 y RF-014 en la vista (quickstart R3) |
| `scripts/reconnect_check.py` | Verificación de RF-004, RF-019, RF-021 y RF-022 (CE-007, CE-008; quickstart R4–R6) |
| `scripts/t0/reconnect_probe.py` | Sin RF: confirma los supuestos de RF-002, RF-007 y CE-002 (T0R) |
| `docs/architecture.md`, `README.md` | Documentación del comportamiento y las variables (Supuestos de la spec; `AGENTS.md`) |

Todos los RF (RF-001 a RF-023) quedan cubiertos por al menos un módulo de `src/`.

## Estrategia de tests

**Pytest: funciones puras, escritas antes de la implementación (principio 10).**

| Archivo | Qué prueba | RF |
| --- | --- | --- |
| `test_reconnect_policy.py` (+) | **Cálculo de esperas**: 0 ms antes del primer intento; 500, 1000, 2000, 4000 con los valores por defecto; se duplica hasta el tope y nunca lo supera; secuencia no decreciente; con inicial = máximo, todas las esperas iguales. **Decisión de reintento**: reintenta mientras fallos < máximo; abandona al llegar al máximo; con máximo = 1, abandona al primer fallo; una cuenta nueva (después de un éxito) vuelve a empezar sin espera | RF-002, RF-003, RF-004, RF-005, RF-006 |
| `test_config.py` | **Validación de configuración**: valores por defecto de las cinco variables; vacías = por defecto; límites inferiores y superiores aceptados y rechazados (`RECONNECT_MAX_ATTEMPTS` 0, `RECONNECT_BACKOFF_INITIAL_MS` 99, `RECONNECT_ATTEMPT_TIMEOUT_S` 0,5 y 121, `LIVE_SESSION_MAX_S` 0 o no entero); máximo < inicial rechazado con un mensaje que nombra `RECONNECT_BACKOFF_MAX_MS` | RF-006, RF-007, RF-023 |
| `test_segment_tracker.py` | **Final vacío**: corte con frase abierta → final con `text=""`, mismo `segment_id` y `start_ms`, `end_ms` = posición del corte, `revision` mayor que la del último parcial, `latency_ms` nulo; `segment_id` avanza y `sequence` sigue. Corte sin frase abierta → nada y numeración igual. Corte tras un corte forzado sin final → se descarta igual. La frase siguiente empieza en un bloque enviado después del corte (nunca antes) y su `revision` arranca en 0. Dos cortes seguidos no repiten `segment_id` | RF-012, RF-013, RF-014, CE-004 |
| `test_audio_clock.py` | Saltar un bloque avanza la posición sin hora de envío ni voz; el bloque registrado después queda en la posición real; la latencia de §8 y la búsqueda de voz o silencio ignoran lo saltado | RF-011, RF-016 |
| `test_scenario_state.py` (+) | `reconnecting` no se pisa con la regla `starting → live`; éxito → `live` y `reconnects + 1`; fallo → `errors + 1` y `last_error`; `last_error` se conserva tras un éxito; `reconnects` no vuelve a 0 entre vueltas; el abandono no suma otro error | RF-017, RF-018, RF-019, RF-004 |
| `test_schema.py` | El predicado reconoce solo finales originales con texto vacío; no confunde parciales ni traducciones | RF-014 |
| `test_recent_finals.py` | Un final vacío no entra entre las últimas frases y no desplaza a las anteriores | RF-014 |
| `test_env_example.py` | `.env.example` tiene la unión de los contratos de 001 y 002 con sus valores por defecto | RF-006, RF-007, RF-023 |

Las partes asíncronas (bucle de conexiones, descartador, temporizador) no se prueban con mocks de
Gemini (`AGENTS.md`). Se verifican con el servicio real en los escenarios siguientes.

**Integración con `LIVE_SESSION_MAX_S=60`** (detalle en [quickstart.md](quickstart.md)):

| Escenario | Qué verifica |
| --- | --- |
| R1: `docker compose up` con `LIVE_SESSION_MAX_S=60` y los clips de 135 s en loop (2 reconexiones por vuelta) | RF-001, RF-002, RF-008, RF-010 a RF-016 y RF-020; CE-002, CE-003, CE-004 y CE-006 |
| R2: `/api/status` cada 1 s durante R1 | RF-017, RF-018; CE-005 |
| R3: `replay_events.py` y la vista durante R1 | RF-012, RF-014; CE-009 |
| R4–R6: `scripts/reconnect_check.py` (A con `LIVE_SESSION_MAX_S=60`, B sin él; credencial inválida desde la reconexión) | RF-003, RF-004, RF-019, RF-021, RF-022; CE-007, CE-008 |
| R7: fuente de 30 min sin loop, `LIVE_SESSION_MAX_S` vacío | RF-001 con cierres reales; CE-001, CE-002, CE-004, CE-006 |
| R8: `docker compose stop worker` durante una reconexión | Caso borde: el estado expira, nunca queda `live` |
| R9: clon limpio | Principio 12 |

## Actualización de `docs/architecture.md` (parte de la feature)

Se hace en la misma feature (`AGENTS.md`), después de implementar y antes de la validación final. Solo
cambian estas tres secciones:

| Sección | Cambio |
| --- | --- |
| §6.2.5 Reconexión | Pasa de una línea de intención a la regla completa, referenciando §6.1.6 y §7.2 en lugar de repetirlos. Cubre: qué cierre la dispara (R3); corte en el instante de detección y resultados tardíos ignorados (R4); audio descartado con el reloj avanzando y `gap_ms` (R5, R6); frase abierta → final vacío, que no se traduce, no entra en las últimas frases y que el historial y la exportación (P1) tampoco deberán incluir (R7, R8); primer intento inmediato, espera exponencial con tope, tiempo límite por intento y `error` tras el máximo (R2, R9); el fin de la fuente prevalece (R10); estado `reconnecting` y contador (R11); `LIVE_SESSION_MAX_S` solo para pruebas (R12). Reanudación y pre-apertura siguen en P2 |
| §7.7 Variables de entorno | Cinco filas nuevas: `RECONNECT_MAX_ATTEMPTS`, `RECONNECT_BACKOFF_INITIAL_MS`, `RECONNECT_BACKOFF_MAX_MS`, `RECONNECT_ATTEMPT_TIMEOUT_S` y `LIVE_SESSION_MAX_S`, con los valores de [contracts/env.md](contracts/env.md) y referencia a §6.2.5 |
| §9 Errores y recuperación | La fila "Se cierra la sesión Live" pasa a: estado `reconnecting`; reintentos con espera progresiva; `error` con la causa tras `RECONNECT_MAX_ATTEMPTS`; se acepta un hueco breve, que se mide; los demás escenarios siguen. Prioridad P1, implementada en `002-reconexion`. La fila P2 "Cierre anticipado de la Live API" no cambia |

Fuera de esas tres secciones no se toca nada en esta feature sin pedido explícito. Al cerrar la
validación se **proponen** dos cambios, que necesitan el OK del responsable: subir la versión del
documento (0.5 → 0.6) y marcar el criterio P1 de §15 "La sesión continúa tras un cierre de la conexión
Live".

## Complexity Tracking

Sin violaciones de la constitución que justificar.
