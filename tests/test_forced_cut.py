"""Tests for the forced sentence cut rule (RF-046; docs/architecture.md §6.2.4)."""

from subs.worker.transcriber import should_force_cut

T0 = 1_790_000_000_000  # wall-clock ms of the first partial of the open sentence
MAX_MS = 8000


def test_no_open_sentence_never_cuts():
    assert not should_force_cut(open_since_ms=None, last_cut_ms=None, now_ms=T0 + 60_000, max_segment_ms=MAX_MS)


def test_cuts_when_the_sentence_reaches_max_duration():
    assert not should_force_cut(open_since_ms=T0, last_cut_ms=None, now_ms=T0 + MAX_MS - 1, max_segment_ms=MAX_MS)
    assert should_force_cut(open_since_ms=T0, last_cut_ms=None, now_ms=T0 + MAX_MS, max_segment_ms=MAX_MS)
    assert should_force_cut(open_since_ms=T0, last_cut_ms=None, now_ms=T0 + MAX_MS + 500, max_segment_ms=MAX_MS)


def test_after_a_cut_waits_another_max_duration():
    cut_at = T0 + MAX_MS
    assert not should_force_cut(open_since_ms=T0, last_cut_ms=cut_at, now_ms=cut_at + 100, max_segment_ms=MAX_MS)
    assert not should_force_cut(
        open_since_ms=T0, last_cut_ms=cut_at, now_ms=cut_at + MAX_MS - 1, max_segment_ms=MAX_MS
    )
    assert should_force_cut(open_since_ms=T0, last_cut_ms=cut_at, now_ms=cut_at + MAX_MS, max_segment_ms=MAX_MS)


def test_a_new_sentence_restarts_the_count():
    new_open = T0 + 20_000
    assert not should_force_cut(open_since_ms=new_open, last_cut_ms=None, now_ms=new_open + 1000, max_segment_ms=MAX_MS)
    assert should_force_cut(open_since_ms=new_open, last_cut_ms=None, now_ms=new_open + MAX_MS, max_segment_ms=MAX_MS)
