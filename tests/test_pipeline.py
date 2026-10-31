import os
import threading
import time

from needledrop.audio_sink import PipeSink
from needledrop.pipeline import AudioPipeline

BPS = 44100 * 4


class FakeSource:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def open(self):
        pass

    def read(self):
        return next(self._chunks, b"")

    def close(self):
        pass


class CollectingSink:
    """Accepts at most `max_write` bytes per call; refuses until `ready_after` calls."""

    def __init__(self, max_write=None, ready_after=0, delay=0.0):
        self.data = bytearray()
        self.max_write = max_write
        self.calls = 0
        self.ready_after = ready_after
        self.delay = delay

    def write(self, data):
        self.calls += 1
        if self.calls <= self.ready_after:
            return 0
        time.sleep(self.delay)
        n = len(data) if self.max_write is None else min(len(data), self.max_write)
        self.data += bytes(data[:n])
        return n

    def close(self):
        pass


def make_chunks(count=200, size=4096):
    return [bytes([i % 251]) * size for i in range(count)]


def run(chunks, sink, **kwargs):
    pipeline = AudioPipeline(FakeSource(chunks), sink, BPS, **kwargs)
    pipeline.start()
    assert pipeline.wait_until_finished(timeout=20)
    pipeline.stop()
    return pipeline


def test_bytes_pass_through_unchanged_and_in_order():
    chunks = make_chunks()
    sink = CollectingSink()
    pipeline = run(chunks, sink)
    assert bytes(sink.data) == b"".join(chunks)
    assert pipeline.stats()["undelivered_bytes"] == 0


def test_slow_partial_sink_loses_nothing():
    chunks = make_chunks(50)
    sink = CollectingSink(max_write=1000, ready_after=20, delay=0.0005)
    pipeline = run(chunks, sink)
    assert bytes(sink.data) == b"".join(chunks)
    stats = pipeline.stats()
    assert stats["undelivered_bytes"] == 0
    assert stats["queued_bytes"] == 0


def test_queue_overflow_is_counted():
    chunks = make_chunks(10, 1000)
    sink = CollectingSink(ready_after=10**9)  # never accepts
    pipeline = AudioPipeline(
        FakeSource(chunks),
        sink,
        bytes_per_second=1000,
        queue_limit_s=3.5,
        drain_timeout_s=0.1,
    )
    pipeline.start()
    time.sleep(0.3)
    pipeline.stop()
    stats = pipeline.stats()
    assert stats["delivered_bytes"] == 0
    assert stats["undelivered_bytes"] == 10_000


def test_named_pipe_with_late_slow_reader(tmp_path):
    path = str(tmp_path / "vinyl.pipe")
    os.mkfifo(path)
    chunks = make_chunks(100, 4096)
    expected = b"".join(chunks)
    received = bytearray()

    def reader():
        time.sleep(0.2)  # OwnTone not ready yet
        fd = os.open(path, os.O_RDONLY)
        while len(received) < len(expected):
            received.extend(os.read(fd, 1000))
            time.sleep(0.0005)
        os.close(fd)

    thread = threading.Thread(target=reader)
    thread.start()
    pipeline = run(chunks, PipeSink(path))
    thread.join(timeout=20)
    assert bytes(received) == expected
    assert pipeline.stats()["undelivered_bytes"] == 0


def test_missing_pipe_is_tolerated(tmp_path):
    sink = PipeSink(str(tmp_path / "nope.pipe"))
    assert sink.write(b"abc") == 0
