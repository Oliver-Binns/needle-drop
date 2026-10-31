"""Audio level measurement for the gate's start/stop detection.

Measures how loud (and, optionally, how "scratchy") a chunk of audio is.
This is only ever used to *decide* whether the gate should be open; the
original, unfiltered audio is always the one forwarded to the speaker.
"""

from __future__ import annotations

import math
import struct
from typing import Final

# Full-scale reference for 16-bit signed PCM, used as the 0 dBFS point.
_INT16_FULL_SCALE: Final[float] = 32768.0

# Level reported for silence (zero RMS), since dB of zero is undefined.
SILENCE_DB: Final[float] = -120.0


def dbfs_from_pcm16(chunk: bytes) -> float:
    """Compute the RMS level of a raw 16-bit PCM chunk, in dBFS.

    ``chunk`` may hold any number of interleaved channels; all samples are
    treated equally when computing RMS. Returns ``SILENCE_DB`` for an empty
    or all-zero chunk rather than raising on log(0).
    """
    if not chunk:
        return SILENCE_DB

    sample_count = len(chunk) // 2
    if sample_count == 0:
        return SILENCE_DB

    samples = struct.unpack(f"<{sample_count}h", chunk[: sample_count * 2])
    mean_square = sum(sample * sample for sample in samples) / sample_count
    if mean_square <= 0.0:
        return SILENCE_DB

    rms = math.sqrt(mean_square)
    return 20.0 * math.log10(rms / _INT16_FULL_SCALE)


class HighPassFilter:
    """Simple one-pole high-pass filter used only for crackle *detection*.

    Emphasises high frequencies (where vinyl crackle lives) and attenuates
    mains hum, so the level meter can tell "needle in groove" apart from
    background electrical noise. Applied only to the copy of the audio used
    for measurement; never to the audio forwarded to the speaker.
    """

    def __init__(self, cutoff_hz: float, sample_rate_hz: float) -> None:
        if cutoff_hz <= 0:
            raise ValueError("cutoff_hz must be > 0")
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")
        rc = 1.0 / (2.0 * math.pi * cutoff_hz)
        dt = 1.0 / sample_rate_hz
        self._alpha = rc / (rc + dt)
        self._prev_in = 0.0
        self._prev_out = 0.0

    def apply(self, chunk: bytes) -> bytes:
        """Return a filtered copy of ``chunk`` (same length, 16-bit PCM)."""
        sample_count = len(chunk) // 2
        if sample_count == 0:
            return chunk

        samples = struct.unpack(f"<{sample_count}h", chunk[: sample_count * 2])
        out = []
        prev_in = self._prev_in
        prev_out = self._prev_out
        alpha = self._alpha
        for sample in samples:
            filtered = alpha * (prev_out + sample - prev_in)
            prev_in = float(sample)
            prev_out = filtered
            out.append(max(-32768, min(32767, int(filtered))))
        self._prev_in = prev_in
        self._prev_out = prev_out
        return struct.pack(f"<{sample_count}h", *out)


class LevelMeter:
    """Measures the detection level of successive audio chunks.

    Wraps :func:`dbfs_from_pcm16`, optionally pre-filtering with a
    :class:`HighPassFilter` first when ``filter_type == "highpass"``.
    """

    def __init__(
        self,
        filter_type: str | None,
        filter_freq_hz: float,
        sample_rate_hz: float,
    ) -> None:
        self._filter: HighPassFilter | None
        if filter_type is None:
            self._filter = None
        elif filter_type == "highpass":
            self._filter = HighPassFilter(filter_freq_hz, sample_rate_hz)
        else:
            raise ValueError(f"unsupported filter_type: {filter_type!r}")

    def measure(self, chunk: bytes) -> float:
        """Return the detection level of ``chunk``, in dBFS."""
        detection_chunk = chunk if self._filter is None else self._filter.apply(chunk)
        return dbfs_from_pcm16(detection_chunk)
