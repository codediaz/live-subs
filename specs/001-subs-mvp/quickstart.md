# Quickstart de validación: Live Subs MVP (P0)

**Feature**: `001-subs-mvp` | **Plan**: [plan.md](plan.md)

Guía para comprobar de punta a punta que el P0 cumple la spec. No reemplaza al README: el README es
para quien usa el sistema y esta guía es para validar la feature.

## Requisitos previos

- Docker con Compose v2, acceso a internet y una API key de Gemini con acceso a los modelos de
  [contracts/env.md](contracts/env.md).
- Para los tests locales: Python 3.12.

## V0. Tests de funciones puras (principio 11)

```bash
pip install -e ".[dev]"
pytest -q
```

**Esperado**: todo en verde. Cubre la lista de "Estrategia de tests" del plan.

## V1. Arranque desde un clon limpio (CE-004, CE-005, RF-033, RF-040)

Hacerlo en una carpeta nueva, siguiendo **solo el README** y cronometrando desde el `git clone`:

```bash
git clone <repo> /tmp/live-subs-check && cd /tmp/live-subs-check
cp .env.example .env        # editar: GEMINI_API_KEY=...
docker compose up --build
```

**Esperado**:

- los tres servicios quedan arriba y `curl -s localhost:8000/healthz` responde 200;
- en `http://localhost:8000/` aparecen `sala1` (EN → pista `es`) y `sala2` (ES → pista `en`);
- menos de 10 min desde el clone hasta ver subtítulos (CE-005);
- menos de 30 s desde abrir la vista hasta leer la pista elegida (CE-004).

## V2. Parciales, finales y traducción (CE-001, CE-002, CE-003)

1. En la vista, elegir `sala1` → `original`: el texto de la frase en curso se actualiza y al terminar
   queda fijo, sin parciales viejos en pantalla.
2. Cambiar a `sala1` → `es`: solo aparecen frases completas en español.
3. Repetir con `sala2` (`original` en español y `en`).
4. Ver los eventos crudos en Redis:
   `docker compose exec redis redis-cli PSUBSCRIBE 'subs:*'`. Cada traducción tiene el mismo
   `segment_id` que un final del original y todos los eventos traen `latency_ms` (CE-008).

## V3. Loop y espectador que llega tarde (RF-043, historia 3)

Esperar a que termine una vuelta del clip más largo y abrir la vista recién entonces.

**Esperado**:

- hay subtítulos en curso en los dos escenarios;
- con la vista abierta durante el cambio de vuelta, la pantalla se limpia y sigue (RF-021);
- `docker compose exec redis redis-cli GET run:sala1` cambia en cada vuelta.

## V4. Aislamiento ante una falla (CE-007, RF-025)

Matar el ffmpeg de `sala2` dentro del worker:

```bash
docker compose exec worker python -c "import os,signal; [os.kill(int(p), signal.SIGTERM) for p in os.listdir('/proc') if p.isdigit() and b'ffmpeg' in open(f'/proc/{p}/cmdline','rb').read() and b'charla_es' in open(f'/proc/{p}/cmdline','rb').read()]"
curl -s localhost:8000/api/status
```

**Esperado**: `sala2` en `error` con `last_error`; `sala1` sigue en `live` y la vista de `sala1` no se
interrumpe.

## V5. Fuente de stream (RF-002)

Agregar un escenario temporal con `source.type: stream` y la URL de una radio o HLS pública en inglés
o en español. Usar otro archivo de configuración (`SESSIONS_FILE=sessions.stream.yaml`) y reiniciar
el worker.

**Esperado**: ese escenario produce subtítulos del audio en vivo. Con una URL inaccesible, queda en
`error` y los demás siguen.

## V6. Eventos repetidos y desordenados en la vista (RF-019 a RF-021)

Con la vista abierta en una sesión de prueba, ejecutar el script de repetición:

```bash
docker compose exec worker python scripts/replay_events.py --session demo
```

El script publica en `subs:demo:*` una secuencia fija con parciales duplicados, revisiones
desordenadas, un final antes de su último parcial y un cambio de `run_id`.

**Esperado**:

- una línea por frase con el texto de mayor revisión;
- el final no se reemplaza por un parcial tardío;
- la pantalla se limpia al cambiar de ejecución.

## V7. Configuración inválida (RF-029)

Poner un `id` repetido en una copia de `sessions.yaml` y arrancar el worker con ella.

**Esperado**: el worker sale con código distinto de 0 y un mensaje que nombra el escenario y el
campo. No arranca ningún escenario.

## V8. Secretos y logs (RF-031, RF-034)

```bash
docker compose exec gateway env | grep -c GEMINI_API_KEY   # esperado: 0
docker compose logs worker | head                          # JSON con session_id, sin texto de subtítulos
```

## V9. Legibilidad de la vista (RF-044)

En las herramientas de desarrollo del navegador, con un ancho de 360 px, comprobar:

- no hay desplazamiento horizontal;
- el contraste texto/fondo es ≥ 4,5:1;
- los botones A− / A+ cambian entre al menos 3 tamaños y el tamaño elegido se conserva al recargar.
