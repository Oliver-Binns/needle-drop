"""Wraps a raw :class:`AudioSource` with the gate's start/stop decisions.

`GatedSource` sits between the sound card and :class:`AudioPipeline`: it
measures every chunk read from the wrapped source via a `Gate`, and only
ever hands on the audio the gate decides to forward (including any
buffered pre-roll, released the moment the gate opens). `AudioPipeline`
itself stays unaware of gating; it just delivers whatever bytes it's given
without ever dropping them silently.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from needledrop.audio_source import AudioSource
from needledrop.gate import Gate, GateState


class GatedSource:
    """`AudioSource` that only yields audio while the gate is forwarding it.

    ``on_start`` and ``on_stop`` are optional callbacks fired once per
    open/close cycle: ``on_start`` when the gate first enters
    :attr:`GateState.STREAMING` (a record started playing), and ``on_stop``
    when it returns to :attr:`GateState.IDLE` from
    :attr:`GateState.COOLING_DOWN` (the record stopped and the stop delay
    elapsed). Each callback runs on its own daemon thread so a slow or
    unreachable OwnTone API never blocks audio capture.
    """

    def __init__(
        self,
        source: AudioSource,
        gate: Gate,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._gate = gate
        self._on_start = on_start
        self._on_stop = on_stop
        self._clock = clock

    def open(self) -> None:
        self._source.open()

    def read(self) -> bytes:
        """Return the next chunk the gate forwards; empty bytes at end of stream."""
        while True:
            chunk = self._source.read()
            if not chunk:
                return b""

            previous_state = self._gate.state
            forwarded = self._gate.process(chunk, self._clock())
            self._fire_transition_callbacks(previous_state, self._gate.state)

            if forwarded:
                return b"".join(forwarded)

    def close(self) -> None:
        self._source.close()

    def _fire_transition_callbacks(
        self, previous_state: GateState, new_state: GateState
    ) -> None:
        if (
            new_state == GateState.STREAMING
            and previous_state != GateState.STREAMING
            and self._on_start is not None
        ):
            self._run_in_background(self._on_start)
        elif (
            new_state == GateState.IDLE
            and previous_state == GateState.COOLING_DOWN
            and self._on_stop is not None
        ):
            self._run_in_background(self._on_stop)

    @staticmethod
    def _run_in_background(callback: Callable[[], None]) -> None:
        threading.Thread(target=callback, daemon=True).start()
