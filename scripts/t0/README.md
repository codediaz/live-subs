# T0 — technical probe (throwaway)

Probes for task T001 in `specs/001-subs-mvp/tasks.md`. Results go to
`specs/001-subs-mvp/research.md` ("Resultados de T0"). Not part of the product: no tests, not copied
into the Docker image. Raw output goes to `scripts/t0/out/` (git-ignored). Time box: 60 min.

## Prerequisites (T000)

- A 2–3 min clip of a real Nerdearla talk in English in `samples/local/` (git-ignored).
- `ffmpeg` on the PATH.
- `GEMINI_API_KEY` exported in the shell.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install google-genai==2.25.0
```

## Steps

```bash
# 1. Transcription timing, one session (also checks utterance offsets)
python scripts/t0/live_probe.py samples/local/<clip> --lang en --seconds 180

# 2. Two concurrent sessions (quota check)
python scripts/t0/live_probe.py samples/local/<clip> --lang en --seconds 60 --sessions 2

# 3. Translators on the same 10 finals from step 1
python scripts/t0/translate_probe.py scripts/t0/out/live_<ts>_verbatim_s1.jsonl \
  --title "<talk title>" --source en --target es --count 10

# 4. Optional, if time is left: SMART vs VERBATIM
python scripts/t0/live_probe.py samples/local/<clip> --lang en --seconds 180 --mode SMART
```

Re-run the analysis without calling the API, optionally against a hand-made reference
(`end_s,text` CSV with sentence end times in seconds from the clip start):

```bash
python scripts/t0/live_probe.py --analyze scripts/t0/out/live_<ts>_verbatim_s1.jsonl --reference ref.csv
```

## Reading the output

- `*.summary.json`:
  - `partial_latency_ms`: voice onset → first partial;
  - `final_latency_ms`: end of the voiced run (≥ 300 ms of silence after it) → final;
  - `utterance_offsets_found`: whether the Live API returned timing fields (R4);
  - `errors`: failed sessions (the quota check fails here).
- `*_translate_en-es.csv`: per-model timings. Fill `quality_1_5` and `term_errors` by hand for the
  10 sentences.
