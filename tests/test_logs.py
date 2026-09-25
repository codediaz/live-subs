"""Tests for structured JSON logs (RF-034, constitution principle 14)."""

import io
import json
import logging

import pytest

from subs.common.logs import JsonFormatter, setup_logging


@pytest.fixture
def capture():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.logs")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    def records() -> list[dict]:
        return [json.loads(line) for line in stream.getvalue().splitlines()]

    yield logger, records
    logger.handlers = []


def test_record_is_json_with_level_msg_and_session_id(capture):
    logger, records = capture
    logger.info("session started", extra={"session_id": "sala1"})
    [record] = records()
    assert record["level"] == "INFO"
    assert record["msg"] == "session started"
    assert record["session_id"] == "sala1"
    assert record["logger"] == "test.logs"
    assert "ts" in record


def test_session_id_is_present_even_when_missing(capture):
    logger, records = capture
    logger.info("gateway ready")
    assert records()[0]["session_id"] is None


def test_message_arguments_are_formatted(capture):
    logger, records = capture
    logger.info("dropped %d chunks", 3, extra={"session_id": "sala1"})
    assert records()[0]["msg"] == "dropped 3 chunks"


def test_extra_metrics_are_kept(capture):
    logger, records = capture
    logger.info("final published", extra={"session_id": "sala1", "segment_id": 4, "latency_ms": 1700})
    record = records()[0]
    assert record["segment_id"] == 4
    assert record["latency_ms"] == 1700


@pytest.mark.parametrize("level", [logging.INFO, logging.WARNING, logging.ERROR])
def test_info_and_above_never_include_text_or_audio(capture, level):
    logger, records = capture
    logger.log(level, "event", extra={"session_id": "sala1", "text": "Bienvenidos a Nerdearla", "audio": b"\x00\x01"})
    output = json.dumps(records()[0])
    assert "text" not in records()[0]
    assert "audio" not in records()[0]
    assert "Bienvenidos" not in output


def test_debug_may_include_text_but_never_audio(capture):
    logger, records = capture
    logger.debug("partial", extra={"session_id": "sala1", "text": "hello", "audio": b"\x00\x01"})
    record = records()[0]
    assert record["text"] == "hello"
    assert "audio" not in record


def test_exception_is_included(capture):
    logger, records = capture
    try:
        raise RuntimeError("ffmpeg exited with 1")
    except RuntimeError:
        logger.exception("source failed", extra={"session_id": "sala2"})
    record = records()[0]
    assert record["level"] == "ERROR"
    assert "RuntimeError: ffmpeg exited with 1" in record["exc"]


def test_non_serializable_values_do_not_break_logging(capture):
    logger, records = capture
    logger.info("odd value", extra={"session_id": "sala1", "path": object()})
    assert records()[0]["msg"] == "odd value"


@pytest.fixture
def root_logger():
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    yield root
    root.handlers, root.level = saved[0], saved[1]


def test_setup_logging_configures_root_once(root_logger):
    setup_logging("WARNING")
    setup_logging("INFO")
    assert root_logger.level == logging.INFO
    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0].formatter, JsonFormatter)
