"""T0 probe: translate the same final sentences with several models and thinking levels.

Throwaway script for the technical test described in specs/001-subs-mvp/research.md (T0).
It reads the finals logged by live_probe.py, translates N of them with each model, and writes a CSV
with timings plus empty columns for the manual quality score (1-5) and term errors.

Usage:
    python scripts/t0/translate_probe.py scripts/t0/out/live_<ts>.jsonl --title "Talk title" \
        --source en --target es --count 10
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from pathlib import Path

from google import genai
from google.genai import types

DEFAULT_MODELS = "gemini-3.8-flash:LOW,gemini-3.5-flash-lite:MINIMAL"
LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese"}


def load_finals(path: Path, min_words: int) -> list[str]:
    finals = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("kind") == "final" and record.get("session") == 0:
            finals.append(record["text"].strip())
    return [text for text in finals if len(text.split()) >= min_words]


def system_instruction(source: str, target: str) -> str:
    return (
        f"You translate live conference subtitles from {LANGUAGE_NAMES[source]} to {LANGUAGE_NAMES[target]}. "
        "Return only the translation of the sentence, with no quotes, notes or explanations. "
        "Keep product names, code identifiers and technical terms that are usually left untranslated."
    )


def user_prompt(title: str, context: list[str], sentence: str) -> str:
    previous = "\n".join(context) if context else "(none)"
    return f"Talk title: {title}\nPrevious sentences (context only, do not translate):\n{previous}\n\nSentence to translate:\n{sentence}"


def percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("live_log", type=Path, help="JSONL written by live_probe.py")
    parser.add_argument("--title", required=True, help="talk title, sent as context")
    parser.add_argument("--source", default="en", choices=sorted(LANGUAGE_NAMES))
    parser.add_argument("--target", default="es", choices=sorted(LANGUAGE_NAMES))
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--min-words", type=int, default=4)
    parser.add_argument("--context", type=int, default=3, help="previous finals sent as context")
    parser.add_argument("--models", default=DEFAULT_MODELS, help="comma-separated model:THINKING_LEVEL pairs")
    args = parser.parse_args()

    finals = load_finals(args.live_log, args.min_words)
    sentences = finals[: args.count]
    if len(sentences) < args.count:
        print(f"warning: only {len(sentences)} finals with >= {args.min_words} words")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    out_path = args.live_log.with_name(args.live_log.stem + f"_translate_{args.source}-{args.target}.csv")
    rows = []
    timings: dict[str, list[int]] = {}
    for pair in args.models.split(","):
        model, level = pair.split(":")
        key = f"{model}:{level}"
        timings[key] = []
        config = types.GenerateContentConfig(
            system_instruction=system_instruction(args.source, args.target),
            thinking_config=types.ThinkingConfig(thinking_level=level, include_thoughts=False),
        )
        for index, sentence in enumerate(sentences):
            context = sentences[max(0, index - args.context) : index]
            started = time.perf_counter()
            error = ""
            translation = ""
            try:
                response = client.models.generate_content(
                    model=model, contents=user_prompt(args.title, context, sentence), config=config
                )
                translation = (response.text or "").strip()
            except Exception as exc:  # noqa: BLE001 - a probe records every failure
                error = f"{type(exc).__name__}: {exc}"
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            if not error:
                timings[key].append(elapsed_ms)
            rows.append(
                {
                    "idx": index,
                    "model": model,
                    "thinking_level": level,
                    "source": sentence,
                    "translation": translation,
                    "ms": elapsed_ms,
                    "error": error,
                    "quality_1_5": "",
                    "term_errors": "",
                }
            )
            print(f"[{key}] {index}: {elapsed_ms} ms {'ERROR ' + error if error else ''}")

    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["idx"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\ncsv: {out_path}")
    for key, values in timings.items():
        print(f"{key}: p50={percentile(values, 50)} ms p95={percentile(values, 95)} ms n={len(values)}")


if __name__ == "__main__":
    main()
