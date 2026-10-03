# Contrato: variables de entorno nuevas (002)

Base: `docs/architecture.md` §7.7 y `specs/001-subs-mvp/contracts/env.md`, que no cambian. Esta tabla
lista solo las variables que agrega la feature (**Δ**). Las recibe solo el worker y llegan por
`env_file: .env`, sin cambios en Compose. `.env.example` debe incluir la unión de ambos contratos
(`tests/test_env_example.py`, R14).

| Variable | Por defecto | Servicio | Uso |
| --- | --- | --- | --- |
| **Δ** `RECONNECT_MAX_ATTEMPTS` | `5` | worker | Intentos consecutivos de reconexión antes de pasar a `error`. Entero ≥ 1 (RF-004, RF-006) |
| **Δ** `RECONNECT_BACKOFF_INITIAL_MS` | `500` | worker | Espera antes del segundo intento; se duplica en cada intento siguiente. Entero ≥ 100 (RF-003, RF-006) |
| **Δ** `RECONNECT_BACKOFF_MAX_MS` | `8000` | worker | Tope de la espera entre intentos. Entero ≥ `RECONNECT_BACKOFF_INITIAL_MS` (RF-006) |
| **Δ** `RECONNECT_ATTEMPT_TIMEOUT_S` | `10` | worker | Límite para que un intento quede listo. Entre 1 y 120 s (RF-007) |
| **Δ** `LIVE_SESSION_MAX_S` | vacío | worker | **Solo para pruebas.** Cierra a propósito cada conexión a los N s de quedar lista. Vacío o no definido = solo cierres reales; con valor, entero ≥ 1 (RF-023, R13) |

Reglas:

- Una variable vacía cuenta como no configurada y toma el valor por defecto, como en el MVP.
- Si un valor no cumple su regla, el worker no arranca y el error nombra la variable (RF-029 del MVP).
  Para la regla cruzada se nombra `RECONNECT_BACKOFF_MAX_MS`.
- Con los valores por defecto, las esperas son 0, 500, 1000, 2000 y 4000 ms (R2).
- En `.env.example`, `LIVE_SESSION_MAX_S` va vacío y con un comentario que dice que es solo para
  pruebas.
