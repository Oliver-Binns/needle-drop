"""Tests for needledrop.gated_source: wrapping a source with the gate."""

from __future__ import annotations

import math
import struct
import threading

from needledrop.gate import Gate, GateState
from needledrop.gated_source import GatedSource

SAMPLE_RATE_HZ = 44100
BYTES_PER_SECOND = SAMPLE_RATE_HZ * 2  # mono 16-bit for simplicity
CHUNK_S = 0.1
CHUNK_SAMPLES = int(SAMPLE_RATE_HZ * CHUNK_S)


def _silence() -> bytes:
    return bytes(CHUNK_SAMPLES * 2)


def _loud() -> bytes:
    samples = [
        int(20000 * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE_HZ))
        for i in range(CHUNK_SAMPLES)
    ]
    return struct.pack(f"<{CHUNK_SAMPLES}h", *samples)


class FakeSource:
    """A fake AudioSource that yields pre-set chunks, then signals EOF."""

    def __init__(self, chunks: list[bytes]):
        self._chunks = iter(chunks)
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def read(self) -> bytes:
        return next(self._chunks, b"")

    def close(self) -> None:
        self.closed = True


class TickingClock:
    """A fake clock that advances by `step` seconds on every call.

    Matches the "one chunk, one tick" relationship the real pipeline has
    (each underlying chunk covers `step` seconds of audio), without
    depending on wall-clock time in tests.
    """

    def __init__(self, step: float) -> None:
        self._now = -step
        self._step = step

    def __call__(self) -> float:
        self._now += self._step
        return self._now


def make_gate(**overrides) -> Gate:
    params = {
        "start_delay_s": 1.0,
        "stop_delay_s": 2.0,
        "preroll_s": 1.5,
        "start_level": -40.0,
        "stop_level": -50.0,
        "bytes_per_second": BYTES_PER_SECOND,
    }
    params.update(overrides)
    return Gate(**params)


def _drain(source: GatedSource) -> bytes:
    """Read until end of stream, concatenating everything forwarded."""
    forwarded = bytearray()
    while True:
        chunk = source.read()
        if not chunk:
            return bytes(forwarded)
        forwarded += chunk


def test_forwards_nothing_while_idle():
    chunks = [_silence()] * 5
    source = GatedSource(FakeSource(chunks), make_gate(), clock=TickingClock(CHUNK_S))

    assert _drain(source) == b""


def test_forwards_preroll_and_live_audio_once_armed_long_enough():
    # Enough loud chunks to cross start_delay_s (1.0s = 10 chunks @ 0.1s).
    chunks = [_loud()] * 15
    source = GatedSource(FakeSource(chunks), make_gate(), clock=TickingClock(CHUNK_S))

    forwarded = _drain(source)

    # All 15 loud chunks eventually get forwarded (pre-roll once armed, then
    # live), since the gate never drops audio once it decides to open.
    assert forwarded == b"".join(chunks)


def test_calls_on_start_when_gate_opens():
    chunks = [_loud()] * 15
    started = threading.Event()

    source = GatedSource(
        FakeSource(chunks),
        make_gate(),
        on_start=started.set,
        clock=TickingClock(CHUNK_S),
    )

    _drain(source)

    assert started.wait(timeout=2.0)


def test_calls_on_stop_after_gate_closes():
    # Loud long enough to open (>= start_delay_s), then quiet long enough
    # to close (>= stop_delay_s), plus a little headroom.
    chunks = [_loud()] * 15 + [_silence()] * 30
    started = threading.Event()
    stopped = threading.Event()

    source = GatedSource(
        FakeSource(chunks),
        make_gate(),
        on_start=started.set,
        on_stop=stopped.set,
        clock=TickingClock(CHUNK_S),
    )

    _drain(source)

    assert started.wait(timeout=2.0)
    assert stopped.wait(timeout=2.0)


def test_on_start_and_on_stop_not_called_without_a_full_open_close_cycle():
    chunks = [_loud()] * 3  # not enough to cross start_delay_s
    started = threading.Event()
    stopped = threading.Event()

    source = GatedSource(
        FakeSource(chunks),
        make_gate(),
        on_start=started.set,
        on_stop=stopped.set,
        clock=TickingClock(CHUNK_S),
    )

    assert _drain(source) == b""
    assert not started.is_set()
    assert not stopped.is_set()


def test_ends_in_idle_state_after_full_open_close_cycle():
    chunks = [_loud()] * 15 + [_silence()] * 30
    source = GatedSource(FakeSource(chunks), make_gate(), clock=TickingClock(CHUNK_S))

    _drain(source)

    assert source._gate.state == GateState.IDLE


def test_propagates_end_of_stream():
    source = GatedSource(FakeSource([]), make_gate(), clock=TickingClock(CHUNK_S))
    assert source.read() == b""


def test_open_and_close_delegate_to_wrapped_source():
    fake = FakeSource([])
    source = GatedSource(fake, make_gate(), clock=TickingClock(CHUNK_S))

    source.open()
    source.close()

    assert fake.opened
    assert fake.closed
