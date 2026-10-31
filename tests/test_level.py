"""Tests for needledrop.level: audio level measurement for gate detection."""

from __future__ import annotations

import math
import struct

from needledrop.level import SILENCE_DB, HighPassFilter, LevelMeter, dbfs_from_pcm16


def _sine_chunk(amplitude: int, freq_hz: float, sample_rate_hz: int, n: int) -> bytes:
    samples = [
        int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate_hz))
        for i in range(n)
    ]
    return struct.pack(f"<{n}h", *samples)


def test_silence_reports_silence_db():
    assert dbfs_from_pcm16(b"") == SILENCE_DB
    assert dbfs_from_pcm16(bytes(2000)) == SILENCE_DB


def test_louder_signal_has_higher_level():
    quiet = _sine_chunk(amplitude=1000, freq_hz=440, sample_rate_hz=44100, n=1024)
    loud = _sine_chunk(amplitude=20000, freq_hz=440, sample_rate_hz=44100, n=1024)
    assert dbfs_from_pcm16(loud) > dbfs_from_pcm16(quiet)


def test_full_scale_sine_is_close_to_0_dbfs():
    full_scale = _sine_chunk(
        amplitude=32767, freq_hz=1000, sample_rate_hz=44100, n=4096
    )
    level = dbfs_from_pcm16(full_scale)
    # RMS of a sine wave is amplitude / sqrt(2), so full-scale is about -3dBFS.
    assert -4.0 < level < -2.0


def test_highpass_filter_attenuates_low_frequency_hum_more_than_high_frequency():
    sample_rate_hz = 44100
    hum = _sine_chunk(20000, 50, sample_rate_hz, 4410)  # mains hum-like
    crackle = _sine_chunk(20000, 8000, sample_rate_hz, 4410)  # scratchy high end

    hum_filtered = HighPassFilter(3000, sample_rate_hz).apply(hum)
    crackle_filtered = HighPassFilter(3000, sample_rate_hz).apply(crackle)

    hum_level = dbfs_from_pcm16(hum_filtered)
    crackle_level = dbfs_from_pcm16(crackle_filtered)
    assert crackle_level > hum_level


def test_level_meter_without_filter_matches_raw_dbfs():
    chunk = _sine_chunk(10000, 440, 44100, 1024)
    meter = LevelMeter(filter_type=None, filter_freq_hz=3000, sample_rate_hz=44100)
    assert meter.measure(chunk) == dbfs_from_pcm16(chunk)


def test_level_meter_unsupported_filter_type_raises():
    import pytest

    with pytest.raises(ValueError):
        LevelMeter(filter_type="lowpass", filter_freq_hz=3000, sample_rate_hz=44100)
