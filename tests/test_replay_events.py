"""The replay fixture exercises the browser's event merge cases."""

import runpy
from pathlib import Path

from subs.common.schema import SubtitleEvent

SCRIPT = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/replay_events.py"))
first_run_events = SCRIPT["first_run_events"]
next_run_events = SCRIPT["next_run_events"]


def test_replay_sequence_covers_duplicates_reordering_final_and_new_run() -> None:
    first = first_run_events("sala1", "en", 1000)
    second = next_run_events("sala1", "en", 2000)

    assert all(isinstance(event, SubtitleEvent) for event in [*first, *second])
    assert all(event.latency_ms is not None for event in [*first, *second])
    assert all(SubtitleEvent.model_validate_json(event.model_dump_json()) == event for event in [*first, *second])
    assert all(event.session_id == "sala1" and event.track == "original" for event in [*first, *second])

    assert first[0] == first[1]  # duplicate partial
    assert [event.revision for event in first[:4]] == [0, 0, 2, 1]
    assert first[4].is_final and first[4].revision == 4
    assert not first[5].is_final and first[5].revision < first[4].revision
    assert first[5].revision == 3
    assert first[5].segment_id == first[4].segment_id
    assert first[6].segment_id == first[7].segment_id == 1
    assert first[7].is_final

    assert {event.run_id for event in first} == {1000}
    assert {event.run_id for event in second} == {2000}
    assert second[0].sequence == 0 and second[0].segment_id == 0


def test_replay_uses_configured_source_language() -> None:
    first = first_run_events("sala2", "es", 1000)
    second = next_run_events("sala2", "es", 2000)

    assert all(event.lang == "es" for event in [*first, *second])
    assert first[4].text == "El despliegue está estable hoy."
    assert second[-1].text == "Empieza una charla nueva."
