"""Contract tests for SubtitleEvent and SessionStatus (docs/architecture.md §7.1, §7.2)."""

import pytest
from pydantic import ValidationError

from subs.common.schema import SessionStatus, SubtitleEvent, channel_name

ARCHITECTURE_EXAMPLE = """
{
  "schema_version": 1,
  "session_id": "sala1",
  "run_id": 1790263700000,
  "track": "es",
  "sequence": 87,
  "segment_id": 42,
  "revision": 0,
  "kind": "translation",
  "lang": "es",
  "text": "Bienvenidos a Nerdearla",
  "is_final": true,
  "start_ms": 12340,
  "end_ms": 14120,
  "emitted_at_ms": 1790263812345,
  "latency_ms": 2310
}
"""


def make_event(**overrides) -> SubtitleEvent:
    fields = {
        "session_id": "sala1",
        "run_id": 1790263700000,
        "track": "original",
        "sequence": 1,
        "segment_id": 0,
        "kind": "original",
        "lang": "en",
        "text": "Welcome to Nerdearla",
        "is_final": False,
        "start_ms": 0,
        "emitted_at_ms": 1790263700100,
    }
    fields.update(overrides)
    return SubtitleEvent(**fields)


def make_status(**overrides) -> SessionStatus:
    fields = {
        "session_id": "sala1",
        "state": "live",
        "source_type": "file",
        "uptime_s": 12,
        "last_event_at_ms": 1790263700100,
        "latency_original_ms": 900,
        "latency_translation_ms": 2400,
        "reconnects": 0,
        "errors": 0,
        "last_error": None,
        "updated_at_ms": 1790263700200,
    }
    fields.update(overrides)
    return SessionStatus(**fields)


class TestSubtitleEvent:
    def test_defaults(self):
        event = make_event()
        assert event.schema_version == 1
        assert event.revision == 0
        assert event.end_ms is None
        assert event.latency_ms is None

    def test_json_round_trip(self):
        event = make_event(is_final=True, end_ms=1800, latency_ms=1700, revision=3)
        assert SubtitleEvent.model_validate_json(event.model_dump_json()) == event

    def test_parses_architecture_example(self):
        event = SubtitleEvent.model_validate_json(ARCHITECTURE_EXAMPLE)
        assert event.kind == "translation"
        assert event.track == "es"
        assert event.latency_ms == 2310

    def test_rejects_invalid_kind(self):
        with pytest.raises(ValidationError):
            make_event(kind="partial")

    @pytest.mark.parametrize("version", [0, 2])
    def test_rejects_other_schema_version(self, version):
        with pytest.raises(ValidationError):
            make_event(schema_version=version)

    def test_rejects_missing_required_field(self):
        with pytest.raises(ValidationError):
            SubtitleEvent(session_id="sala1")

    def test_original_goes_to_original_track(self):
        with pytest.raises(ValidationError):
            make_event(kind="original", track="es")

    def test_translation_is_always_final(self):
        with pytest.raises(ValidationError):
            make_event(kind="translation", track="es", lang="es", is_final=False)

    def test_accepts_final_translation(self):
        event = make_event(kind="translation", track="es", lang="es", is_final=True, end_ms=1800)
        assert event.is_final


class TestSessionStatus:
    def test_json_round_trip(self):
        status = make_status()
        assert SessionStatus.model_validate_json(status.model_dump_json()) == status

    @pytest.mark.parametrize("state", ["starting", "live", "reconnecting", "stopped", "error"])
    def test_accepts_every_state(self, state):
        assert make_status(state=state).state == state

    def test_rejects_invalid_state(self):
        with pytest.raises(ValidationError):
            make_status(state="paused")

    def test_rejects_invalid_source_type(self):
        with pytest.raises(ValidationError):
            make_status(source_type="youtube")

    def test_optional_values_may_be_null(self):
        status = make_status(last_event_at_ms=None, latency_original_ms=None, latency_translation_ms=None)
        assert status.latency_original_ms is None


def test_channel_name():
    assert channel_name("sala1", "es") == "subs:sala1:es"
    assert channel_name("sala2", "original") == "subs:sala2:original"
