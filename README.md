# Live Subs

Live Subs provides real-time subtitles and translation for multiple conference stages. An audience member selects a stage and a subtitle track in a browser; original speech appears as partial and final subtitles, while translations are published for final sentences.

## Requirements

- Docker with the Compose plugin.
- A Gemini API key with access to the models configured below, and network access for the worker to call Gemini.

## Quickstart

From the repository root:

```bash
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env` to your Gemini API key. Keep this file private; only the worker service receives the key. Then start the stack:

```bash
docker compose up --build
```

Open <http://localhost:8000/>. The default `sessions.yaml` starts two looping sample talks: `sala1` (English with Spanish translation) and `sala2` (Spanish with English translation). Select a stage and its original or translated track in the audience page.

## Architecture

![Live Subs solution architecture](docs/architecture.svg)

The worker reads each stage's file or stream through ffmpeg, sends continuous PCM audio to Gemini Live for transcription, and translates final sentences with Gemini Flash. It publishes subtitle events through Redis. The FastAPI gateway serves the audience page and delivers the selected stage and track over WebSocket. See the [detailed architecture](docs/architecture.md) for design and data-flow details.

## Configuration

The worker reads its settings from `.env`. These model settings are provided in `.env.example`; edit them in `.env` before starting the stack:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRANSCRIBE_MODEL` | `gemini-3.5-transcribe-live` | Live audio transcription |
| `TRANSLATE_MODEL` | `gemini-3.5-flash-lite` | Translation of final sentences |
| `TRANSLATE_THINKING_LEVEL` | `MINIMAL` | Translation model's thinking level |

The documented translation alternative is `TRANSLATE_MODEL=gemini-3.8-flash` with `TRANSLATE_THINKING_LEVEL=LOW`; change both settings together. The transcription model can be changed through `TRANSCRIBE_MODEL`. The worker receives these values when its container is created, so recreate it after changing `.env`.

Edit [`sessions.yaml`](sessions.yaml) to add or change stages. Each session has a unique `id`, `name`, `title`, `source` (`type` and `uri`), `source_language`, and `target_languages`. Supported sources are `file` and `stream`; file paths are relative to `sessions.yaml`. For a file, `source.loop: true` repeats the talk after it ends; omit it or set it to `false` for a single run. `loop` is not valid for streams. The current configuration contains the two sample stages described above. The Docker image copies `sessions.yaml`, so rebuild the image after editing it for a Compose deployment.

## Scaling stages

A stage is the unit of scale: each stage has its own audio stream and Live transcription session. With an empty `WORKER_SESSIONS` value, the worker serves every stage in `sessions.yaml`. To grow from the two sample stages to 100, add the stage definitions and run, for example, 10 workers with 10 distinct stage IDs assigned to each via its comma-separated `WORKER_SESSIONS` value. Point all workers at the same Redis instance. Gateways are separate from audio processing; run multiple gateway instances behind a load balancer as audience traffic grows.

Each additional target language adds one text translation call per final sentence, rather than another audio session. Capacity and cost depend on your Gemini project's concurrent-session and token quotas; check those limits before scaling.

## Sample audio and license

The included English and Spanish OGG/Opus clips are synthetic, generated from the accompanying talk scripts with Gemini TTS. Their model, voices, generation date, and script provenance are recorded in the [sample audio README](samples/audio/README.md).

Live Subs and its sample audio are distributed under the [Apache License 2.0](LICENSE).
