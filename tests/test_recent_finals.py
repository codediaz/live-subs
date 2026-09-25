"""Recent final subtitle snapshots for newly connected clients (RF-048)."""

import asyncio
from collections.abc import AsyncIterator

from subs.common.schema import SubtitleEvent, channel_name
from subs.gateway import main as gateway_main


def event(
    *,
    session_id: str = "sala1",
    track: str = "original",
    run_id: int = 100,
    segment_id: int = 1,
    is_final: bool = True,
) -> SubtitleEvent:
    return SubtitleEvent(
        session_id=session_id,
        run_id=run_id,
        track=track,
        sequence=segment_id,
        segment_id=segment_id,
        kind="original" if track == "original" else "translation",
        lang="en" if track == "original" else track,
        text=f"segment {segment_id}",
        is_final=is_final,
        start_ms=segment_id * 1000,
        end_ms=segment_id * 1000 + 500 if is_final else None,
        emitted_at_ms=run_id + segment_id,
    )


def test_keeps_only_latest_finals_per_session_and_track_in_arrival_order() -> None:
    recent = gateway_main.RecentFinals(2)
    first = event(segment_id=1)
    second = event(segment_id=2)
    third = event(segment_id=3)
    other_track = event(track="es", segment_id=4)
    other_session = event(session_id="sala2", segment_id=5)

    for item in (first, other_track, second, other_session, third):
        recent.add(item)

    assert recent.snapshot("sala1", "original") == [second, third]
    assert recent.snapshot("sala1", "es") == [other_track]
    assert recent.snapshot("sala2", "original") == [other_session]


def test_ignores_partials() -> None:
    recent = gateway_main.RecentFinals(2)
    final = event(segment_id=1)
    recent.add(final)
    recent.add(event(segment_id=2, is_final=False))

    assert recent.snapshot("sala1", "original") == [final]


def test_newer_run_replaces_previous_finals_for_its_track() -> None:
    recent = gateway_main.RecentFinals(2)
    previous = event(run_id=100)
    other_track = event(track="es", run_id=100)
    current = event(run_id=200, segment_id=2)
    recent.add(previous)
    recent.add(other_track)
    recent.add(current)
    recent.add(event(run_id=100, segment_id=3))

    assert recent.snapshot("sala1", "original") == [current]
    assert recent.snapshot("sala1", "es") == [other_track]


def test_partial_from_newer_run_clears_previous_finals() -> None:
    recent = gateway_main.RecentFinals(2)
    recent.add(event(run_id=100))
    recent.add(event(run_id=200, is_final=False))

    assert recent.snapshot("sala1", "original") == []


def test_zero_capacity_stores_nothing() -> None:
    recent = gateway_main.RecentFinals(0)
    recent.add(event())

    assert recent.snapshot("sala1", "original") == []


def test_snapshot_is_a_copy() -> None:
    recent = gateway_main.RecentFinals(2)
    final = event()
    recent.add(final)

    snapshot = recent.snapshot("sala1", "original")
    snapshot.clear()

    assert recent.snapshot("sala1", "original") == [final]


def test_distributor_caches_only_valid_channel_events() -> None:
    final = event(track="es")
    mismatched = event(track="es", segment_id=2)

    class PubSubMessages:
        async def listen(self) -> AsyncIterator[dict[str, str | bytes]]:
            yield {
                "type": "pmessage",
                "channel": channel_name(final.session_id, final.track).encode(),
                "data": final.model_dump_json(),
            }
            yield {"type": "pmessage", "channel": "subs:sala2:es", "data": mismatched.model_dump_json()}
            yield {"type": "pmessage", "channel": "subs:sala1:es", "data": "not json"}

    recent = gateway_main.RecentFinals(5)
    distributor = gateway_main.EventDistributor(recent)
    asyncio.run(distributor.listen(PubSubMessages()))  # type: ignore[arg-type]

    assert recent.snapshot("sala1", "es") == [final]
    assert recent.snapshot("sala2", "es") == []
