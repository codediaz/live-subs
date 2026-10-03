"""Tests for the transcription segment state machine (data-model.md §5; RF-006, RF-007, RF-037)."""

import struct

import pytest

from subs.common.schema import SubtitleEvent
from subs.worker.ingest import AudioClock
from subs.worker.transcriber import SegmentTracker, should_force_cut

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


class TestConnectionCut:
    def test_open_sentence_emits_empty_final_and_continues_identifiers(self, tracker: SegmentTracker) -> None:
        first = tracker.on_interim("unfinished", now_ms=at(700))
        second = tracker.on_interim("unfinished phrase", now_ms=at(1200))

        cut = tracker.on_connection_cut(now_ms=at(2500), position_ms=2500)

        assert isinstance(cut, SubtitleEvent)
        assert (cut.session_id, cut.run_id, cut.track, cut.kind) == ("sala1", T0, "original", "original")
        assert (cut.sequence, cut.segment_id, cut.revision) == (2, 0, 2)
        assert cut.revision > second.revision
        assert (cut.is_final, cut.text, cut.start_ms, cut.end_ms, cut.latency_ms) == (True, "", first.start_ms, 2500, None)
        assert cut.emitted_at_ms == at(2500)
        assert tracker.open_since_ms is None

        following = tracker.on_interim("new sentence", now_ms=at(3600))
        assert (following.run_id, following.sequence, following.segment_id, following.revision) == (T0, 3, 1, 0)
        assert following.start_ms == 3000

    def test_cut_without_open_sentence_emits_nothing_and_preserves_numbering(self, tracker: SegmentTracker) -> None:
        assert tracker.on_connection_cut(now_ms=at(2500), position_ms=2500) is None

        following = tracker.on_interim("new sentence", now_ms=at(3600))
        assert (following.sequence, following.segment_id, following.revision) == (0, 0, 0)
        assert following.start_ms == 3000

    def test_cut_after_forced_signal_but_before_final_discards_open_sentence(self) -> None:
        tracker = SegmentTracker(
            session_id="sala1", run_id=T0, lang="en", clock=clock_with("v" * 100), min_silence_ms=300
        )
        partial = tracker.on_interim("still open", now_ms=at(700))
        assert should_force_cut(open_since_ms=tracker.open_since_ms, last_cut_ms=None, now_ms=at(8700), max_segment_ms=8000)

        cut = tracker.on_connection_cut(now_ms=at(8800), position_ms=8800)

        assert (cut.sequence, cut.segment_id, cut.revision) == (partial.sequence + 1, partial.segment_id, 1)
        assert (cut.is_final, cut.text, cut.start_ms, cut.end_ms, cut.latency_ms) == (True, "", partial.start_ms, 8800, None)

    def test_two_cuts_do_not_reuse_segment_ids(self, tracker: SegmentTracker) -> None:
        first = tracker.on_interim("first", now_ms=at(700))
        first_cut = tracker.on_connection_cut(now_ms=at(2500), position_ms=2500)
        second = tracker.on_interim("second", now_ms=at(3600))
        second_cut = tracker.on_connection_cut(now_ms=at(4500), position_ms=4500)
        assert tracker.on_connection_cut(now_ms=at(4600), position_ms=4600) is None
        third = tracker.on_interim("third", now_ms=at(4800))

        assert [event.sequence for event in (first, first_cut, second, second_cut, third)] == [0, 1, 2, 3, 4]
        assert [event.segment_id for event in (first, first_cut, second, second_cut, third)] == [0, 0, 1, 1, 2]
        assert (second.revision, third.revision) == (0, 0)

    def test_cut_after_final_anchors_next_start_after_the_cut(self, tracker: SegmentTracker) -> None:
        tracker.on_interim("complete", now_ms=at(700))
        final = tracker.on_final("Complete.", now_ms=at(2900))
        assert tracker.on_connection_cut(now_ms=at(3200), position_ms=3200) is None

        following = tracker.on_interim("after cut", now_ms=at(3600))
        assert (following.sequence, following.segment_id) == (final.sequence + 1, final.segment_id + 1)
        assert following.start_ms == 3300
        assert following.start_ms >= 3200
