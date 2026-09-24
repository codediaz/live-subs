# AGENTS.md — live-subs

Instructions for AI coding agents (Claude Code, Codex) working in this repository.

## Project

Open source, real-time subtitles and translation for conferences with many stages in parallel
(Nerdearla Vibeathon 2026). Audio (file, stream URL, mic) → Gemini Live transcription →
translation of final sentences → Redis → FastAPI gateway → audience web, OBS overlay, ops panel.

**Hard deadline: 2026-09-25 15:00 UTC.** A working, simple solution beats an elegant unfinished one.

## Read before any task

1. `.specify/memory/constitution.md` — non-negotiable principles. They win over anything else.
2. `docs/architecture.md` — system design, contracts and decisions (single source of truth for design).
3. `specs/<feature>/spec.md`, `plan.md`, `tasks.md` — what to build now and how to verify it.

If these documents conflict, stop and ask. Never resolve a conflict silently.

## Workflow (Spec-Driven Development with Spec Kit)

- Phases: `/speckit-constitution` → `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`.
- **Implement one task at a time.** Do only the requested task, run the tests, show the result,
  mark the task `[x]` in `tasks.md` and **stop**. Do not start the next task unasked.
- Priorities: P0 (MVP) → P1 → P2. Never start P1 work while any P0 task is open.
- Behavior changes go to the spec first. Show the spec diff before touching code.
- Do not refactor, rename or "improve" code outside the current task.

## Git

- The agent never runs `git commit`, `git push` or `git reset`.
- Leave all changes uncommitted for human review.
- When a task is done, propose a commit message in Conventional Commits format, in English.

## Stack and layout

- Python 3.12, asyncio, FastAPI + uvicorn, Pydantic v2, redis-py (asyncio), google-genai SDK, PyYAML.
- ffmpeg for audio ingestion. Frontend: plain HTML + vanilla JS, no build step. **No Node.**
- One Docker image, two processes: `python -m subs.worker` and `python -m subs.gateway`.

```
src/subs/common/    config.py, schema.py (SubtitleEvent, SessionStatus)
src/subs/worker/    main.py, ingest.py, transcriber.py, translator.py, publisher.py
src/subs/gateway/   main.py, static/ (index.html, overlay.html, panel.html)
samples/            audio/ (test clips), glossaries/
tests/              pytest
```

## Commands

```bash
cp .env.example .env              # then set GEMINI_API_KEY
docker compose up --build         # full stack: redis + worker + gateway
pip install -e ".[dev]"           # local dev
pytest -q                         # test suite (must pass before marking a task done)
```

## Gemini rules

- Models come from env vars only: `TRANSCRIBE_MODEL=gemini-3.5-transcribe-live`,
  `TRANSLATE_MODEL=gemini-3.8-flash`. Use exact model IDs, never `-latest` aliases.
- Audio goes only through the Live API as a continuous stream: 16-bit PCM, 16 kHz, mono,
  chunks of `AUDIO_CHUNK_MS`. **Never send audio chunks through REST calls.**
- Translate **final** sentences only, never partials. Keep model reasoning/thinking at the minimum.
- Live connections last about 10 minutes: code must survive a closed connection (reconnect, P1).
- When unsure about the SDK or API, check the official docs before guessing parameter names.

## Code conventions

- English for code, identifiers, comments, commits and README. Internal docs in Spanish.
- Type hints everywhere. Small modules with one responsibility, matching `docs/architecture.md` §5.
- Every inter-component message is a `SubtitleEvent`. Changing it requires a spec update and,
  if incompatible, a `schema_version` bump.
- No magic values: models, timings, limits and paths come from `.env`, `sessions.yaml` or glossaries.
- One stage failing must never stop another stage. The ingestion loop must never block.
- Structured JSON logs with `session_id`. At INFO level, never log audio or subtitle text.

## Testing

- Pure functions get pytest tests written first: schema validation, config/`sessions.yaml` parsing,
  glossary merge and filtering, SRT/VTT export.
- Event merge by `(run_id, track, segment_id)` + `revision` lives in the audience page JS in P0 and is
  verified with `scripts/replay_events.py`. It moves to Python with a pytest test in P1, when the
  gateway uses it.
- Gemini and ffmpeg integration is verified with the clips in `samples/audio/` using the
  "Done when" command of each task. Do not mock the Gemini API to fake a passing task.


## Boundaries

**Never:** add Node or a frontend build step; send audio via REST; hardcode keys or model names;
change `SubtitleEvent` without updating the spec; add a dependency not justified in `plan.md`;
start a task that is not in `tasks.md`; delete or rewrite docs in `docs/` or `specs/` without being asked.

**Ask first when:** a requirement is ambiguous, a task needs more than ~30 minutes, the docs conflict,
or an external limit (quota, API behavior) blocks the planned approach.