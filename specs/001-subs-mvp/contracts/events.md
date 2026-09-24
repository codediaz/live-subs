# Contrato: eventos y claves de Redis (P0)

Base: `docs/architecture.md` §7.1 (`SubtitleEvent`), §7.2 (`SessionStatus`) y §7.5 (claves). El
contrato no cambia: `schema_version = 1`.

## Reglas del P0 que precisan §7.1

1. Numeración:
   - `sequence` es monótona dentro de una ejecución y la comparten todas las pistas del escenario;
   - `segment_id` empieza en 0 en cada ejecución.
2. El final de una frase lleva una `revision` mayor que la de cualquier parcial de esa frase.
3. Una traducción copia `run_id`, `segment_id`, `start_ms` y `end_ms` de su original. Su `revision`
   es 0 y su `latency_ms` es la latencia de traducción de §8.
4. `latency_ms` es obligatorio en P0 (RF-038). El campo sigue siendo opcional en el esquema para no
   romper la compatibilidad.
5. No se publican parciales vacíos ni repetidos.

## Claves de Redis usadas en P0

| Clave | Tipo | P0 |
| --- | --- | --- |
| `subs:{session_id}:{track}` | pub/sub | Sí: un mensaje = un `SubtitleEvent` en JSON |
| `run:{session_id}` | cadena | Sí: `run_id` de la ejecución actual |
| `status:{session_id}` | cadena JSON con expiración | Sí: último `SessionStatus` |
| `hist:{session_id}:{run_id}:{track}` | lista | No (P1) |
