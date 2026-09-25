"""Small real-ffmpeg checks for T019 ingestion behavior."""

import asyncio
from pathlib import Path

import pytest

from subs.common.config import SourceConfig
from subs.common.queues import DropOldestQueue
from subs.worker.ingest import IngestError, ingest_audio


CLIP = Path(__file__).resolve().parents[1] / "samples/audio/charla_en.ogg"


def test_file_ingest_drops_oldest_chunks_when_queue_fills(caplog: pytest.LogCaptureFixture) -> None:
    queue: DropOldestQueue[bytes] = DropOldestQueue(1)
    count = asyncio.run(
        ingest_audio(
            SourceConfig(type="file", uri=str(CLIP)),
            queue,
            chunk_ms=100,
            session_id="sala1",
            seconds=0.3,
        )
    )

    assert count == 3
    assert queue.qsize() == 1
    assert queue.dropped == 2
    assert len(asyncio.run(queue.get())) == 3200
    assert [record.dropped_chunks for record in caplog.records] == [1, 2]
    assert all(record.session_id == "sala1" for record in caplog.records)


def test_nonzero_ffmpeg_exit_is_an_ingest_failure(tmp_path: Path) -> None:
    queue: DropOldestQueue[bytes] = DropOldestQueue(2)
    missing_file = tmp_path / "missing.ogg"

    with pytest.raises(IngestError, match="ffmpeg exited with status"):
        asyncio.run(
            ingest_audio(
                SourceConfig(type="file", uri=str(missing_file)),
                queue,
                chunk_ms=100,
                session_id="sala1",
            )
        )
