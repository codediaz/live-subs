"""T0 probe: stream a clip at real time to the Gemini Live API and log transcription timing.

Throwaway script for the technical test described in specs/001-subs-mvp/research.md (T0).
It is not part of the product: no tests, not copied into the Docker image.

Usage:
    python scripts/t0/live_probe.py samples/local/nerdearla_en.mp4 --lang en --seconds 180
    python scripts/t0/live_probe.py <clip> --sessions 2          # two concurrent Live sessions
    python scripts/t0/live_probe.py <clip> --mode SMART          # optional SMART vs VERBATIM
    python scripts/t0/live_probe.py --analyze scripts/t0/out/live_<ts>.jsonl [--reference ref.csv]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import time
from array import array
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
OUT_DIR = Path(__file__).parent / "out"


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def rms(chunk: bytes) -> float:
    """Root mean square of a little-endian s16 PCM chunk."""
    samples = array("h")
    samples.frombytes(chunk[: len(chunk) - len(chunk) % BYTES_PER_SAMPLE])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class JsonlLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("w", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


async def read_pcm(clip: str, chunk_ms: int, seconds: float | None, queues: list[asyncio.Queue], log: JsonlLog) -> None:
    """Decode the clip with ffmpeg at real-time pace and fan out PCM chunks to every session queue."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-i", clip]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
    chunk_bytes = SAMPLE_RATE * BYTES_PER_SAMPLE * chunk_ms // 1000
    position_ms = 0
    assert proc.stdout is not None
    while True:
        try:
            chunk = await proc.stdout.readexactly(chunk_bytes)
        except asyncio.IncompleteReadError as exc:
            chunk = exc.partial
        if not chunk:
            break
        sent_at = now_ms()
        log.write({"kind": "chunk", "pos_ms": position_ms, "sent_at_ms": sent_at, "rms": round(rms(chunk), 1)})
        for queue in queues:
            queue.put_nowait(chunk)
        position_ms += chunk_ms
    code = await proc.wait()
    log.write({"kind": "source_end", "pos_ms": position_ms, "at_ms": now_ms(), "ffmpeg_exit": code})


async def run_session(
    client: genai.Client,
    index: int,
    model: str,
    lang: str,
    mode: str,
    queue: asyncio.Queue,
    source_done: asyncio.Event,
    tail_s: float,
    chunk_ms: int,
    log: JsonlLog,
) -> None:
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.TEXT],
        input_audio_transcription=types.AudioTranscriptionConfig(language_codes=[lang], mode=mode),
    )
    raw_dumped = 0
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            log.write({"kind": "session_open", "session": index, "at_ms": now_ms()})

            async def send() -> None:
                while not (source_done.is_set() and queue.empty()):
                    try:
                        chunk = await asyncio.wait_for(queue.get(), timeout=0.5)
                    except TimeoutError:
                        continue
                    await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={SAMPLE_RATE}"))
                # Trailing silence lets server VAD close the last utterance without audio_stream_end.
                silence = bytes(SAMPLE_RATE * BYTES_PER_SAMPLE * chunk_ms // 1000)
                for _ in range(int(tail_s * 1000 / chunk_ms)):
                    await session.send_realtime_input(audio=types.Blob(data=silence, mime_type=f"audio/pcm;rate={SAMPLE_RATE}"))
                    await asyncio.sleep(chunk_ms / 1000)

            async def receive() -> None:
                nonlocal raw_dumped
                while True:
                    async for message in session.receive():
                        content = message.server_content
                        if content is None:
                            continue
                        for kind, transcription in (
                            ("interim", content.interim_input_transcription),
                            ("final", content.input_transcription),
                        ):
                            if transcription is None or not transcription.text:
                                continue
                            extra = transcription.model_dump(mode="json", exclude_none=True)
                            extra.pop("text", None)
                            log.write(
                                {
                                    "kind": kind,
                                    "session": index,
                                    "recv_ms": now_ms(),
                                    "text": transcription.text,
                                    "extra": extra,
                                }
                            )
                        if raw_dumped < 5:
                            raw_dumped += 1
                            log.write({"kind": "raw", "session": index, "message": message.model_dump(mode="json", exclude_none=True)})

            receiver = asyncio.create_task(receive())
            await send()
            await asyncio.sleep(3)
            receiver.cancel()
            log.write({"kind": "session_close", "session": index, "at_ms": now_ms()})
    except Exception as exc:  # noqa: BLE001 - a probe records every failure
        log.write({"kind": "error", "session": index, "at_ms": now_ms(), "error": f"{type(exc).__name__}: {exc}"})


async def probe(args: argparse.Namespace) -> Path:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT_DIR / f"live_{stamp}_{args.mode.lower()}_s{args.sessions}.jsonl"
    log = JsonlLog(path)
    log.write({"kind": "meta", "clip": args.clip, "model": args.model, "lang": args.lang, "mode": args.mode, "sessions": args.sessions, "chunk_ms": args.chunk_ms, "start_ms": now_ms()})
    queues: list[asyncio.Queue] = [asyncio.Queue() for _ in range(args.sessions)]
    source_done = asyncio.Event()
    sessions = [
        asyncio.create_task(run_session(client, i, args.model, args.lang, args.mode, queues[i], source_done, args.tail, args.chunk_ms, log))
        for i in range(args.sessions)
    ]
    await asyncio.sleep(1)  # let the sessions open before audio starts
    await read_pcm(args.clip, args.chunk_ms, args.seconds, queues, log)
    source_done.set()
    await asyncio.gather(*sessions)
    log.close()
    return path


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[rank]


def speech_ends(chunks: list[dict], threshold: float, min_gap_ms: int) -> list[int]:
    """sent_at_ms of the last voiced chunk of each voiced run followed by at least min_gap_ms of silence."""
    ends: list[int] = []
    last_voiced: dict | None = None
    silence_ms = 0
    for chunk in chunks:
        if chunk["rms"] >= threshold:
            last_voiced, silence_ms = chunk, 0
            continue
        if last_voiced is None:
            continue
        silence_ms += chunk.get("chunk_ms", 100)
        if silence_ms >= min_gap_ms:
            ends.append(last_voiced["sent_at_ms"])
            last_voiced = None
    if last_voiced is not None:
        ends.append(last_voiced["sent_at_ms"])
    return ends


def analyze(path: Path, threshold: float, min_gap_ms: int, reference: Path | None) -> dict[str, Any]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    meta = next(r for r in records if r["kind"] == "meta")
    chunks = [dict(r, chunk_ms=meta["chunk_ms"]) for r in records if r["kind"] == "chunk"]
    voiced = [c for c in chunks if c["rms"] >= threshold]
    ends = speech_ends(chunks, threshold, min_gap_ms)
    summary: dict[str, Any] = {
        "file": str(path),
        "mode": meta["mode"],
        "sessions_requested": meta["sessions"],
        "errors": [r["error"] for r in records if r["kind"] == "error"],
        "rms_threshold": threshold,
        "voiced_ratio": round(len(voiced) / len(chunks), 3) if chunks else None,
        "per_session": {},
    }
    extra_keys: set[str] = set()
    for session in range(meta["sessions"]):
        events = [r for r in records if r.get("session") == session and r["kind"] in ("interim", "final")]
        for event in events:
            extra_keys.update(event["extra"].keys())
        partial_lat: list[int] = []
        final_lat: list[int] = []
        segment_open = False
        previous_end = 0
        finals = 0
        for event in events:
            if event["kind"] == "interim" and not segment_open:
                segment_open = True
                onset = next((c["sent_at_ms"] for c in voiced if c["sent_at_ms"] > previous_end), None)
                if onset is not None and onset <= event["recv_ms"]:
                    partial_lat.append(event["recv_ms"] - onset)
            if event["kind"] == "final":
                finals += 1
                segment_open = False
                end = max((e for e in ends if e <= event["recv_ms"]), default=None)
                if end is not None:
                    final_lat.append(event["recv_ms"] - end)
                    previous_end = end
        summary["per_session"][session] = {
            "interims": sum(1 for e in events if e["kind"] == "interim"),
            "finals": finals,
            "partial_latency_ms": {"p50": percentile(partial_lat, 50), "p95": percentile(partial_lat, 95), "n": len(partial_lat)},
            "final_latency_ms": {"p50": percentile(final_lat, 50), "p95": percentile(final_lat, 95), "n": len(final_lat)},
        }
    summary["transcription_extra_fields"] = sorted(extra_keys)
    summary["utterance_offsets_found"] = any(k in extra_keys for k in ("words", "start_offset", "end_offset"))
    if reference:
        summary["final_latency_vs_reference_ms"] = reference_latency(records, meta, reference)
    return summary


def reference_latency(records: list[dict], meta: dict, reference: Path) -> dict[str, Any]:
    """Match each reference sentence end (seconds from clip start) to the next final of session 0."""
    first_chunk = next(r for r in records if r["kind"] == "chunk")
    finals = [r for r in records if r["kind"] == "final" and r["session"] == 0]
    latencies: list[int] = []
    with reference.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            end_at = first_chunk["sent_at_ms"] + int(float(row["end_s"]) * 1000)
            match = next((f for f in finals if f["recv_ms"] >= end_at), None)
            if match and match["recv_ms"] - end_at < 15_000:
                latencies.append(match["recv_ms"] - end_at)
    return {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95), "n": len(latencies)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clip", nargs="?", help="audio/video file readable by ffmpeg")
    parser.add_argument("--model", default=os.environ.get("TRANSCRIBE_MODEL", "gemini-3.5-transcribe-live"))
    parser.add_argument("--lang", default="en")
    parser.add_argument("--mode", default="VERBATIM", choices=["VERBATIM", "SMART"])
    parser.add_argument("--sessions", type=int, default=1, help="concurrent Live sessions fed with the same audio")
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--seconds", type=float, help="only send the first N seconds of the clip")
    parser.add_argument("--tail", type=float, default=2.0, help="seconds of trailing silence after the clip")
    parser.add_argument("--analyze", type=Path, help="analyze an existing JSONL log instead of probing")
    parser.add_argument("--rms-threshold", type=float, default=500.0)
    parser.add_argument("--min-gap-ms", type=int, default=300, help="silence that closes a voiced run")
    parser.add_argument("--reference", type=Path, help="CSV with columns end_s,text (sentence ends in seconds)")
    args = parser.parse_args()

    path = args.analyze
    if path is None:
        if not args.clip:
            parser.error("clip is required unless --analyze is given")
        path = asyncio.run(probe(args))
        print(f"log: {path}")
    summary = analyze(path, args.rms_threshold, args.min_gap_ms, args.reference)
    summary_path = path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
