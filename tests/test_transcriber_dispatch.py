"""Connection-cut dispatch tests for RF-008, RF-013, and RF-014."""

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from subs.common.queues import DropOldestQueue
from subs.common.schema import SubtitleEvent
from subs.worker.ingest import AudioClock
from subs.worker.transcriber import SegmentTracker, _AudioGapDiscarder, _ConnectionDispatch, should_force_cut


def _content(*, partial: str | None = None, final: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        interim_input_transcription=SimpleNamespace(text=partial) if partial is not None else None,
        input_transcription=SimpleNamespace(text=final) if final is not None else None,
    )


def _dispatch(
    on_event: Callable[[SubtitleEvent], Awaitable[None]],
) -> tuple[SegmentTracker, _ConnectionDispatch]:
    clock = AudioClock(chunk_ms=100, window_s=1, voice_rms_threshold=500)
    clock.record(bytes(3200), sent_at_ms=1000)
    tracker = SegmentTracker(session_id="sala1", run_id=1000, lang="en", clock=clock, min_silence_ms=300)
    return tracker, _ConnectionDispatch(tracker=tracker, clock=clock, on_event=on_event)


def test_cut_rejects_late_partial_and_final_without_changing_tracker() -> None:
    async def scenario() -> None:
        delivered: list[SubtitleEvent] = []

        async def on_event(event: SubtitleEvent) -> None:
            delivered.append(event)

        tracker, dispatch = _dispatch(on_event)
        await dispatch.deliver(_content(partial="open phrase"))
        assert tracker.open_since_ms is not None
        assert should_force_cut(
            open_since_ms=tracker.open_since_ms,
            last_cut_ms=None,
            now_ms=tracker.open_since_ms + 8000,
            max_segment_ms=8000,
        )
        # Model the pending final after a forced audio_stream_end decision.
        cut = dispatch.mark_cut()
        assert cut is not None
        assert (cut.text, cut.is_final, cut.segment_id, cut.revision, cut.end_ms, cut.latency_ms) == (
            "", True, 0, 1, 100, None
        )
        assert dispatch.mark_cut() is None

        await dispatch.deliver(_content(partial="late partial"))
        await dispatch.deliver(_content(final="late final"))

        assert len(delivered) == 1
        assert tracker.open_since_ms is None
        next_event = tracker.on_interim("new phrase", now_ms=2000)
        assert (next_event.sequence, next_event.segment_id, next_event.revision) == (2, 1, 0)

    asyncio.run(scenario())


def test_cut_during_partial_delivery_rejects_final_from_same_message() -> None:
    async def scenario() -> None:
        delivered: list[SubtitleEvent] = []
        dispatch: _ConnectionDispatch | None = None

        async def on_event(event: SubtitleEvent) -> None:
            delivered.append(event)
            assert dispatch is not None
            dispatch.mark_cut()

        tracker, dispatch = _dispatch(on_event)
        await dispatch.deliver(_content(partial="open phrase", final="late final"))

        assert len(delivered) == 1
        assert delivered[0].is_final is False
        assert tracker.open_since_ms is None
        next_event = tracker.on_interim("new phrase", now_ms=2000)
        assert (next_event.sequence, next_event.segment_id) == (2, 1)

    asyncio.run(scenario())


def test_audio_gap_discarder_skips_pending_and_new_blocks_until_connection_ready() -> None:
    async def scenario() -> None:
        queue: DropOldestQueue[bytes] = DropOldestQueue(2)
        queue.put_nowait(b"pending-1")
        queue.put_nowait(b"pending-2")
        clock = AudioClock(chunk_ms=100, window_s=1, voice_rms_threshold=500)
        discarder = _AudioGapDiscarder(queue=queue, clock=clock)
        task = discarder.start()

        assert discarder.gap_ms == 200
        assert queue.empty()
        assert clock.position_ms == 200
        assert clock.sent_at(0) is None

        async def wait_for_gap(expected_ms: int) -> None:
            for _ in range(20):
                if discarder.gap_ms == expected_ms:
                    return
                await asyncio.sleep(0)
            assert discarder.gap_ms == expected_ms

        queue.put_nowait(b"during-open")
        await wait_for_gap(300)
        assert queue.empty()
        assert clock.position_ms == 300

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        queue.put_nowait(b"after-ready")
        assert await queue.get() == b"after-ready"
        assert discarder.gap_ms == 300
        assert clock.position_ms == 300

    asyncio.run(scenario())
