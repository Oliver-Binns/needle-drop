"""Audio capture from the sound card."""

from __future__ import annotations

from typing import Protocol


class AudioSource(Protocol):
    def open(self) -> None: ...

    def read(self) -> bytes:
        """Block until the next chunk is available. Empty bytes means end of stream."""

    def close(self) -> None: ...


class PyAudioSource:
    """Reads raw PCM straight from a sound card device (Raspberry Pi only)."""

    def __init__(
        self,
        sample_rate_hz: int = 44100,
        channels: int = 2,
        bit_depth: int = 16,
        chunk_frames: int = 1024,
        device_index: int | None = None,
    ) -> None:
        if bit_depth != 16:
            raise ValueError("only 16-bit capture is supported")
        self._rate = sample_rate_hz
        self._channels = channels
        self._chunk_frames = chunk_frames
        self._device_index = device_index
        self._pa = None
        self._stream = None

    def open(self) -> None:
        import pyaudio  # imported lazily: only installed on the Pi

        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._rate,
            input=True,
            input_device_index=self._device_index,
            frames_per_buffer=self._chunk_frames,
        )

    def read(self) -> bytes:
        # Don't raise on overflow; the data is still returned.
        return self._stream.read(self._chunk_frames, exception_on_overflow=False)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
