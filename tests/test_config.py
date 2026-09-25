"""Tests for sessions.yaml and environment configuration.

Rules: specs/001-subs-mvp/contracts/sessions-yaml.md and contracts/env.md.
"""

from pathlib import Path

import pytest
import yaml

from subs.common.config import ConfigError, GatewaySettings, WorkerSettings, load_sessions

CLIP = "samples/audio/charla_en.ogg"


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    clip = tmp_path / CLIP
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"")
    (tmp_path / "samples/audio/charla_es.ogg").write_bytes(b"")
    return tmp_path


def session(**overrides) -> dict:
    data = {
        "id": "sala1",
        "name": "Main stage",
        "title": "Talk title",
        "source": {"type": "file", "uri": CLIP},
        "source_language": "en",
        "target_languages": ["es"],
    }
    data.update(overrides)
    return data


def write(base_dir: Path, sessions: list[dict], defaults: dict | None = None) -> Path:
    content: dict = {"sessions": sessions}
    if defaults is not None:
        content["defaults"] = defaults
    path = base_dir / "sessions.yaml"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return path


class TestLoadSessions:
    def test_loads_valid_file(self, base_dir):
        second = session(
            id="sala2",
            source={"type": "stream", "uri": "https://example.org/live.m3u8"},
            source_language="es",
            target_languages=["en"],
        )
        loaded = load_sessions(write(base_dir, [session(), second]), "")
        assert [s.id for s in loaded] == ["sala1", "sala2"]
        assert loaded[1].source.type == "stream"
        assert loaded[1].source.uri == "https://example.org/live.m3u8"

    def test_file_uri_is_resolved_relative_to_sessions_file(self, base_dir):
        loaded = load_sessions(write(base_dir, [session()]), "")
        assert Path(loaded[0].source.uri) == base_dir / CLIP

    def test_target_languages_inherited_from_defaults(self, base_dir):
        data = session()
        del data["target_languages"]
        loaded = load_sessions(write(base_dir, [data], defaults={"target_languages": ["es"]}), "")
        assert loaded[0].target_languages == ["es"]

    def test_session_overrides_defaults(self, base_dir):
        path = write(base_dir, [session(target_languages=["es"])], defaults={"target_languages": ["en"]})
        assert load_sessions(path, "")[0].target_languages == ["es"]

    def test_target_equal_to_source_is_ignored(self, base_dir):
        loaded = load_sessions(write(base_dir, [session(source_language="es", target_languages=["es", "en"])]), "")
        assert loaded[0].target_languages == ["en"]
        assert loaded[0].tracks == ["original", "en"]

    def test_tracks_without_targets(self, base_dir):
        loaded = load_sessions(write(base_dir, [session(target_languages=[])]), "")
        assert loaded[0].tracks == ["original"]

    def test_loop_defaults_to_false_and_accepted_for_file(self, base_dir):
        looped = session(id="sala2", source={"type": "file", "uri": CLIP, "loop": True})
        loaded = load_sessions(write(base_dir, [session(), looped]), "")
        assert loaded[0].source.loop is False
        assert loaded[1].source.loop is True

    def test_glossary_path_is_accepted(self, base_dir):
        loaded = load_sessions(write(base_dir, [session(glossary="samples/glossaries/sala1.yaml")]), "")
        assert loaded[0].glossary == "samples/glossaries/sala1.yaml"


class TestValidationRules:
    def test_id_is_required(self, base_dir):
        data = session()
        del data["id"]
        with pytest.raises(ConfigError, match=r"#1.*'id'"):
            load_sessions(write(base_dir, [data]), "")

    def test_id_must_be_unique(self, base_dir):
        with pytest.raises(ConfigError, match=r"sala1.*'id'.*duplicated"):
            load_sessions(write(base_dir, [session(), session()]), "")

    def test_id_without_spaces(self, base_dir):
        with pytest.raises(ConfigError, match=r"'id'"):
            load_sessions(write(base_dir, [session(id="sala 1")]), "")

    @pytest.mark.parametrize("field", ["name", "title", "source_language"])
    def test_required_fields(self, base_dir, field):
        data = session()
        del data[field]
        with pytest.raises(ConfigError, match=rf"sala1.*'{field}'"):
            load_sessions(write(base_dir, [data]), "")

    @pytest.mark.parametrize("source_type", ["file", "stream"])
    def test_uri_is_required(self, base_dir, source_type):
        with pytest.raises(ConfigError, match=r"sala1.*'source\.uri'"):
            load_sessions(write(base_dir, [session(source={"type": source_type})]), "")

    def test_file_must_exist(self, base_dir):
        missing = session(source={"type": "file", "uri": "samples/audio/missing.ogg"})
        with pytest.raises(ConfigError, match=r"sala1.*'source\.uri'.*missing\.ogg"):
            load_sessions(write(base_dir, [missing]), "")

    def test_loop_with_stream_is_an_error(self, base_dir):
        stream = session(source={"type": "stream", "uri": "https://example.org/live.m3u8", "loop": True})
        with pytest.raises(ConfigError, match=r"sala1.*'source\.loop'"):
            load_sessions(write(base_dir, [stream]), "")

    def test_microphone_is_rejected(self, base_dir):
        with pytest.raises(ConfigError, match=r"sala1.*'source\.type'"):
            load_sessions(write(base_dir, [session(source={"type": "microphone", "uri": "default"})]), "")

    def test_auto_source_language_is_rejected(self, base_dir):
        with pytest.raises(ConfigError, match=r"sala1.*'source_language'"):
            load_sessions(write(base_dir, [session(source_language="auto")]), "")

    def test_portuguese_target_is_rejected(self, base_dir):
        with pytest.raises(ConfigError, match=r"sala1.*'target_languages"):
            load_sessions(write(base_dir, [session(target_languages=["es", "pt"])]), "")

    def test_unknown_field_is_rejected(self, base_dir):
        with pytest.raises(ConfigError, match=r"sala1.*'titel'"):
            load_sessions(write(base_dir, [session(titel="typo")]), "")

    def test_sessions_list_is_required(self, base_dir):
        path = base_dir / "sessions.yaml"
        path.write_text("defaults: {}\n", encoding="utf-8")
        with pytest.raises(ConfigError, match=r"'sessions'"):
            load_sessions(path, "")

    def test_missing_sessions_file(self, base_dir):
        with pytest.raises(ConfigError, match=r"nope\.yaml"):
            load_sessions(base_dir / "nope.yaml", "")


class TestWorkerSessions:
    @pytest.fixture
    def path(self, base_dir):
        second = session(
            id="sala2",
            source={"type": "file", "uri": "samples/audio/charla_es.ogg"},
            source_language="es",
            target_languages=["en"],
        )
        return write(base_dir, [session(), second])

    def test_empty_means_all(self, path):
        assert [s.id for s in load_sessions(path, "")] == ["sala1", "sala2"]

    def test_filters_by_id(self, path):
        assert [s.id for s in load_sessions(path, "sala2")] == ["sala2"]

    def test_ignores_whitespace(self, path):
        assert [s.id for s in load_sessions(path, " sala1 , sala2 ")] == ["sala1", "sala2"]

    def test_unknown_id_is_an_error(self, path):
        with pytest.raises(ConfigError, match=r"WORKER_SESSIONS.*sala9"):
            load_sessions(path, "sala1,sala9")


class TestWorkerSettings:
    def test_defaults_from_contract(self):
        settings = WorkerSettings.from_env({"GEMINI_API_KEY": "test-key"})
        assert settings.gemini_api_key == "test-key"
        assert settings.redis_url == "redis://redis:6379/0"
        assert settings.transcribe_model == "gemini-3.5-transcribe-live"
        assert settings.translate_model == "gemini-3.5-flash-lite"
        assert settings.translate_thinking_level == "MINIMAL"
        assert settings.translate_timeout_s == 10
        assert settings.translation_context_segments == 3
        assert settings.translation_queue_max == 10
        assert settings.audio_chunk_ms == 100
        assert settings.audio_queue_max_chunks == 50
        assert settings.voice_rms_threshold == 500
        assert settings.audio_clock_window_s == 120
        assert settings.source_end_grace_ms == 3000
        assert settings.status_interval_s == 2
        assert settings.status_ttl_s == 15
        assert settings.sessions_file == "sessions.yaml"
        assert settings.worker_sessions == ""
        assert settings.log_level == "INFO"

    def test_reads_overrides(self):
        settings = WorkerSettings.from_env(
            {"GEMINI_API_KEY": "k", "AUDIO_CHUNK_MS": "50", "TRANSLATE_MODEL": "gemini-3.8-flash", "TRANSLATE_THINKING_LEVEL": "LOW"}
        )
        assert settings.audio_chunk_ms == 50
        assert settings.translate_model == "gemini-3.8-flash"
        assert settings.translate_thinking_level == "LOW"

    def test_api_key_is_required(self):
        with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
            WorkerSettings.from_env({})

    def test_empty_value_counts_as_unset(self):
        with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
            WorkerSettings.from_env({"GEMINI_API_KEY": ""})
        assert WorkerSettings.from_env({"GEMINI_API_KEY": "k", "AUDIO_CHUNK_MS": ""}).audio_chunk_ms == 100

    def test_invalid_number_names_the_variable(self):
        with pytest.raises(ConfigError, match="AUDIO_CHUNK_MS"):
            WorkerSettings.from_env({"GEMINI_API_KEY": "k", "AUDIO_CHUNK_MS": "fast"})

    def test_invalid_thinking_level_is_rejected(self):
        with pytest.raises(ConfigError, match="TRANSLATE_THINKING_LEVEL"):
            WorkerSettings.from_env({"GEMINI_API_KEY": "k", "TRANSLATE_THINKING_LEVEL": "OFF"})


class TestGatewaySettings:
    def test_has_no_api_key(self):
        assert "gemini_api_key" not in GatewaySettings.model_fields
        settings = GatewaySettings.from_env({"GEMINI_API_KEY": "leaked"})
        assert "leaked" not in settings.model_dump_json()

    def test_defaults_from_contract(self):
        settings = GatewaySettings.from_env({})
        assert settings.redis_url == "redis://redis:6379/0"
        assert settings.sessions_file == "sessions.yaml"
        assert settings.gateway_port == 8000
        assert settings.ws_ping_s == 20
        assert settings.ws_client_queue_max == 100
        assert settings.log_level == "INFO"
