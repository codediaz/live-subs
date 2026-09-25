# Especificación de la feature: Live Subs MVP (P0)

**Rama de la feature**: `001-subs-mvp`

**Creada**: 2026-09-24

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Feature 001-subs-mvp: alcance P0 (MVP eliminatorio) de live-subs.
Usa docs/architecture.md como contexto (§2.1, fila P0 de §4, §6, §7 y P0 de §15). Solo el QUÉ y el
POR QUÉ. Historias para espectador, operador y evaluador; requisitos EARS; fuera de alcance todo P1 y
P2; criterios de finalización tomados de P0 en §15."

> **Contexto.** Toda esta feature es prioridad **P0** del proyecto (`docs/architecture.md` §4). Las
> prioridades 1–3 de las historias solo ordenan el trabajo dentro de la feature. `sessions.yaml`,
> `docker compose up` y `SubtitleEvent` se nombran porque son interfaces del producto exigidas por el
> desafío y por la constitución, no decisiones de implementación.
>
> **Cambio de alcance (2026-09-25).** La validación desde un clon limpio (T038) falló en CE-004: la
> sala en español no producía frases finales y las pistas traducidas tardaban más de 30 s en mostrar
> la primera línea (también afecta CE-001 y CE-003). Con los datos de `scripts/t0/vad_probe.py`
> (`research.md` § Resultados del probe de corte de frase) pasan a P0 el cierre de frase ajustado y el
> corte por duración máxima (RF-045, RF-046), la traducción de fragmentos (RF-047) y las últimas
> frases al conectarse (RF-048).

## Escenarios de usuario y pruebas *(obligatorio)*

### Historia de usuario 1 - El espectador sigue una charla con subtítulos (Prioridad: 1)

Una persona en la audiencia abre la vista web, elige el escenario que está mirando y la pista que
quiere leer: el idioma original de la charla o una traducción. Si elige el original, ve cómo la frase
se va escribiendo mientras el speaker habla (parcial) y cómo se consolida al terminar (final). Si elige
una traducción, ve cada frase traducida en cuanto el speaker la termina.

**Por qué esta prioridad**: es el valor central del producto y el requisito eliminatorio "mostrar los
subtítulos". Sin esta vista no hay demo.

**Prueba independiente**: con un escenario procesando un clip en inglés, abrir la vista, elegir el
escenario y la pista original y comprobar parciales y finales; luego cambiar a la pista `es` y
comprobar que aparecen las frases traducidas.

**Escenarios de aceptación**:

1. **Dado** un escenario activo con charla en inglés, **Cuando** el espectador elige ese escenario y la
   pista original, **Entonces** ve el texto de la frase en curso actualizarse mientras se habla y
   quedar fijo cuando la frase termina.
2. **Dado** el mismo escenario, **Cuando** el espectador elige la pista `es`, **Entonces** ve solo
   frases completas traducidas al español, cada una correspondiente a una frase final del original.
3. **Dado** que una frase recibió varias hipótesis parciales, **Cuando** llega su versión final,
   **Entonces** en pantalla queda una única línea para esa frase, con el texto final.
4. **Dado** dos escenarios activos, **Cuando** el espectador cambia de un escenario a otro,
   **Entonces** deja de ver los subtítulos del primero y ve solo los del segundo.

---

### Historia de usuario 2 - El operador configura y levanta los escenarios (Prioridad: 2)

La persona que opera el evento describe cada escenario en `sessions.yaml` (nombre, título de la
charla, fuente de audio, idioma de origen e idiomas destino), coloca la credencial del proveedor de IA
en la configuración del entorno y levanta todo con `docker compose up`. Cada escenario funciona por su
cuenta: si uno falla, los demás siguen.

**Por qué esta prioridad**: el desafío exige al menos dos sesiones simultáneas y un despliegue
sencillo; operar desde configuración, sin tocar código, es lo que permite usarlo en un evento real.

**Prueba independiente**: definir dos escenarios (uno con archivo, otro con URL de stream), levantar
el sistema y comprobar que ambos producen subtítulos; luego romper la fuente de uno y comprobar que el
otro sigue.

**Escenarios de aceptación**:

1. **Dado** un `sessions.yaml` con dos escenarios válidos, **Cuando** el operador ejecuta
   `docker compose up`, **Entonces** ambos escenarios empiezan a producir subtítulos sin otra acción.
2. **Dado** un escenario con fuente de tipo archivo, **Cuando** arranca, **Entonces** los subtítulos
   avanzan al ritmo real de la grabación, no más rápido.
3. **Dado** un escenario con fuente de tipo URL de stream, **Cuando** arranca, **Entonces** se
   subtitula el audio en vivo de esa URL.
4. **Dado** dos escenarios activos, **Cuando** la fuente de uno falla, **Entonces** ese escenario queda
   en estado de error con su causa y el otro sigue produciendo subtítulos sin interrupción.
5. **Dado** un `sessions.yaml` con un error (por ejemplo, un `id` repetido), **Cuando** el operador
   levanta el sistema, **Entonces** recibe un mensaje que indica el escenario y el campo inválido.

---

### Historia de usuario 3 - El evaluador prueba el sistema con los clips del repositorio (Prioridad: 3)

Una persona del jurado clona el repositorio, sigue el README, configura únicamente su API key de
Gemini y levanta el sistema. Sin preparar audio ni editar escenarios, ve dos escenarios en paralelo
con los clips de `samples/audio/` (uno en inglés y otro en español), cada uno con su traducción. Los
clips se repiten en loop, así que ve subtítulos aunque abra la vista mucho después de levantar el
sistema.

**Por qué esta prioridad**: es el camino por el que el jurado valida los requisitos eliminatorios. Si
falla, el proyecto queda descalificado aunque todo lo demás funcione.

**Prueba independiente**: desde un clon limpio, en una máquina con Docker, seguir el README al pie de
la letra configurando solo la API key y comprobar los criterios de éxito CE-001 a CE-006.

**Escenarios de aceptación**:

1. **Dado** un clon limpio, **Cuando** el evaluador copia el ejemplo de configuración del entorno,
   agrega su API key y ejecuta `docker compose up`, **Entonces** el sistema arranca sin otro paso.
2. **Dado** el sistema levantado con la configuración por defecto, **Cuando** el evaluador abre la vista
   de audiencia, **Entonces** encuentra dos escenarios: uno en inglés con pista `es` y otro en español
   con pista `en`.
3. **Dado** el sistema levantado hace más tiempo que la duración de los clips, **Cuando** el evaluador
   abre la vista de audiencia, **Entonces** ve subtítulos en curso en ambos escenarios, porque cada clip
   volvió a empezar al terminar.
4. **Dado** el README, **Cuando** el evaluador lo lee, **Entonces** encuentra qué credencial hace
   falta, qué modelos se usan y cómo escalar a más escenarios.

---

### Casos borde

- **Frase muy larga sin pausas**: si una frase sigue abierta al llegar a la duración máxima, se cierra
  como final aunque el speaker no haya hecho una pausa (RF-046). Esa frase puede ser un fragmento y su
  traducción se hace como fragmento, sin completarla (RF-047).
- **La conexión de transcripción se cierra** (dura unos 10 minutos): en P0 no hay reconexión (es P1);
  si ocurre, el escenario pasa a estado de error y los demás siguen. Con loop activado, cada vuelta del
  clip abre una ejecución y una sesión de transcripción nuevas, así que un clip de menos de 10 minutos
  nunca llega a ese límite.
- **Un clip en loop vuelve a empezar**: comienza una ejecución nueva; la vista limpia la pantalla y
  sigue con la nueva vuelta (RF-021).
- **La URL de stream no responde al arrancar o se corta a mitad**: el escenario pasa a estado de error
  con la causa; los demás siguen.
- **Silencio prolongado**: no se publican subtítulos y no se considera un error.
- **Idioma destino igual al de origen** (por ejemplo, charla en `es` con destino `es`): no se traduce
  a ese idioma; la pista original ya lo cubre.
- **Escenario sin idiomas destino**: solo existe la pista original.
- **El procesamiento no da abasto con el audio entrante**: se descarta el audio pendiente más antiguo y
  se registra el descarte; el retraso no se acumula.
- **Las traducciones de una pista se atrasan**: la cola de pendientes de esa pista es acotada; si se
  llena, se descarta la frase pendiente más antigua y se registra el descarte. El original nunca espera
  a la traducción.
- **Eventos repetidos o fuera de orden**: la vista conserva, por frase, la revisión mayor; un final
  reemplaza a cualquier parcial.
- **Reinicio del procesamiento**: comienza una ejecución nueva; la vista limpia la pantalla y no mezcla
  frases de ejecuciones distintas.
- **Espectador que llega tarde o pierde la conexión**: en P0, al conectarse ve las últimas frases
  finales de la pista elegida (RF-048) y luego los subtítulos en vivo; el historial completo y la
  reconexión automática son P1. Recargar la página vuelve a conectar.

## Requisitos *(obligatorio)*

Formato EARS: *El sistema deberá…* (siempre), *Cuando…* (evento), *Mientras…* (estado),
*Si…, entonces…* (condición no deseada), *Donde…* (opción configurada).

### Requisitos funcionales

**Ingesta de audio**

- **RF-001**: Cuando arranca un escenario con fuente de tipo archivo, el sistema deberá entregar su
  audio a la transcripción a velocidad real, como si la charla estuviera ocurriendo en vivo.
- **RF-002**: Cuando arranca un escenario con fuente de tipo URL de stream, el sistema deberá consumir
  el audio en vivo de esa URL.
- **RF-003**: Mientras un escenario está activo, el sistema deberá enviar su audio a la transcripción
  como un flujo continuo, sin partirlo en fragmentos independientes.
- **RF-004**: Si la transcripción no acepta audio al ritmo en que llega, entonces el sistema deberá
  seguir recibiendo audio, descartar lo pendiente más antiguo y registrar el descarte, sin acumular
  retraso.
- **RF-005**: Mientras un escenario está activo, el sistema deberá conocer la posición en la charla (ms
  desde el inicio de la ejecución) de cada porción de audio y la hora real en que la envió.

**Transcripción del idioma original**

- **RF-006**: Mientras el speaker habla, el sistema deberá publicar en la pista `original` hipótesis
  parciales de la frase en curso, cada una con una revisión mayor que la anterior de la misma frase.
- **RF-007**: Cuando termina una frase, el sistema deberá publicar su versión final en la pista
  `original`, con su posición de inicio y fin en la charla; la siguiente hipótesis abrirá una frase
  nueva.
- **RF-008**: El sistema deberá transcribir charlas cuyo idioma de origen configurado sea `en` o `es`.
- **RF-045**: Cuando el speaker hace una pausa, el sistema deberá cerrar la frase en curso como final;
  la sensibilidad de detección del fin de la voz y el silencio mínimo que cierra una frase deberán ser
  configurables.
- **RF-046**: Si una frase sigue abierta sin versión final durante más de una duración máxima
  configurable, entonces el sistema deberá forzar su cierre como final sin interrumpir el envío de
  audio; si después del cierre forzado sigue sin final durante otra duración máxima, deberá forzarlo
  otra vez.

**Traducción**

- **RF-009**: Cuando se publica una frase final original, el sistema deberá traducirla a cada idioma
  destino del escenario distinto del idioma de la frase y publicar cada traducción en la pista de su
  idioma, vinculada a la misma frase.
- **RF-010**: El sistema deberá traducir solo frases finales; nunca deberá traducir ni publicar
  traducciones de hipótesis parciales.
- **RF-011**: El sistema deberá soportar al menos las direcciones inglés → español y español → inglés.
- **RF-012**: Cuando traduce una frase, el sistema deberá usar como contexto el título de la charla y
  las últimas frases finales del escenario (cantidad configurable).
- **RF-047**: Cuando traduce una frase, el sistema deberá tratarla como un posible fragmento de una
  frase más larga: deberá traducirla como fragmento, sin completarla ni agregar contenido, apoyándose
  en las frases previas del contexto.
- **RF-013**: Mientras hay traducciones pendientes, el sistema deberá publicar el original sin esperar
  a ellas; las pistas de traducción deberán avanzar en paralelo y, dentro de cada pista, en el orden de
  las frases.
- **RF-014**: Mientras hay frases pendientes de traducir, el sistema deberá mantenerlas en una cola
  acotada por pista (tamaño configurable); si la cola se llena, entonces deberá descartar la frase
  pendiente más antigua y registrar el descarte.
- **RF-015**: Si la traducción de una frase falla, entonces el sistema deberá mantener publicado el
  original, registrar el error y continuar con las frases siguientes.

**Vista de audiencia**

- **RF-016**: Cuando un espectador abre la vista de audiencia, el sistema deberá listar los escenarios
  configurados con su nombre, título de la charla, idioma de origen y pistas disponibles.
- **RF-017**: Cuando el espectador elige un escenario y una pista, el sistema deberá mostrarle en vivo
  solo los subtítulos de esa pista de ese escenario.
- **RF-018**: Cuando el espectador cambia de escenario o de pista, el sistema deberá dejar de mostrar
  la selección anterior y mostrar solo la nueva.
- **RF-019**: Mientras una frase está en curso, la vista deberá reemplazar el parcial anterior de esa
  frase por el más reciente y, cuando llega el final, dejar solo el texto final; nunca deberá quedar en
  pantalla un parcial obsoleto.
- **RF-020**: Si llegan eventos repetidos o fuera de orden, entonces la vista deberá conservar para
  cada frase el de revisión mayor, y un final deberá reemplazar a cualquier parcial de la misma frase.
- **RF-021**: Cuando llega un evento de una ejecución distinta a la que se muestra, la vista deberá
  limpiar la pantalla y continuar con la ejecución nueva.
- **RF-048**: Cuando un espectador se conecta a una o más pistas de un escenario, el sistema deberá
  enviarle primero las últimas frases finales de cada pista en la ejecución actual (cantidad
  configurable) y después los subtítulos en vivo. Esas frases se guardan solo en la memoria del
  componente que atiende a los espectadores; no es el historial persistente de P1.
- **RF-022**: La vista de audiencia no deberá permitir que un cliente indique fuentes de audio, URLs ni
  rutas; las fuentes solo se definen en la configuración del operador.
- **RF-044**: La vista de audiencia deberá ser legible en celular y en escritorio, con alto contraste
  entre texto y fondo, y deberá permitir que el espectador ajuste el tamaño de letra.

**Sesiones simultáneas e independientes**

- **RF-023**: El sistema deberá procesar al menos dos escenarios a la vez, cada uno con su propia
  fuente, idioma de origen e idiomas destino.
- **RF-024**: Cuando arranca un escenario, el sistema deberá iniciar una ejecución nueva con su propio
  identificador; la numeración de frases, las posiciones en la charla y los eventos no se mezclarán con
  los de ejecuciones anteriores.
- **RF-025**: Si la fuente o la transcripción de un escenario falla, entonces el sistema deberá marcar
  ese escenario en estado de error con la causa y los demás escenarios deberán seguir sin interrupción.
- **RF-026**: Cuando la fuente de un escenario termina y el escenario no tiene loop activado, el
  sistema deberá marcar el escenario como detenido y cerrar su transcripción.
- **RF-043**: Donde una fuente de tipo archivo tenga loop activado, cuando el clip termine, el sistema
  deberá iniciar una ejecución nueva del escenario con una sesión de transcripción nueva.
- **RF-027**: Donde se indique a una instancia de procesamiento un subconjunto de escenarios, esa
  instancia deberá atender solo esos escenarios; sin indicación, deberá atenderlos todos.

**Configuración y operación**

- **RF-028**: El sistema deberá leer los escenarios de `sessions.yaml`: identificador, nombre, título,
  fuente (tipo archivo o stream, con su URI; loop opcional para archivos), idioma de origen e idiomas
  destino, con valores por defecto comunes que cada escenario puede sobrescribir.
- **RF-029**: Si `sessions.yaml` no es válido (identificador repetido o con espacios, fuente sin URI,
  idioma no soportado), entonces el sistema deberá informar al arrancar qué escenario y qué campo son
  inválidos y no deberá arrancar con una configuración parcial.
- **RF-030**: El sistema deberá tomar los modelos de IA, los parámetros de audio y de traducción y la
  credencial del proveedor de la configuración del entorno; ninguno de esos valores deberá estar fijo
  en el código.
- **RF-031**: El sistema deberá entregar la credencial del proveedor de IA solo al componente que
  procesa el audio; el componente que atiende a los espectadores no deberá recibirla.
- **RF-032**: Cuando el operador cambia `sessions.yaml`, el cambio deberá aplicarse al reiniciar el
  procesamiento.
- **RF-033**: Cuando el operador ejecuta `docker compose up` en un clon limpio con la credencial
  configurada, el sistema deberá levantar todos sus componentes y empezar a procesar los escenarios
  configurados.
- **RF-034**: El sistema deberá registrar sus eventos operativos en formato estructurado con el
  identificador del escenario; en el nivel de registro normal no deberá incluir audio ni texto de
  subtítulos.

**Contrato de eventos**

- **RF-035**: Todo subtítulo que circule entre componentes deberá ser un `SubtitleEvent` versión 1 con
  los campos definidos en `docs/architecture.md` §7.1.
- **RF-036**: El sistema deberá publicar el original siempre en la pista `original`, aunque su idioma
  sea `en` o `es`, y cada traducción en la pista de su idioma; las traducciones serán siempre finales.
- **RF-037**: El sistema deberá identificar cada subtítulo en pantalla por la clave (ejecución, pista,
  frase); dentro de una clave gana la revisión mayor.
- **RF-038**: Cuando publica un evento, el sistema deberá registrar en él su hora real de emisión y su
  latencia medida según `docs/architecture.md` §8.
- **RF-039**: Si el contrato cambia de forma incompatible, entonces su versión (`schema_version`)
  deberá incrementarse y la especificación deberá actualizarse antes del código.

**Repositorio y documentación**

- **RF-040**: El repositorio deberá incluir clips de audio de prueba en `samples/audio/` (al menos uno
  en inglés y uno en español) y una configuración por defecto de dos escenarios que los usa en loop,
  con traducción EN→ES y ES→EN.
- **RF-041**: El README deberá explicar, en inglés, qué credencial se necesita y dónde se configura,
  qué modelos se usan y cómo cambiarlos, cómo levantar el sistema desde un clon limpio y cómo escalar
  (unidad de escala, reparto de escenarios entre instancias, costo de sumar idiomas y límites externos
  de cuota).
- **RF-042**: El repositorio deberá publicarse con licencia Apache 2.0.

### Entidades clave

- **Escenario (sesión)**: una sala o track de la conferencia. Tiene identificador único, nombre, título
  de la charla en curso, fuente de audio (archivo o URL de stream), idioma de origen e idiomas destino.
- **Ejecución**: cada arranque de un escenario. Agrupa las frases y posiciones de esa corrida; un
  reinicio crea una ejecución nueva.
- **Pista**: flujo de subtítulos de un escenario. `original` para el idioma hablado y una por cada
  idioma destino (`es`, `en`).
- **Frase (segmento)**: unidad de subtítulo. La comparten sus parciales, su final y sus traducciones;
  tiene posición de inicio y fin en la charla. Si se cerró por duración máxima (RF-046), puede ser un
  fragmento de una frase más larga.
- **SubtitleEvent**: el mensaje de un subtítulo. Lleva versión del contrato, escenario, ejecución,
  pista, orden de emisión, frase, revisión, tipo (original o traducción), idioma, texto, si es final,
  posición de inicio y fin, hora de emisión y latencia.
- **Estado del escenario**: arrancando, en vivo, detenido o con error (con su causa). En P0 se registra;
  el panel que lo muestra es P1.
- **Configuración de escenarios**: el archivo `sessions.yaml` con valores por defecto y la lista de
  escenarios.

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **CE-001**: Dos escenarios corren a la vez desde clips de `samples/audio/` (uno en inglés y otro en
  español) y ambos muestran subtítulos durante toda la duración de sus clips.
- **CE-002**: En la pista original se ven parciales mientras se habla y finales al terminar cada frase;
  al revisar la pantalla después de cada frase final hay 0 parciales obsoletos.
- **CE-003**: La sala en inglés muestra traducción EN→ES y la sala en español ES→EN; el 100 % de las
  traducciones corresponde a una frase final del original de su escenario.
- **CE-004**: Un espectador llega a leer subtítulos de la pista que eligió en menos de 30 segundos
  desde que abre la vista, sin instrucciones. Se valida con una prueba propia desde un clon limpio en
  una carpeta nueva, siguiendo solo el README.
- **CE-005**: Una persona sin conocimiento previo del proyecto, en una máquina con Docker, pasa de un
  clon limpio a ver subtítulos en menos de 10 minutos siguiendo solo el README y configurando solo su
  API key. Se valida con una prueba propia desde un clon limpio en una carpeta nueva, siguiendo solo el
  README.
- **CE-006**: Leyendo solo el README, un evaluador responde correctamente qué credencial hace falta,
  qué modelos se usan y cómo pasar de 2 a 100 escenarios.
- **CE-007**: Con dos escenarios activos, al hacer fallar la fuente de uno, el otro sigue mostrando
  subtítulos sin interrupción y el fallido queda en estado de error con su causa.
- **CE-008**: El 100 % de los subtítulos publicados lleva su latencia medida. Los objetivos de latencia
  de `docs/architecture.md` §8 se verifican en P1.

## Supuestos

- Toda la feature respeta la constitución (`.specify/memory/constitution.md`); ante un conflicto,
  gana la constitución.
- El proveedor de IA es Gemini; el evaluador tiene una API key con acceso a los modelos configurados.
- La máquina del evaluador tiene Docker con Compose y acceso a internet.
- Los clips de `samples/audio/` duran menos de 10 minutos y corren en loop con una sesión de
  transcripción nueva por vuelta, por lo que en P0 no hace falta reconexión.
- El espectador lee una pista a la vez; el modo bilingüe (original y traducción juntos) es P2.
- El MVP no tiene autenticación: cualquier persona con la URL ve los escenarios.
- Un error de validación de `sessions.yaml` impide arrancar (RF-029): se prefiere detectar el error
  antes del evento. El aislamiento entre escenarios (RF-025) aplica a fallas en ejecución.
- La medición de latencia existe desde P0 porque la constitución (principio 7) exige medir toda
  latencia; la fila P1 de §4 ("latencia registrada") se interpreta como su visualización y validación
  contra los objetivos de §8.

## Fuera de alcance

Todo lo P1 y P2 de `docs/architecture.md` §4:

- **P1**: reconexión ante cierre de la conexión de transcripción; glosarios; historial completo para
  espectadores que llegan tarde (más allá de las últimas frases de RF-048) y reconexión automática del
  cliente; panel de estado y latencia; exportación SRT/VTT/TXT; overlay para OBS/vMix; portugués;
  traducción agrupada de frases pendientes para recuperar el retraso; reintento de traducciones
  fallidas; reintento ante caída de la mensajería interna.
- **P2**: panel de producción completo; modo bilingüe; idioma de origen automático; recarga en caliente
  de `sessions.yaml`; micrófono; URLs de YouTube; reanudación de sesión y pre-apertura.
- **Fuera del producto**: autenticación, almacenamiento permanente, edición colaborativa de
  subtítulos, entrega garantizada durante caídas y selección automática de proveedores de IA.
