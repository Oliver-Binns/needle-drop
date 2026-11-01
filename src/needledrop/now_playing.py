"""Helpers for synthetic now-playing metadata shown by OwnTone/AirPlay."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Final

from needledrop.owntone import OwnToneClient

DEFAULT_TITLE_OPTIONS: Final[tuple[str, ...]] = (
    "Now Spinning...",
    "Drop the Needle",
    "Needle in the Groove",
    "Vinyl in Session",
    "Record on Deck",
)
DEFAULT_ARTIST_OPTIONS: Final[tuple[str, ...]] = (
    "Vinyl Record",
    "33 ⅓ RPM",
    "The Turntable",
    "Needle-Drop Ensemble",
)
DEFAULT_ALBUM_OPTIONS: Final[tuple[str, ...]] = (
    "Living Room Sessions",
    "Analogue to AirPlay",
    "HiFi at Home",
    "Side A Stories",
)


@dataclass(frozen=True)
class NowPlayingMetadata:
    """Synthetic metadata payload for OwnTone now-playing updates."""

    title: str
    artist: str
    album: str


class MetadataRotator:
    """Cycle synthetic now-playing title/artist/album at different intervals."""

    def __init__(
        self,
        *,
        title_options: tuple[str, ...],
        artist_options: tuple[str, ...],
        album_options: tuple[str, ...],
        title_interval_s: float,
        artist_interval_s: float,
        album_interval_s: float,
    ) -> None:
        if not title_options or not artist_options or not album_options:
            raise ValueError("title/artist/album options must not be empty")
        if title_interval_s <= 0 or artist_interval_s <= 0 or album_interval_s <= 0:
            raise ValueError("metadata rotation intervals must be > 0")

        self._title_options = title_options
        self._artist_options = artist_options
        self._album_options = album_options
        self._title_interval_s = title_interval_s
        self._artist_interval_s = artist_interval_s
        self._album_interval_s = album_interval_s

        self._title_index = 0
        self._artist_index = 0
        self._album_index = 0
        self._next_title_at = 0.0
        self._next_artist_at = 0.0
        self._next_album_at = 0.0

    def reset(self, now: float) -> None:
        """Reset rotation to first values and schedule next updates."""
        self._title_index = 0
        self._artist_index = 0
        self._album_index = 0
        self._next_title_at = now + self._title_interval_s
        self._next_artist_at = now + self._artist_interval_s
        self._next_album_at = now + self._album_interval_s

    def current(self) -> NowPlayingMetadata:
        """Return current metadata without advancing."""
        return NowPlayingMetadata(
            title=self._title_options[self._title_index],
            artist=self._artist_options[self._artist_index],
            album=self._album_options[self._album_index],
        )

    def advance_if_due(self, now: float) -> NowPlayingMetadata | None:
        """Advance any fields whose update time has passed."""
        changed = False

        while now >= self._next_title_at:
            self._title_index = (self._title_index + 1) % len(self._title_options)
            self._next_title_at += self._title_interval_s
            changed = True

        while now >= self._next_artist_at:
            self._artist_index = (self._artist_index + 1) % len(self._artist_options)
            self._next_artist_at += self._artist_interval_s
            changed = True

        while now >= self._next_album_at:
            self._album_index = (self._album_index + 1) % len(self._album_options)
            self._next_album_at += self._album_interval_s
            changed = True

        if not changed:
            return None
        return self.current()


class NowPlayingController:
    """Drive periodic OwnTone now-playing updates while streaming is active."""

    def __init__(
        self,
        client: OwnToneClient,
        rotator: MetadataRotator,
        *,
        artwork_url: str | None,
        clock=time.monotonic,
        poll_interval_s: float = 1.0,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        self._client = client
        self._rotator = rotator
        self._artwork_url = artwork_url
        self._clock = clock
        self._poll_interval_s = poll_interval_s
        self._lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        self._thread: threading.Thread | None = None

    def start_streaming(self) -> None:
        """Publish initial metadata and start periodic rotation updates."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._rotator.reset(self._clock())
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run_rotation_loop,
                args=(stop_event,),
                daemon=True,
            )
            self._stop_event = stop_event
            self._thread = worker

        self._publish(self._rotator.current())
        worker.start()

    def stop_streaming(self) -> None:
        """Stop periodic updates and clear now-playing metadata."""
        stop_event = None
        worker = None
        with self._lock:
            stop_event = self._stop_event
            worker = self._thread
            self._stop_event = None
            self._thread = None

        if stop_event is not None:
            stop_event.set()
        if worker is not None:
            worker.join(timeout=2.0)

        self._client.clear_now_playing_metadata()

    def _run_rotation_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(self._poll_interval_s):
            metadata = self._rotator.advance_if_due(self._clock())
            if metadata is not None:
                self._publish(metadata)

    def _publish(self, metadata: NowPlayingMetadata) -> None:
        self._client.set_now_playing_metadata(
            title=metadata.title,
            artist=metadata.artist,
            album=metadata.album,
            artwork_url=self._artwork_url,
        )
