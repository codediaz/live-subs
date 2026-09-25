"""Translation of final sentences into each target track (data-model.md §8).

Only final original sentences are translated, never partials (constitution, principle 2).
"""

from collections import deque
from collections.abc import Iterable

from subs.common.schema import SubtitleEvent

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese"}
_WRAPPING_QUOTES = {'"': '"', "'": "'", "“": "”", "«": "»", "„": "“"}


def target_tracks(source_language: str, target_languages: Iterable[str]) -> list[str]:
    """Target tracks for a scenario: configured targets minus the source language, in order."""
    return [lang for lang in dict.fromkeys(target_languages) if lang != source_language]


class FinalHistory:
    """Last final original sentences of the run, sent as translation context (RF-012)."""

    def __init__(self, max_segments: int) -> None:
        self._texts: deque[str] = deque(maxlen=max_segments)

    def add(self, event: SubtitleEvent) -> None:
        if event.is_final and event.kind == "original":
            self._texts.append(event.text)

    def texts(self) -> list[str]:
        return list(self._texts)


def system_instruction(source_language: str, target_language: str) -> str:
    try:
        source, target = LANGUAGE_NAMES[source_language], LANGUAGE_NAMES[target_language]
    except KeyError as exc:
        raise ValueError(f"unsupported language: {exc.args[0]}") from None
    return (
        f"You translate live conference subtitles from {source} to {target}. "
        "Return only the translation of the sentence, with no quotes, notes or explanations. "
        "Keep product names, code identifiers and technical terms that are usually left untranslated."
    )


def build_prompt(title: str, context: list[str], sentence: str) -> str:
    previous = "\n".join(context) if context else "(none)"
    return (
        f"Talk title: {title}\n"
        f"Previous sentences (context only, do not translate):\n{previous}\n\n"
        f"Sentence to translate:\n{sentence}"
    )


def clean_translation(text: str) -> str:
    """Single-line subtitle text without surrounding whitespace or wrapping quotes."""
    cleaned = " ".join(text.split())
    if len(cleaned) >= 2 and _WRAPPING_QUOTES.get(cleaned[0]) == cleaned[-1]:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def translation_event(
    original: SubtitleEvent, *, target: str, text: str, sequence: int, emitted_at_ms: int
) -> SubtitleEvent:
    """Translation of one final sentence, linked to it by run_id and segment_id (contracts/events.md)."""
    if not (original.is_final and original.kind == "original"):
        raise ValueError("only final original sentences are translated")
    # Same reference as the original's latency: when the end of the sentence was sent (§8).
    latency_ms = None
    if original.latency_ms is not None:
        latency_ms = emitted_at_ms - (original.emitted_at_ms - original.latency_ms)
    return SubtitleEvent(
        session_id=original.session_id,
        run_id=original.run_id,
        track=target,
        sequence=sequence,
        segment_id=original.segment_id,
        revision=0,
        kind="translation",
        lang=target,
        text=text,
        is_final=True,
        start_ms=original.start_ms,
        end_ms=original.end_ms,
        emitted_at_ms=emitted_at_ms,
        latency_ms=latency_ms,
    )
