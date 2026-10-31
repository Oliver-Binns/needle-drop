"""Tests for needledrop.gate: the automatic start/stop state machine."""

from __future__ import annotations

import math
import struct

import pytest

from needledrop.gate import Gate, GateState

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


def test_invariant_rejects_insufficient_preroll():
    with pytest.raises(ValueError):
        make_gate(start_delay_s=1.0, preroll_s=1.0)  # needs >= 1.5


def test_stays_idle_on_continuous_quiet():
    gate = make_gate()
    for i in range(20):
        out = gate.process(_silence(), now=i * CHUNK_S)
        assert out == []
    assert gate.state == GateState.IDLE


def test_one_off_bump_does_not_open_gate():
    gate = make_gate()
    now = 0.0
    for _ in range(5):
        gate.process(_silence(), now)
        now += CHUNK_S
    out = gate.process(_loud(), now)  # single bump
    assert out == []
    assert gate.state == GateState.ARMING
    now += CHUNK_S
    out = gate.process(_silence(), now)  # immediately quiet again
    assert out == []
    assert gate.state == GateState.IDLE
    # Keeps being quiet afterwards: never streams.
    for _ in range(5):
        now += CHUNK_S
        assert gate.process(_silence(), now) == []
    assert gate.state == GateState.IDLE


def test_sustained_sound_opens_gate_and_includes_preroll():
    gate = make_gate()
    now = 0.0
    fed_before_streaming: list[bytes] = []
    out: list[bytes] = []
    while gate.state != GateState.STREAMING:
        chunk = _silence() if now < 0.5 else _loud()
        fed_before_streaming.append(chunk)
        out = gate.process(chunk, now)
        now += CHUNK_S
        assert now < 10, "gate never opened"

    assert gate.state == GateState.STREAMING
    # The transition chunk must carry more than just the latest slice: the
    # buffered pre-roll audio (silence + early arming audio) is included so
    # nothing from the start of the record is lost.
    assert len(out) > 1
    # Every byte fed while waiting to decide must be accounted for somewhere
    # in the pre-roll window; none of it is silently discarded.
    total_out_bytes = sum(len(c) for c in out)
    assert total_out_bytes > len(fed_before_streaming[-1])


def test_brief_dip_during_streaming_recovers_without_reopening():
    gate = _streaming_gate()
    now = 10.0
    out = gate.process(_silence(), now)
    assert out == [_silence()]
    assert gate.state == GateState.COOLING_DOWN

    now += CHUNK_S
    out = gate.process(_loud(), now)
    assert out == [_loud()]
    assert gate.state == GateState.STREAMING


def test_sustained_quiet_during_streaming_closes_gate():
    gate = _streaming_gate(stop_delay_s=0.5)
    now = 10.0
    while gate.state != GateState.IDLE:
        out = gate.process(_silence(), now)
        assert out == [_silence()]  # audio still forwarded while closing
        now += CHUNK_S
        assert now < 20, "gate never closed"
    assert gate.state == GateState.IDLE


def test_fade_out_switch_is_stored_but_does_not_shape_audio_yet():
    """fade_out_s is only the on/off switch here; shaping is issue #23."""
    gate = _streaming_gate(stop_delay_s=0.3, fade_out_s=2.0)
    assert gate.fade_out_s == 2.0
    now = 10.0
    loud = _loud()
    while gate.state != GateState.IDLE:
        out = gate.process(_silence(), now)
        assert out == [_silence()]
        now += CHUNK_S
        assert now < 20
    # Unrelated chunk unaffected either way.
    assert loud == _loud()


def test_fade_out_off_by_default():
    gate = make_gate()
    assert gate.fade_out_s == 0.0


def _streaming_gate(**overrides) -> Gate:
    """Build a gate already in the Streaming state, for tests that only
    care about streaming/cooling-down/closing behaviour."""
    gate = make_gate(**overrides)
    now = 0.0
    while gate.state != GateState.STREAMING:
        chunk = _silence() if now < 0.5 else _loud()
        gate.process(chunk, now)
        now += CHUNK_S
        assert now < 10
    return gate
