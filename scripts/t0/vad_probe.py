"""T0 probe: how often the Live API closes a sentence (final) under four activity-detection variants.

Throwaway script, like the rest of scripts/t0: no tests, not copied into the Docker image.
Each variant streams the same first N seconds of the clip at real time to its own Live session,
one variant after the other, and counts finals.

Variants:
    a  current worker config (server VAD defaults)
    b  automatic activity detection with END_SENSITIVITY_HIGH and silence_duration_ms=300
    c  current config plus audio_stream_end every 6 s, without pausing the audio stream
    d  variant b plus audio_stream_end only when the open sentence exceeds 8 s

Usage:
    python scripts/t0/vad_probe.py samples/audio/charla_es.ogg --lang es --seconds 90
    python scripts/t0/vad_probe.py <clip> --variants b c
    python scripts/t0/vad_probe.py <clip> --variants d --max-open-ms 8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
MIME_TYPE = f"audio/pcm;rate={SAMPLE_RATE}"
OUT_DIR = Path(__file__).parent / "out"
VARIANTS = ("a", "b", "c", "d")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def decode_pcm(clip: str, seconds: float) -> bytes:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", clip, "-t", str(seconds),
           "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def live_config(variant: str, lang: str, silence_ms: int) -> types.LiveConnectConfig:
    transcription = types.AudioTranscriptionConfig(
        language_codes=[lang], mode=types.AudioTranscriptionConfigMode.VERBATIM
    )
    if variant in ("b", "d"):
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.TEXT],
            input_audio_transcription=transcription,
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=silence_ms,
                )
            ),
        )
    return types.LiveConnectConfig(response_modalities=[types.Modality.TEXT], input_audio_transcription=transcription)


async def run_variant(
    client: genai.Client, args: argparse.Namespace, variant: str, pcm: bytes, log: list[dict[str, Any]]
) -> None:
    chunk_bytes = SAMPLE_RATE * BYTES_PER_SAMPLE * args.chunk_ms // 1000
    stream_end_every = args.stream_end_ms // args.chunk_ms if variant == "c" else 0

    async with client.aio.live.connect(model=args.model, config=live_config(variant, args.lang, args.silence_ms)) as session:
        started = now_ms()
        log.append({"kind": "start", "at_ms": started})
        # Variant d: when the open sentence started (first interim after the last final) and when
        # it was last flushed; the sender flushes again if it stays open another max_open_ms.
        open_since: int | None = None
        last_flush: int | None = None

        def sentence_too_long() -> bool:
            if variant != "d" or open_since is None:
                return False
            return now_ms() - max(open_since, last_flush or 0) >= args.max_open_ms

        async def send() -> None:
            nonlocal last_flush
            silence = bytes(chunk_bytes)
            chunks = [pcm[i : i + chunk_bytes] for i in range(0, len(pcm), chunk_bytes)]
            chunks += [silence] * (args.tail_ms // args.chunk_ms)
            for index, chunk in enumerate(chunks, start=1):
                await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=MIME_TYPE))
                if stream_end_every and index % stream_end_every == 0:
                    await session.send_realtime_input(audio_stream_end=True)
                    log.append({"kind": "stream_end", "at_ms": now_ms()})
                if sentence_too_long():
                    await session.send_realtime_input(audio_stream_end=True)
                    last_flush = now_ms()
                    log.append({"kind": "stream_end", "at_ms": last_flush})
                # Absolute pacing keeps real time even if a send is slow.
                await asyncio.sleep(max(0.0, (started + index * args.chunk_ms - now_ms()) / 1000))

        async def receive() -> None:
            nonlocal open_since, last_flush
            while True:
                async for message in session.receive():
                    content = message.server_content
                    if content is None:
                        continue
                    for kind, item in (("interim", content.interim_input_transcription), ("final", content.input_transcription)):
                        if item is not None and item.text:
                            log.append({"kind": kind, "at_ms": now_ms(), "text": item.text})
                            if kind == "final":
                                open_since = last_flush = None
                            elif open_since is None:
                                open_since = now_ms()

        receiver = asyncio.create_task(receive())
        try:
            await send()
            await asyncio.sleep(args.wait_ms / 1000)
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            log.append({"kind": "end", "at_ms": now_ms()})


def summarize(variant: str, log: list[dict[str, Any]], audio_s: float) -> dict[str, Any]:
    """Sentence duration = first interim of the sentence -> its final (time the sentence stays open)."""
    start = next((r["at_ms"] for r in log if r["kind"] == "start"), None)
    finals: list[dict[str, Any]] = []
    durations: list[int] = []
    opened_at: int | None = None
    for record in log:
        if record["kind"] == "interim" and opened_at is None:
            opened_at = record["at_ms"]
        elif record["kind"] == "final":
            finals.append(record)
            if opened_at is not None:
                durations.append(record["at_ms"] - opened_at)
            opened_at = None
    marks = [start] + [f["at_ms"] for f in finals] if start is not None else []
    gaps = [b - a for a, b in zip(marks, marks[1:])]
    words = [len(f["text"].split()) for f in finals]
    return {
        "variant": variant,
        "error": next((r["error"] for r in log if r["kind"] == "error"), None),
        "interims": sum(1 for r in log if r["kind"] == "interim"),
        "finals": len(finals),
        "finals_per_min": round(len(finals) / (audio_s / 60), 2),
        "mean_sentence_s": round(sum(durations) / len(durations) / 1000, 2) if durations else None,
        "punctuated": f"{sum(f['text'].strip()[-1:] in '.?!' for f in finals)}/{len(finals)}",
        "mean_words": round(sum(words) / len(words), 1) if words else None,
        "max_gap_between_finals_s": round(max(gaps) / 1000, 1) if gaps else None,
        "stream_ends_sent": sum(1 for r in log if r["kind"] == "stream_end"),
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    columns = ["variant", "finals", "finals_per_min", "mean_sentence_s", "mean_words", "punctuated",
               "max_gap_between_finals_s", "interims", "stream_ends_sent", "error"]
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in columns}
    print(" | ".join(c.ljust(widths[c]) for c in columns))
    print("-|-".join("-" * widths[c] for c in columns))
    for row in rows:
        print(" | ".join(str(row[c]).ljust(widths[c]) for c in columns))


async def main_async(args: argparse.Namespace) -> None:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    pcm = decode_pcm(args.clip, args.seconds)
    audio_s = len(pcm) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for variant in args.variants:
        log: list[dict[str, Any]] = []
        print(f"variant {variant}: streaming {audio_s:.0f} s ...", flush=True)
        try:
            await run_variant(client, args, variant, pcm, log)
        except Exception as exc:  # noqa: BLE001 - a probe records every failure
            log.append({"kind": "error", "at_ms": now_ms(), "error": f"{type(exc).__name__}: {exc}"})
        (OUT_DIR / f"vad_{stamp}_{variant}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in log), encoding="utf-8"
        )
        rows.append(summarize(variant, log, audio_s))
    (OUT_DIR / f"vad_{stamp}.summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print_table(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clip", help="audio file readable by ffmpeg")
    parser.add_argument("--model", default=os.environ.get("TRANSCRIBE_MODEL", "gemini-3.5-transcribe-live"))
    parser.add_argument("--lang", default="es")
    parser.add_argument("--seconds", type=float, default=90.0, help="audio sent per variant")
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--chunk-ms", type=int, default=int(os.environ.get("AUDIO_CHUNK_MS", "100")))
    parser.add_argument("--silence-ms", type=int, default=300, help="variant b: silence_duration_ms")
    parser.add_argument("--stream-end-ms", type=int, default=6000, help="variant c: audio_stream_end period")
    parser.add_argument("--max-open-ms", type=int, default=8000, help="variant d: flush a sentence open this long")
    parser.add_argument("--tail-ms", type=int, default=2000, help="trailing silence after the clip")
    parser.add_argument("--wait-ms", type=int, default=3000, help="wait for the last final after sending")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
