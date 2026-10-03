"""Pure reconnection policy tests (RF-002 through RF-006)."""

import subs.worker.transcriber as transcriber


def test_first_attempt_has_no_delay() -> None:
    assert transcriber.reconnect_delay_ms(attempt=1, initial_ms=500, max_ms=8000) == 0


def test_delays_double_until_the_cap_without_decreasing() -> None:
    delays = [
        transcriber.reconnect_delay_ms(attempt=n, initial_ms=500, max_ms=8000)
        for n in range(1, 9)
    ]
    assert delays == [0, 500, 1000, 2000, 4000, 8000, 8000, 8000]


def test_custom_initial_and_cap_are_used() -> None:
    delays = [
        transcriber.reconnect_delay_ms(attempt=n, initial_ms=250, max_ms=600)
        for n in range(1, 6)
    ]
    assert delays == [0, 250, 500, 600, 600]


def test_equal_initial_and_cap_hold_each_later_delay_constant() -> None:
    assert [
        transcriber.reconnect_delay_ms(attempt=n, initial_ms=100, max_ms=100)
        for n in range(1, 5)
    ] == [0, 100, 100, 100]


def test_retry_until_consecutive_failures_reach_the_limit() -> None:
    assert transcriber.should_retry_reconnect(failures=1, max_attempts=3)
    assert transcriber.should_retry_reconnect(failures=2, max_attempts=3)
    assert not transcriber.should_retry_reconnect(failures=3, max_attempts=3)


def test_one_attempt_abandons_after_first_failure() -> None:
    assert not transcriber.should_retry_reconnect(failures=1, max_attempts=1)


def test_success_starts_a_new_attempt_count() -> None:
    assert not transcriber.should_retry_reconnect(failures=3, max_attempts=3)
    assert transcriber.reconnect_delay_ms(attempt=1, initial_ms=500, max_ms=8000) == 0
    assert transcriber.should_retry_reconnect(failures=1, max_attempts=3)
