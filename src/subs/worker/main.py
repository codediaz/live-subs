"""Worker orchestrator: one supervised task per scenario (ingest -> transcribe -> publish).

A scenario failure is caught by its own supervisor and reported as status 'error'; it never
stops other scenarios (constitution, principle 6).
"""

import asyncio
import logging
import sys
import time
from typing import Literal

from google import genai
from redis.asyncio import Redis

from subs.common.config import ConfigError, SessionConfig, WorkerSettings, load_sessions
from subs.common.logs import setup_logging
from subs.common.queues import DropOldestQueue
from subs.common.schema import SessionStatus, SubtitleEvent
from subs.worker.ingest import AudioClock, ingest_audio
from subs.worker.publisher import Publisher
from subs.worker.transcriber import SegmentTracker, transcribe
from subs.worker.translator import FinalHistory, TrackTranslator, target_tracks

_LOGGER = logging.getLogger(__name__)

# End of a voiced run = last voiced chunk followed by at least this much silence (research.md R4).
VOICE_END_SILENCE_MS = 300


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class ScenarioState:
    """Mutable status of one scenario, snapshotted into SessionStatus for Redis."""

    def __init__(self, config: SessionConfig) -> None:
        self.config = config
        self.started_at_ms = now_ms()
        self.state: Literal["starting", "live", "stopped", "error"] = "starting"
        self.clock: AudioClock | None = None
        self.last_event_at_ms: int | None = None
        self.latency_original_ms: int | None = None
        self.latency_translation_ms: int | None = None
        self.errors = 0
        self.last_error: str | None = None

    def observe(self, event: SubtitleEvent) -> None:
        self.last_event_at_ms = event.emitted_at_ms
        if event.latency_ms is None:
            return
        if event.kind == "original":
            self.latency_original_ms = event.latency_ms
        else:
            self.latency_translation_ms = event.latency_ms

    def record_translation_error(self, error: str) -> None:
        """A failed sentence counts as an error but does not change the scenario state (RF-015)."""
        self.errors += 1
        self.last_error = f"translation: {error}"[:300]

    def snapshot(self) -> SessionStatus:
        # starting -> live once the first audio chunk has been sent (data-model.md §7).
        if self.state == "starting" and self.clock is not None and self.clock.sent_at(0) is not None:
            self.state = "live"
        current = now_ms()
        return SessionStatus(
            session_id=self.config.id,
            state=self.state,
            source_type=self.config.source.type,
            uptime_s=(current - self.started_at_ms) // 1000,
            last_event_at_ms=self.last_event_at_ms,
            latency_original_ms=self.latency_original_ms,
            latency_translation_ms=self.latency_translation_ms,
            reconnects=0,
            errors=self.errors,
            last_error=self.last_error,
            updated_at_ms=current,
        )


class SourceProducedNoAudio(RuntimeError):
    """The source ended without a single audio chunk; looping it would spin without end."""


async def run_scenario(
    config: SessionConfig,
    settings: WorkerSettings,
    client: genai.Client,
    publisher: Publisher,
    state: ScenarioState,
) -> None:
    """Supervise one scenario. Never raises: failures become status 'error' for this scenario only.

    Without loop, the scenario stops when the source ends. With loop (files only), every pass of
    the clip is a new run with its own run_id, ffmpeg process and Live session (RF-043).
    """
    extra = {"session_id": config.id}
    try:
        while True:
            await _run_once(config, settings, client, publisher, state)
            if not config.source.loop:
                state.state = "stopped"
                _LOGGER.info("scenario_stopped", extra=extra)
                return
            state.state = "starting"  # next pass starts a new run (data-model.md §7)
    except Exception as exc:  # noqa: BLE001 - the supervisor turns every failure into status 'error'
        cause = exc.exceptions[0] if isinstance(exc, ExceptionGroup) else exc
        state.state = "error"
        state.errors += 1
        state.last_error = f"{type(cause).__name__}: {cause}"[:300]
        _LOGGER.error("run_failed", extra={**extra, "error": state.last_error})


async def _run_once(
    config: SessionConfig,
    settings: WorkerSettings,
    client: genai.Client,
    publisher: Publisher,
    state: ScenarioState,
) -> None:
    """One run: new run_id, ffmpeg process and Live session. Returns when the source ends (exit 0)
    and the Live session and translations were given SOURCE_END_GRACE_MS to finish; raises otherwise."""
    extra = {"session_id": config.id}
    run_id = now_ms()
    await publisher.set_run(config.id, run_id)
    audio_queue: DropOldestQueue[bytes] = DropOldestQueue(settings.audio_queue_max_chunks)
    clock = AudioClock(
        chunk_ms=settings.audio_chunk_ms,
        window_s=settings.audio_clock_window_s,
        voice_rms_threshold=settings.voice_rms_threshold,
    )
    state.clock = clock
    tracker = SegmentTracker(
        session_id=config.id,
        run_id=run_id,
        lang=config.source_language,
        clock=clock,
        min_silence_ms=VOICE_END_SILENCE_MS,
    )
    source_done = asyncio.Event()

    async def publish(event: SubtitleEvent) -> None:
        state.observe(await publisher.publish_event(event))

    history = FinalHistory(settings.translation_context_segments)
    translators = [
        TrackTranslator(
            client,
            session_id=config.id,
            source_language=config.source_language,
            target=target,
            title=config.title,
            model=settings.translate_model,
            thinking_level=settings.translate_thinking_level,
            timeout_s=settings.translate_timeout_s,
            queue_max=settings.translation_queue_max,
            take_sequence=tracker.take_sequence,
            publish=publish,
            on_error=state.record_translation_error,
        )
        for target in target_tracks(config.source_language, config.target_languages)
    ]

    async def on_event(event: SubtitleEvent) -> None:
        await publish(event)
        if event.is_final:
            # Enqueue only: the original is already published and never waits for translation.
            context = history.texts()
            history.add(event)
            for translator in translators:
                translator.submit(event, context)

    chunks_read = 0

    async def feed() -> None:
        nonlocal chunks_read
        try:
            chunks_read = await ingest_audio(
                config.source, audio_queue, chunk_ms=settings.audio_chunk_ms, session_id=config.id
            )
        finally:
            source_done.set()

    _LOGGER.info("run_started", extra={**extra, "run_id": run_id})
    translator_tasks = [asyncio.create_task(translator.run()) for translator in translators]
    try:
        # Ingestion and transcription of this run; a failure in either cancels the other.
        async with asyncio.TaskGroup() as group:
            group.create_task(feed())
            group.create_task(
                transcribe(
                    client,
                    model=settings.transcribe_model,
                    source_language=config.source_language,
                    session_id=config.id,
                    audio_queue=audio_queue,
                    source_done=source_done,
                    clock=clock,
                    tracker=tracker,
                    on_event=on_event,
                    end_grace_ms=settings.source_end_grace_ms,
                )
            )
        await asyncio.gather(*(t.drain(settings.source_end_grace_ms / 1000) for t in translators))
    finally:
        for task in translator_tasks:
            task.cancel()
        await asyncio.gather(*translator_tasks, return_exceptions=True)
    if chunks_read == 0:
        raise SourceProducedNoAudio(f"source produced no audio: {config.source.uri}")
    _LOGGER.info("run_finished", extra={**extra, "run_id": run_id, "dropped_chunks": audio_queue.dropped})


async def run_worker(settings: WorkerSettings, sessions: list[SessionConfig]) -> None:
    redis = Redis.from_url(settings.redis_url)
    publisher = Publisher(redis, status_interval_s=settings.status_interval_s, status_ttl_s=settings.status_ttl_s)
    client = genai.Client(api_key=settings.gemini_api_key)
    states = [ScenarioState(config) for config in sessions]
    # Status keeps being published after a run ends, so 'stopped'/'error' stay visible while the
    # worker lives; if the worker dies, the key expires and the panel shows no data (§7.2).
    heartbeats = [asyncio.create_task(publisher.publish_status_periodically(state.snapshot)) for state in states]
    try:
        # One independent supervisor per scenario, no shared TaskGroup (research.md R12): even an
        # unexpected escape from one supervisor must not cancel the others or stop the worker.
        results = await asyncio.gather(
            *(run_scenario(state.config, settings, client, publisher, state) for state in states),
            return_exceptions=True,
        )
        for state, result in zip(states, results, strict=True):
            if isinstance(result, BaseException):
                _LOGGER.error(
                    "supervisor_crashed",
                    extra={"session_id": state.config.id, "error": f"{type(result).__name__}: {result}"[:300]},
                )
        _LOGGER.info("all_runs_finished", extra={"sessions": [state.config.id for state in states]})
        await asyncio.gather(*heartbeats)
    finally:
        for task in heartbeats:
            task.cancel()
        await redis.aclose()


def main() -> None:
    try:
        settings = WorkerSettings.from_env()
        setup_logging(settings.log_level)
        sessions = load_sessions(settings.sessions_file, settings.worker_sessions)
    except ConfigError as exc:
        setup_logging("INFO")
        _LOGGER.error("invalid_configuration", extra={"error": str(exc)})
        sys.exit(2)
    _LOGGER.info("worker_starting", extra={"sessions": [config.id for config in sessions]})
    try:
        asyncio.run(run_worker(settings, sessions))
    except KeyboardInterrupt:
        pass
