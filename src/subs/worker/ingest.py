"""Pure audio clock and PCM voice detection for worker ingestion."""

import math
import struct
from collections import deque
from dataclasses import dataclass


def rms_pcm_s16le(pcm: bytes) -> float:
    """Return the RMS amplitude of signed 16-bit little-endian mono PCM."""
    if len(pcm) % 2:
        raise ValueError("PCM s16le data must have an even number of bytes")
    sample_count = len(pcm) // 2
    if sample_count == 0:
        return 0.0
    squared_sum = sum(sample * sample for (sample,) in struct.iter_unpack("<h", pcm))
    return math.sqrt(squared_sum / sample_count)


@dataclass(frozen=True, slots=True)
class AudioBlock:
    position_ms: int
    sent_at_ms: int
    voiced: bool


class AudioClock:
    """Keep recent audio positions, actual send times, and RMS voice flags."""

    def __init__(self, *, chunk_ms: int, window_s: float, voice_rms_threshold: float) -> None:
        if chunk_ms <= 0:
            raise ValueError("chunk_ms must be positive")
        if window_s * 1000 < chunk_ms:
            raise ValueError("window_s must hold at least one audio chunk")
        if voice_rms_threshold < 0:
            raise ValueError("voice_rms_threshold must be non-negative")
        self.chunk_ms = chunk_ms
        self.voice_rms_threshold = voice_rms_threshold
        self._blocks: deque[AudioBlock] = deque(maxlen=int(window_s * 1000 // chunk_ms))
        self._next_position_ms = 0

    def record(self, pcm: bytes, *, sent_at_ms: int) -> AudioBlock:
        """Record a chunk when it is sent to the Live API, advancing the run clock."""
        block = AudioBlock(
            position_ms=self._next_position_ms,
            sent_at_ms=sent_at_ms,
            voiced=rms_pcm_s16le(pcm) > self.voice_rms_threshold,
        )
        self._blocks.append(block)
        self._next_position_ms += self.chunk_ms
        return block

    def sent_at(self, position_ms: int) -> int | None:
        """Return the actual send time for a retained audio position."""
        for block in self._blocks:
            if block.position_ms == position_ms:
                return block.sent_at_ms
        return None

    def last_voiced_before(self, at_ms: int) -> AudioBlock | None:
        """Find the latest voiced block sent at or before a wall-clock time."""
        return next(
            (block for block in reversed(self._blocks) if block.voiced and block.sent_at_ms <= at_ms),
            None,
        )

    def first_voiced_after(self, at_ms: int) -> AudioBlock | None:
        """Find the first voiced block sent after a wall-clock time."""
        return next(
            (block for block in self._blocks if block.voiced and block.sent_at_ms > at_ms),
            None,
        )

    def last_completed_voice_end_before(
        self, at_ms: int, *, min_silence_ms: int
    ) -> AudioBlock | None:
        """Find the last voice run closed by the requested length of silence."""
        if min_silence_ms <= 0:
            raise ValueError("min_silence_ms must be positive")
        candidate: AudioBlock | None = None
        completed: AudioBlock | None = None
        silence_ms = 0
        for block in self._blocks:
            if block.sent_at_ms > at_ms:
                continue
            if block.voiced:
                candidate = block
                silence_ms = 0
            elif candidate is not None:
                silence_ms += self.chunk_ms
                if silence_ms >= min_silence_ms:
                    completed = candidate
                    candidate = None
        return completed

    def latency_ms(self, *, emitted_at_ms: int, end_ms: int) -> int | None:
        """Measure final latency from the send time of the block at end_ms."""
        sent_at_ms = self.sent_at(end_ms)
        return None if sent_at_ms is None else emitted_at_ms - sent_at_ms
