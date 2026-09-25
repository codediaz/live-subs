"""Keep the operator's environment template aligned with its contract."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "specs/001-subs-mvp/contracts/env.md"
EXAMPLE = ROOT / ".env.example"


def test_env_example_matches_contract() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    example = EXAMPLE.read_text(encoding="utf-8")

    defaults = dict(
        re.findall(
            r"^\| (?:\*\*Δ\*\* )?`([A-Z][A-Z0-9_]*)` \| `([^`]*)` \|",
            contract,
            re.MULTILINE,
        )
    )
    entries = dict(
        re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", example, re.MULTILINE)
    )
    required = set(
        re.findall(
            r"^\| (?:\*\*Δ\*\* )?`([A-Z][A-Z0-9_]*)` \|",
            contract,
            re.MULTILINE,
        )
    )
    assert set(entries) == required
    assert entries["GEMINI_API_KEY"] == ""
    assert entries["WORKER_SESSIONS"] == ""
    assert {name: entries[name] for name in defaults} == defaults

    p1_defaults = {
        "MAX_SEGMENT_MS": "6000",
        "HISTORY_MAX_EVENTS": "5000",
        "HISTORY_TTL_S": "86400",
    }
    for name, value in p1_defaults.items():
        assert f"# {name}={value}" in example.splitlines()
        assert name not in entries
