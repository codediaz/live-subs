"""HTTP contract checks for the P0 gateway."""

import pytest
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError

from subs.common.config import GatewaySettings, load_sessions
from subs.common.schema import SessionStatus
from subs.gateway.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeRedis:
    def __init__(self) -> None:
        self.healthy = True
        self.status: dict[str, bytes] = {}

    async def ping(self) -> bool:
        if not self.healthy:
            raise ConnectionError("unavailable")
        return True

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        if not self.healthy:
            raise ConnectionError("unavailable")
        return [self.status.get(key) for key in keys]


@pytest.mark.anyio
async def test_http_contract() -> None:
    redis = FakeRedis()
    sessions = load_sessions("sessions.yaml", "")
    status = SessionStatus(
        session_id="sala1",
        state="live",
        source_type="file",
        uptime_s=10,
        last_event_at_ms=None,
        latency_original_ms=None,
        latency_translation_ms=None,
        reconnects=0,
        errors=0,
        last_error=None,
        updated_at_ms=123,
    )
    redis.status["status:sala1"] = status.model_dump_json().encode()
    app = create_app(GatewaySettings(), sessions, redis)  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/")).status_code == 200
        listing = (await client.get("/api/sessions")).json()
        assert [item["id"] for item in listing] == ["sala1", "sala2"]
        assert listing[0]["tracks"] == ["original", "es"]
        assert listing[1]["tracks"] == ["original", "en"]
        assert all("source" not in item for item in listing)
        assert (await client.get("/api/status")).json() == {"sala1": status.model_dump(), "sala2": None}
        redis.healthy = False
        assert (await client.get("/healthz")).status_code == 503
        assert (await client.get("/api/status")).status_code == 503
