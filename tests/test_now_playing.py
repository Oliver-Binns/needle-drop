"""Tests for synthetic now-playing metadata rotation."""

from __future__ import annotations

import threading
import time

from needledrop.now_playing import MetadataRotator, NowPlayingController


def test_metadata_rotator_advances_each_field_on_its_own_interval():
    rotator = MetadataRotator(
        title_options=("t1", "t2"),
        artist_options=("a1", "a2"),
        album_options=("l1", "l2"),
        title_interval_s=10,
        artist_interval_s=30,
        album_interval_s=30,
    )
    rotator.reset(0.0)

    assert rotator.current().title == "t1"
    assert rotator.current().artist == "a1"
    assert rotator.current().album == "l1"

    assert rotator.advance_if_due(9.9) is None
    assert rotator.advance_if_due(10.0).title == "t2"
    assert rotator.current().artist == "a1"
    assert rotator.current().album == "l1"

    updated = rotator.advance_if_due(30.0)
    assert updated is not None
    assert updated.artist == "a2"
    assert updated.album == "l2"


class AdjustableClock:
    def __init__(self, initial: float = 0.0) -> None:
        self._now = initial
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, delta: float) -> None:
        with self._lock:
            self._now += delta


class FakeOwnToneClient:
    def __init__(self) -> None:
        self.set_calls: list[tuple[str, str, str, str | None]] = []
        self.clear_calls = 0

    def set_now_playing_metadata(
        self, *, title: str, artist: str, album: str, artwork_url: str | None
    ) -> None:
        self.set_calls.append((title, artist, album, artwork_url))

    def clear_now_playing_metadata(self) -> None:
        self.clear_calls += 1


def test_now_playing_controller_sets_rotates_and_clears_metadata():
    clock = AdjustableClock()
    client = FakeOwnToneClient()
    rotator = MetadataRotator(
        title_options=("title-1", "title-2"),
        artist_options=("artist-1", "artist-2"),
        album_options=("album-1", "album-2"),
        title_interval_s=1.0,
        artist_interval_s=3.0,
        album_interval_s=3.0,
    )
    controller = NowPlayingController(
        client,
        rotator,
        artwork_url="file:///tmp/artwork.png",
        clock=clock,
        poll_interval_s=0.01,
    )

    controller.start_streaming()
    time.sleep(0.05)
    assert client.set_calls[0] == (
        "title-1",
        "artist-1",
        "album-1",
        "file:///tmp/artwork.png",
    )

    clock.advance(1.1)
    time.sleep(0.05)
    assert any(call[0] == "title-2" for call in client.set_calls)

    clock.advance(2.0)
    time.sleep(0.05)
    assert any(
        call[1] == "artist-2" and call[2] == "album-2" for call in client.set_calls
    )

    controller.stop_streaming()
    assert client.clear_calls == 1
