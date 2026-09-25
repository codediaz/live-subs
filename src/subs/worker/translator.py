"""Translation of final sentences into each target track (data-model.md §8).

Only final original sentences are translated, never partials (constitution, principle 2).
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable

from google import genai
from google.genai import types

from subs.common.queues import DropOldestQueue
from subs.common.schema import SubtitleEvent

_LOGGER = logging.getLogger(__name__)

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


def system_instruction(source_language: str, target_language: str, vocabulary: list[str] | None = None) -> str:
    try:
        source, target = LANGUAGE_NAMES[source_language], LANGUAGE_NAMES[target_language]
    except KeyError as exc:
        raise ValueError(f"unsupported language: {exc.args[0]}") from None
    instruction = (
        f"You translate live conference subtitles from {source} to {target}. "
        "Return only the translation of the sentence, with no quotes, notes or explanations. "
        # RF-047: forced cuts close sentences mid-way.
        "The sentence may be a fragment of a longer sentence: translate it as a fragment, "
        "do not complete it and do not add content; use the previous sentences to understand it. "
        "Keep product names, code identifiers and technical terms that are usually left untranslated."
    )
    if vocabulary:
        instruction += (
            " Treat these vocabulary terms as proper nouns or technical jargon;"
            " preserve their spelling and do not translate them: " + ", ".join(vocabulary) + "."
        )
    return instruction


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


class TrackTranslator:
    """One target track: a bounded queue of final sentences, translated in order (RF-013, RF-014).

    submit() never blocks, so publishing the original never waits for a translation. A failed or
    timed-out translation is logged and skipped; the next sentence continues (RF-015).
    """

    def __init__(
        self,
        client: genai.Client,
        *,
        session_id: str,
        source_language: str,
        target: str,
        title: str,
        vocabulary: list[str],
        model: str,
        thinking_level: str,
        timeout_s: float,
        queue_max: int,
        take_sequence: Callable[[], int],
        publish: Callable[[SubtitleEvent], Awaitable[None]],
        on_error: Callable[[str], None],
    ) -> None:
        self.client = client
        self.session_id = session_id
        self.target = target
        self.title = title
        self.model = model
        self.timeout_s = timeout_s
        self.take_sequence = take_sequence
        self.publish = publish
        self.on_error = on_error
        self.config = types.GenerateContentConfig(
            system_instruction=system_instruction(source_language, target, vocabulary),
            # Minimum reasoning the model allows, to keep latency low (research.md R3).
            thinking_config=types.ThinkingConfig(thinking_level=thinking_level, include_thoughts=False),
            # No tools are used; skip the SDK's function-calling loop.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self._queue: DropOldestQueue[tuple[SubtitleEvent, list[str]]] = DropOldestQueue(queue_max)
        self._idle = asyncio.Event()
        self._idle.set()

    def submit(self, original: SubtitleEvent, context: list[str]) -> None:
        self._idle.clear()
        dropped = self._queue.put_nowait((original, context))
        if dropped is not None:
            _LOGGER.warning(
                "translation_dropped",
                extra={
                    "session_id": self.session_id,
                    "track": self.target,
                    "segment_id": dropped[0].segment_id,
                    "dropped_total": self._queue.dropped,
                },
            )

    async def run(self) -> None:
        while True:
            original, context = await self._queue.get()
            await self._translate(original, context)
            if self._queue.empty():
                self._idle.set()

    async def drain(self, timeout_s: float) -> None:
        """Wait up to timeout_s for pending sentences, e.g. when the source ends."""
        try:
            await asyncio.wait_for(self._idle.wait(), timeout_s)
        except TimeoutError:
            _LOGGER.warning(
                "translation_drain_timeout",
                extra={"session_id": self.session_id, "track": self.target, "pending": self._queue.qsize()},
            )

    async def _translate(self, original: SubtitleEvent, context: list[str]) -> None:
        extra = {"session_id": self.session_id, "track": self.target, "segment_id": original.segment_id}
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=build_prompt(self.title, context, original.text),
                    config=self.config,
                ),
                self.timeout_s,
            )
            text = clean_translation(response.text or "")
            if not text:
                raise ValueError("empty translation")
            event = translation_event(
                original,
                target=self.target,
                text=text,
                sequence=self.take_sequence(),
                emitted_at_ms=time.time_ns() // 1_000_000,
            )
            await self.publish(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one failed sentence must not stop the track
            error = "timeout" if isinstance(exc, TimeoutError) else f"{type(exc).__name__}: {exc}"[:300]
            _LOGGER.error("translation_failed", extra={**extra, "error": error})
            self.on_error(error)
