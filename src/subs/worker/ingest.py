"""Audio clock, PCM voice detection, and ffmpeg source ingestion."""

import argparse
import asyncio
import logging
import math
import struct
import time
from collections import deque
from dataclasses import dataclass

from subs.common.config import SourceConfig, WorkerSettings
from subs.common.queues import DropOldestQueue


PCM_SAMPLE_RATE = 16_000
PCM_BYTES_PER_SAMPLE = 2
_LOGGER = logging.getLogger(__name__)


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


class IngestError(RuntimeError):
    """The audio source or ffmpeg failed."""


async def ingest_audio(
    source: SourceConfig,
    audio_queue: DropOldestQueue[bytes],
    *,
    chunk_ms: int,
    session_id: str,
    seconds: float | None = None,
) -> int:
    """Convert one source to PCM and enqueue chunks without producer backpressure.

    A file is read in real time. A stream supplies its own pacing. The caller owns
    the queue and records AudioClock send times when it sends chunks to Live API.
    """
    if chunk_ms <= 0:
        raise ValueError("chunk_ms must be positive")
    if seconds is not None and seconds <= 0:
        raise ValueError("seconds must be positive")

    chunk_bytes = PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE * chunk_ms // 1000
    if chunk_bytes <= 0:
        raise ValueError("chunk_ms produces an empty PCM chunk")

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if source.type == "file":
        command.append("-re")
    command.extend(["-i", source.uri])
    if seconds is not None:
        command.extend(["-t", str(seconds)])
    command.extend(
        ["-vn", "-ac", "1", "-ar", str(PCM_SAMPLE_RATE), "-acodec", "pcm_s16le", "-f", "s16le", "pipe:1"]
    )

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert process.stdout is not None
    chunk_count = 0
    try:
        while True:
            try:
                chunk = await process.stdout.readexactly(chunk_bytes)
                ended = False
            except asyncio.IncompleteReadError as exc:
                chunk = exc.partial
                ended = True

            if chunk:
                dropped = audio_queue.put_nowait(chunk)
                chunk_count += 1
                if dropped is not None:
                    _LOGGER.warning(
                        "audio_chunk_dropped",
                        extra={"session_id": session_id, "dropped_chunks": audio_queue.dropped},
                    )
            if ended:
                break

        exit_code = await process.wait()
        if exit_code != 0:
            raise IngestError(f"ffmpeg exited with status {exit_code}")
        return chunk_count
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read an audio source through ffmpeg at real-time pace")
    parser.add_argument("uri", help="audio file to read")
    parser.add_argument("--seconds", type=float, required=True, help="audio duration to read")
    args = parser.parse_args()

    settings = WorkerSettings.from_env()
    audio_queue: DropOldestQueue[bytes] = DropOldestQueue(settings.audio_queue_max_chunks)
    started = time.perf_counter()
    count = asyncio.run(
        ingest_audio(
            SourceConfig(type="file", uri=args.uri),
            audio_queue,
            chunk_ms=settings.audio_chunk_ms,
            session_id="diagnostic",
            seconds=args.seconds,
        )
    )
    print(f"chunks={count} elapsed_s={time.perf_counter() - started:.2f} dropped={audio_queue.dropped}")


if __name__ == "__main__":
    main()
