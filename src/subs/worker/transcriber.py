"""Live transcription: turn Live API partials and finals into original-track SubtitleEvents."""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

from google import genai
from google.genai import types

from subs.common.queues import DropOldestQueue
from subs.common.schema import ORIGINAL_TRACK, SubtitleEvent
from subs.worker.ingest import PCM_SAMPLE_RATE, AudioClock

_LOGGER = logging.getLogger(__name__)
_AUDIO_MIME_TYPE = f"audio/pcm;rate={PCM_SAMPLE_RATE}"
_QUEUE_POLL_S = 0.2


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def should_force_cut(*, open_since_ms: int | None, last_cut_ms: int | None, now_ms: int, max_segment_ms: int) -> bool:
    """Forced cut rule (RF-046): cut a sentence open for max_segment_ms since its first partial,
    and again every max_segment_ms after the previous cut while it stays open."""
    if open_since_ms is None:
        return False
    since = open_since_ms if last_cut_ms is None else last_cut_ms
    return now_ms - since >= max_segment_ms


class LiveSessionClosed(RuntimeError):
    """The Live API closed the session while audio was still being sent."""


class SegmentTracker:
    """Pure state machine for one run (data-model.md §5).

    Partials of the open sentence share a segment_id with a growing revision; the final gets a
    higher revision and closes the sentence. Timing comes from the AudioClock (research.md R4):
    a sentence starts at the first voiced block after the previous sentence ended, and ends at the
    last voiced block closed by min_silence_ms of silence (or the last voiced block if the speaker
    has not paused yet).
    """

    def __init__(self, *, session_id: str, run_id: int, lang: str, clock: AudioClock, min_silence_ms: int) -> None:
        self.session_id = session_id
        self.run_id = run_id
        self.lang = lang
        self.clock = clock
        self.min_silence_ms = min_silence_ms
        self._sequence = 0
        self._segment_id = 0
        self._open = False
        self._revision = -1
        self._last_text = ""
        self._start_ms = 0
        self._previous_end_ms = 0
        self._previous_end_sent_at_ms = 0
        # Wall-clock ms of the first partial of the open sentence; None when no sentence is open.
        self.open_since_ms: int | None = None

    def take_sequence(self) -> int:
        """Next emission number of the run; translations share it with the original track."""
        sequence = self._sequence
        self._sequence += 1
        return sequence

    def on_interim(self, text: str, *, now_ms: int) -> SubtitleEvent | None:
        text = text.strip()
        if not text or (self._open and text == self._last_text):
            return None
        if not self._open:
            self._open_segment()
            self.open_since_ms = now_ms
        self._revision += 1
        self._last_text = text
        voiced = self.clock.last_voiced_before(now_ms)
        latency = None if voiced is None else now_ms - voiced.sent_at_ms
        return self._event(text, is_final=False, end_ms=None, now_ms=now_ms, latency_ms=latency)

    def on_final(self, text: str, *, now_ms: int) -> SubtitleEvent | None:
        text = text.strip() or (self._last_text if self._open else "")
        if not text:
            return None
        if not self._open:
            self._open_segment()
        self._revision += 1

        end = self.clock.last_completed_voice_end_before(now_ms, min_silence_ms=self.min_silence_ms)
        if end is None or end.position_ms < self._start_ms:
            end = self.clock.last_voiced_before(now_ms)
        if end is None or end.position_ms < self._start_ms:
            end_ms, end_sent_at_ms = self._start_ms, now_ms
        else:
            end_ms, end_sent_at_ms = end.position_ms, end.sent_at_ms
        event = self._event(
            text,
            is_final=True,
            end_ms=end_ms,
            now_ms=now_ms,
            latency_ms=self.clock.latency_ms(emitted_at_ms=now_ms, end_ms=end_ms),
        )

        self._open = False
        self.open_since_ms = None
        self._segment_id += 1
        self._previous_end_ms = end_ms
        self._previous_end_sent_at_ms = end_sent_at_ms
        return event

    def _open_segment(self) -> None:
        onset = self.clock.first_voiced_after(self._previous_end_sent_at_ms)
        self._start_ms = self._previous_end_ms if onset is None else onset.position_ms
        self._open = True
        self._revision = -1
        self._last_text = ""

    def _event(
        self, text: str, *, is_final: bool, end_ms: int | None, now_ms: int, latency_ms: int | None
    ) -> SubtitleEvent:
        return SubtitleEvent(
            session_id=self.session_id,
            run_id=self.run_id,
            track=ORIGINAL_TRACK,
            sequence=self.take_sequence(),
            segment_id=self._segment_id,
            revision=self._revision,
            kind="original",
            lang=self.lang,
            text=text,
            is_final=is_final,
            start_ms=self._start_ms,
            end_ms=end_ms,
            emitted_at_ms=now_ms,
            latency_ms=latency_ms,
        )


async def transcribe(
    client: genai.Client,
    *,
    model: str,
    source_language: str,
    session_id: str,
    audio_queue: DropOldestQueue[bytes],
    source_done: asyncio.Event,
    clock: AudioClock,
    tracker: SegmentTracker,
    on_event: Callable[[SubtitleEvent], Awaitable[None]],
    end_grace_ms: int,
    vad_end_sensitivity: str,
    vad_silence_ms: int,
    max_segment_ms: int,
) -> None:
    """Stream the audio queue to one Live session and hand every subtitle event to on_event.

    Audio goes only through the Live API as a continuous stream (constitution, principle 2).
    Returns after the source ends and the queue is drained, waiting up to end_grace_ms for the
    last final. Any session error propagates to the caller (the scenario supervisor).
    """
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.TEXT],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=[source_language],
            mode=types.AudioTranscriptionConfigMode.VERBATIM,  # research.md R5
        ),
        # Close sentences on short pauses (RF-045, research.md R5).
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                end_of_speech_sensitivity=types.EndSensitivity[f"END_SENSITIVITY_{vad_end_sensitivity}"],
                silence_duration_ms=vad_silence_ms,
            )
        ),
    )
    async with client.aio.live.connect(model=model, config=config) as session:
        _LOGGER.info("live_session_open", extra={"session_id": session_id, "model": model})

        async def send() -> None:
            last_cut: tuple[int, int] | None = None  # (open_since_ms of the cut sentence, cut time)
            while not (source_done.is_set() and audio_queue.empty()):
                try:
                    chunk = await asyncio.wait_for(audio_queue.get(), timeout=_QUEUE_POLL_S)
                except TimeoutError:
                    continue
                clock.record(chunk, sent_at_ms=now_ms())
                await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=_AUDIO_MIME_TYPE))
                # Forced cut (RF-046): flush a sentence that stays open too long; audio keeps flowing.
                open_since = tracker.open_since_ms
                last_cut_ms = last_cut[1] if last_cut is not None and last_cut[0] == open_since else None
                cut_at = now_ms()
                if open_since is not None and should_force_cut(
                    open_since_ms=open_since, last_cut_ms=last_cut_ms, now_ms=cut_at, max_segment_ms=max_segment_ms
                ):
                    await session.send_realtime_input(audio_stream_end=True)
                    last_cut = (open_since, cut_at)
                    _LOGGER.info("forced_cut", extra={"session_id": session_id})

        async def receive() -> None:
            while True:
                received = False
                async for message in session.receive():
                    received = True
                    content = message.server_content
                    if content is None:
                        continue
                    if content.interim_input_transcription and content.interim_input_transcription.text:
                        event = tracker.on_interim(content.interim_input_transcription.text, now_ms=now_ms())
                        if event is not None:
                            await on_event(event)
                    if content.input_transcription and content.input_transcription.text:
                        event = tracker.on_final(content.input_transcription.text, now_ms=now_ms())
                        if event is not None:
                            await on_event(event)
                if not received:
                    raise LiveSessionClosed("Live API closed the transcription session")

        sender = asyncio.create_task(send())
        receiver = asyncio.create_task(receive())
        try:
            done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                receiver.result()  # re-raises the session error
                raise LiveSessionClosed("Live API closed the transcription session")
            sender.result()
            # Source ended: give the Live API a moment to finalize the last sentence.
            done, _ = await asyncio.wait({receiver}, timeout=end_grace_ms / 1000)
            if receiver in done:
                receiver.result()
        finally:
            for task in (sender, receiver):
                task.cancel()
            for task in (sender, receiver):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        _LOGGER.info("live_session_closed", extra={"session_id": session_id})
