# Live Subs

# SDD — Live Subs (MVP)
| Campo | Valor |
| ----- | ----- |
| Documento | Software Design Description (`docs/architecture.md`) |
| Sistema | Live Subs |
| Versión | 0.4 — diseño del MVP para la Nerdearla Vibeathon 2026, alineado con `specs/001-subs-mvp/` |
| Fecha | 24 de septiembre de 2026 |
| Estado | Aprobado para implementación. Pendientes explícitos en §14 |
| Licencia | Apache 2.0 |
---

## 1. Propósito y alcance
Live Subs genera subtítulos en vivo para conferencias con varios escenarios en paralelo. Toma audio de un archivo, una URL de stream o un micrófono; publica la transcripción en el idioma original (parcial y final) y traducciones de las frases finales a los idiomas configurados. Los subtítulos llegan a una vista web de audiencia, a un overlay para OBS/vMix y a un panel de producción.

Es una solución open source pensada para que cualquier conferencia la despliegue con un solo comando y la opere desde archivos de configuración.

---

## 2. Trazabilidad con el desafío
### 2.1 Requisitos mínimos (eliminatorios)
| Requisito del desafío | Respuesta del diseño | Prioridad |
| ----- | ----- | ----- |
| Recibir audio en vivo de al menos una fuente, con audios de prueba en el repo | Ingesta `ffmpeg` de archivo (a velocidad real con `-re`) y URL de stream; clips en `samples/audio/`  | P0 |
| Transcripción en tiempo real del idioma original | Gemini Live API con `gemini-3.5-transcribe-live`: parciales y finales | P0 |
| Traducción en tiempo real inglés → español | Traductor de frases finales con Gemini Flash | P0 |
| Mostrar los subtítulos | Vista web de audiencia (elige sesión e idioma) | P0 |
| Al menos dos sesiones simultáneas y explicar cómo escalar | `sessions.yaml` + una tarea asíncrona por escenario; escalado en §10 | P0 |
| Licencia OSI y README con credenciales y modelos | Apache 2.0; README con `.env.example`  | P0 |
### 2.2 Criterios del jurado
| Criterio | Respuesta del diseño |
| ----- | ----- |
| Calidad | Glosario por escenario usado en transcripción (vocabulario) y traducción (términos); contexto de la charla y frases previas al traducir |
| Latencia | Streaming continuo; parciales visibles de inmediato; solo se traducen finales; latencia medida y visible en el panel |
| Escalabilidad | Escenarios como configuración; workers horizontales; agregar un idioma cuesta una llamada de texto por frase, no otra sesión de audio |
| Despliegue y operación | `docker compose up`; una sola imagen; panel de estado; exportación SRT/VTT/TXT |
| Innovación | Overlay para quemar subtítulos en OBS/vMix; modo bilingüe; video de demo subtitulado por el propio sistema |
---

## 3. Vista general de la arquitectura
```text
 sessions.yaml ─────────────┐        Glosarios ──────────────┐
                            ▼                                 │ vocabulario / términos
 Archivo / Stream URL / Mic ──► Ingesta ffmpeg ──► Transcriptor ──► Traductor
                                  (PCM 16 kHz)        ⇅   │            ⇅   │
                                          Gemini Live API │     Gemini Flash
                                    (transcribe-live)     │                 │
                                                          ▼                 ▼
                                               Redis: pub/sub + historial + estado
                                                          │
                                                   Gateway FastAPI
                                        ┌─────────────────┼─────────────────┐
                                  Audiencia web       Overlay OBS      Panel producción
```
El **Worker** procesa audio y produce eventos. **Redis** desacopla el procesamiento de la entrega. El **Gateway** distribuye eventos a los clientes y expone historial, exportación y estado. El Gateway no transcribe ni traduce; el Worker no atiende clientes.

### 3.1 Decisiones fundamentales
| # | Decisión | Motivo |
| ----- | ----- | ----- |
| D1 | Audio por streaming continuo (Live API). Nunca fragmentos por REST | Los fragmentos cortan palabras, pierden contexto y suman latencia por petición |
| D2 | Pipeline A decidido: `transcribe-live` + traducción de texto con Gemini Flash. La alternativa B (`live-translate`) se descarta: no da parciales ni admite glosario | A admite glosario en ambos pasos y abarata sumar idiomas |
| D3 | `SubtitleEvent` es el contrato único entre todos los componentes | Permite cambiar piezas sin romper el resto |
| D4 | Los parciales solo se muestran en el original; se traducen únicamente las frases finales | Traducir parciales es caro, ruidoso y empeora la lectura |
| D5 | Un evento por idioma y un canal por sesión y pista (_track_) | Cada cliente recibe solo lo que eligió; sumar idiomas no cambia el contrato |
| D6 | Un solo código Python, una sola imagen, dos procesos (worker y gateway) | Menos piezas que mantener; esquema compartido |
| D7 | Configuración en lugar de código: `sessions.yaml`, glosarios y `.env`  | Operar el evento sin tocar código |
| D8 | Parámetros de audio y segmentación configurables; se ajustan midiendo latencia de punta a punta | No casarse con valores antes de medir |
| D9 | Robustez incremental: MVP → reconexión simple → mejoras | Primero subtítulos funcionando, después resiliencia |
---

## 4. Alcance por prioridad
| Prioridad | Contenido |
| ----- | ----- |
| **P0 — MVP** | Ingesta de archivo y URL; transcripción parcial y final; traducción de finales EN→ES y ES→EN; vista de audiencia con elección de sesión y pista; dos sesiones simultáneas; `docker compose`; README |
| **P1 — Inmediatamente después del MVP** | Reconexión simple ante cierre de sesión Live; glosarios; corte forzado de frase (`MAX_SEGMENT_MS`); historial para clientes que llegan tarde; latencia registrada; panel mínimo (tabla de estado y latencia por sala); exportación SRT/VTT/TXT; overlay OBS; portugués (solo configuración, el traductor es genérico) |
| **P2 — Si sobra tiempo** | Panel de producción completo (gráficos, alertas); modo bilingüe; idioma de origen `auto`; recarga en caliente de `sessions.yaml`; micrófono; URLs de YouTube vía `yt-dlp`; reanudación de sesión y pre-apertura para reconexión sin huecos |
| **Fuera de alcance** | Autenticación; almacenamiento permanente; edición colaborativa de subtítulos; entrega garantizada durante caídas de Redis; selección automática de proveedores de IA |
---

## 5. Componentes
| Componente | Módulo | Responsabilidad | Entradas | Salidas |
| ----- | ----- | ----- | ----- | ----- |
| Configuración | `common/config.py`  | Leer `.env`, `sessions.yaml` y glosarios; validar | Archivos | Objetos de configuración |
| Contrato | `common/schema.py`  | Definir `SubtitleEvent` y `SessionStatus`  | — | Modelos Pydantic |
| Orquestador | `worker/main.py`  | Lanzar una tarea asíncrona por escenario asignado | Configuración | Tareas en ejecución |
| Ingesta | `worker/ingest.py`  | Abrir la fuente con `ffmpeg` y entregar PCM 16 kHz mono en bloques de `AUDIO_CHUNK_MS`  | Archivo, URL o micrófono | Bloques de audio + reloj de audio |
| Transcriptor | `worker/transcriber.py`  | Mantener la sesión Live, convertir resultados en eventos originales y forzar cortes largos | Audio, vocabulario | Eventos `original` parciales y finales |
| Traductor | `worker/translator.py`  | Traducir cada frase final a cada idioma destino con glosario y contexto | Frase final | Eventos `translation`  |
| Publicador | `worker/publisher.py`  | Publicar eventos, guardar historial y reportar estado | Eventos | Redis |
| Colas | `common/queues.py`  | Cola acotada que, al llenarse, descarta el elemento más antiguo y cuenta el descarte. La usan la ingesta, el traductor y el gateway | Elementos | Elementos + descartes |
| Logs | `common/logs.py`  | Formato JSON con `session_id`; en `INFO`, sin audio ni texto | Registros | Salida estándar |
| Redis | servicio | Pub/sub, historial por pista y estado por sesión | Eventos | Eventos, historial, estado |
| Gateway | `gateway/main.py`  | WebSocket, API de sesiones, historial, exportación, estado; servir páginas | Redis, `sessions.yaml`  | WebSocket y HTTP |
| Clientes | `gateway/static/`  | Audiencia, overlay y panel | Gateway | Vistas |
---

## 6. Flujos de procesamiento
### 6.1 Arranque e ingesta
1. El Worker lee `sessions.yaml`  y toma los escenarios indicados en `WORKER_SESSIONS`  (vacío = todos).
2. Por cada escenario genera un `run_id`  (hora de inicio en epoch ms) y lo guarda en `run:{session_id}` . Cada arranque es una ejecución nueva: `start_ms` , `segment_id`  y el historial se cuentan dentro de ella, así un reinicio nunca mezcla frases de ejecuciones distintas.
3. Por cada escenario carga el glosario global y el del escenario, y lanza una tarea asíncrona independiente. Una falla en un escenario no afecta a los demás.
4. La ingesta abre la fuente con `ffmpeg`  y la convierte a PCM 16 bits, 16 kHz, mono. Para archivos usa `-re`  (cadencia de tiempo real).
5. La ingesta mantiene un **reloj de audio**: por cada bloque enviado registra su posición en la charla (ms) y la hora real de envío. Ese reloj alimenta `start_ms` , `end_ms`  y la medición de latencia (§8).
6. Entre la ingesta y el Transcriptor hay una cola acotada. La ingesta nunca se detiene: si la cola se llena, se descartan los bloques más antiguos y se registra el descarte. Durante una reconexión los bloques también se descartan y el reloj de audio sigue avanzando. Así el retraso nunca se acumula.
### 6.2 Transcripción
1. El Transcriptor abre una sesión Live con `TRANSCRIBE_MODEL` , idioma de origen y vocabulario del glosario.
2. Cada hipótesis parcial (`interim_input_transcription` ) se publica como evento `original`  con `is_final=false`  y `revision`  creciente para el mismo `segment_id` .
3. Cada transcripción final (`input_transcription` ) se publica como evento `original`  con `is_final=true`  y se entrega al Traductor. El siguiente parcial abre un nuevo `segment_id` .
4. **Corte forzado (P1):** si una frase supera `MAX_SEGMENT_MS`  sin final, el Transcriptor envía una señal de fin de audio (`audio_stream_end` ) para forzar la finalización y sigue enviando audio. Evita que la traducción se atrase cuando el speaker no hace pausas.
5. **Reconexión (P1):** si la conexión se cierra (las conexiones de la Live API duran unos 10 minutos), el Transcriptor abre una nueva sesión y continúa. Se acepta un hueco breve. `sequence`  y `segment_id`  continúan su numeración: una reconexión no los reinicia. Un parcial abierto al momento del corte se descarta. Reanudación de sesión y pre-apertura quedan para P2.
### 6.3 Traducción
1. El Traductor recibe cada frase final y, por cada idioma de `target_languages`  distinto del idioma de la frase, llama a `TRANSLATE_MODEL` .
2. El prompt incluye: la frase, el título de la charla, las últimas `TRANSLATION_CONTEXT_SEGMENTS`  frases finales y **solo** los términos del glosario presentes en la frase.
3. Cada traducción se publica como evento `translation`  con `is_final=true` , el mismo `segment_id`  del original y el `track`  del idioma destino.
4. Hay una cola por pista de traducción: las pistas avanzan en paralelo y, dentro de cada una, las frases se traducen en orden. La traducción nunca bloquea la publicación del original.
5. La cola de cada pista es acotada (`TRANSLATION_QUEUE_MAX`). Si se llena, se descarta la frase pendiente más antigua y se registra el descarte. **(P1)** Unir las frases pendientes en una sola petición para recuperar el retraso.
### 6.4 Distribución y conexión de clientes
1. El Gateway mantiene **una sola suscripción a Redis por canal**, compartida por todos los clientes que piden esa pista, y reparte cada evento en memoria. El costo en Redis no crece con la cantidad de espectadores.
2. Un cliente nuevo abre el WebSocket y acumula lo que llega; luego pide el historial reciente por HTTP y fusiona ambos por la clave `(run_id, track, segment_id)` , conservando la `revision`  mayor. Así no hay huecos ni duplicados.
3. En pantalla, un parcial reemplaza al anterior del mismo `segment_id` ; el final lo consolida.
4. Si llega un evento con un `run_id`  distinto al actual, el cliente limpia la pantalla y empieza la nueva ejecución.
### 6.5 Fin de sesión y exportación
1. Cuando la fuente termina y el escenario no tiene loop, el Worker publica el estado `stopped`  y cierra la sesión Live.
2. Si la fuente es un archivo con `loop: true`, cuando el clip termina el Worker cierra la sesión Live, genera un `run_id` nuevo y vuelve a empezar con un `ffmpeg` y una sesión Live nuevos. Cada vuelta es una ejecución distinta; con clips de menos de 10 minutos, la sesión Live nunca llega a su límite. Los clientes limpian la pantalla al ver el `run_id` nuevo (§6.4.4).
3. La exportación SRT, VTT o TXT se genera en el Gateway a partir del historial de finales de la pista pedida, usando `start_ms`  y `end_ms` .
---

## 7. Contratos
### 7.1 `SubtitleEvent` 
```python
from typing import Literal
from pydantic import BaseModel

class SubtitleEvent(BaseModel):
    schema_version: Literal[1] = 1
    session_id: str
    run_id: int                       # ejecución del escenario (epoch ms de inicio)
    track: str                        # "original" o código del idioma destino ("es", "en", "pt")
    sequence: int                     # orden de emisión dentro de la sesión (monótono)
    segment_id: int                   # frase: lo comparten parciales, final y traducciones
    revision: int = 0                 # sube con cada parcial; el cliente reemplaza
    kind: Literal["original", "translation"]
    lang: str                         # idioma real del texto ("en", "es", "pt")
    text: str
    is_final: bool
    start_ms: int                     # posición en la charla, desde el inicio de la sesión
    end_ms: int | None = None         # solo en finales
    emitted_at_ms: int                # hora real de emisión (epoch ms)
    latency_ms: int | None = None     # ver §8
```
Ejemplo:

```json
{
  "schema_version": 1,
  "session_id": "sala1",
  "run_id": 1790263700000,
  "track": "es",
  "sequence": 87,
  "segment_id": 42,
  "revision": 0,
  "kind": "translation",
  "lang": "es",
  "text": "Bienvenidos a Nerdearla",
  "is_final": true,
  "start_ms": 12340,
  "end_ms": 14120,
  "emitted_at_ms": 1790263812345,
  "latency_ms": 2310
}
```
Reglas:

- El original siempre va a la pista `original` , aunque su idioma sea `en`  o `es` . Las traducciones van a la pista de su idioma.
- Los eventos `translation`  son siempre finales.
- La clave de un subtítulo en pantalla es `(run_id, track, segment_id)` ; gana la `revision`  mayor y un final reemplaza a cualquier parcial.
- Cualquier cambio incompatible del contrato incrementa `schema_version` .
### 7.2 `SessionStatus` 
```python
class SessionStatus(BaseModel):
    session_id: str
    state: Literal["starting", "live", "reconnecting", "stopped", "error"]
    source_type: Literal["file", "stream", "microphone"]
    uptime_s: int
    last_event_at_ms: int | None
    latency_original_ms: int | None     # último valor medido
    latency_translation_ms: int | None  # último valor medido
    reconnects: int
    errors: int
    last_error: str | None
    updated_at_ms: int
```
El Worker lo publica cada 2 segundos con expiración de 15 segundos. Si expira, el panel muestra **sin datos**: una sesión detenida nunca aparece como activa.

### 7.3 `sessions.yaml` 
```yaml
defaults:
  target_languages: [es]
  glossary: samples/glossaries/nerdearla.yaml

sessions:
  - id: sala1
    name: "Escenario principal"
    title: "Título de la charla en curso"     # contexto para la traducción
    source:
      type: file                               # file | stream | microphone
      uri: samples/audio/charla_en.ogg
      loop: true                               # opcional, solo para file: repite el clip
    source_language: en                        # en | es | auto (P2)
    target_languages: [es, pt]
    glossary: samples/glossaries/sala1.yaml    # opcional; se suma al global

  - id: sala2
    name: "Sala workshops"
    title: "Título de la charla en curso"
    source:
      type: stream
      uri: https://ejemplo.org/sala2/stream.m3u8
    source_language: es
    target_languages: [en]
```
Reglas: `id` único y sin espacios; `uri` obligatorio para `file` y `stream`; `loop` (por defecto `false`) solo se admite con `type: file` (§6.5); los valores de `defaults` aplican cuando el escenario no los define. Si el archivo no es válido, el worker no arranca e indica el escenario y el campo con error. Un cambio en el archivo se aplica reiniciando el worker (`docker compose restart worker`); la recarga en caliente es P2.

### 7.4 Glosario
```yaml
terms:
  - source: Kubernetes          # sin target: se conserva tal cual en todos los idiomas
  - source: Nerdearla
  - source: pull request
  - source: deployment
    target: { es: despliegue, pt: implantação }
  - source: open source
    target: { es: código abierto }
  - source: código abierto
    target: { en: open source }
```
Reglas:

- Se combinan el glosario global y el del escenario; ante conflicto gana el del escenario.
- **Transcripción:** los `source`  forman el vocabulario de la sesión Live, priorizando los del escenario, hasta 100 términos.
- **Traducción:** solo se envían al modelo los términos cuyo `source`  aparece en la frase (comparación sin distinguir mayúsculas).
### 7.5 Claves de Redis
| Clave | Tipo | Uso |
| ----- | ----- | ----- |
| `subs:{session_id}:{track}`  | Canal pub/sub | Eventos en vivo de una pista |
| `run:{session_id}`  | Cadena | `run_id` de la ejecución actual |
| `hist:{session_id}:{run_id}:{track}`  | Lista | Solo eventos finales de esa ejecución; recortada a `HISTORY_MAX_EVENTS`; expira tras `HISTORY_TTL_S`  |
| `status:{session_id}`  | Cadena JSON con expiración | Último `SessionStatus`  |
### 7.6 API del Gateway
| Método y ruta | Uso |
| ----- | ----- |
| `GET /`  | Vista de audiencia |
| `GET /overlay.html?session=sala1&tracks=es&size=48&position=bottom&partials=true`  | Overlay para OBS/vMix (fondo transparente) |
| `GET /panel.html`  | Panel de producción |
| `GET /api/sessions`  | Escenarios con nombre, título, idioma de origen y pistas disponibles |
| `GET /api/sessions/{id}/history?track=es&limit=50`  | Historial reciente de finales de la ejecución actual |
| `GET /api/sessions/{id}/runs`  | Ejecuciones disponibles en el historial (una por charla) |
| `GET /api/sessions/{id}/export?track=es&format=srt&run=`  | Exportación `srt`, `vtt` o `txt`; sin `run`, la ejecución actual |
| `GET /api/status`  | `SessionStatus` de todas las sesiones |
| `GET /healthz`  | Salud del gateway y de su conexión a Redis |
| `WS /ws/{session_id}?tracks=original,es`  | Eventos en vivo de una o más pistas |
Mensajes del WebSocket: `{"type": "subtitle", "data": SubtitleEvent}` y `{"type": "ping"}` cada 20 segundos.

### 7.7 Variables de entorno
| Variable | Valor por defecto | Uso |
| ----- | ----- | ----- |
| `GEMINI_API_KEY`  | — | Credencial; solo la necesita el worker |
| `REDIS_URL`  | `redis://redis:6379/0`  | Conexión a Redis |
| `TRANSCRIBE_MODEL`  | `gemini-3.5-transcribe-live`  | Modelo de transcripción |
| `TRANSLATE_MODEL`  | `gemini-3.8-flash` (la prueba técnica lo compara con `gemini-3.5-flash-lite`) | Modelo de traducción |
| `TRANSLATE_THINKING_LEVEL`  | `LOW`  | Razonamiento del traductor: el mínimo que admite el modelo (`LOW` en 3.8 Flash, `MINIMAL` en 3.5 Flash-Lite) |
| `TRANSLATE_TIMEOUT_S`  | `10`  | Límite por llamada de traducción |
| `TRANSLATION_CONTEXT_SEGMENTS`  | `3`  | Frases previas enviadas como contexto |
| `TRANSLATION_QUEUE_MAX`  | `10`  | Frases pendientes por pista antes de descartar la más antigua (§6.3.5) |
| `AUDIO_CHUNK_MS`  | `100`  | Tamaño de bloque de audio |
| `AUDIO_QUEUE_MAX_CHUNKS`  | `50`  | Bloques pendientes entre ingesta y Transcriptor antes de descartar (§6.1.6) |
| `VOICE_RMS_THRESHOLD`  | `500`  | Umbral de energía para detectar voz en el reloj de audio (§8) |
| `AUDIO_CLOCK_WINDOW_S`  | `120`  | Ventana que guarda el reloj de audio |
| `SOURCE_END_GRACE_MS`  | `3000`  | Espera del último final y de las traducciones al terminar la fuente |
| `STATUS_INTERVAL_S`  | `2`  | Periodo de publicación de `SessionStatus` (§7.2) |
| `STATUS_TTL_S`  | `15`  | Expiración de `SessionStatus` (§7.2) |
| `MAX_SEGMENT_MS`  | `6000`  | Duración máxima de una frase antes del corte forzado (P1) |
| `HISTORY_MAX_EVENTS`  | `5000`  | Tamaño máximo del historial por pista (P1) |
| `HISTORY_TTL_S`  | `86400`  | Retención del historial (P1) |
| `SESSIONS_FILE`  | `sessions.yaml`  | Ruta de la configuración |
| `WORKER_SESSIONS`  | vacío | Escenarios que atiende este worker (vacío = todos) |
| `GATEWAY_PORT`  | `8000`  | Puerto del gateway |
| `WS_PING_S`  | `20`  | Periodo del ping del WebSocket (§7.6) |
| `WS_CLIENT_QUEUE_MAX`  | `100`  | Eventos pendientes por cliente WebSocket antes de descartar el más antiguo |
| `LOG_LEVEL`  | `INFO`  | Nivel de logs |
---

## 8. Latencia: definición, medición y objetivos
- **Latencia del original parcial:** hora de recepción del parcial menos la hora real de envío del bloque de audio más reciente. Mide cuánto tarda el modelo en reaccionar.
- **Latencia del original final:** hora de emisión del evento menos la hora real en que se envió el audio correspondiente a su `end_ms` , según el reloj de audio de la ingesta.
- **Latencia de la traducción:** hora de emisión de la traducción menos la misma referencia del original. Además se registra por separado el tiempo propio de traducción (final original → traducción).
- **Distribución:** el Gateway mide el tiempo entre la recepción desde Redis y el envío por WebSocket.
Si la Live API entrega marcas de tiempo por enunciado, se usan para `start_ms` y `end_ms` (a verificar en la prueba técnica). Si no, se aproximan con el reloj de audio y una detección de voz por energía: cada bloque se marca con voz si su energía RMS supera `VOICE_RMS_THRESHOLD`. `end_ms` es el último bloque con voz antes de recibir el final y `start_ms` es el primer bloque con voz después del final anterior. No se usa la posición del audio al *recibir* el evento, porque daría una latencia cercana a 0 por construcción.

La latencia se mide y viaja en cada evento (`latency_ms`) desde P0; la validación contra los objetivos es P1.

| Métrica | Objetivo del MVP |
| ----- | ----- |
| Original parcial en pantalla | ≤ 1,5 s |
| Original final | ≤ 3 s desde el fin de la frase |
| Traducción en pantalla | ≤ 5 s desde el fin de la frase |
Los objetivos se validan con datos; si no se cumplen, se ajustan `AUDIO_CHUNK_MS` y `MAX_SEGMENT_MS` antes que el diseño.

---

## 9. Errores y recuperación
| Situación | Comportamiento | Prioridad |
| ----- | ----- | ----- |
| La fuente termina | Estado `stopped`; se cierra la sesión Live | P0 |
| La fuente falla | Estado `error` con la causa; los demás escenarios siguen | P0 |
| Se cierra la sesión Live | Estado `reconnecting`; se abre una nueva sesión y se continúa; se acepta un hueco breve | P1 |
| Falla una traducción | El original se mantiene; un reintento; si falla, se omite esa frase en esa pista y se registra el error | P1 |
| Redis no disponible | Reintento de conexión; no se garantiza la entrega durante la caída | P1 |
| Se desconecta un cliente | Reconexión automática y recuperación desde el historial | P1 |
| Eventos repetidos o fuera de orden | El cliente fusiona por `(run_id, track, segment_id)` y `revision`  | P0 |
| Cierre anticipado de la Live API | Reanudación de sesión y pre-apertura de la nueva conexión | P2 |
---

## 10. Escalabilidad y capacidad
- **Unidad de escala:** el escenario. Cada uno es un flujo de audio independiente; la calidad de uno no depende de cuántos haya.
- **Asignación:** cada contenedor de worker atiende los escenarios de su `WORKER_SESSIONS` . Para 100 escenarios, por ejemplo, 10 workers con 10 escenarios cada uno, en una o varias máquinas, todos contra el mismo Redis.
- **Distribución:** el Gateway es independiente del procesamiento; pueden correr varias instancias detrás de un balanceador, todas suscritas al mismo Redis.
- **Idiomas:** cada idioma adicional agrega una llamada de texto por frase final, no una sesión de audio.
- **Límites externos:** cuota de sesiones concurrentes y de tokens de Gemini según el nivel del proyecto (en Vertex AI con pago por uso, hasta 1.000 sesiones concurrentes por proyecto); se documentan en el README.
- **Costo por hora y por escenario:** `costo_transcripción_por_hora + (idiomas_destino × costo_traducción_por_hora)` , con valores de la página de precios de Gemini (a completar, §14).
---

## 11. Despliegue y operación
`docker compose up` levanta tres servicios con una sola imagen Python que incluye `ffmpeg`:

| Servicio | Comando | Notas |
| ----- | ----- | ----- |
| `redis`  | imagen oficial | Sin persistencia |
| `worker`  | `python -m subs.worker`  | Único servicio con `GEMINI_API_KEY`  |
| `gateway`  | `python -m subs.gateway`  | Expone `GATEWAY_PORT`  |
Operación durante el evento:

1. Editar `sessions.yaml`  (fuente, idioma, título, glosario) y reiniciar el worker.
2. Compartir la URL de audiencia (por ejemplo, con un QR por sala).
3. Cargar el overlay en OBS/vMix como fuente de navegador.
4. Supervisar el panel de producción: estado, latencia y errores por sala.
5. Al terminar cada charla, descargar la transcripción desde la exportación.
**Micrófono:** Docker en macOS y Windows no accede al micrófono del equipo. Para esa fuente el worker se ejecuta fuera de Docker, apuntando al mismo Redis (P2, documentado en el README).

---

## 12. Seguridad y privacidad
- Las credenciales viven solo en `.env`  (fuera del repositorio) y solo el worker recibe `GEMINI_API_KEY` .
- El MVP no tiene autenticación; recomendación para producción: gateway detrás de un proxy con TLS y autenticación básica para el panel.
- Las fuentes solo se definen en `sessions.yaml` , bajo control del operador; los clientes no pueden indicar URLs ni rutas.
- Los logs en nivel `INFO`  no incluyen audio ni texto de subtítulos, solo identificadores y métricas.
---

## 13. Estructura del código
```text
live-subs/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── sessions.yaml
├── LICENSE
├── README.md
├── CLAUDE.md
├── AGENTS.md
├── .claude/skills/
├── .specify/memory/
│   └── constitution.md
├── docs/
│   └── architecture.md      # este documento
├── specs/
│   └── 001-subs-mvp/        # spec.md, plan.md, research.md, tasks.md, contracts/...
├── samples/
│   ├── audio/               # clips EN y ES generados con TTS + guiones + README.md con su origen
│   ├── local/               # audio real solo para pruebas locales (en .gitignore)
│   └── glossaries/
├── scripts/                 # t0/ (prueba técnica), make_clips.py, replay_events.py
├── src/subs/
│   ├── common/   (config.py, schema.py, queues.py, logs.py)
│   ├── worker/   (main.py, ingest.py, transcriber.py, translator.py, publisher.py)
│   └── gateway/  (main.py, static/index.html, static/overlay.html (P1), static/panel.html (P1))
└── tests/
```
---

## 14. Decisiones pendientes
1. **Cuota:** confirmar la cuota de sesiones concurrentes del proyecto.
2. **Marcas de tiempo:** verificar si la Live API entrega tiempos por enunciado (§8).
3. **Corte forzado (P1):** verificar que `audio_stream_end`  a mitad de una frase fuerza el final y que la sesión sigue aceptando audio. Si no funciona, el corte se hace en el cliente con el último parcial.
4. **Costos:** completar la fórmula de §10 con los precios vigentes.
5. **Capacidad por worker:** medir cuántos escenarios soporta un proceso antes de degradar la latencia.
---

## 15. Criterios de validación
### P0 — MVP
- [ ] Dos escenarios simultáneos desde archivos de `samples/audio/`  (uno en inglés, uno en español).
- [ ] Original parcial y final en pantalla, sin parciales obsoletos.
- [ ] Traducción EN→ES en la sala en inglés y ES→EN en la sala en español, vinculadas a su frase original.
- [ ] La vista de audiencia permite elegir sesión y pista.
- [ ] `docker compose up`  funciona desde un clon limpio siguiendo el README.
- [ ] El README explica credenciales, modelos y cómo escalar.
### P1
- [ ] La sesión continúa tras un cierre de la conexión Live (prueba de más de 10 minutos).
- [ ] El glosario corrige al menos un término técnico visible en la demo.
- [ ] Un cliente que se conecta tarde ve las últimas frases.
- [ ] Exportación SRT/VTT/TXT de una charla completa.
- [ ] Overlay funcionando en OBS sobre el video de la charla.
- [ ] Latencias registradas y dentro de los objetivos de §8.
### Pruebas automáticas (mínimas)
Se prueban las funciones puras, que son baratas de testear y donde un error rompe la demo: validación de `SubtitleEvent` y de `sessions.yaml`; combinación y filtrado del glosario; fusión de eventos por clave y `revision`; generación de SRT y VTT a partir de eventos finales. La integración con Gemini se valida manualmente con los clips de `samples/audio/`.

### Entrega
- [ ] Video de 1 a 2 minutos con audio real de Nerdearla y subtítulos en inglés generados por el sistema.
- [ ] Repositorio público con licencia Apache 2.0.
- [ ] Envío en Devpost antes del viernes 25 a las 10:00 (hora de Ecuador).


