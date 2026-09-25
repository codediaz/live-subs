"""Configuration: environment settings per process and sessions.yaml loading.

Contracts: specs/001-subs-mvp/contracts/env.md and contracts/sessions-yaml.md.
Any invalid value raises ConfigError naming the variable, or the session and field.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from subs.common.schema import ORIGINAL_TRACK

Language = Literal["en", "es"]


class ConfigError(ValueError):
    """Invalid configuration. The worker must not start with a partial configuration."""


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


class _EnvSettings(BaseModel):
    """Settings read from environment variables named like the fields, in upper case."""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        env = os.environ if env is None else env
        # Empty values count as unset, so compose interpolation of blank variables keeps defaults.
        values = {name: env[name.upper()] for name in cls.model_fields if env.get(name.upper(), "") != ""}
        try:
            return cls(**values)
        except ValidationError as exc:
            error = exc.errors()[0]
            variable = str(error["loc"][0]).upper()
            raise ConfigError(f"environment variable {variable}: {error['msg']}") from None


class WorkerSettings(_EnvSettings):
    gemini_api_key: str = Field(repr=False)
    redis_url: str = "redis://redis:6379/0"
    transcribe_model: str = "gemini-3.5-transcribe-live"
    translate_model: str = "gemini-3.5-flash-lite"
    translate_thinking_level: Literal["MINIMAL", "LOW", "MEDIUM", "HIGH"] = "MINIMAL"
    translate_timeout_s: float = 10
    translation_context_segments: int = 3
    translation_queue_max: int = 10
    audio_chunk_ms: int = 100
    audio_queue_max_chunks: int = 50
    voice_rms_threshold: float = 500
    audio_clock_window_s: int = 120
    source_end_grace_ms: int = 3000
    status_interval_s: float = 2
    status_ttl_s: int = 15
    sessions_file: str = "sessions.yaml"
    worker_sessions: str = ""
    log_level: str = "INFO"


class GatewaySettings(_EnvSettings):
    """Gateway settings. Deliberately has no GEMINI_API_KEY (RF-031)."""

    redis_url: str = "redis://redis:6379/0"
    sessions_file: str = "sessions.yaml"
    gateway_port: int = 8000
    ws_ping_s: float = 20
    ws_client_queue_max: int = 100
    log_level: str = "INFO"


# ---------------------------------------------------------------------------
# sessions.yaml
# ---------------------------------------------------------------------------


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["file", "stream"]
    uri: str
    loop: bool = False


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^\S+$")
    name: str
    title: str
    source: SourceConfig
    source_language: Language
    target_languages: list[Language]
    glossary: str | None = None  # accepted in P0, used in P1

    @property
    def tracks(self) -> list[str]:
        return [ORIGINAL_TRACK, *self.target_languages]


class _Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_languages: list[Language] = []
    glossary: str | None = None


def load_sessions(path: str | Path, worker_sessions: str) -> list[SessionConfig]:
    """Load and validate sessions.yaml, keeping only the ids in worker_sessions (empty = all)."""
    path = Path(path)
    data = _read_yaml(path)
    defaults = _parse_defaults(path, data.get("defaults") or {})
    raw_sessions = data.get("sessions")
    if not isinstance(raw_sessions, list) or not raw_sessions:
        raise ConfigError(f"{path}: field 'sessions': a non-empty list of sessions is required")

    sessions: list[SessionConfig] = []
    seen: set[str] = set()
    for position, raw in enumerate(raw_sessions, start=1):
        config = _parse_session(path, position, raw, defaults)
        if config.id in seen:
            raise _session_error(path, f"'{config.id}'", "id", "duplicated")
        seen.add(config.id)
        sessions.append(config)
    return _filter(sessions, worker_sessions)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file ({exc.strerror})") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML ({exc})") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: the top level must be a mapping with 'sessions'")
    return data


def _parse_defaults(path: Path, raw: Any) -> _Defaults:
    try:
        return _Defaults.model_validate(raw)
    except ValidationError as exc:
        error = exc.errors()[0]
        field = ".".join(str(part) for part in ("defaults", *error["loc"]))
        raise ConfigError(f"{path}: field '{field}': {error['msg']}") from None


def _parse_session(path: Path, position: int, raw: Any, defaults: _Defaults) -> SessionConfig:
    raw_id = raw.get("id") if isinstance(raw, dict) else None
    label = f"'{raw_id}'" if isinstance(raw_id, str) and raw_id else f"#{position}"
    if not isinstance(raw, dict):
        raise _session_error(path, label, "session", "must be a mapping")

    merged = {**defaults.model_dump(exclude_none=True), **raw}
    try:
        config = SessionConfig.model_validate(merged)
    except ValidationError as exc:
        error = exc.errors()[0]
        field = ".".join(str(part) for part in error["loc"])
        raise _session_error(path, label, field, error["msg"]) from None

    if config.source.loop and config.source.type != "file":
        raise _session_error(path, label, "source.loop", "loop is only allowed with type 'file'")
    if config.source.type == "file":
        clip = Path(config.source.uri)
        if not clip.is_absolute():
            clip = path.parent / clip
        if not clip.is_file():
            raise _session_error(path, label, "source.uri", f"file not found: {config.source.uri}")
        config.source.uri = str(clip)

    # A target equal to the source language adds nothing: the original track already covers it.
    targets = [lang for lang in dict.fromkeys(config.target_languages) if lang != config.source_language]
    config.target_languages = targets
    return config


def _filter(sessions: list[SessionConfig], worker_sessions: str) -> list[SessionConfig]:
    wanted = [item.strip() for item in worker_sessions.split(",") if item.strip()]
    if not wanted:
        return sessions
    known = {config.id for config in sessions}
    unknown = [item for item in wanted if item not in known]
    if unknown:
        raise ConfigError(f"WORKER_SESSIONS: unknown session ids: {', '.join(unknown)}")
    return [config for config in sessions if config.id in wanted]


def _session_error(path: Path, label: str, field: str, message: str) -> ConfigError:
    return ConfigError(f"{path}: session {label}: field '{field}': {message}")
