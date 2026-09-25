# Validación: Live Subs MVP (P0)

**Propósito**: registrar el resultado de los escenarios de [quickstart.md](../quickstart.md) y de los
criterios de éxito de [spec.md](../spec.md).
**Feature**: [spec.md](../spec.md)

## V1. Arranque desde un clon limpio (T038)

**Fecha**: 2026-09-25 (UTC) · **Commit**: `c0ffa8e` · **Carpeta**: clon nuevo `jury-live-subs`
(`git clone git@github.com:codediaz/live-subs.git`), siguiendo solo el README, con el `.env` existente.

| Hito | Hora (UTC) | Evidencia |
|------|------------|-----------|
| `git clone` | 04:15:17 | `git reflog` (`clone: from ...`) |
| `.env` creado | 04:15:35 | fecha de creación del archivo |
| Imagen construida | 04:18:06 | `docker images` (`live-subs:local`) |
| Contenedores creados | 04:18:09 | `docker inspect` |
| Sesiones Live abiertas (`sala1`, `sala2`) | 04:18:14 | log del worker `live_session_open` |
| Primera frase final traducida | 04:18:35 | log del worker (llamada a `TRANSLATE_MODEL`) |

`curl -s localhost:8000/healthz` → 200 y `/` lista `sala1` y `sala2`.

### Resultado

- [x] **CE-005** (clon limpio → subtítulos en < 10 min): **3 min 18 s** (04:15:17 → 04:18:35). OK.
- [ ] **CE-004** (abrir la vista → leer la pista elegida en < 30 s): **FALLA**.
  Medido con Chromium headless: se abre `http://localhost:8000/`, se elige escenario y pista y se
  cronometra hasta la primera línea en `#subtitles`.

  | Escenario → pista | Escenarios listados | Pista elegida | Primera línea |
  |-------------------|---------------------|---------------|---------------|
  | `sala1` → `es` | 0,72 s | 0,73 s | **54,9 s** |
  | `sala2` → `en` | 0,44 s | 0,45 s | **sin línea en 122 s** |

### Causa observada

Muestra de eventos en Redis (`PSUBSCRIBE 'subs:*'`, 75 s, solo metadatos):

| Escenario | Pista | Parciales | Finales |
|-----------|-------|-----------|---------|
| `sala1` | `original` | 132 | 3 |
| `sala1` | `es` | 0 | 3 |
| `sala2` | `original` | 133 | **0** |
| `sala2` | `en` | 0 | **0** |

- `sala2` (ES): la transcripción entrega parciales pero no finales, así que la pista `en` no recibe
  traducciones (afecta también CE-001 y CE-003).
- `sala1` (EN): hay un final cada ~20–25 s, y un hueco de ~75 s entre la última frase del clip y la
  primera del siguiente ciclo. La vista no muestra historial al conectarse, así que una pista traducida
  puede tardar más de 30 s en mostrar su primera línea.

**Pendiente**: tarea de corrección a definir (finales en `sala2` y tiempo hasta la primera línea en
pistas traducidas). T038 queda abierta.

**Nota**: se usa la numeración de `spec.md`, que coincide con `quickstart.md` §V1 (CE-004 = abrir la
vista → leer la pista en < 30 s; CE-005 = clon → subtítulos en < 10 min).
