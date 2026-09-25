"""Tests for the translator's pure functions (data-model.md §8; RF-009 to RF-012)."""

import pytest

from subs.common.schema import SubtitleEvent
from subs.worker.translator import (
    FinalHistory,
    build_prompt,
    clean_translation,
    system_instruction,
    target_tracks,
    translation_event,
)


def original(segment_id: int, text: str, *, is_final: bool = True, **overrides) -> SubtitleEvent:
    fields = {
        "session_id": "sala1",
        "run_id": 1790000000000,
        "track": "original",
        "sequence": segment_id * 2,
        "segment_id": segment_id,
        "revision": 3,
        "kind": "original",
        "lang": "en",
        "text": text,
        "is_final": is_final,
        "start_ms": 1000 * segment_id,
        "end_ms": 1000 * segment_id + 800 if is_final else None,
        "emitted_at_ms": 1790000005000,
        "latency_ms": 1500 if is_final else 300,
    }
    fields.update(overrides)
    return SubtitleEvent(**fields)


class TestTargetTracks:
    def test_excludes_source_language(self):
        assert target_tracks("es", ["es", "en"]) == ["en"]

    def test_keeps_order_and_removes_duplicates(self):
        assert target_tracks("en", ["es", "pt", "es"]) == ["es", "pt"]

    def test_no_targets(self):
        assert target_tracks("en", []) == []
        assert target_tracks("en", ["en"]) == []


class TestFinalHistory:
    def test_keeps_only_the_last_n_finals(self):
        history = FinalHistory(max_segments=3)
        for index in range(5):
            history.add(original(index, f"sentence {index}"))
        assert history.texts() == ["sentence 2", "sentence 3", "sentence 4"]

    def test_ignores_partials(self):
        history = FinalHistory(max_segments=3)
        history.add(original(0, "final one"))
        history.add(original(1, "partial two", is_final=False))
        assert history.texts() == ["final one"]

    def test_zero_context(self):
        history = FinalHistory(max_segments=0)
        history.add(original(0, "final one"))
        assert history.texts() == []


class TestPrompt:
    def test_system_instruction_names_languages_and_asks_for_translation_only(self):
        instruction = system_instruction("en", "es")
        assert "English" in instruction
        assert "Spanish" in instruction
        assert "only the translation" in instruction

    def test_system_instruction_rejects_unknown_language(self):
        with pytest.raises(ValueError):
            system_instruction("en", "xx")

    def test_prompt_contains_title_context_and_sentence(self):
        prompt = build_prompt("Kubernetes in production", ["First.", "Second."], "Third sentence.")
        assert "Kubernetes in production" in prompt
        assert "First.\nSecond." in prompt
        assert prompt.rstrip().endswith("Third sentence.")
        assert prompt.index("Second.") < prompt.index("Third sentence.")

    def test_prompt_without_context(self):
        prompt = build_prompt("Title", [], "Only sentence.")
        assert "(none)" in prompt
        assert "Only sentence." in prompt


class TestCleanTranslation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  Hola a todos.  ", "Hola a todos."),
            ('"Hola a todos."', "Hola a todos."),
            ("“Hola a todos.”", "Hola a todos."),
            ("«Hola a todos.»", "Hola a todos."),
            ("'Hola'", "Hola"),
            ("Hola\na todos.", "Hola a todos."),
            ('Dijo "hola" y se fue.', 'Dijo "hola" y se fue.'),
        ],
    )
    def test_cleans_whitespace_and_wrapping_quotes(self, raw, expected):
        assert clean_translation(raw) == expected


class TestTranslationEvent:
    def test_copies_the_original_sentence(self):
        source = original(4, "Welcome to Nerdearla")
        event = translation_event(source, target="es", text="Bienvenidos a Nerdearla", sequence=10, emitted_at_ms=1790000006000)
        assert (event.session_id, event.run_id, event.segment_id) == ("sala1", source.run_id, 4)
        assert (event.start_ms, event.end_ms) == (source.start_ms, source.end_ms)
        assert (event.track, event.lang, event.kind) == ("es", "es", "translation")
        assert (event.revision, event.is_final, event.sequence) == (0, True, 10)
        assert event.text == "Bienvenidos a Nerdearla"

    def test_latency_uses_the_same_reference_as_the_original(self):
        # Original emitted at 5000 with latency 1500 -> end of sentence sent at 3500.
        source = original(4, "Welcome")
        event = translation_event(source, target="es", text="Bienvenidos", sequence=10, emitted_at_ms=1790000006000)
        assert event.latency_ms == 2500

    def test_latency_unknown_when_original_has_none(self):
        source = original(4, "Welcome", latency_ms=None)
        event = translation_event(source, target="es", text="Bienvenidos", sequence=10, emitted_at_ms=1790000006000)
        assert event.latency_ms is None

    def test_partials_are_never_translated(self):
        with pytest.raises(ValueError):
            translation_event(original(4, "Welc", is_final=False), target="es", text="Bienv", sequence=10, emitted_at_ms=1)
