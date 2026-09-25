"""Publish subtitle events, run identifiers, and live session status to Redis."""

import asyncio
import time
from collections.abc import Callable

from redis.asyncio import Redis

from subs.common.schema import SessionStatus, SubtitleEvent, channel_name


class Publisher:
    def __init__(self, redis: Redis, *, status_interval_s: float, status_ttl_s: int) -> None:
        self.redis = redis
        self.status_interval_s = status_interval_s
        self.status_ttl_s = status_ttl_s

    async def set_run(self, session_id: str, run_id: int) -> None:
        """Store the current run identifier without an expiry."""
        await self.redis.set(f"run:{session_id}", str(run_id))

    async def publish_event(self, event: SubtitleEvent) -> SubtitleEvent:
        """Stamp and publish one event; return the exact event sent to Redis."""
        published = event.model_copy(update={"emitted_at_ms": time.time_ns() // 1_000_000})
        await self.redis.publish(
            channel_name(published.session_id, published.track),
            published.model_dump_json(),
        )
        return published

    async def publish_status(self, status: SessionStatus) -> None:
        """Replace the latest status and refresh its configured expiry."""
        await self.redis.set(
            f"status:{status.session_id}",
            status.model_dump_json(),
            ex=self.status_ttl_s,
        )

    async def publish_status_periodically(
        self, current_status: Callable[[], SessionStatus]
    ) -> None:
        """Publish immediately, then at the configured interval until cancelled."""
        while True:
            await self.publish_status(current_status())
            await asyncio.sleep(self.status_interval_s)
