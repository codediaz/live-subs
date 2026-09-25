"""Tests for the transcription segment state machine (data-model.md §5; RF-006, RF-007, RF-037)."""

import struct

import pytest

from subs.common.schema import SubtitleEvent
from subs.worker.ingest import AudioClock
from subs.worker.transcriber import SegmentTracker

T0 = 1_790_000_000_000  # wall-clock ms when the first chunk was sent
CHUNK_MS = 100
VOICED = struct.pack("<h", 2000) * 1600  # 100 ms of loud PCM at 16 kHz
SILENT = bytes(3200)


def clock_with(pattern: str) -> AudioClock:
    """Build a clock from a pattern: 'v' = voiced chunk, '.' = silent chunk, 100 ms each."""
    clock = AudioClock(chunk_ms=CHUNK_MS, window_s=120, voice_rms_threshold=500)
    for index, mark in enumerate(pattern):
        clock.record(VOICED if mark == "v" else SILENT, sent_at_ms=T0 + index * CHUNK_MS)
    return clock


# Speech 0–1900 ms, silence 2000–2900, speech 3000–4900, silence 5000–5900.
TWO_SENTENCES = "v" * 20 + "." * 10 + "v" * 20 + "." * 10


@pytest.fixture
def tracker() -> SegmentTracker:
    return SegmentTracker(
        session_id="sala1", run_id=T0, lang="en", clock=clock_with(TWO_SENTENCES), min_silence_ms=300
    )


def at(position_ms: int) -> int:
    return T0 + position_ms


class TestRevisionsAndSegments:
    def test_partials_share_segment_with_growing_revision(self, tracker):
        first = tracker.on_interim("hello", now_ms=at(700))
        second = tracker.on_interim("hello world", now_ms=at(1200))
        assert (first.segment_id, first.revision) == (0, 0)
        assert (second.segment_id, second.revision) == (0, 1)
        for event in (first, second):
            assert event.is_final is False
            assert event.end_ms is None
            assert (event.track, event.kind, event.lang) == ("original", "original", "en")

    def test_final_revision_is_greater_than_any_partial(self, tracker):
        tracker.on_interim("hello", now_ms=at(700))
        tracker.on_interim("hello world", now_ms=at(1200))
        final = tracker.on_final("Hello world.", now_ms=at(2900))
        assert final.is_final is True
        assert final.segment_id == 0
        assert final.revision == 2
        assert final.text == "Hello world."

    def test_final_without_partials_has_revision_zero(self, tracker):
        final = tracker.on_final("Hello world.", now_ms=at(2900))
        assert (final.segment_id, final.revision, final.is_final) == (0, 0, True)

    def test_next_partial_opens_a_new_segment(self, tracker):
        tracker.on_interim("hello", now_ms=at(700))
        tracker.on_final("Hello world.", now_ms=at(2900))
        nxt = tracker.on_interim("second", now_ms=at(3600))
        assert (nxt.segment_id, nxt.revision) == (1, 0)

    @pytest.mark.parametrize("text", ["", "   "])
    def test_empty_partials_are_not_emitted(self, tracker, text):
        assert tracker.on_interim(text, now_ms=at(700)) is None

    def test_repeated_partial_is_not_emitted(self, tracker):
        tracker.on_interim("hello", now_ms=at(700))
        assert tracker.on_interim("hello", now_ms=at(800)) is None
        assert tracker.on_interim("hello there", now_ms=at(900)).revision == 1

    def test_empty_final_closes_open_segment_with_last_partial(self, tracker):
        tracker.on_interim("hello world", now_ms=at(1200))
        final = tracker.on_final("", now_ms=at(2900))
        assert final.is_final is True
        assert final.text == "hello world"
        assert tracker.on_interim("next", now_ms=at(3600)).segment_id == 1

    def test_empty_final_without_open_segment_is_ignored(self, tracker):
        assert tracker.on_final("  ", now_ms=at(2900)) is None

    def test_sequence_is_monotonic_and_shared(self, tracker):
        events = [
            tracker.on_interim("hello", now_ms=at(700)),
            tracker.on_final("Hello.", now_ms=at(2900)),
        ]
        translation_sequence = tracker.take_sequence()
        events.append(tracker.on_interim("second", now_ms=at(3600)))
        assert [e.sequence for e in events[:2]] == [0, 1]
        assert translation_sequence == 2
        assert events[2].sequence == 3

    def test_open_since_tracks_the_first_partial_until_the_final(self, tracker):
        assert tracker.open_since_ms is None
        tracker.on_interim("hello", now_ms=at(700))
        tracker.on_interim("hello world", now_ms=at(1200))
        assert tracker.open_since_ms == at(700)
        tracker.on_final("Hello world.", now_ms=at(2900))
        assert tracker.open_since_ms is None
        tracker.on_interim("second", now_ms=at(3600))
        assert tracker.open_since_ms == at(3600)

    def test_events_are_valid_subtitle_events(self, tracker):
        event = tracker.on_interim("hello", now_ms=at(700))
        assert isinstance(event, SubtitleEvent)
        assert (event.session_id, event.run_id, event.emitted_at_ms) == ("sala1", T0, at(700))


class TestTimingFromAudioClock:
    def test_start_end_and_latency_of_two_sentences(self, tracker):
        tracker.on_interim("hello", now_ms=at(700))
        first = tracker.on_final("Hello world.", now_ms=at(2900))
        second_partial = tracker.on_interim("second", now_ms=at(3600))
        second = tracker.on_final("Second one.", now_ms=at(5800))
        # End = last voiced block followed by >= 300 ms of silence; latency from its send time.
        assert (first.start_ms, first.end_ms, first.latency_ms) == (0, 1900, 1000)
        assert second_partial.start_ms == 3000
        assert (second.start_ms, second.end_ms, second.latency_ms) == (3000, 4900, 900)

    def test_partial_latency_is_measured_from_last_voiced_block(self, tracker):
        partial = tracker.on_interim("hello world", now_ms=at(2500))
        assert partial.latency_ms == 600  # last voiced block sent at 1900 ms

    def test_final_during_continuous_speech_uses_last_voiced_block(self):
        tracker = SegmentTracker(
            session_id="sala1", run_id=T0, lang="en", clock=clock_with("v" * 30), min_silence_ms=300
        )
        final = tracker.on_final("Still talking", now_ms=at(1500))
        assert (final.start_ms, final.end_ms, final.latency_ms) == (0, 1500, 0)

    def test_end_is_never_before_start(self, tracker):
        tracker.on_final("Hello world.", now_ms=at(2900))
        # Second sentence finalized before its voice run closes: falls back to the last voiced block.
        tracker.on_interim("second", now_ms=at(3200))
        final = tracker.on_final("Second", now_ms=at(3500))
        assert final.start_ms == 3000
        assert final.end_ms >= final.start_ms
