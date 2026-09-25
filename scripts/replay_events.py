"""Replay fixed subtitle events against a configured session for quickstart V6."""

import argparse
import asyncio
import time

from redis.asyncio import Redis

from subs.common.config import ConfigError, GatewaySettings, load_sessions
from subs.common.schema import ORIGINAL_TRACK, SubtitleEvent, channel_name


# Pacing makes each fixture state visible in the browser during manual verification.
REPLAY_STEP_DELAY_S = 0.35
REPLAY_RUN_PAUSE_S = 2.0


def first_run_events(session_id: str, language: str, run_id: int) -> list[SubtitleEvent]:
    """Duplicate and reorder partials, then deliver the last partial after its final."""
    if language == "en":
        words = (
            "The deployment", "The deployment is", "The deployment is healthy",
            "The deployment is healthy today", "The deployment is healthy today.",
            "The audience can follow", "The audience can follow along.",
        )
    elif language == "es":
        words = (
            "El despliegue", "El despliegue está", "El despliegue está estable",
            "El despliegue está estable hoy", "El despliegue está estable hoy.",
            "El público puede seguir", "El público puede seguir la charla.",
        )
    else:
        raise ValueError(f"Unsupported source language: {language}")

    first = SubtitleEvent(
        session_id=session_id,
        run_id=run_id,
        track=ORIGINAL_TRACK,
        sequence=0,
        segment_id=0,
        revision=0,
        kind="original",
        lang=language,
        text=words[0],
        is_final=False,
        start_ms=0,
        emitted_at_ms=0,
        latency_ms=0,  # synthetic fixture has no audio clock
    )
    partial_one = first.model_copy(update={"sequence": 1, "revision": 1, "text": words[1]})
    partial_two = first.model_copy(
        update={"sequence": 2, "revision": 2, "text": words[2]}
    )
    late_partial = first.model_copy(
        update={"sequence": 3, "revision": 3, "text": words[3]}
    )
    final = first.model_copy(
        update={
            "sequence": 4,
            "revision": 4,
            "text": words[4],
            "is_final": True,
            "end_ms": 1500,
        }
    )
    next_partial = first.model_copy(
        update={
            "sequence": 5,
            "segment_id": 1,
            "revision": 0,
            "text": words[5],
            "start_ms": 1800,
        }
    )
    next_final = next_partial.model_copy(
        update={
            "sequence": 6,
            "revision": 1,
            "text": words[6],
            "is_final": True,
            "end_ms": 3000,
        }
    )
    return [
        first,
        first,  # duplicate delivery of the same partial
        partial_two,
        partial_one,  # lower revision arrives after a higher one
        final,
        late_partial,  # last partial arrives after the final
        next_partial,
        next_final,
    ]


def next_run_events(session_id: str, language: str, run_id: int) -> list[SubtitleEvent]:
    """A new run starts numbering and audio positions from zero."""
    if language == "en":
        partial_text, final_text = "A new talk begins", "A new talk begins."
    elif language == "es":
        partial_text, final_text = "Empieza una charla nueva", "Empieza una charla nueva."
    else:
        raise ValueError(f"Unsupported source language: {language}")

    partial = SubtitleEvent(
        session_id=session_id,
        run_id=run_id,
        track=ORIGINAL_TRACK,
        sequence=0,
        segment_id=0,
        revision=0,
        kind="original",
        lang=language,
        text=partial_text,
        is_final=False,
        start_ms=0,
        emitted_at_ms=0,
        latency_ms=0,
    )
    final = partial.model_copy(
        update={
            "sequence": 1,
            "revision": 1,
            "text": final_text,
            "is_final": True,
            "end_ms": 1200,
        }
    )
    return [partial, final]


async def replay(session_id: str, language: str, redis_url: str) -> None:
    async with Redis.from_url(redis_url) as redis:
        first_run_id = time.time_ns() // 1_000_000
        for event in first_run_events(session_id, language, first_run_id):
            published = event.model_copy(update={"emitted_at_ms": time.time_ns() // 1_000_000})
            await redis.publish(channel_name(session_id, ORIGINAL_TRACK), published.model_dump_json())
            await asyncio.sleep(REPLAY_STEP_DELAY_S)

        await asyncio.sleep(REPLAY_RUN_PAUSE_S)
        next_run_id = max(time.time_ns() // 1_000_000, first_run_id + 1)
        for event in next_run_events(session_id, language, next_run_id):
            published = event.model_copy(update={"emitted_at_ms": time.time_ns() // 1_000_000})
            await redis.publish(channel_name(session_id, ORIGINAL_TRACK), published.model_dump_json())
            await asyncio.sleep(REPLAY_STEP_DELAY_S)

    print(f"Replayed duplicate, reordered, final, and new-run events for {session_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="ID of a session in sessions.yaml")
    args = parser.parse_args()

    settings = GatewaySettings.from_env()
    try:
        sessions = load_sessions(settings.sessions_file, worker_sessions="")
    except ConfigError as exc:
        parser.error(str(exc))
    session = next((item for item in sessions if item.id == args.session), None)
    if session is None:
        parser.error(f"session '{args.session}' is not in {settings.sessions_file}")

    asyncio.run(replay(session.id, session.source_language, settings.redis_url))


if __name__ == "__main__":
    main()
