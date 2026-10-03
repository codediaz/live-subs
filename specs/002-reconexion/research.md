# Investigación: Reconexión de la transcripción

**Feature**: `002-reconexion` | **Plan**: [plan.md](plan.md) | **Spec**: [spec.md](spec.md)

Base de diseño: `docs/architecture.md` §6.1.6 (descarte durante la reconexión), §6.2 (transcripción),
§7.2 (`SessionStatus`), §8 (latencia) y §9 (errores). Este documento no los repite: solo registra las
decisiones nuevas y lo que se mide en el probe.

## Punto de partida (código del MVP)

- `worker/transcriber.py::transcribe()` abre **una** sesión Live y, si se cierra, lanza
  `LiveSessionClosed`. El supervisor (`worker/main.py::run_scenario`) la convierte en estado `error`.
- `worker/main.py::_run_once()` crea por ejecución el `run_id`, la cola de audio, el `AudioClock`, el
  `SegmentTracker` y los traductores. La ingesta y la transcripción corren en un `TaskGroup`.
- `ScenarioState` no conoce `reconnecting` y publica `reconnects=0` fijo.
- El gateway (`RecentFinals`) y los clientes (`index.html`, `overlay.html`) guardan y muestran todo
  final, sin importar su texto.
- No existe todavía el historial en Redis ni la exportación (§7.5 `hist:*` es P1): la parte de RF-014
  que los nombra queda como regla de diseño para cuando se implementen (ver R8).

## Verificado en el SDK

En `google-genai` 2.25.0 (`google/genai/live.py`), `client.aio.live.connect()` envía el setup y
**espera la primera respuesta del servidor** (`setup_complete`) antes de entregar la sesión; si el
servidor cierra durante el setup, lanza un error de la API con el código de cierre. Un cierre posterior
termina la iteración de `session.receive()` o lanza el error de cierre de `websockets`. Por eso "la
conexión queda lista para recibir audio" (RF-005) equivale a que `connect()` entregó la sesión. El probe
T0R confirma los tiempos y el comportamiento observado.

## Decisiones

### R1. La reconexión vive dentro del Transcriptor, en la misma ejecución

- **Decisión**: `transcribe()` pasa a ser un bucle de conexiones Live sobre los mismos objetos de la
  ejecución (cola de audio, `AudioClock`, `SegmentTracker`, `on_event`). La ingesta, los traductores y el
  `run_id` no se enteran de la reconexión.
- **Por qué**: es la única forma de cumplir RF-009 (la ingesta no se reinicia), RF-011 (el reloj sigue)
  y RF-012 (`run_id`, `sequence` y `segment_id` continúan) sin coordinar componentes. Coincide con la
  responsabilidad del Transcriptor en §5 ("mantener la sesión Live").
- **Descartada**: que el supervisor vuelva a llamar a `_run_once()`. Crearía un `run_id` nuevo, un
  `ffmpeg` nuevo y reiniciaría la numeración: los clientes limpiarían la pantalla (§6.4.4), contra
  RF-009, RF-012 y la historia 1.

### R2. Política de reintento: función pura, exponencial con tope y sin jitter

- **Decisión**: dos funciones puras en `worker/transcriber.py`, junto a `should_force_cut`:
  - **espera antes del intento n**: 0 ms para el primero (RF-002); para n ≥ 2,
    `min(RECONNECT_BACKOFF_INITIAL_MS × 2^(n−2), RECONNECT_BACKOFF_MAX_MS)` (RF-003, RF-006). Con los
    valores por defecto: 0, 500, 1000, 2000, 4000 ms;
  - **decisión tras un fallo**: reintentar si los fallos consecutivos son menos que
    `RECONNECT_MAX_ATTEMPTS`; si no, abandonar (RF-004). La cuenta es por reconexión y vuelve a cero con
    cada éxito (RF-005).
- **Por qué**: son las reglas que más se pueden romper sin que la integración lo note; puras se prueban
  con pytest en milisegundos. Sin jitter, las esperas son deterministas y no decrecientes, como exige
  CE-008.
- **Descartada (jitter)**: evita que muchos clientes reintenten a la vez contra un servicio, pero un
  worker tiene pocos escenarios, cada uno reintenta por su cuenta, y el jitter puede dar esperas
  decrecientes (CE-008) y tests no deterministas.
- **Descartada (módulo nuevo `worker/reconnect.py`)**: obligaría a cambiar §5 y §13 de la arquitectura
  por dos funciones pequeñas. `should_force_cut` ya marca el patrón: reglas puras del Transcriptor en su
  propio módulo.

### R3. Qué cuenta como cierre de la conexión

- **Decisión**: cualquier final de la conexión mientras la fuente sigue activa: `receive()` termina sin
  mensajes, error de cierre de `websockets` o de la API (cualquier código), o una falla al enviar audio.
  La cancelación (worker que se detiene) **no** cuenta: se propaga sin reconectar. El aviso `go_away`
  del servidor solo se registra en DEBUG con su `time_left`.
- **Por qué**: la spec trata igual el límite de duración y las fallas (Supuestos); distinguir códigos no
  cambia la acción. El `go_away` serviría para pre-abrir la conexión, que es P2 (Fuera de alcance), pero
  registrarlo deja el dato para esa feature.
- **Descartada (reaccionar al `go_away`)**: es pre-apertura (P2).
- **Descartada (solo cierres limpios, código 1000)**: una caída de red dejaría el escenario en `error`
  sin reintentar, contra RF-001 y la historia 3.
- **Fuente terminada**: si el cierre llega cuando la fuente ya terminó y la cola está vacía (durante
  `SOURCE_END_GRACE_MS`), no se reconecta: el escenario termina como en el MVP (RF-001 pide la fuente
  activa).

### R4. Instante del corte e ignorar resultados tardíos (RF-008)

- **Decisión**: cada conexión tiene una marca de corte. Quien detecta el cierre (emisor, receptor o el
  temporizador de R12) la marca **antes de cualquier `await`**, y en ese mismo instante se toman la hora y
  la posición del reloj de audio. El receptor consulta la marca antes de entregar cada resultado al
  `SegmentTracker`. Después se cancelan las tareas de esa conexión y se cierra su contexto.
- **Por qué**: asyncio es cooperativo; una marca puesta sin ceder el control es atómica respecto del
  receptor. Fija el corte en el instante de detección, como pide la spec (Supuestos), y no cuando termina
  la limpieza.
- **Descartada (solo cancelar las tareas)**: el receptor puede estar esperando a Redis dentro de
  `on_event` con un resultado ya leído; al reanudarse, lo entregaría después del corte.

### R5. Audio durante la reconexión: un descartador activo

- **Decisión**: mientras el escenario está en `reconnecting` (intentos y esperas), una tarea del
  Transcriptor vacía la cola de audio: primero los bloques que ya estaban al detectar el corte y después
  los que siguen llegando. Por cada bloque avanza el reloj (R6) y suma `AUDIO_CHUNK_MS` al hueco. Se
  detiene en cuanto la conexión nueva queda lista, así el primer bloque enviado ya es audio actual.
- **Por qué**: cumple RF-009 y RF-010 sin tocar la ingesta, y el hueco (`gap_ms`) es exactamente el
  audio descartado (CE-002).
- **Descartada (dejar que la cola acotada descarte sola)**: al reconectar se enviarían hasta
  `AUDIO_QUEUE_MAX_CHUNKS` bloques viejos (5 s por defecto). Eso retrasa todo lo que sigue (CE-006),
  contradice RF-010, mezcla los descartes de la reconexión con los de la cola (CE-007 cuenta estos
  últimos) y no avanza el reloj.
- **Descartada (guardar y reenviar el audio)**: es rescatar audio, fuera de alcance; RF-010 lo prohíbe.

### R6. El reloj avanza sin registrar bloques enviados

- **Decisión**: `AudioClock` gana una operación para saltar un bloque: avanza la posición
  `AUDIO_CHUNK_MS` sin agregar un bloque con hora de envío ni marca de voz.
- **Por qué**: `start_ms` y `end_ms` posteriores quedan en su posición real (RF-011). La latencia de §8
  usa la hora de envío de bloques **enviados**, así que el tramo descartado no la infla (RF-016), y la
  detección de silencio no confunde audio descartado con silencio.
- **Descartada (registrar los bloques descartados como bloques sin voz)**: falsearía silencios para la
  detección de fin de frase y daría horas de envío a audio que nunca llegó al modelo.
- **Descartada (no avanzar el reloj)**: comprimiría la charla; `start_ms` dejaría de ser la posición
  real (RF-011) y la exportación quedaría desfasada.

### R7. La frase abierta se cierra con un final vacío y el inicio se ancla en el corte

- **Decisión**: el `SegmentTracker` gana una operación de corte de conexión, pura, que recibe la hora y
  la posición del corte:
  - con frase abierta, devuelve un final con texto vacío (RF-014): mismo `segment_id` y `start_ms`,
    `end_ms` igual a la posición del corte, `revision` mayor que la del último parcial y `latency_ms`
    nulo; luego avanza `segment_id` (RF-013);
  - sin frase abierta, no devuelve nada y la numeración no cambia (caso borde "cierre en silencio");
  - en ambos casos, ancla el inicio de la próxima frase en el corte: la siguiente empieza en el primer
    bloque con voz **enviado después** del corte.
- **Por qué**: sin el ancla, la frase siguiente podría tomar como inicio un bloque con voz de antes del
  corte (de la frase descartada o de audio enviado sin parcial). Su `start_ms` quedaría antes del hueco
  y la posición podría retroceder (CE-004).
- **Descartada (no publicar nada)**: el último parcial quedaría en pantalla para siempre (CE-009); el
  cliente no tiene forma de saber que la frase murió.
- **Descartada (publicar el último parcial como final)**: es rescatar la frase (fuera de alcance) y
  traduciría texto incompleto como si fuera una frase.
- **Corte forzado en curso**: si se envió `audio_stream_end` y el final no llegó, la frase sigue abierta
  en el tracker y se descarta igual (caso borde de la spec).

### R8. Un único predicado de "final vacío" para worker, gateway y clientes

- **Decisión**: un predicado en `common/schema.py` (original, final y texto vacío) que usan:
  - el worker, para no agregarlo al contexto de traducción ni enviarlo a los traductores (RF-014,
    RF-015);
  - el gateway, para no guardarlo en `RecentFinals` (RF-048 del MVP).

  Las vistas (`index.html`, `overlay.html`) aplican la misma regla en JS: guardan el evento en la fusión
  (para que un parcial tardío con `revision` menor no reviva la frase) pero no lo dibujan. El historial y
  la exportación (P1) deberán usar el mismo predicado; queda escrito en §6.2.5.
- **Por qué**: es una regla del contrato (`SubtitleEvent` sin cambios) y conviene que haya una sola
  definición en Python.
- **Descartada (campo nuevo, por ejemplo `discarded: true`)**: cambio de contrato y `schema_version`;
  la spec pide no cambiar `SubtitleEvent`.
- **Descartada (no publicar el final y que los clientes expiren parciales viejos)**: obliga a un timeout
  arbitrario en el cliente y deja el parcial visible hasta que vence.

### R9. "Lista para recibir audio" y tiempo límite de cada intento

- **Decisión**: un intento tiene éxito cuando `connect()` entrega la sesión (incluye `setup_complete`,
  ver "Verificado en el SDK"). `RECONNECT_ATTEMPT_TIMEOUT_S` limita solo esa apertura (RF-007). Si vence,
  el intento cuenta como fallido y la conexión a medio abrir se cierra.
- **Descartada (esperar el primer parcial para dar la reconexión por buena)**: en silencio nunca llega;
  la reconexión quedaría colgada o contaría como fallida.

### R10. El fin de la fuente prevalece sobre la reconexión (RF-022)

- **Decisión**: cada intento y cada espera compiten con el aviso de fin de fuente que ya existe
  (`source_done`). Si la fuente termina primero, se cancela el intento o la espera y `transcribe()`
  vuelve sin error: el supervisor sigue el camino normal (`stopped`, o vuelta nueva con `loop`). Las
  traducciones pendientes se drenan como en el MVP.
- **Descartada (terminar el intento en curso y revisar después)**: si ese era el último intento y
  fallaba, el escenario pasaría a `error`, contra RF-022.

### R11. Estado y contadores: callbacks del Transcriptor a `ScenarioState`

- **Decisión**: el Transcriptor avisa por callbacks, el mismo patrón que `on_error` del traductor:
  - reconexión iniciada → `reconnecting`;
  - intento fallido → `errors + 1` y `last_error` con la causa;
  - éxito → `live` y `reconnects + 1`.

  Al agotar los intentos lanza un error de abandono con la causa del último fallo. El supervisor lo
  convierte en `error` **sin sumar otro error**, porque ese fallo ya se contó (RF-019); el `TaskGroup`
  cancela la ingesta (RF-004). `reconnects` vive en `ScenarioState`, que dura lo mismo que el worker, así
  que las vueltas con loop no lo reinician (Supuestos). La regla `starting → live` del snapshot no debe
  pisar `reconnecting`.
- **Descartada (que el Transcriptor escriba el estado en Redis)**: rompería la separación de §5, donde
  solo el Publicador habla con Redis.
- **Descartada (contar también el abandono como un error más)**: con N intentos, `errors` daría N + 1 y
  no coincidiría con los eventos `reconnect_attempt_failed`.

### R12. `LIVE_SESSION_MAX_S`: temporizador por conexión, mismo camino de cierre

- **Decisión**: si la variable tiene valor, cada conexión arranca un temporizador cuando queda lista.
  Al vencer, marca el corte (R4) con motivo `max_session` y sigue el mismo camino que un cierre del
  servidor (RF-023).
- **Descartada (cerrar desde el supervisor)**: daría un segundo camino de cierre que la prueba no
  ejercitaría igual que el real.
- **Descartada (provocar cortes de red)**: no es reproducible ni portable entre máquinas.

### R13. Validación de las variables nuevas al arrancar

- **Decisión**: los rangos de RF-006 y RF-007 se validan en `WorkerSettings`, igual que el resto. La
  regla "espera máxima ≥ espera inicial" es una validación cruzada y su mensaje nombra
  `RECONNECT_BACKOFF_MAX_MS` (hoy `from_env` toma el nombre de la variable del primer error de campo;
  la validación cruzada debe nombrarla explícitamente). `LIVE_SESSION_MAX_S` vacío equivale a no
  configurado; con valor, debe ser un entero ≥ 1.
- **Spec alineada en S0**: RF-023 fija `LIVE_SESSION_MAX_S` vacío o no definido, o entero ≥ 1; ante un
  valor inválido, el worker no arranca e identifica la variable, como en RF-006.
- **Descartada (validar al usar la variable)**: el worker arrancaría con una configuración inválida y
  fallaría recién en la primera reconexión, contra RF-006 y RF-029 del MVP.

### R14. Contrato de variables de 002 separado del de 001

- **Decisión**: `contracts/env.md` de esta feature lista solo las variables nuevas. `tests/test_env_example.py`
  lee los dos contratos y exige que `.env.example` tenga la unión.
- **Descartada (editar `specs/001-subs-mvp/contracts/env.md`)**: reescribe documentos de una feature
  cerrada y validada (`AGENTS.md`: no reescribir `specs/` sin pedido).

### R15. Verificar aislamiento y falla con un harness de desarrollo

- **Problema**: `LIVE_SESSION_MAX_S` y los modelos son globales al worker. Con dos escenarios en el mismo
  proceso, ambos se reconectan casi a la vez y ninguno puede quedar "inaccesible" solo. Así no se pueden
  medir CE-007 ni CE-008 dentro de un mismo proceso.
- **Decisión**: un script de desarrollo, `scripts/reconnect_check.py`, fuera de la imagen como
  `replay_events.py`. Ejecuta dos escenarios en un mismo proceso con el código real del worker
  (`run_scenario`), Gemini y Redis reales:
  - **aislamiento**: el escenario A recibe una configuración con `LIVE_SESSION_MAX_S=60` y el B sin
    ella (`run_scenario` ya recibe la configuración por parámetro);
  - **falla**: el cliente de A abre su primera conexión con la credencial válida y, desde la
    reconexión, con una credencial inválida. El rechazo lo da el servicio real (el caso "credencial
    revocada" de la historia 3), no un mock;
  - **salida**: un resumen por escenario: eventos de reconexión, transiciones de estado leídas de
    `status:*`, mayor espera entre finales y bloques descartados.
- **Por qué**: mide CE-007, CE-008 y RF-022 en un solo proceso, sin agregar variables de prueba al
  producto ni simular éxitos (`AGENTS.md`).
- **Descartada (variables nuevas en el producto, por ejemplo `LIVE_SESSION_MAX_S` por escenario o una
  lista de escenarios con fallas inyectadas)**: más configuración de producción solo para probar, con
  cambio de spec.
- **Descartada (dos workers con distinto entorno)**: solo prueba aislamiento entre procesos, que es
  trivial; el riesgo real es dentro del proceso.

### R16. Validación de 30 minutos con cierres reales

- **Decisión**: CE-001 se valida con `LIVE_SESSION_MAX_S` vacío y una fuente de ≥ 30 min sin loop:
  audio real en `samples/local/` o el clip del repo repetido con ffmpeg (sin recodificar) a un archivo de
  `samples/local/`. Se ejecuta con un `docker-compose.override.yml` y un `sessions.local.yaml`; los dos
  ya están en `.gitignore`.
- **Descartada (validar solo con `LIVE_SESSION_MAX_S=60`)**: no ejercita el cierre real del servicio a
  los ~10 min, que es el motivo de la feature.

### R17. Abandono: se cancelan las traducciones pendientes

- **Decisión**: al abandonar, el error se propaga como cualquier error del MVP: se cancelan la ingesta
  y los traductores. La spec no pide drenar traducciones en ese caso (CE-003 habla de reconexiones con
  éxito).
- **Descartada (drenar las traducciones antes de pasar a `error`)**: suma otro camino de espera para un
  caso final que no lo pide.

### R18. Sin dependencias nuevas

`asyncio` y `google-genai` 2.25.0 alcanzan (temporizadores, `wait_for`, cancelación). No cambian
`pyproject.toml`, `Dockerfile` ni `docker-compose.yml`. El worker ya recibe todo `.env` (`env_file`), así
que las variables nuevas llegan sin tocar Compose.

## T0R. Probe previo de reconexión (descartable)

Tarea previa a la implementación, en `scripts/t0/reconnect_probe.py`. Sigue las reglas de
`scripts/t0/README.md`: sin tests, fuera de la imagen, salida cruda en `scripts/t0/out/` (ignorada por
git). **Límite de tiempo: 30 min** (`AGENTS.md`: preguntar si se excede).

**Configuración**: la misma de la sesión Live del producto (`TRANSCRIBE_MODEL`, idioma, vocabulario,
VAD, `VERBATIM`; §6.2.1) y `samples/audio/charla_en.ogg` (135 s) a ritmo real.

| Paso | Qué hace | Qué mide |
| --- | --- | --- |
| 1. Aperturas | Abre y cierra 10 conexiones seguidas, sin audio | Tiempo desde la llamada a `connect()` hasta que entrega la sesión: p50, p95 y máximo. Tiempo de cierre |
| 2. Relevo con corte propio | Transmite el clip y cierra la conexión desde el cliente cada 60 s (lo que hará `LIVE_SESSION_MAX_S=60`). Descarta el audio durante la apertura de la nueva, como en R5 | Por cada relevo: detección → lista (ms), audio descartado (ms), tiempo hasta el primer parcial y el primer final de la conexión nueva, resultados de la conexión vieja que llegan después del corte |
| 3. Continuidad | En el mismo paso 2, compara los finales con el guion `charla_en.txt` | Que la conexión nueva transcribe normal desde su primera frase (sin "arranque en frío") y que solo se pierde el tramo del hueco y la frase abierta |
| 4. Opcional | Una sola conexión con el clip en loop durante 11 min, sin corte propio | Instante y código del cierre real, `go_away` y su `time_left`. Solo si sobra tiempo; CE-001 lo cubre igual |

**Reglas de decisión** (se registran en "Resultados del probe"):

- p95 de apertura ≤ 1500 ms → se mantienen RF-002 y los valores por defecto; CE-002 (< 2 s) es
  alcanzable. Si p95 > 1500 ms, CE-002 está en riesgo por un límite externo: **se detiene y se consulta**
  antes de implementar (`AGENTS.md`).
- Máximo de apertura < `RECONNECT_ATTEMPT_TIMEOUT_S` / 2 (5 s) → se mantiene el valor por defecto de
  10 s; si no, se registra y se consulta.
- Si en el paso 2 llegan resultados de la conexión vieja después del corte, queda confirmada la marca de
  R4. Si no llegan, R4 se mantiene igual, como defensa.
- Si la conexión nueva tarda en su primer final más que los objetivos de §8, se registra: CE-006 está
  en riesgo y se consulta.
- Si el corte desde el cliente no permite abrir otra conexión de inmediato (por ejemplo, por un límite
  de sesiones concurrentes), R12 y RF-002 se revisan antes de implementar.

**Hecho cuando**: "Resultados del probe" tiene los números de los pasos 1 a 3 y la decisión de cada
regla, o se cumplieron los 30 min (en ese caso se registra lo medido y se consulta).

## Resultados del probe

*(Se completa al ejecutar T0R.)*

| Medida | Valor | Decisión |
| --- | --- | --- |
| Apertura p50 / p95 / máx. (ms) | — | — |
| Cierre (ms) | — | — |
| Relevo: detección → lista (ms), por relevo | — | — |
| Relevo: audio descartado (ms), por relevo | — | — |
| Primer parcial / primer final tras el relevo (ms) | — | — |
| Resultados tardíos de la conexión vieja | — | — |
| Cierre real (opcional): instante, código, `go_away` | — | — |
