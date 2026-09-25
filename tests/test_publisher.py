"""Publisher contract checks without starting the worker (T024)."""

import asyncio
import time
from typing import Any

from subs.common.schema import SessionStatus, SubtitleEvent
from subs.worker.publisher import Publisher


class RecordingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.status_written = asyncio.Event()

    async def publish(self, *args: Any) -> int:
        self.calls.append(("publish", args, {}))
        return 0

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        self.calls.append(("set", args, kwargs))
        if sum(call[1][0] == "status:sala1" for call in self.calls) >= 2:
            self.status_written.set()
        return True


def make_status() -> SessionStatus:
    return SessionStatus(
        session_id="sala1",
        state="live",
        source_type="file",
        uptime_s=2,
        last_event_at_ms=None,
        latency_original_ms=None,
        latency_translation_ms=None,
        reconnects=0,
        errors=0,
        last_error=None,
        updated_at_ms=123,
    )


def test_publisher_uses_event_and_status_contracts() -> None:
    async def check() -> None:
        redis = RecordingRedis()
        publisher = Publisher(redis, status_interval_s=2, status_ttl_s=15)
        event = SubtitleEvent(
            session_id="sala1",
            run_id=1234,
            track="original",
            sequence=0,
            segment_id=0,
            kind="original",
            lang="en",
            text="Hello",
            is_final=False,
            start_ms=0,
            emitted_at_ms=0,
            latency_ms=20,
        )
        before_ms = time.time_ns() // 1_000_000
        await publisher.set_run("sala1", event.run_id)
        published = await publisher.publish_event(event)
        after_ms = time.time_ns() // 1_000_000
        await publisher.publish_status(make_status())

        assert redis.calls[0] == ("set", ("run:sala1", "1234"), {})
        action, args, kwargs = redis.calls[1]
        assert action == "publish" and kwargs == {}
        assert args[0] == "subs:sala1:original"
        assert SubtitleEvent.model_validate_json(args[1]) == published
        assert before_ms <= published.emitted_at_ms <= after_ms
        assert published.latency_ms == 20
        assert event.emitted_at_ms == 0

        action, args, kwargs = redis.calls[2]
        assert action == "set" and args[0] == "status:sala1"
        assert SessionStatus.model_validate_json(args[1]) == make_status()
        assert kwargs == {"ex": 15}

    asyncio.run(check())


def test_status_loop_publishes_immediately_and_can_be_cancelled() -> None:
    async def check() -> None:
        redis = RecordingRedis()
        publisher = Publisher(redis, status_interval_s=0.01, status_ttl_s=15)
        task = asyncio.create_task(publisher.publish_status_periodically(make_status))
        try:
            await asyncio.wait_for(redis.status_written.wait(), timeout=1)
            assert sum(call[1][0] == "status:sala1" for call in redis.calls) >= 2
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(check())
