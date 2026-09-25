"""HTTP and WebSocket gateway for configured sessions."""

import asyncio
import logging
import sys
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from subs.common.config import ConfigError, GatewaySettings, SessionConfig, load_sessions
from subs.common.logs import setup_logging
from subs.common.queues import DropOldestQueue
from subs.common.schema import SessionStatus, SubtitleEvent, channel_name

_LOGGER = logging.getLogger(__name__)
_INDEX = Path(__file__).parent / "static" / "index.html"


class RecentFinals:
    """Bounded final events from the latest run of each session and track."""

    def __init__(self, max_events: int) -> None:
        if max_events < 0:
            raise ValueError("max_events must not be negative")
        self.max_events = max_events
        self._runs: dict[tuple[str, str], int] = {}
        self._events: dict[tuple[str, str], deque[SubtitleEvent]] = {}

    def add(self, event: SubtitleEvent) -> None:
        key = (event.session_id, event.track)
        run_id = self._runs.get(key)
        if run_id is not None and event.run_id < run_id:
            return
        if run_id is None or event.run_id > run_id:
            self._runs[key] = event.run_id
            self._events.pop(key, None)
        if event.is_final and self.max_events:
            self._events.setdefault(key, deque(maxlen=self.max_events)).append(event)

    def snapshot(self, session_id: str, track: str) -> list[SubtitleEvent]:
        return list(self._events.get((session_id, track), ()))


class EventDistributor:
    """One Redis pattern subscription, fanned out to bounded per-client queues."""

    def __init__(self, recent_finals: RecentFinals) -> None:
        self.clients: dict[tuple[str, str], set[DropOldestQueue[str]]] = defaultdict(set)
        self.recent_finals = recent_finals

    async def listen(self, pubsub: PubSub) -> None:
        try:
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    event = SubtitleEvent.model_validate_json(message["data"])
                except ValueError:
                    _LOGGER.warning("invalid_subtitle_event")
                    continue
                actual_channel = message["channel"]
                if isinstance(actual_channel, bytes):
                    actual_channel = actual_channel.decode("utf-8")
                if actual_channel != channel_name(event.session_id, event.track):
                    _LOGGER.warning("mismatched_subtitle_channel")
                    continue
                self.recent_finals.add(event)
                payload = '{"type":"subtitle","data":' + event.model_dump_json() + "}"
                for queue in tuple(self.clients.get((event.session_id, event.track), ())):
                    if queue.put_nowait(payload) is not None:
                        _LOGGER.warning(
                            "ws_event_dropped",
                            extra={"session_id": event.session_id, "dropped_events": queue.dropped},
                        )
        except asyncio.CancelledError:
            raise
        except (RedisError, OSError) as exc:
            _LOGGER.error("redis_subscription_failed", extra={"error": str(exc)})


def create_app(
    settings: GatewaySettings, sessions: list[SessionConfig], redis: Redis | None = None
) -> FastAPI:
    """Build the gateway with one Redis connection and the validated session list."""
    client = redis if redis is not None else Redis.from_url(settings.redis_url)
    distributor = EventDistributor(RecentFinals(settings.recent_finals_n))
    by_id = {session.id: session for session in sessions}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pubsub = client.pubsub()
        listener: asyncio.Task[None] | None = None
        try:
            await pubsub.psubscribe("subs:*")
            listener = asyncio.create_task(distributor.listen(pubsub))
            yield
        finally:
            if listener is not None:
                listener.cancel()
                await asyncio.gather(listener, return_exceptions=True)
            await pubsub.aclose()
            if redis is None:
                await client.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        try:
            if not await client.ping():
                raise HTTPException(status_code=503, detail="Redis unavailable")
        except (RedisError, OSError) as exc:
            _LOGGER.warning("redis_health_failed", extra={"error": str(exc)})
            raise HTTPException(status_code=503, detail="Redis unavailable") from exc
        return {"status": "ok"}

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, object]]:
        return [
            {
                "id": session.id,
                "name": session.name,
                "title": session.title,
                "source_language": session.source_language,
                "tracks": session.tracks,
            }
            for session in sessions
        ]

    @app.get("/api/status")
    async def get_status() -> dict[str, SessionStatus | None]:
        try:
            values = await client.mget([f"status:{session.id}" for session in sessions])
        except (RedisError, OSError) as exc:
            _LOGGER.warning("redis_status_failed", extra={"error": str(exc)})
            raise HTTPException(status_code=503, detail="Redis unavailable") from exc
        return {
            session.id: SessionStatus.model_validate_json(value) if value is not None else None
            for session, value in zip(sessions, values, strict=True)
        }

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(_INDEX.read_text(encoding="utf-8"))

    @app.websocket("/ws/{session_id}")
    async def websocket_subtitles(websocket: WebSocket, session_id: str, tracks: str = "") -> None:
        session = by_id.get(session_id)
        requested = tracks.split(",") if tracks else []
        if session is None or not requested or any(track not in session.tracks for track in requested):
            await websocket.accept()
            await websocket.close(code=1008, reason="Invalid session or track")
            return

        queue: DropOldestQueue[str] = DropOldestQueue(settings.ws_client_queue_max)
        subscriptions = {(session_id, track) for track in requested}
        for key in subscriptions:
            distributor.clients[key].add(queue)
        for track in dict.fromkeys(requested):
            for event in distributor.recent_finals.snapshot(session_id, track):
                payload = '{"type":"subtitle","data":' + event.model_dump_json() + "}"
                queue.put_nowait(payload)
        await websocket.accept()
        send_lock = asyncio.Lock()

        async def send_events() -> None:
            while True:
                payload = await queue.get()
                async with send_lock:
                    await websocket.send_text(payload)

        async def send_pings() -> None:
            while True:
                await asyncio.sleep(settings.ws_ping_s)
                async with send_lock:
                    await websocket.send_json({"type": "ping"})

        async def receive_messages() -> None:
            while True:
                await websocket.receive_text()  # client messages have no effect

        tasks = [asyncio.create_task(coro()) for coro in (send_events, send_pings, receive_messages)]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task.done() and not task.cancelled():
                    exception = task.exception()
                    if exception is not None and not isinstance(exception, WebSocketDisconnect):
                        _LOGGER.warning("ws_connection_failed", extra={"session_id": session_id, "error": str(exception)})
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for key in subscriptions:
                distributor.clients[key].discard(queue)

    return app


def main() -> None:
    """Load configuration before starting uvicorn."""
    try:
        settings = GatewaySettings.from_env()
        setup_logging(settings.log_level)
        sessions = load_sessions(settings.sessions_file, "")
    except ConfigError as exc:
        setup_logging("INFO")
        _LOGGER.error("invalid_configuration", extra={"error": str(exc)})
        sys.exit(2)

    import uvicorn

    uvicorn.run(create_app(settings, sessions), host="0.0.0.0", port=settings.gateway_port)
