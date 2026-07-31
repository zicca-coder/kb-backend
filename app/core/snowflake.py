from __future__ import annotations

import threading
import time
from collections.abc import Callable
from functools import lru_cache

from app.core.settings import settings

WORKER_ID_BITS = 10
SEQUENCE_BITS = 12

MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1

WORKER_ID_SHIFT = SEQUENCE_BITS
TIMESTAMP_SHIFT = WORKER_ID_BITS + SEQUENCE_BITS
MAX_SIGNED_BIGINT = (1 << 63) - 1


class ClockMovedBackwardsError(RuntimeError):
    pass


class SnowflakeGenerator:
    def __init__(
        self,
        *,
        worker_id: int,
        epoch_ms: int,
        time_func: Callable[[], int] | None = None,
    ) -> None:
        if isinstance(worker_id, bool) or not 0 <= worker_id <= MAX_WORKER_ID:
            raise ValueError("worker_id must be between 0 and 1023")
        if isinstance(epoch_ms, bool) or epoch_ms <= 0:
            raise ValueError("epoch_ms must be greater than 0")

        self._worker_id = worker_id
        self._epoch_ms = epoch_ms
        self._time_func = time_func or self._current_time_ms
        self._lock = threading.Lock()
        self._last_timestamp_ms = -1
        self._sequence = 0

        if self._timestamp_ms() < self._epoch_ms:
            raise ValueError("current time must be later than epoch_ms")

    @staticmethod
    def _current_time_ms() -> int:
        return time.time_ns() // 1_000_000

    def _timestamp_ms(self) -> int:
        timestamp_ms = self._time_func()
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
            raise TypeError("time_func must return an integer millisecond timestamp")
        return timestamp_ms

    def next_id(self) -> int:
        with self._lock:
            timestamp_ms = self._timestamp_ms()
            if timestamp_ms < self._last_timestamp_ms:
                raise ClockMovedBackwardsError("system clock moved backwards")

            if timestamp_ms == self._last_timestamp_ms:
                self._sequence = (self._sequence + 1) & MAX_SEQUENCE
                if self._sequence == 0:
                    timestamp_ms = self._wait_next_millis(timestamp_ms)
            else:
                self._sequence = 0

            self._last_timestamp_ms = timestamp_ms
            snowflake_id = (
                ((timestamp_ms - self._epoch_ms) << TIMESTAMP_SHIFT)
                | (self._worker_id << WORKER_ID_SHIFT)
                | self._sequence
            )
            if not 0 < snowflake_id <= MAX_SIGNED_BIGINT:
                raise OverflowError("snowflake ID is outside signed BIGINT range")
            return snowflake_id

    def _wait_next_millis(self, timestamp_ms: int) -> int:
        next_timestamp_ms = self._timestamp_ms()
        while next_timestamp_ms <= timestamp_ms:
            time.sleep(0)
            next_timestamp_ms = self._timestamp_ms()
        return next_timestamp_ms


@lru_cache
def get_snowflake_generator() -> SnowflakeGenerator:
    return SnowflakeGenerator(
        worker_id=settings.snowflake_worker_id,
        epoch_ms=settings.snowflake_epoch_ms,
    )
