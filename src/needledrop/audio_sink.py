"""Hand-off of audio to OwnTone through a named pipe."""

from __future__ import annotations

import errno
import os
from typing import Protocol


class AudioSink(Protocol):
    def write(self, data: bytes) -> int:
        """Accept as much of ``data`` as possible without blocking.

        Returns the number of bytes accepted (0 if the receiver isn't ready).
        """

    def close(self) -> None: ...


class PipeSink:
    """Non-blocking writer for a named pipe (FIFO).

    The pipe is opened lazily and re-opened if the reader goes away, so the
    program tolerates OwnTone not being ready yet.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._fd: int | None = None

    def _open(self) -> bool:
        try:
            self._fd = os.open(self._path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno in (errno.ENXIO, errno.ENOENT):
                return False  # no reader yet, or pipe not created yet
            raise
        return True

    def write(self, data: bytes) -> int:
        if self._fd is None and not self._open():
            return 0
        try:
            return os.write(self._fd, data)
        except BlockingIOError:
            return 0
        except BrokenPipeError:
            self.close()
            return 0

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
