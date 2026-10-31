"""Executable entrypoint for `python -m needledrop`: always-on streaming."""

from __future__ import annotations

import logging
import signal
import sys
import threading

import requests
import yaml

from needledrop.audio_sink import PipeSink
from needledrop.audio_source import PyAudioSource
from needledrop.config import Config, load_config
from needledrop.owntone import OwnToneClient, OwnToneError
from needledrop.pipeline import AudioPipeline

log = logging.getLogger("needledrop")

STATS_INTERVAL_S = 60.0
RETRY_INTERVAL_S = 5.0


def _make_stop_handler(stop_event: threading.Event):
    def _stop_handler(_signum: int, _frame) -> None:
        stop_event.set()

    return _stop_handler


def _open_pipeline(
    config: Config, stop_event: threading.Event, retry_interval_s: float
) -> AudioPipeline | None:
    """Start capturing, retrying until the sound card is ready."""
    bytes_per_second = config.sample_rate_hz * config.channels * config.bit_depth // 8
    while not stop_event.is_set():
        pipeline = AudioPipeline(
            PyAudioSource(config.sample_rate_hz, config.channels, config.bit_depth),
            PipeSink(config.owntone_pipe),
            bytes_per_second,
            queue_limit_s=config.queue_limit_s,
        )
        try:
            pipeline.start()
            return pipeline
        except (
            OSError,
            ImportError,
        ) as exc:  # sound card not ready (or pyaudio missing)
            log.warning("cannot open sound card: %s; retrying", exc)
            stop_event.wait(retry_interval_s)
    return None


def _select_speaker(
    config: Config, stop_event: threading.Event, retry_interval_s: float
) -> None:
    """Select the speaker in OwnTone, retrying until it is available."""
    client = OwnToneClient(timeout_s=config.owntone_timeout_s)
    start_volume = None if config.start_volume is None else int(config.start_volume)
    while not stop_event.is_set():
        try:
            client.select_speaker_and_set_volume(
                config.speaker_name, start_volume, max_attempts=1
            )
        except (OwnToneError, requests.RequestException) as exc:
            log.warning("speaker not ready: %s; retrying", exc)
            stop_event.wait(retry_interval_s)
        else:
            log.info("streaming to speaker %r", config.speaker_name)
            return


def run(
    config: Config,
    stop_event: threading.Event,
    retry_interval_s: float = RETRY_INTERVAL_S,
    stats_interval_s: float = STATS_INTERVAL_S,
) -> None:
    pipeline = _open_pipeline(config, stop_event, retry_interval_s)
    if pipeline is None:
        return
    log.info("capturing audio and streaming to %s", config.owntone_pipe)
    try:
        _select_speaker(config, stop_event, retry_interval_s)
        while not stop_event.wait(stats_interval_s):
            log.info("pipeline stats: %s", pipeline.stats())
    finally:
        pipeline.stop()
        log.info("final pipeline stats: %s", pipeline.stats())


def main() -> None:
    try:
        config = load_config()
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        sys.exit(f"needle-drop: cannot load configuration: {exc}")

    logging.basicConfig(
        level=getattr(logging, str(config.log_level).upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not config.speaker_name:
        sys.exit(
            "needle-drop: speaker_name is not set; add it to "
            "/etc/needle-drop/config.yaml"
        )

    stop_event = threading.Event()
    stop_handler = _make_stop_handler(stop_event)
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    log.info("needle-drop starting")
    run(config, stop_event)
    log.info("needle-drop stopped")


if __name__ == "__main__":
    main()
