import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unittest.mock import MagicMock, patch

import pytest

import needledrop.__main__ as entry
from needledrop.__main__ import _make_stop_handler, main
from needledrop.config import Config
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


def test_run_streams_selects_speaker_and_stops_cleanly():
    stop_event = threading.Event()
    pipeline = MagicMock()
    client = MagicMock()
    client.select_speaker_and_set_volume.side_effect = lambda *a, **k: stop_event.set()

    with (
        patch.object(entry, "AudioPipeline", return_value=pipeline) as pipeline_cls,
        patch.object(entry, "PyAudioSource"),
        patch.object(entry, "PipeSink"),
        patch.object(entry, "OwnToneClient", return_value=client),
    ):
        entry.run(make_config(), stop_event, retry_interval_s=0)

    assert pipeline_cls.call_args.args[2] == 44100 * 2 * 2
    pipeline.start.assert_called_once()
    assert client.select_speaker_and_set_volume.call_args.args == ("Living Room", 25)
    pipeline.stop.assert_called_once()


def test_run_retries_until_speaker_and_sound_card_are_ready():
    stop_event = threading.Event()
    pipeline = MagicMock()
    pipeline.start.side_effect = [OSError("no card"), None]
    outcomes = [OwnToneSpeakerNotFound("missing"), None]

    def select(*_args, **_kwargs):
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome
        stop_event.set()

    client = MagicMock()
    client.select_speaker_and_set_volume.side_effect = select

    with (
        patch.object(entry, "AudioPipeline", return_value=pipeline),
        patch.object(entry, "PyAudioSource"),
        patch.object(entry, "PipeSink"),
        patch.object(entry, "OwnToneClient", return_value=client),
    ):
        entry.run(make_config(), stop_event, retry_interval_s=0)

    assert pipeline.start.call_count == 2
    assert client.select_speaker_and_set_volume.call_count == 2
    pipeline.stop.assert_called_once()


def test_main_is_callable():
    assert callable(main)


def test_stop_handler_sets_event():
    stop_event = threading.Event()
    stop_handler = _make_stop_handler(stop_event)

    stop_handler(0, None)

    assert stop_event.is_set()
