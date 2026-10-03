# Contrato: eventos durante una reconexión (002)

Base: `docs/architecture.md` §7.1 y `specs/001-subs-mvp/contracts/events.md`. **El contrato no cambia**:
`SubtitleEvent` sigue en `schema_version = 1` y los canales de Redis son los mismos. Este documento
precisa cómo se usa ante una reconexión.

## Reglas que agrega 002

1. **Continuidad (RF-012).** Una reconexión no crea una ejecución nueva:
   - `run_id` no cambia;
   - `sequence` sigue siendo estrictamente creciente dentro de la ejecución y compartida por todas las
     pistas;
   - `segment_id` continúa desde el último valor y nunca se repite entre frases distintas.
2. **Posición real (RF-011).** `start_ms` y `end_ms` de las frases posteriores incluyen el hueco. Dentro
   de una ejecución, el `start_ms` de las frases nunca retrocede (CE-004).
3. **Final vacío (RF-013, RF-014).** Si había una frase abierta al cortar, se publica en `original` un
   final con `text = ""` y los valores de [data-model.md §7](../data-model.md#7-final-vacío-δ-uso-del-contrato-existente).
   Es una excepción a la regla 4 del contrato del MVP (`latency_ms` obligatorio): el final vacío lleva
   `latency_ms = null`.
4. **Sin traducción del final vacío.** Ninguna pista de traducción recibe un evento para ese
   `segment_id`.
5. **Resultados tardíos (RF-008).** Después del corte no se publica ningún evento que provenga de la
   conexión cortada.
6. **Traducciones pendientes (RF-015).** Las traducciones de finales publicados antes del corte se
   publican aunque la reconexión siga en curso, con su `segment_id` y `sequence` normales.

## Consumidores

| Consumidor | Comportamiento ante el final vacío |
| --- | --- |
| Gateway (`RecentFinals`, `/ws`) | Lo reenvía en vivo a los clientes conectados (para que oculten el parcial) pero **no** lo guarda entre las últimas frases que se envían al conectarse |
| Vista de audiencia y overlay | Fusionan por `(run_id, track, segment_id)` como siempre; el final vacío reemplaza al parcial y **no se dibuja**. La pantalla no se limpia, porque el `run_id` es el mismo |
| Historial y exportación (P1) | No lo incluyen |

## Ejemplo de secuencia (pista `original`)

| `sequence` | `segment_id` | `revision` | `is_final` | `text` | Nota |
| --- | --- | --- | --- | --- | --- |
| 120 | 41 | 3 | true | "…and that is the deployment." | Final antes del corte |
| 121 | 41 | 0 | — | (traducción `es`) | Se publica aunque haya reconexión |
| 122 | 42 | 0 | false | "So the next" | Parcial; la conexión se corta |
| 123 | 42 | 1 | true | `""` | Final vacío; `latency_ms = null` |
| 124 | 43 | 0 | false | "Observability is…" | Primera frase de la conexión nueva |
