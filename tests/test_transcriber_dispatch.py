"""Connection-cut dispatch tests for RF-008, RF-013, and RF-014."""

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from subs.common.schema import SubtitleEvent
from subs.worker.ingest import AudioClock
from subs.worker.transcriber import SegmentTracker, _ConnectionDispatch, should_force_cut


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
