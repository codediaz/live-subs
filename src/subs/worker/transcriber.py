"""Live transcription: turn Live API partials and finals into original-track SubtitleEvents."""

from subs.common.schema import ORIGINAL_TRACK, SubtitleEvent
from subs.worker.ingest import AudioClock


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
