# Especificación de la feature: Reconexión de la transcripción

**Rama de la feature**: `002-reconexion`

**Creada**: 2026-10-02

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Feature 002-reconexion: cuando la sesión Live se cierra (las
conexiones duran unos 10 min) o falla, el worker abre una nueva y continúa sin detener la ingesta, para
soportar charlas de cualquier duración. Usa docs/architecture.md §6.2.5 y §9 como base. Incluye: estado
"reconnecting" visible en /api/status mientras se reconecta, y un contador de reconexiones; numeración
de frases continua: sequence y segment_id no se reinician y run_id no cambia; un parcial abierto al
momento del corte se descarta; el audio que llega durante la reconexión se descarta y el reloj de audio
sigue avanzando; reintento con espera progresiva si la reconexión falla, y estado "error" tras un
número máximo de intentos configurable; la reconexión de un escenario nunca afecta a los demás.
Criterios de éxito: una charla de 30 min se subtitula completa, con huecos de menos de 2 s por
reconexión. Fuera de alcance: reanudación de sesión y pre-apertura sin huecos (P2). Solo el QUÉ y el
POR QUÉ. Escribe en español."

> **Contexto.** Esta feature corresponde a la fila "Se cierra la sesión Live" (P1) de
> `docs/architecture.md` §9 y al punto §6.2.5. El MVP (`001-subs-mvp`) no reconecta: cada conexión de
> transcripción dura unos 10 minutos y, al cerrarse, el escenario queda en error. Por eso hoy solo
> funcionan clips de menos de 10 minutos. Una charla real dura de 20 a 60 minutos, así que sin esta
> feature el producto no sirve en una conferencia.
>
> `SubtitleEvent` (`sequence`, `segment_id`, `run_id`, `start_ms`), `SessionStatus` (`state`,
> `reconnects`) y `/api/status` se nombran porque son interfaces del producto ya definidas en
> `docs/architecture.md` §7, no decisiones de implementación.

## Escenarios de usuario y pruebas *(obligatorio)*

### Historia de usuario 1 - El espectador sigue una charla larga sin interrupciones (Prioridad: 1)

Una persona en la audiencia lee los subtítulos (original o traducción) de una charla de 30 minutos o
más. Cuando la conexión de transcripción llega a su límite y se renueva, a lo sumo se pierde un instante
de la charla: los subtítulos siguen apareciendo en la misma pantalla, en orden, sin que la vista se
limpie ni haya que recargar la página.

**Por qué esta prioridad**: es el motivo de la feature. Sin reconexión, el subtitulado se corta a los
~10 minutos de cada charla y el producto no es usable en un evento real.

**Prueba independiente**: correr un escenario con una fuente de al menos 30 minutos y mirar la vista de
audiencia y la pista de traducción de punta a punta: hay frases finales hasta el final de la charla, la
pantalla nunca se limpia y el tramo perdido en cada reconexión que tiene éxito en su primer intento es
menor a 2 segundos de audio.

**Escenarios de aceptación**:

1. **Dado** un escenario que transcribe una charla en curso, **cuando** se cierra su conexión de
   transcripción, **entonces** el sistema abre una conexión nueva y los subtítulos siguen apareciendo
   sin reiniciar la ingesta de audio.
2. **Dado** un espectador mirando la pista original o una traducción, **cuando** ocurre una
   reconexión, **entonces** las frases nuevas se agregan a continuación de las anteriores, sin que la
   pantalla se limpie (la ejecución es la misma) y sin repetir ni reemplazar frases ya mostradas.
3. **Dado** que el speaker estaba a mitad de una frase al momento del corte, **cuando** se completa la
   reconexión, **entonces** esa frase incompleta se cierra con un final vacío, no se traduce y deja de
   verse en pantalla; la siguiente frase aparece como una frase nueva.
4. **Dado** que había frases finales esperando traducción al momento del corte, **cuando** ocurre la
   reconexión, **entonces** esas traducciones se publican igual.
5. **Dado** dos escenarios activos, **cuando** uno de ellos se reconecta, **entonces** el otro sigue
   publicando subtítulos sin pausa ni cambio de estado.

---

### Historia de usuario 2 - El operador ve cuándo un escenario se está reconectando (Prioridad: 2)

La persona de producción consulta el estado de los escenarios. Mientras uno renueva su conexión de
transcripción, lo ve en estado "reconectando"; al terminar, vuelve a "en vivo" y un contador le dice
cuántas reconexiones lleva ese escenario.

**Por qué esta prioridad**: un hueco breve en los subtítulos es aceptable, pero el operador necesita
distinguirlo de una falla real para no intervenir sin motivo, y detectar un escenario que se reconecta
demasiado seguido.

**Prueba independiente**: con un escenario activo, provocar o esperar el cierre de su conexión de
transcripción y consultar `/api/status` durante y después de la reconexión.

**Escenarios de aceptación**:

1. **Dado** un escenario en vivo, **cuando** su conexión de transcripción se cierra, **entonces**
   `/api/status` muestra ese escenario en estado `reconnecting` hasta que la conexión nueva está
   lista.
2. **Dado** un escenario en `reconnecting`, **cuando** la conexión nueva queda lista, **entonces** el
   estado vuelve a `live` y el contador de reconexiones sube en uno.
3. **Dado** un escenario que ya se reconectó N veces, **cuando** se consulta su estado, **entonces** el
   contador muestra N.

---

### Historia de usuario 3 - Una reconexión imposible termina en un error visible (Prioridad: 3)

Si el servicio de transcripción no responde (caída de red, servicio no disponible, credencial
revocada), el sistema reintenta con esperas cada vez más largas para no saturar el servicio. Si después
de la cantidad máxima de intentos configurada sigue sin poder conectar, el escenario pasa a error con
la causa, y los demás escenarios siguen funcionando.

**Por qué esta prioridad**: protege el caso raro pero grave. Reintentar sin fin ocultaría una falla
permanente; reintentar sin espera saturaría el servicio y la cuota compartida por todos los escenarios.

**Prueba independiente**: con dos escenarios activos, impedir que uno de ellos se conecte al servicio
de transcripción (por ejemplo, con una configuración de intentos baja y una conexión inaccesible) y
verificar los intentos, las esperas, el estado final `error` con su causa y que el otro escenario no se
ve afectado.

**Escenarios de aceptación**:

1. **Dado** un escenario en `reconnecting`, **cuando** un intento de reconexión falla, **entonces** el
   sistema espera antes del intento siguiente y cada espera es igual o mayor que la anterior, hasta un
   máximo.
2. **Dado** un escenario que ya falló la cantidad máxima de intentos consecutivos, **cuando** falla el
   último, **entonces** el escenario pasa a `error` con la causa del último fallo y no reintenta más.
3. **Dado** un escenario que falló algunos intentos pero no el máximo, **cuando** un intento tiene
   éxito, **entonces** el escenario vuelve a `live` y la próxima vez que se cierre la conexión empieza
   de nuevo con la cuenta de intentos en cero.
4. **Dado** un escenario que reintenta o quedó en `error`, **cuando** se consulta el resto de los
   escenarios, **entonces** siguen en su estado normal y publicando subtítulos.

---

### Casos borde

- **Cierre en silencio**: si la conexión se cierra sin ninguna frase abierta, no se descarta nada y la
  numeración sigue igual.
- **Cierre justo después de un final**: el final ya publicado se conserva y se traduce; solo se descarta
  lo que estaba abierto.
- **Cierres seguidos**: una conexión nueva que se cierra apenas abierta se trata como otro cierre: se
  vuelve a reconectar y el contador sube. Si el cierre ocurre antes de que la conexión quede lista, cuenta
  como intento fallido.
- **La fuente termina mientras el escenario se reconecta, incluso en su último intento**: prevalece el
  fin de la fuente (RF-022): el escenario pasa a `stopped` y se abandonan los intentos pendientes; nunca
  pasa a `error` por esa reconexión.
- **Fin de vuelta de un clip con loop mientras el escenario se reconecta, incluso en su último
  intento**: prevalece el fin de la vuelta (RF-022): se abandona la reconexión y empieza la vuelta nueva
  como en el MVP (ejecución nueva, conexión nueva); nunca pasa a `error` por esa reconexión.
- **El worker se detiene durante la reconexión**: los intentos pendientes se cancelan sin dejar el
  escenario en un estado falso de "en vivo" (el estado expira como en el MVP).
- **Corte forzado en curso**: si la conexión se cierra justo después de un corte forzado de frase y
  antes de recibir su final, esa frase cuenta como abierta y se descarta.
- **Falla permanente (credencial inválida, modelo inexistente)**: se agotan los intentos y el escenario
  queda en `error` con esa causa; no se distingue de una falla transitoria.
- **Varios escenarios se reconectan a la vez** (por ejemplo, porque arrancaron juntos y sus conexiones
  vencen a la par): cada uno se reconecta por su cuenta, sin esperar a los demás.

## Requisitos *(obligatorio)*

Formato EARS: *El sistema deberá…* (siempre), *Cuando…* (evento), *Mientras…* (estado),
*Si…, entonces…* (condición no deseada), *Donde…* (opción configurada).

### Requisitos funcionales

**Reconexión**

- **RF-001**: Cuando se cierra la conexión de transcripción de un escenario (por su límite de duración
  o por una falla) y su fuente sigue activa, el sistema deberá abrir una conexión de transcripción nueva
  y continuar subtitulando la misma charla.
- **RF-002**: Cuando se cierra la conexión de transcripción, el sistema deberá hacer el primer intento
  de reconexión sin espera previa.
- **RF-003**: Si un intento de reconexión falla, entonces el sistema deberá esperar antes del intento
  siguiente, con esperas que crecen intento a intento hasta un tope.
- **RF-004**: Si fallan seguidos la cantidad máxima de intentos configurada, entonces el sistema deberá
  pasar el escenario a estado `error` con la causa del último fallo, dejar de reintentar y detener la
  ingesta de ese escenario. Mientras el worker siga corriendo, el sistema deberá seguir publicando el
  estado `error` y su causa en `/api/status`, aunque el escenario esté detenido.
- **RF-005**: Cuando una conexión nueva queda lista para recibir audio, el sistema deberá dar la
  reconexión por exitosa y volver a cero la cuenta de intentos fallidos.
- **RF-006**: Donde el operador configure la cantidad máxima de intentos (`RECONNECT_MAX_ATTEMPTS`, un
  entero mayor o igual a 1, por defecto 5), la espera inicial entre intentos
  (`RECONNECT_BACKOFF_INITIAL_MS`, mayor o igual a 100, por defecto 500) y la espera máxima
  (`RECONNECT_BACKOFF_MAX_MS`, mayor o igual que la espera inicial, por defecto 8000), el sistema deberá
  usar esos valores, duplicando la espera en cada intento sucesivo hasta llegar al máximo; sin
  configuración, deberá usar los valores por defecto. Si alguno de estos valores no cumple su
  condición, entonces el worker no deberá arrancar e indicará la variable con el error, igual que RF-029
  del MVP (`001-subs-mvp`).
- **RF-007**: Si un intento de reconexión no obtiene respuesta en `RECONNECT_ATTEMPT_TIMEOUT_S` (entre
  1 y 120 s, por defecto 10 s), entonces el sistema deberá darlo por fallido y seguir con el intento
  siguiente según RF-003. Si el valor está fuera de ese rango, entonces el worker no deberá arrancar e
  indicará la variable con el error, igual que en RF-006.
- **RF-008**: Cuando se detecta el cierre de una conexión de transcripción, el sistema deberá tomar ese
  instante como el corte: cualquier resultado que llegue después desde esa conexión (un parcial, un
  final u otro evento) deberá ignorarse.

**Ingesta y reloj de audio durante la reconexión**

- **RF-009**: Mientras un escenario se reconecta, el sistema deberá seguir recibiendo el audio de la
  fuente sin detener ni reiniciar la ingesta.
- **RF-010**: Mientras un escenario se reconecta, el sistema deberá descartar el audio que llega, sin
  guardarlo para enviarlo después, y registrar la cantidad descartada en milisegundos. El audio que ya
  estaba en la cola de ingesta al detectarse el cierre (RF-008) también deberá descartarse y contarse. El
  hueco de una reconexión es la suma del audio descartado y deberá registrarse como `gap_ms` en el evento
  `reconnect_succeeded` (RF-020).
- **RF-011**: Mientras un escenario se reconecta, el reloj de audio deberá seguir avanzando, de modo que
  la posición en la charla (`start_ms`, `end_ms`) de las frases posteriores sea su posición real, con el
  tramo descartado incluido.

**Continuidad de los subtítulos**

- **RF-012**: Cuando un escenario se reconecta, el sistema deberá conservar la misma ejecución
  (`run_id`) y continuar `sequence` y `segment_id` desde el último valor usado, sin reiniciarlos ni
  repetirlos. `sequence` deberá ser estrictamente creciente dentro de una ejecución; dos frases
  distintas nunca deberán compartir `segment_id`, pero los parciales, el final y las traducciones de una
  misma frase sí lo comparten.
- **RF-013**: Si al cerrarse la conexión hay una frase abierta (con parciales y sin final), entonces el
  sistema deberá descartarla: no publica su texto como final ni la traduce, y la siguiente frase usa un
  `segment_id` nuevo.
- **RF-014**: Cuando se descarta una frase abierta, el sistema deberá publicar en la pista `original` un
  final con texto vacío para ese `segment_id`, con el mismo `start_ms` que tenía la frase, con `end_ms` igual a la posición
  del audio en el instante en que se detecta el cierre (RF-008), con `latency_ms` en `null` y con una
  `revision` mayor que la de su último parcial. La vista de audiencia y el overlay deberán ocultar los
  finales vacíos, el traductor no deberá traducirlos, y el final vacío no deberá entrar en las últimas
  frases finales que guarda el gateway (RF-048 del MVP `001-subs-mvp`), ni en el historial, ni en la
  exportación. Esto no cambia el contrato `SubtitleEvent`.
- **RF-015**: Mientras un escenario se reconecta, el sistema deberá seguir traduciendo y publicando las
  frases finales que ya estaban pendientes, sin que la reconexión modifique las colas de traducción: los
  descartes por cola llena o por fallo de traducción siguen las reglas del MVP (`001-subs-mvp`) y son
  independientes de la reconexión.
- **RF-016**: Cuando un escenario se reconecta, el sistema deberá seguir midiendo la latencia de las
  frases nuevas con el mismo criterio que antes del corte, sin que el tramo descartado la infle.

**Estado visible**

- **RF-017**: Mientras un escenario se reconecta (incluidas las esperas entre intentos), el sistema
  deberá informar su estado como `reconnecting` en `/api/status`.
- **RF-018**: Cuando una conexión nueva queda lista para recibir audio, el sistema deberá volver el
  estado a `live` y sumar uno al contador de reconexiones del escenario.
- **RF-019**: Cuando un intento de reconexión falla, el sistema deberá sumar uno al contador de errores
  del escenario y actualizar su última causa de error; esa causa deberá conservarse aunque un intento
  posterior tenga éxito.
- **RF-020**: El sistema deberá registrar en los logs, con el identificador del escenario y sin audio ni
  texto de subtítulos en nivel INFO, un evento `reconnect_started` al detectar el cierre, un evento
  `reconnect_attempt_failed` por cada intento fallido, un evento `reconnect_succeeded` cuando la
  reconexión tiene éxito y un evento `reconnect_abandoned` cuando se agotan los intentos.

**Aislamiento**

- **RF-021**: El sistema deberá reconectar cada escenario de forma independiente: el cierre, los
  reintentos o el error de un escenario no deberán pausar, demorar, reconectar ni cambiar el estado de
  ningún otro.
- **RF-022**: Si el fin de la fuente ocurre mientras un escenario se reconecta o durante su último
  intento, entonces el sistema deberá priorizar el fin de la fuente: el escenario pasa a `stopped` (o,
  con `loop`, empieza una ejecución nueva) y nunca a `error` por esa reconexión.

**Prueba**

- **RF-023**: Donde se configure `LIVE_SESSION_MAX_S` (vacío por defecto), el sistema deberá cerrar a
  propósito cada conexión de transcripción a los N segundos de abierta, para probar la reconexión sin
  esperar el límite real; ese cierre se trata como cualquier otro (RF-001).

### Entidades clave

- **Conexión de transcripción**: el canal con el servicio de transcripción en vivo de un escenario.
  Dura unos 10 minutos; esta feature la renueva todas las veces que haga falta dentro de una misma
  ejecución.
- **Reconexión**: el paso de una conexión cerrada a una nueva dentro de la misma ejecución. Tiene un
  inicio (el cierre), cero o más intentos fallidos con su espera y un final (éxito, abandono por
  máximo de intentos o fin de la fuente).
- **Hueco de reconexión**: el tramo de audio de la charla que no llega a la transcripción por una
  reconexión. Se mide en la posición de la charla, entre el último audio entregado a la conexión
  anterior y el primero entregado a la nueva.
- **Ejecución**: sin cambios respecto del MVP. Una reconexión no crea una ejecución nueva.
- **Estado del escenario**: se suma el uso de `reconnecting`, ya previsto en el contrato, y el contador
  de reconexiones pasa a reflejar valores reales.

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **CE-001**: Una charla de 30 minutos se subtitula completa: la pista original y cada pista de
  traducción tienen frases finales hasta el final de la charla, en una sola ejecución, con al menos 2
  reconexiones registradas, 0 pasos a `error` y una última frase final que termina a menos de 15
  segundos del fin de la fuente.
- **CE-002**: Cada reconexión que tiene éxito en su primer intento deja un hueco de reconexión menor a 2
  segundos de audio (`gap_ms` < 2000 en el evento `reconnect_succeeded`, suma del audio descartado en
  milisegundos). Cuando una reconexión necesita más de un intento, el hueco se registra en los logs sin
  un límite exigido.
- **CE-003**: El texto perdido por cada reconexión se limita a la frase abierta al momento del corte;
  0 frases finales publicadas antes del corte quedan sin su traducción por causa de la reconexión. Un
  descarte de traducción por cola llena o por fallo de traducción (reglas del MVP `001-subs-mvp`) no
  cuenta contra este criterio.
- **CE-004**: En toda la charla, `sequence` es estrictamente creciente, dos frases distintas nunca
  comparten `segment_id` (los parciales, el final y las traducciones de una misma frase sí lo
  comparten), `run_id` es único y la posición en la charla de las frases nunca retrocede.
- **CE-005**: Durante cada reconexión, `/api/status` muestra el escenario en `reconnecting` como mucho
  un periodo de publicación de estado después del cierre, y vuelve a `live` como mucho un periodo
  después de la reconexión; al final, el contador de reconexiones coincide con la cantidad de eventos
  `reconnect_succeeded` registrados en los logs.
- **CE-006**: Las frases posteriores a una reconexión cumplen los mismos objetivos de latencia del MVP
  (`docs/architecture.md` §8) desde la primera frase final: la reconexión no deja retraso acumulado.
- **CE-007**: Con dos escenarios activos, la reconexión de uno no produce en el otro ningún cambio de
  estado ni una espera entre frases finales mayor a `MAX_SEGMENT_MS` más 2 segundos; además, el otro no
  registra eventos de reconexión y no descarta ningún bloque de audio.
- **CE-008**: Con el servicio de transcripción inaccesible para un escenario, ese escenario hace
  exactamente la cantidad máxima de intentos configurada, con esperas no decrecientes, y termina en
  `error` con la causa visible en `/api/status`, mientras el otro escenario sigue `live`.
- **CE-009**: 0 frases descartadas quedan visibles como frase en curso en la vista de audiencia
  después de que aparece la frase siguiente.

## Supuestos

- Toda la feature respeta la constitución (`.specify/memory/constitution.md`); ante un conflicto, gana
  la constitución.
- La conexión de transcripción se cierra sola a los ~10 minutos o por fallas; el sistema trata igual
  ambos casos. Usar un aviso previo del servicio para abrir la conexión nueva antes del cierre es
  pre-apertura (P2, fuera de alcance).
- **Definición de hueco**: CE-002 mide el audio que no llega a la transcripción. La frase abierta que
  se descarta (RF-013) es una pérdida de texto aparte y se acepta en esta feature tal como lo indica
  `docs/architecture.md` §6.2.5. Se espera que normalmente se pierda a lo sumo una frase gracias al
  corte forzado, pero esto es una expectativa y no un criterio de éxito. El
  límite de 2 s de CE-002 solo exige rapidez cuando el primer intento tiene éxito; una reconexión con
  reintentos puede tardar más (cada espera y el tiempo de cada intento, con su propio tope de
  `RECONNECT_ATTEMPT_TIMEOUT_S`), y ese hueco mayor es aceptable mientras quede en los logs.
- Un intento es exitoso cuando la conexión nueva queda lista para recibir audio (RF-005), y fallido si
  no lo logra o si no responde dentro de `RECONNECT_ATTEMPT_TIMEOUT_S` (RF-007). La cuenta de intentos
  fallidos es por reconexión: se reinicia con cada éxito.
- El instante del corte es cuando se detecta el cierre (RF-008), no cuando termina de procesarse: así
  `start_ms`/`end_ms` y el hueco medido no dependen de cuánto tarda el sistema en reaccionar.
- El contador de reconexiones acumula desde que el worker arrancó el escenario y se reinicia solo al
  reiniciar el worker; las vueltas de un clip con loop no lo reinician.
- El estado `error` por agotar los intentos es final para ese escenario: se recupera reiniciando el
  worker, igual que cualquier otro error del MVP.
- La primera conexión de un escenario, al arrancar, sigue como en el MVP; esta feature cubre el cierre
  de una conexión que ya estaba funcionando.
- Los clips sintéticos de `samples/audio/` duran menos de 10 minutos. La validación de 30 minutos usa
  una fuente más larga: audio real en `samples/local/` (ignorado por git) o un clip largo generado, sin
  loop, ya que cada vuelta de un loop abre una ejecución nueva.
- No cambia `SubtitleEvent`: `SessionStatus` ya incluye `reconnecting` y `reconnects`, y el final vacío
  de RF-014 usa el contrato actual (`text` vacío, `is_final=true`, misma `start_ms`, `revision` mayor
  que la del último parcial de esa frase).
- `last_error` en `/api/status` conserva la causa del último fallo aunque la reconexión termine en
  éxito (RF-019); es informativo y no implica que el escenario siga fallando.
- `LIVE_SESSION_MAX_S` (RF-023) es una herramienta de prueba: con un valor bajo (por ejemplo, 60 s) un
  clip corto de `samples/audio/` provoca varias reconexiones y permite verificar RF-001 a RF-022 y los
  criterios CE-002 a CE-009 sin esperar ~10 minutos. Vacío, el sistema solo reconecta ante cierres
  reales. No se usa en producción.
- Esta feature actualiza `docs/architecture.md` (§6.2.5, §7.7 y §9) con el comportamiento y las
  variables nuevas, según `AGENTS.md`.

## Fuera de alcance

- Reanudación de sesión y pre-apertura de la conexión nueva para reconectar sin huecos (P2).
- Rescatar la frase abierta al momento del corte (forzar su final antes de cerrar o reenviar su audio).
- Reintentos de la primera conexión al arrancar un escenario.
- Recuperación automática de un escenario que quedó en `error` sin reiniciar el worker.
- Reconexión ante caídas de Redis, reconexión de clientes y reintento de traducciones fallidas (otras
  filas de `docs/architecture.md` §9).
- Ingesta RTMP (`003-ingesta-rtmp`) y glosarios por escenario (`004-glosario`).
- Cambios en el panel de producción: esta feature solo garantiza que el estado y el contador estén en
  `/api/status`.
