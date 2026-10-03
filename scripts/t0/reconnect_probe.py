"""Throwaway T0R probe for sequential Gemini Live openings and client-initiated handovers.

Run with ``.venv/bin/python scripts/t0/reconnect_probe.py``. Raw JSONL is written to
``scripts/t0/out/``; this module is not part of the product or Docker image.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from array import array
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from subs.common.config import WorkerSettings


ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "samples/audio/charla_en.ogg"
REFERENCE = ROOT / "samples/audio/charla_en.txt"
OUT = Path(__file__).parent / "out"
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
HANDOVER_POSITIONS_MS = (60_000, 120_000)
OPEN_TIMEOUT_S = 10
TAIL_S = 3


def wall_ms() -> int:
    return time.time_ns() // 1_000_000


def elapsed_ms(start_ns: int) -> float:
    return round((time.perf_counter_ns() - start_ns) / 1_000_000, 3)


def load_env() -> dict[str, str]:
    """Read local .env without putting the credential in logs or command arguments."""
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    values.update(os.environ)
    return values


class RawLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.file = path.open("w", encoding="utf-8", buffering=1)

    def write(self, kind: str, **fields: Any) -> None:
        self.file.write(json.dumps({"kind": kind, "at_ms": wall_ms(), **fields}, ensure_ascii=False) + "\n")

    def close(self) -> None:
        self.file.close()


@dataclass
class Connection:
    number: int
    context: Any
    session: Any
    receiver: asyncio.Task[None] | None = None
    cut: bool = False
    open_since_ms: int | None = None
    last_cut_ms: int | None = None


def live_config(settings: WorkerSettings) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.TEXT],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=["en"],
            custom_vocabulary=settings.transcribe_vocabulary,
            mode=types.AudioTranscriptionConfigMode.VERBATIM,
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                end_of_speech_sensitivity=types.EndSensitivity[f"END_SENSITIVITY_{settings.vad_end_sensitivity}"],
                silence_duration_ms=settings.vad_silence_ms,
            )
        ),
    )


async def open_connection(
    client: genai.Client, model: str, config: types.LiveConnectConfig, number: int, log: RawLog
) -> Connection | None:
    context = client.aio.live.connect(model=model, config=config)
    started_ns = time.perf_counter_ns()
    log.write("open_start", connection=number)
    try:
        session = await asyncio.wait_for(context.__aenter__(), timeout=OPEN_TIMEOUT_S)
    except Exception as exc:  # A probe must retain unsuccessful attempts.
        log.write("open_failed", connection=number, elapsed_ms=elapsed_ms(started_ns), error=f"{type(exc).__name__}: {exc}")
        return None
    log.write("open_ready", connection=number, elapsed_ms=elapsed_ms(started_ns))
    return Connection(number, context, session)


async def close_connection(connection: Connection, log: RawLog) -> None:
    started_ns = time.perf_counter_ns()
    try:
        await connection.context.__aexit__(None, None, None)
        log.write("close_done", connection=connection.number, elapsed_ms=elapsed_ms(started_ns))
    except Exception as exc:
        log.write("close_failed", connection=connection.number, elapsed_ms=elapsed_ms(started_ns), error=f"{type(exc).__name__}: {exc}")
    if connection.receiver is not None:
        connection.receiver.cancel()
        try:
            await connection.receiver
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.write("receiver_error", connection=connection.number, error=f"{type(exc).__name__}: {exc}")


async def receive(connection: Connection, log: RawLog) -> None:
    try:
        while True:
            async for message in connection.session.receive():
                if message.go_away is not None:
                    log.write("go_away", connection=connection.number, time_left=str(message.go_away.time_left))
                content = message.server_content
                if content is None:
                    continue
                for kind, item in (("partial", content.interim_input_transcription), ("final", content.input_transcription)):
                    if item is None or not item.text:
                        continue
                    if not connection.cut:
                        if kind == "partial" and connection.open_since_ms is None:
                            connection.open_since_ms = wall_ms()
                        elif kind == "final":
                            connection.open_since_ms = None
                            connection.last_cut_ms = None
                    log.write(
                        "late_result" if connection.cut else kind,
                        connection=connection.number,
                        result_kind=kind,
                        text=item.text,
                        extra=item.model_dump(mode="json", exclude_none=True, exclude={"text"}),
                    )
            log.write("receive_cycle_end", connection=connection.number, cut=connection.cut)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.write("receive_failed", connection=connection.number, cut=connection.cut, error=f"{type(exc).__name__}: {exc}")


def rms(chunk: bytes) -> float:
    samples = array("h")
    samples.frombytes(chunk[: len(chunk) - len(chunk) % BYTES_PER_SAMPLE])
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5 if samples else 0.0


async def ten_openings(client: genai.Client, model: str, config: types.LiveConnectConfig, log: RawLog) -> None:
    for number in range(1, 11):
        connection = await open_connection(client, model, config, number, log)
        if connection is not None:
            await close_connection(connection, log)


async def handovers(client: genai.Client, settings: WorkerSettings, config: types.LiveConnectConfig, log: RawLog) -> None:
    connection = await open_connection(client, settings.transcribe_model, config, 11, log)
    if connection is None:
        log.write("handover_aborted", reason="initial_connection_failed")
        return
    connection.receiver = asyncio.create_task(receive(connection, log))
    chunk_ms = settings.audio_chunk_ms
    chunk_bytes = SAMPLE_RATE * BYTES_PER_SAMPLE * chunk_ms // 1000
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-i", str(CLIP),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-acodec", "pcm_s16le", "-f", "s16le", "pipe:1",
    ]
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    assert process.stdout is not None
    position_ms = 0
    handover_index = 0
    pending: asyncio.Task[Connection | None] | None = None
    cut_at_ms: int | None = None
    gap_ms = 0

    async def replace(old: Connection, new_number: int) -> Connection | None:
        await close_connection(old, log)
        return await open_connection(client, settings.transcribe_model, config, new_number, log)

    try:
        while True:
            try:
                chunk = await process.stdout.readexactly(chunk_bytes)
            except asyncio.IncompleteReadError as exc:
                chunk = exc.partial
            if not chunk:
                break
            if pending is not None and pending.done():
                new_connection = pending.result()
                pending = None
                if new_connection is None:
                    log.write("handover_failed", handover=handover_index, gap_ms=gap_ms)
                    connection = None
                else:
                    connection = new_connection
                    connection.receiver = asyncio.create_task(receive(connection, log))
                    log.write(
                        "handover_ready", handover=handover_index, connection=connection.number,
                        elapsed_ms=wall_ms() - cut_at_ms if cut_at_ms is not None else None, gap_ms=gap_ms,
                    )
                cut_at_ms = None
            if handover_index < len(HANDOVER_POSITIONS_MS) and position_ms >= HANDOVER_POSITIONS_MS[handover_index]:
                handover_index += 1
                if connection is not None:
                    connection.cut = True
                    cut_at_ms = wall_ms()
                    gap_ms = 0
                    log.write("handover_cut", handover=handover_index, old_connection=connection.number, position_ms=position_ms)
                    pending = asyncio.create_task(replace(connection, 11 + handover_index))
                    connection = None
            voice_rms = rms(chunk)
            if connection is None:
                gap_ms += chunk_ms
                log.write("audio_block", position_ms=position_ms, action="discard", rms=round(voice_rms, 1), chunk_ms=chunk_ms)
            else:
                sent_at_ms = wall_ms()
                try:
                    await connection.session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={SAMPLE_RATE}"))
                    log.write(
                        "audio_block", position_ms=position_ms, action="sent", connection=connection.number,
                        sent_at_ms=sent_at_ms, rms=round(voice_rms, 1), chunk_ms=chunk_ms,
                    )
                    open_since_ms = connection.open_since_ms
                    last_cut_ms = connection.last_cut_ms
                    cut_reference_ms = open_since_ms if last_cut_ms is None else last_cut_ms
                    if cut_reference_ms is not None and wall_ms() - cut_reference_ms >= settings.max_segment_ms:
                        await connection.session.send_realtime_input(audio_stream_end=True)
                        connection.last_cut_ms = wall_ms()
                        log.write("forced_cut", connection=connection.number, position_ms=position_ms)
                except Exception as exc:
                    log.write("send_failed", connection=connection.number, error=f"{type(exc).__name__}: {exc}")
                    connection.cut = True
                    cut_at_ms = wall_ms()
                    pending = asyncio.create_task(replace(connection, 12 + handover_index))
                    connection = None
            position_ms += chunk_ms
        exit_code = await process.wait()
        log.write("source_end", position_ms=position_ms, ffmpeg_exit=exit_code)
        if pending is not None:
            connection = pending.result() if pending.done() else await pending
            if connection is not None:
                connection.receiver = asyncio.create_task(receive(connection, log))
                log.write("handover_ready", handover=handover_index, connection=connection.number, elapsed_ms=wall_ms() - cut_at_ms if cut_at_ms else None, gap_ms=gap_ms)
        if connection is not None:
            await asyncio.sleep(TAIL_S)
            await close_connection(connection, log)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, int((percentile * len(ordered) + 99) // 100) - 1)]


def summarize(path: Path, settings: WorkerSettings) -> dict[str, Any]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    opens = [r["elapsed_ms"] for r in records if r["kind"] == "open_ready" and r["connection"] <= 10]
    closes = [r["elapsed_ms"] for r in records if r["kind"] == "close_done" and r["connection"] <= 10]
    handovers_done = [r for r in records if r["kind"] == "handover_ready"]
    reference = REFERENCE.read_text(encoding="utf-8")
    finals = [r for r in records if r["kind"] == "final"]
    transcript = " ".join(r["text"] for r in finals)
    first_after: list[dict[str, Any]] = []
    for handover in handovers_done:
        number = handover["connection"]
        first_partial = next((r for r in records if r["kind"] == "partial" and r.get("connection") == number), None)
        first_final = next((r for r in records if r["kind"] == "final" and r.get("connection") == number), None)
        forced_cut = next(
            (r for r in reversed(records) if r["kind"] == "forced_cut" and r.get("connection") == number
             and first_final is not None and r["at_ms"] <= first_final["at_ms"]),
            None,
        )
        voiced = [
            r for r in records if r["kind"] == "audio_block" and r.get("connection") == number
            and r["action"] == "sent" and r["rms"] > settings.voice_rms_threshold
            and first_final is not None and r["sent_at_ms"] <= first_final["at_ms"]
            and (forced_cut is None or r["position_ms"] <= forced_cut["position_ms"])
        ]
        # For a forced final, the sentence ends at the cut, not at later audio still being streamed.
        # Keep the result unmeasured when no cut gives a reliable phrase boundary in this probe.
        end_block = voiced[-1] if voiced else None
        first_after.append({
            "handover": handover["handover"], "connection": number,
            "first_partial_after_ready_ms": None if first_partial is None else first_partial["at_ms"] - handover["at_ms"],
            "first_final_after_ready_ms": None if first_final is None else first_final["at_ms"] - handover["at_ms"],
            "first_final_latency_ms": None if first_final is None or end_block is None or forced_cut is None else first_final["at_ms"] - end_block["sent_at_ms"],
            "latency_reference": "last_voiced_block_at_or_before_forced_cut" if forced_cut is not None else None,
            "voice_end_position_ms": None if end_block is None else end_block["position_ms"],
            "first_final_text": None if first_final is None else first_final["text"],
        })
    return {
        "raw_file": str(path), "open_success_count": len(opens), "open_p50_ms": statistics.median(opens) if opens else None,
        "open_p95_ms": nearest_rank(opens, 95), "open_max_ms": max(opens, default=None),
        "close_ms": closes, "handovers": handovers_done, "first_after_handover": first_after,
        "late_results": [r for r in records if r["kind"] == "late_result"],
        "all_finals_by_connection": {str(n): [r["text"] for r in finals if r["connection"] == n] for n in (11, 12, 13)},
        "reference_similarity_ratio": round(SequenceMatcher(None, reference.lower(), transcript.lower()).ratio(), 3) if transcript else None,
        "failures": [r for r in records if r["kind"] in ("open_failed", "close_failed", "receive_failed", "send_failed", "handover_failed", "handover_aborted")],
    }


async def main() -> None:
    env = load_env()
    settings = WorkerSettings.from_env(env)
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    raw_path = OUT / f"reconnect_{stamp}.jsonl"
    summary_path = OUT / f"reconnect_{stamp}.summary.json"
    log = RawLog(raw_path)
    log.write(
        "meta", clip=str(CLIP.relative_to(ROOT)), reference=str(REFERENCE.relative_to(ROOT)),
        model=settings.transcribe_model, source_language="en", vocabulary=settings.transcribe_vocabulary,
        mode="VERBATIM", vad_end_sensitivity=settings.vad_end_sensitivity,
        vad_silence_ms=settings.vad_silence_ms, audio_chunk_ms=settings.audio_chunk_ms,
        max_segment_ms=settings.max_segment_ms,
        voice_rms_threshold=settings.voice_rms_threshold, handover_positions_ms=HANDOVER_POSITIONS_MS,
        open_timeout_s=OPEN_TIMEOUT_S,
    )
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        config = live_config(settings)
        await ten_openings(client, settings.transcribe_model, config, log)
        await handovers(client, settings, config, log)
    finally:
        log.close()
    summary = summarize(raw_path, settings)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"raw_file": str(raw_path), "summary_file": str(summary_path), "open_success_count": summary["open_success_count"], "handovers": len(summary["handovers"]), "failures": len(summary["failures"])}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
