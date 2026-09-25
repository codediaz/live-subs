"""Tests for the bounded drop-oldest queue (research.md R7; RF-004, RF-014)."""

import asyncio

import pytest

from subs.common.queues import DropOldestQueue


def test_rejects_non_positive_maxsize():
    with pytest.raises(ValueError):
        DropOldestQueue(0)


def test_get_returns_items_in_order():
    async def scenario():
        queue = DropOldestQueue(5)
        for item in range(3):
            queue.put_nowait(item)
        return [await queue.get() for _ in range(3)]

    assert asyncio.run(scenario()) == [0, 1, 2]


def test_drops_oldest_when_full():
    async def scenario():
        queue = DropOldestQueue(3)
        for item in range(1, 6):
            queue.put_nowait(item)
        return [await queue.get() for _ in range(queue.qsize())], queue.dropped

    items, dropped = asyncio.run(scenario())
    assert items == [3, 4, 5]
    assert dropped == 2


def test_put_returns_the_dropped_item():
    queue = DropOldestQueue(2)
    assert queue.put_nowait("a") is None
    assert queue.put_nowait("b") is None
    assert queue.put_nowait("c") == "a"
    assert queue.dropped == 1


def test_put_never_blocks():
    async def scenario():
        queue = DropOldestQueue(2)
        for item in range(1000):
            queue.put_nowait(item)  # synchronous: the producer can never be blocked
        return queue.qsize(), queue.dropped, await queue.get()

    assert asyncio.run(scenario()) == (2, 998, 998)


def test_get_waits_for_an_item():
    async def scenario():
        queue = DropOldestQueue(2)
        consumer = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        assert not consumer.done()
        queue.put_nowait("chunk")
        return await asyncio.wait_for(consumer, timeout=1)

    assert asyncio.run(scenario()) == "chunk"


def test_size_helpers():
    queue = DropOldestQueue(2)
    assert queue.empty()
    assert queue.maxsize == 2
    queue.put_nowait(1)
    assert queue.qsize() == 1
    assert not queue.empty()
