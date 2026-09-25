"""Bounded queue that drops the oldest item when full (research.md R7).

Producers never block: ingestion, translation and WebSocket fan-out keep up with real time by
discarding stale items instead of accumulating delay. Callers log the drops.
"""

import asyncio


class DropOldestQueue[T]:
    def __init__(self, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize must be at least 1, got {maxsize}")
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize)
        self.dropped = 0

    @property
    def maxsize(self) -> int:
        return self._queue.maxsize

    def put_nowait(self, item: T) -> T | None:
        """Add an item without blocking. Returns the dropped item when the queue was full."""
        dropped: T | None = None
        if self._queue.full():
            dropped = self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(item)
        return dropped

    async def get(self) -> T:
        return await self._queue.get()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()
