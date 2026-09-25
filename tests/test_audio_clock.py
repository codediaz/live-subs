"""Audio clock and PCM voice detection (data-model.md §4, architecture.md §8)."""

import math
import struct

import pytest

from subs.worker.ingest import AudioClock, rms_pcm_s16le


def pcm(*samples: int) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_rms_of_little_endian_signed_pcm() -> None:
    assert rms_pcm_s16le(b"") == 0
    assert rms_pcm_s16le(pcm(1000, -1000)) == 1000
    assert rms_pcm_s16le(pcm(0, 1000)) == pytest.approx(math.sqrt(500_000))
    with pytest.raises(ValueError, match="even"):
        rms_pcm_s16le(b"\x01")


def test_positions_send_times_and_voice_threshold() -> None:
    clock = AudioClock(chunk_ms=100, window_s=1, voice_rms_threshold=500)
    first = clock.record(pcm(500, -500), sent_at_ms=1000)
    second = clock.record(pcm(501, -501), sent_at_ms=1100)
    third = clock.record(pcm(0, 0), sent_at_ms=1200)

    assert [block.position_ms for block in (first, second, third)] == [0, 100, 200]
    assert [block.voiced for block in (first, second, third)] == [False, True, False]
    assert clock.sent_at(100) == 1100
    assert clock.sent_at(250) is None


def test_voice_lookup_uses_send_time_and_audio_position() -> None:
    clock = AudioClock(chunk_ms=100, window_s=1, voice_rms_threshold=500)
    clock.record(pcm(0), sent_at_ms=1000)
    clock.record(pcm(1000), sent_at_ms=1100)
    clock.record(pcm(0), sent_at_ms=1200)
    clock.record(pcm(1000), sent_at_ms=1300)

    assert clock.last_voiced_before(1250).position_ms == 100
    assert clock.first_voiced_after(1100).position_ms == 300
    assert clock.last_voiced_before(1050) is None
    assert clock.first_voiced_after(1300) is None


def test_completed_voice_end_needs_configured_silence_gap() -> None:
    clock = AudioClock(chunk_ms=100, window_s=2, voice_rms_threshold=500)
    clock.record(pcm(1000), sent_at_ms=1000)
    for sent_at_ms in (1100, 1200):
        clock.record(pcm(0), sent_at_ms=sent_at_ms)
    assert clock.last_completed_voice_end_before(1200, min_silence_ms=300) is None

    clock.record(pcm(0), sent_at_ms=1300)
    assert clock.last_completed_voice_end_before(1300, min_silence_ms=300).position_ms == 0
    clock.record(pcm(1000), sent_at_ms=1400)
    assert clock.last_completed_voice_end_before(1400, min_silence_ms=300).position_ms == 0


def test_window_discards_old_blocks_without_restarting_position() -> None:
    clock = AudioClock(chunk_ms=100, window_s=0.3, voice_rms_threshold=500)
    for index in range(4):
        latest = clock.record(pcm(1000), sent_at_ms=1000 + index * 100)

    assert latest.position_ms == 300
    assert clock.sent_at(0) is None
    assert [clock.sent_at(position) for position in (100, 200, 300)] == [1100, 1200, 1300]
    assert clock.first_voiced_after(1000).position_ms == 100


def test_final_latency_uses_send_time_of_end_ms() -> None:
    clock = AudioClock(chunk_ms=100, window_s=1, voice_rms_threshold=500)
    clock.record(pcm(1000), sent_at_ms=1000)
    clock.record(pcm(1000), sent_at_ms=1100)
    clock.record(pcm(0), sent_at_ms=1200)

    assert clock.latency_ms(emitted_at_ms=1800, end_ms=100) == 700
    assert clock.latency_ms(emitted_at_ms=1800, end_ms=900) is None
