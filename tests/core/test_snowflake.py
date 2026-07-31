from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.snowflake import (
    MAX_SEQUENCE,
    MAX_SIGNED_BIGINT,
    ClockMovedBackwardsError,
    SnowflakeGenerator,
)

EPOCH_MS = 1_700_000_000_000
NOW_MS = EPOCH_MS + 10_000


class StepClock:
    def __init__(self, values: list[int]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> int:
        if self.index >= len(self.values):
            return self.values[-1]
        value = self.values[self.index]
        self.index += 1
        return value


def test_next_id_generates_positive_bigint() -> None:
    generator = SnowflakeGenerator(
        worker_id=1,
        epoch_ms=EPOCH_MS,
        time_func=StepClock([NOW_MS, NOW_MS]),
    )

    snowflake_id = generator.next_id()

    assert snowflake_id > 0
    assert snowflake_id <= MAX_SIGNED_BIGINT


def test_continuous_ids_are_unique_and_same_millisecond_sequence_increments() -> None:
    generator = SnowflakeGenerator(
        worker_id=1,
        epoch_ms=EPOCH_MS,
        time_func=StepClock([NOW_MS, NOW_MS, NOW_MS]),
    )

    first = generator.next_id()
    second = generator.next_id()

    assert first != second
    assert first & MAX_SEQUENCE == 0
    assert second & MAX_SEQUENCE == 1


def test_sequence_resets_after_millisecond_changes() -> None:
    generator = SnowflakeGenerator(
        worker_id=1,
        epoch_ms=EPOCH_MS,
        time_func=StepClock([NOW_MS, NOW_MS, NOW_MS + 1]),
    )

    first = generator.next_id()
    second = generator.next_id()

    assert first & MAX_SEQUENCE == 0
    assert second & MAX_SEQUENCE == 0
    assert second > first


def test_ids_trend_upward_with_time() -> None:
    generator = SnowflakeGenerator(
        worker_id=1,
        epoch_ms=EPOCH_MS,
        time_func=StepClock([NOW_MS, NOW_MS, NOW_MS + 10]),
    )

    assert generator.next_id() < generator.next_id()


def test_different_worker_ids_generate_different_ids() -> None:
    left = SnowflakeGenerator(
        worker_id=1,
        epoch_ms=EPOCH_MS,
        time_func=StepClock([NOW_MS, NOW_MS]),
    )
    right = SnowflakeGenerator(
        worker_id=2,
        epoch_ms=EPOCH_MS,
        time_func=StepClock([NOW_MS, NOW_MS]),
    )

    assert left.next_id() != right.next_id()


@pytest.mark.parametrize("worker_id", [-1, 1024])
def test_invalid_worker_id_is_rejected(worker_id: int) -> None:
    with pytest.raises(ValueError):
        SnowflakeGenerator(
            worker_id=worker_id,
            epoch_ms=EPOCH_MS,
            time_func=StepClock([NOW_MS]),
        )


@pytest.mark.parametrize("epoch_ms", [0, -1])
def test_invalid_epoch_is_rejected(epoch_ms: int) -> None:
    with pytest.raises(ValueError):
        SnowflakeGenerator(
            worker_id=1,
            epoch_ms=epoch_ms,
            time_func=StepClock([NOW_MS]),
        )


def test_epoch_in_future_is_rejected() -> None:
    with pytest.raises(ValueError):
        SnowflakeGenerator(
            worker_id=1,
            epoch_ms=NOW_MS + 1,
            time_func=StepClock([NOW_MS]),
        )


def test_clock_moved_backwards_raises_error() -> None:
    generator = SnowflakeGenerator(
        worker_id=1,
        epoch_ms=EPOCH_MS,
        time_func=StepClock([NOW_MS, NOW_MS, NOW_MS - 1]),
    )

    generator.next_id()
    with pytest.raises(ClockMovedBackwardsError):
        generator.next_id()


def test_sequence_overflow_waits_until_next_millisecond() -> None:
    values = [NOW_MS] * (MAX_SEQUENCE + 3)
    values.append(NOW_MS + 1)
    generator = SnowflakeGenerator(
        worker_id=1,
        epoch_ms=EPOCH_MS,
        time_func=StepClock(values),
    )

    ids = [generator.next_id() for _ in range(MAX_SEQUENCE + 2)]

    assert ids[-1] & MAX_SEQUENCE == 0
    assert ids[-1] > ids[-2]


def test_multithreaded_generation_has_no_duplicates() -> None:
    generator = SnowflakeGenerator(
        worker_id=1,
        epoch_ms=EPOCH_MS,
        time_func=StepClock([NOW_MS] * 1002),
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(lambda _index: generator.next_id(), range(1000)))

    assert len(ids) == len(set(ids))
