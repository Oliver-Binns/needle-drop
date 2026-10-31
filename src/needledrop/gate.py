"""The gate: decides when a record is actually playing and audio should flow.

Moves through four states (Idle -> Arming -> Streaming -> Cooling down ->
Idle) based on the measured audio level, while always forwarding the
original, unfiltered audio byte-for-byte. A short pre-roll buffer is kept so
the very start of a record is never lost, covering the time spent deciding
to open the gate.
"""

from __future__ import annotations

import math
from collections import deque
from enum import Enum, auto

from needledrop.level import LevelMeter


class GateState(Enum):
    IDLE = auto()
    ARMING = auto()
    STREAMING = auto()
    COOLING_DOWN = auto()


class _PrerollBuffer:
    """Keeps the most recent ``duration_s`` seconds of audio chunks."""

    def __init__(self, duration_s: float, bytes_per_second: float) -> None:
        self._limit_bytes = int(duration_s * bytes_per_second)
        self._chunks: deque[bytes] = deque()
        self._bytes = 0

    def append(self, chunk: bytes) -> None:
        self._chunks.append(chunk)
        self._bytes += len(chunk)
        while self._bytes > self._limit_bytes and len(self._chunks) > 1:
            dropped = self._chunks.popleft()
            self._bytes -= len(dropped)

    def drain(self) -> list[bytes]:
        """Return and clear all buffered chunks, in order."""
        chunks = list(self._chunks)
        self._chunks.clear()
        self._bytes = 0
        return chunks


class Gate:
    """State machine deciding when to forward audio to the speaker.

    Feed it successive audio chunks via :meth:`process`; it returns the
    chunks (if any) that should now be sent on, including any buffered
    pre-roll audio at the moment streaming starts. No audio is ever dropped
    by the gate itself: it is either forwarded now, forwarded later (held in
    the pre-roll buffer), or (while Idle/Arming) deliberately not sent,
    consistent with "a record is not playing, so there is nothing to send".

    ``fade_out_s`` is only the on/off switch for a gentle fade-out (off by
    default, i.e. ``0.0``); the actual fade shaping is implemented in a
    later task (see issue #23). Until then the gate forwards the closing
    audio unchanged regardless of ``fade_out_s``.
    """

    def __init__(
        self,
        start_delay_s: float,
        stop_delay_s: float,
        preroll_s: float,
        start_level: float,
        stop_level: float,
        bytes_per_second: float,
        fade_out_s: float = 0.0,
        filter_type: str | None = None,
        filter_freq_hz: float = 3000.0,
        sample_rate_hz: float = 44100.0,
    ) -> None:
        if preroll_s < start_delay_s + 0.5:
            raise ValueError(
                f"preroll_s ({preroll_s}) must be >= start_delay_s "
                f"({start_delay_s}) + 0.5. Pre-roll exists to cover the "
                "start delay so no audio is lost."
            )
        if fade_out_s < 0:
            raise ValueError("fade_out_s must be >= 0")

        self._start_delay_s = start_delay_s
        self._stop_delay_s = stop_delay_s
        self._start_level = start_level
        self._stop_level = stop_level
        self._fade_out_s = fade_out_s
        self._bytes_per_second = bytes_per_second

        self._meter = LevelMeter(filter_type, filter_freq_hz, sample_rate_hz)
        self._preroll = _PrerollBuffer(preroll_s, bytes_per_second)

        self._state = GateState.IDLE
        self._level_db = math.nan
        # Time (seconds since gate creation, from `now`) at which the
        # current above/below-threshold run began.
        self._threshold_crossed_at: float | None = None

    @property
    def state(self) -> GateState:
        return self._state

    @property
    def level_db(self) -> float:
        return self._level_db

    @property
    def fade_out_s(self) -> float:
        """The fade-out on/off switch (0.0 = off). See class docstring."""
        return self._fade_out_s

    def process(self, chunk: bytes, now: float) -> list[bytes]:
        """Feed in the next chunk of audio; returns chunks to forward now.

        ``now`` is a monotonically increasing clock in seconds, supplied by
        the caller so behaviour is deterministic and testable.
        """
        self._level_db = self._meter.measure(chunk)

        if self._state == GateState.IDLE:
            return self._process_idle(chunk, now)
        if self._state == GateState.ARMING:
            return self._process_arming(chunk, now)
        if self._state == GateState.STREAMING:
            return self._process_streaming(chunk, now)
        return self._process_cooling_down(chunk, now)

    def _process_idle(self, chunk: bytes, now: float) -> list[bytes]:
        self._preroll.append(chunk)
        if self._level_db >= self._start_level:
            self._state = GateState.ARMING
            self._threshold_crossed_at = now
        return []

    def _process_arming(self, chunk: bytes, now: float) -> list[bytes]:
        if self._level_db < self._start_level:
            # False alarm: back to idle, keep buffering pre-roll.
            self._state = GateState.IDLE
            self._threshold_crossed_at = None
            self._preroll.append(chunk)
            return []

        self._preroll.append(chunk)
        assert self._threshold_crossed_at is not None
        if now - self._threshold_crossed_at >= self._start_delay_s:
            self._state = GateState.STREAMING
            self._threshold_crossed_at = None
            return self._preroll.drain()
        return []

    def _process_streaming(self, chunk: bytes, now: float) -> list[bytes]:
        if self._level_db < self._stop_level:
            self._state = GateState.COOLING_DOWN
            self._threshold_crossed_at = now
        return [chunk]

    def _process_cooling_down(self, chunk: bytes, now: float) -> list[bytes]:
        if self._level_db >= self._stop_level:
            # Recovered before the stop delay elapsed: keep streaming.
            self._state = GateState.STREAMING
            self._threshold_crossed_at = None
            return [chunk]

        assert self._threshold_crossed_at is not None
        elapsed = now - self._threshold_crossed_at
        if elapsed >= self._stop_delay_s:
            self._state = GateState.IDLE
            self._threshold_crossed_at = None
        # self._fade_out_s is plumbed through as the on/off switch but the
        # actual fade shaping is implemented in a later task (gentle
        # fade-out); for now the gate always forwards the chunk unchanged.
        return [chunk]
