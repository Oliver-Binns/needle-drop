"""Capture audio and pass it on to the sink without ever dropping it silently."""

from __future__ import annotations

import threading
import time
from collections import deque

from needledrop.audio_sink import AudioSink
from needledrop.audio_source import AudioSource


class AudioPipeline:
    """source -> time-bounded in-memory queue -> sink.

    Capture never waits for the sink, so the sound card buffer can't overrun.
    Audio is sent in order and byte-for-byte unchanged. Bytes that cannot be
    delivered (queue limit exceeded, or still queued when ``stop`` gives up)
    are counted in ``undelivered_bytes``, which should always be zero.
    """

    def __init__(
        self,
        source: AudioSource,
        sink: AudioSink,
        bytes_per_second: int,
        queue_limit_s: float = 30.0,
        drain_timeout_s: float = 10.0,
        retry_interval_s: float = 0.005,
    ) -> None:
        self._source = source
        self._sink = sink
        self._limit_bytes = int(bytes_per_second * queue_limit_s)
        self._drain_timeout_s = drain_timeout_s
        self._retry_interval_s = retry_interval_s

        self._queue: deque[bytes] = deque()
        self._cond = threading.Condition()
        self._queued_bytes = 0
        self._undelivered_bytes = 0
        self._delivered_bytes = 0
        self._capture_done = False
        self._abort = False
        self._capture_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None

    def start(self) -> None:
        self._source.open()
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._send_thread.start()
        self._capture_thread.start()

    def stop(self) -> None:
        """Stop capturing, then deliver everything already queued."""
        with self._cond:
            self._capture_done = True
            self._cond.notify_all()
        self._join(self._capture_thread)
        self.wait_until_drained()
        self._source.close()
        self._sink.close()

    def wait_until_drained(self) -> None:
        """Wait for the queue to empty; give up after ``drain_timeout_s``."""
        with self._cond:
            self._capture_done = True
            self._cond.notify_all()
        self._join(self._send_thread, self._drain_timeout_s)
        with self._cond:
            self._abort = True
            self._undelivered_bytes += self._queued_bytes
            self._queued_bytes = 0
            self._queue.clear()
            self._cond.notify_all()
        self._join(self._send_thread)

    def wait_until_finished(self, timeout: float | None = None) -> bool:
        """Block until the source ends and everything is delivered."""
        self._join(self._send_thread, timeout)
        return not self._send_thread.is_alive()

    def stats(self) -> dict[str, int]:
        with self._cond:
            return {
                "queued_bytes": self._queued_bytes,
                "delivered_bytes": self._delivered_bytes,
                "undelivered_bytes": self._undelivered_bytes,
            }

    @staticmethod
    def _join(thread: threading.Thread | None, timeout: float | None = None) -> None:
        if thread is not None:
            thread.join(timeout)

    def _capture_loop(self) -> None:
        try:
            while not self._capture_done:
                chunk = self._source.read()
                if not chunk:
                    break
                with self._cond:
                    if self._queued_bytes + len(chunk) > self._limit_bytes:
                        self._undelivered_bytes += len(chunk)
                        continue
                    self._queue.append(chunk)
                    self._queued_bytes += len(chunk)
                    self._cond.notify()
        finally:
            with self._cond:
                self._capture_done = True
                self._cond.notify_all()

    def _send_loop(self) -> None:
        while True:
            with self._cond:
                while not self._queue:
                    if self._capture_done or self._abort:
                        return
                    self._cond.wait()
                if self._abort:
                    return
                chunk = self._queue[0]

            view = memoryview(chunk)
            while len(view) and not self._abort:
                try:
                    written = self._sink.write(view)
                except OSError:
                    written = 0
                if written:
                    view = view[written:]
                    with self._cond:
                        self._queued_bytes -= written
                        self._delivered_bytes += written
                else:
                    time.sleep(self._retry_interval_s)

            with self._cond:
                if self._abort:
                    return
                self._queue.popleft()
