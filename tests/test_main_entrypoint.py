import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from needledrop.__main__ import _make_stop_handler, main


def test_main_is_callable():
    assert callable(main)


def test_stop_handler_sets_event():
    stop_event = threading.Event()
    stop_handler = _make_stop_handler(stop_event)

    stop_handler(0, None)

    assert stop_event.is_set()
