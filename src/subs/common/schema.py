"""Inter-component contracts (docs/architecture.md §7.1, §7.2).

Every message between components is a SubtitleEvent. An incompatible change must bump
schema_version and update the spec first.
"""

from typing import Literal, Self

from pydantic import BaseModel, model_validator

ORIGINAL_TRACK = "original"


class SubtitleEvent(BaseModel):
    schema_version: Literal[1] = 1
    session_id: str
    run_id: int  # scenario run (epoch ms at start)
    track: str  # "original" or target language code ("es", "en", "pt")
    sequence: int  # emission order within the run (monotonic)
    segment_id: int  # sentence: shared by partials, final and translations
    revision: int = 0  # grows with each partial; clients keep the highest
    kind: Literal["original", "translation"]
    lang: str  # actual language of the text
    text: str
    is_final: bool
    start_ms: int  # position in the talk, from the start of the run
    end_ms: int | None = None  # finals only
    emitted_at_ms: int  # wall-clock emission time (epoch ms)
    latency_ms: int | None = None  # see §8

    @model_validator(mode="after")
    def _check_track_rules(self) -> Self:
        if self.kind == "original" and self.track != ORIGINAL_TRACK:
            raise ValueError(f"original events must use track '{ORIGINAL_TRACK}', got '{self.track}'")
        if self.kind == "translation" and not self.is_final:
            raise ValueError("translation events are always final")
        return self


class SessionStatus(BaseModel):
    session_id: str
    state: Literal["starting", "live", "reconnecting", "stopped", "error"]
    source_type: Literal["file", "stream", "microphone"]
    uptime_s: int
    last_event_at_ms: int | None
    latency_original_ms: int | None  # last measured value
    latency_translation_ms: int | None  # last measured value
    reconnects: int
    errors: int
    last_error: str | None
    updated_at_ms: int


def channel_name(session_id: str, track: str) -> str:
    """Redis pub/sub channel for one track of one session (§7.5)."""
    return f"subs:{session_id}:{track}"
