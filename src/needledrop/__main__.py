"""Executable entrypoint for `python -m needledrop`.

Streams audio from the sound card to OwnTone only while the gate decides a
record is actually playing (see :mod:`needledrop.gate`), selecting the
configured speaker when streaming starts and releasing it again once the
gate closes, so other AirPlay devices can take over when nothing is
playing.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from collections.abc import Callable

import requests
import yaml

from needledrop.audio_sink import PipeSink
from needledrop.audio_source import PyAudioSource
from needledrop.config import Config, load_config
from needledrop.gate import Gate
from needledrop.gated_source import GatedSource
from needledrop.owntone import OwnToneClient, OwnToneError
from needledrop.pipeline import AudioPipeline

log = logging.getLogger("needledrop")

STATS_INTERVAL_S = 60.0
RETRY_INTERVAL_S = 5.0


def _make_stop_handler(stop_event: threading.Event):
    def _stop_handler(_signum: int, _frame) -> None:
        stop_event.set()

    return _stop_handler


def _build_gate(config: Config) -> Gate:
    bytes_per_second = config.sample_rate_hz * config.channels * config.bit_depth // 8
    return Gate(
        start_delay_s=config.start_delay_s,
        stop_delay_s=config.stop_delay_s,
        preroll_s=config.preroll_s,
        start_level=config.start_level,
        stop_level=config.stop_level,
        bytes_per_second=bytes_per_second,
        fade_out_s=config.fade_out_s,
        filter_type=config.filter_type,
        filter_freq_hz=config.filter_freq_hz,
        sample_rate_hz=config.sample_rate_hz,
    )


def _make_speaker_callbacks(
    config: Config, client: OwnToneClient
) -> tuple[Callable[[], None], Callable[[], None]]:
    """Build the gate's on_start/on_stop hooks: select/release the speaker.

    Each hook is called on its own background thread by `GatedSource`, so
    these can block (e.g. retrying) without holding up audio capture.
    """
    start_volume = None if config.start_volume is None else int(config.start_volume)

    def on_start() -> None:
        try:
            client.select_speaker_and_set_volume(config.speaker_name, start_volume)
        except (OwnToneError, requests.RequestException) as exc:
            log.warning("could not select speaker %r: %s", config.speaker_name, exc)
        else:
            log.info("streaming to speaker %r", config.speaker_name)

    def on_stop() -> None:
        try:
            client.deselect_speaker(config.speaker_name)
        except (OwnToneError, requests.RequestException) as exc:
            log.warning("could not release speaker %r: %s", config.speaker_name, exc)
        else:
            log.info("released speaker %r", config.speaker_name)

    return on_start, on_stop


def _open_pipeline(
    config: Config,
    gate: Gate,
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
    stop_event: threading.Event,
    retry_interval_s: float,
) -> AudioPipeline | None:
    """Start capturing through the gate, retrying until the sound card is ready."""
    bytes_per_second = config.sample_rate_hz * config.channels * config.bit_depth // 8
    while not stop_event.is_set():
        source = GatedSource(
            PyAudioSource(config.sample_rate_hz, config.channels, config.bit_depth),
            gate,
            on_start=on_start,
            on_stop=on_stop,
        )
        pipeline = AudioPipeline(
            source,
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


def run(
    config: Config,
    stop_event: threading.Event,
    retry_interval_s: float = RETRY_INTERVAL_S,
    stats_interval_s: float = STATS_INTERVAL_S,
) -> None:
    gate = _build_gate(config)
    client = OwnToneClient(timeout_s=config.owntone_timeout_s)
    on_start, on_stop = _make_speaker_callbacks(config, client)

    pipeline = _open_pipeline(
        config, gate, on_start, on_stop, stop_event, retry_interval_s
    )
    if pipeline is None:
        return
    log.info("listening for records, ready to stream to %s", config.owntone_pipe)
    try:
        while not stop_event.wait(stats_interval_s):
            log.info(
                "pipeline stats: %s gate=%s level=%.1fdBFS",
                pipeline.stats(),
                gate.state.name,
                gate.level_db,
            )
    finally:
        pipeline.stop()
        log.info("final pipeline stats: %s gate=%s", pipeline.stats(), gate.state.name)


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
