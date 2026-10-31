"""Temporary executable entrypoint for `python -m needledrop`."""

from __future__ import annotations

import signal
import threading


def _make_stop_handler(stop_event: threading.Event):
    def _stop_handler(_signum: int, _frame) -> None:
        stop_event.set()

    return _stop_handler


def main() -> None:
    stop_event = threading.Event()
    stop_handler = _make_stop_handler(stop_event)

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    print("needle-drop placeholder service running", flush=True)
    while not stop_event.wait(timeout=5):
        pass
    print("needle-drop placeholder service stopping", flush=True)


if __name__ == "__main__":
    main()
