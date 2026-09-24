# Contrato: `sessions.yaml` (P0)

Base: `docs/architecture.md` §7.3. Solo se listan las diferencias y las reglas que valida el P0.

## Diferencia con §7.3

- **Δ `source.loop`** (bool, opcional, por defecto `false`). Solo vale con `source.type: file`. Si
  está activado, cuando el clip termina empieza una ejecución nueva con una sesión de transcripción
  nueva (RF-043).

## Valores admitidos en P0

| Campo | Valores |
| --- | --- |
| `source.type` | `file`, `stream` (`microphone` es P2 y se rechaza) |
| `source_language` | `en`, `es` (`auto` es P2 y se rechaza) |
| `target_languages` | `en`, `es` (`pt` es P1 y se rechaza) |
| `glossary` | Se acepta la ruta, pero en P0 no se usa (P1) |

## Reglas de validación (RF-029)

1. `id` es obligatorio, único y sin espacios.
2. `name`, `title` y `source_language` son obligatorios.
3. `source.uri` es obligatorio para `file` y `stream`. Para `file`, el archivo tiene que existir.
4. `loop: true` con `type: stream` es un error.
5. `target_languages` viene del escenario o, si no está, de `defaults`.
6. Cada id de `WORKER_SESSIONS` tiene que existir en el archivo.

Un error detiene el arranque. El mensaje nombra el `id` del escenario (o su posición en la lista) y el
campo.

## Configuración por defecto del repositorio (RF-040)

Dos escenarios, los dos con `type: file` y `loop: true`:

- `sala1`: clip en inglés, destino `[es]`.
- `sala2`: clip en español, destino `[en]`.
