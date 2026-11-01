import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unittest.mock import MagicMock, patch

import pytest

import needledrop.__main__ as entry
from needledrop.__main__ import _make_stop_handler, main
from needledrop.config import Config
from needledrop.gate import Gate
from needledrop.owntone import OwnToneSpeakerNotFound


def make_config(**overrides) -> Config:
    values = {
        "start_delay_s": 1.0,
        "stop_delay_s": 25.0,
        "preroll_s": 1.5,
        "fade_out_s": 0.0,
        "start_level": -40.0,
        "stop_level": -50.0,
        "filter_type": None,
        "filter_freq_hz": 3000,
        "owntone_pipe": "/tmp/test.pipe",
        "queue_limit_s": 30,
        "owntone_timeout_s": 10,
        "speaker_name": "Living Room",
        "start_volume": 25.0,
        "sample_rate_hz": 44100,
        "bit_depth": 16,
        "channels": 2,
        "status_port": 8099,
        "log_level": "INFO",
    }
    values.update(overrides)
    return Config(**values)


def test_main_refuses_to_start_without_speaker_name():
    with (
        patch.object(entry, "load_config", return_value=make_config(speaker_name=None)),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert "speaker_name" in str(exc.value)


def test_build_gate_computes_bytes_per_second_and_passes_config_through():
    config = make_config(
        start_delay_s=2.0, stop_delay_s=10.0, preroll_s=2.5, sample_rate_hz=48000
    )

    gate = entry._build_gate(config)

    assert isinstance(gate, Gate)
    assert gate.state.name == "IDLE"


def test_run_wires_a_gated_source_and_stops_cleanly():
    stop_event = threading.Event()
    pipeline = MagicMock()
    pipeline.start.side_effect = lambda: stop_event.set()
    captured = {}

    def fake_gated_source(source, gate, on_start=None, on_stop=None):
        captured["gate"] = gate
        captured["on_start"] = on_start
        captured["on_stop"] = on_stop
        return MagicMock()

    with (
        patch.object(entry, "AudioPipeline", return_value=pipeline) as pipeline_cls,
        patch.object(entry, "PyAudioSource"),
        patch.object(entry, "PipeSink"),
        patch.object(entry, "GatedSource", side_effect=fake_gated_source) as gated_cls,
        patch.object(entry, "OwnToneClient"),
    ):
        entry.run(make_config(), stop_event, retry_interval_s=0, stats_interval_s=0)

    gated_cls.assert_called_once()
    assert pipeline_cls.call_args.args[2] == 44100 * 2 * 2
    pipeline.start.assert_called_once()
    pipeline.stop.assert_called_once()
    assert isinstance(captured["gate"], Gate)
    assert callable(captured["on_start"])
    assert callable(captured["on_stop"])


def test_run_retries_until_sound_card_is_ready():
    stop_event = threading.Event()
    pipeline = MagicMock()
    attempts = iter([OSError("no card"), None])

    def start_side_effect():
        outcome = next(attempts)
        if outcome is not None:
            raise outcome
        stop_event.set()

    pipeline.start.side_effect = start_side_effect

    with (
        patch.object(entry, "AudioPipeline", return_value=pipeline),
        patch.object(entry, "PyAudioSource"),
        patch.object(entry, "PipeSink"),
        patch.object(entry, "GatedSource"),
        patch.object(entry, "OwnToneClient"),
    ):
        entry.run(make_config(), stop_event, retry_interval_s=0, stats_interval_s=0)

    assert pipeline.start.call_count == 2
    pipeline.stop.assert_called_once()


def test_on_start_callback_selects_speaker_and_sets_volume():
    client = MagicMock()
    on_start, _on_stop = entry._make_speaker_callbacks(make_config(), client)

    on_start()

    assert client.select_speaker_and_set_volume.call_args.args == ("Living Room", 25)


def test_on_start_callback_logs_and_swallows_errors():
    client = MagicMock()
    client.select_speaker_and_set_volume.side_effect = OwnToneSpeakerNotFound("gone")
    on_start, _on_stop = entry._make_speaker_callbacks(make_config(), client)

    on_start()  # must not raise


def test_on_stop_callback_deselects_speaker():
    client = MagicMock()
    _on_start, on_stop = entry._make_speaker_callbacks(make_config(), client)

    on_stop()

    assert client.deselect_speaker.call_args.args == ("Living Room",)


def test_on_stop_callback_logs_and_swallows_errors():
    client = MagicMock()
    client.deselect_speaker.side_effect = OwnToneSpeakerNotFound("gone")
    _on_start, on_stop = entry._make_speaker_callbacks(make_config(), client)

    on_stop()  # must not raise


def test_main_is_callable():
    assert callable(main)


def test_stop_handler_sets_event():
    stop_event = threading.Event()
    stop_handler = _make_stop_handler(stop_event)

    stop_handler(0, None)

    assert stop_event.is_set()
