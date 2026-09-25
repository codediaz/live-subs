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
- **CE-004** (abrir la vista → leer la pista elegida en < 30 s): **FALLA** en este intento; se
  corrigió en T045–T052 y pasó en la repetición (T053, más abajo).
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

## V1 repetida desde un clon limpio (T053)

**Fecha**: 2026-09-25 (UTC) · **Commit**: `57f9638` (incluye T045–T052) · **Carpeta**: clon nuevo
`jury2-live-subs` (`git clone git@github.com:codediaz/live-subs.git`), siguiendo solo el README
(`docker compose up --build`), con una copia del `.env` existente.

| Hito | Hora (UTC) | Desde el clone | Evidencia |
|------|------------|----------------|-----------|
| Inicio de `git clone` | 11:37:45,9 | 0 s | reloj antes del clone |
| Clone terminado y `.env` copiado | 11:37:48 | 2 s | reloj |
| `curl localhost:8000/healthz` → 200 | 11:38:18,7 | 33 s | sondeo con `curl` |
| Primer subtítulo (`subs:sala2:original`) | 11:38:20,0 | 34 s | `PSUBSCRIBE 'subs:*'` |
| Primera frase final | 11:38:21,5 | 36 s | `PSUBSCRIBE 'subs:*'` |

La imagen usó capas de la caché local de Docker (compilaciones anteriores del mismo `Dockerfile`).
En T038, con la imagen compilada casi desde cero, el mismo recorrido tomó 3 min 18 s.

**CE-004**: Chromium headless abre `http://localhost:8000/`, elige escenario y pista y cronometra hasta
la primera línea en `#subtitles` (`ce004_timing.py`, el mismo método de T038).

| Momento | Escenario → pista | Escenarios listados | Pista elegida | Primera línea | Líneas |
|---------|-------------------|---------------------|---------------|---------------|--------|
| 11:38:30, primera vuelta | `sala1` → `es` | 0,73 s | 0,74 s | **0,84 s** | 1 |
| 11:38:32, primera vuelta | `sala2` → `en` | 0,44 s | 0,44 s | **0,54 s** | 2 |
| 11:38:33, primera vuelta | `sala1` → `es` | 0,31 s | 0,33 s | **0,43 s** | 1 |
| 11:38:34, primera vuelta | `sala2` → `en` | 0,33 s | 0,34 s | **0,45 s** | 2 |
| 11:40:36, justo al cambiar `run:sala1` | `sala1` → `es` | 0,44 s | 0,44 s | **0,55 s** | 5 |
| 11:42:52, justo al cambiar `run:sala2` | `sala2` → `en` | 0,32 s | 0,33 s | **0,43 s** | 5 |

Justo después de que el clip vuelve a empezar, la vista muestra las últimas 5 frases de la vuelta
anterior (RF-048). Las reemplaza el primer evento de la ejecución nueva, como indica §6.4.2.

### Resultado

- [x] **CE-005** (clon limpio → subtítulos en < 10 min): **34 s** hasta el primer subtítulo y **36 s**
  hasta la primera frase final (con caché de Docker). OK.
- [x] **CE-004** (abrir la vista → leer la pista elegida en < 30 s): **≤ 0,84 s** en las dos pistas
  traducidas, también justo después de un cambio de vuelta. OK.
- `pytest -q`: 141 passed.
