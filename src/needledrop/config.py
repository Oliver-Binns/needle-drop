"""Settings file reader for needle-drop.

Loads configuration from two layers:
1. config/default.yaml (default settings, committed)
2. /etc/needle-drop/config.yaml (device-specific overrides, not committed)

Missing keys in the device file fall back to defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Config:
    """Typed configuration container.

    All values are optional to allow partial overrides, but runtime
    validation ensures critical fields are present.
    """

    # Gate behavior: timing in seconds
    start_delay_s: float
    stop_delay_s: float
    preroll_s: float
    fade_out_s: float

    # Detection thresholds
    start_level: float
    stop_level: float

    # Audio processing
    filter_type: str | None
    filter_freq_hz: float

    # OwnTone connection
    owntone_pipe: str
    queue_limit_s: float
    owntone_timeout_s: float

    # Speaker configuration
    speaker_name: str | None
    start_volume: float | None

    # Now-playing metadata
    now_playing_artwork_path: str
    now_playing_title_interval_s: float
    now_playing_artist_interval_s: float
    now_playing_album_interval_s: float

    # Audio parameters
    sample_rate_hz: int
    bit_depth: int
    channels: int

    # Status page
    status_port: int

    # Logging
    log_level: str

    def validate(self) -> None:
        """Validate critical constraints.

        Raises:
            ValueError: If validation fails.
        """
        if self.preroll_s < self.start_delay_s + 0.5:
            raise ValueError(
                f"preroll_s ({self.preroll_s}) must be >= start_delay_s ({self.start_delay_s}) + 0.5. "
                "Pre-roll exists to cover the start delay so no audio is lost."
            )
        if (
            self.now_playing_title_interval_s <= 0
            or self.now_playing_artist_interval_s <= 0
            or self.now_playing_album_interval_s <= 0
        ):
            raise ValueError("now-playing rotation intervals must be greater than zero")


def _get_project_root() -> Path:
    """Get the project root directory.

    Assumes this module is at src/needledrop/config.py, so the root
    is three levels up.
    """
    return Path(__file__).parent.parent.parent


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file safely.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed YAML content as a dictionary.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        yaml.YAMLError: If the YAML is malformed.
    """
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data if data is not None else {}


def _dict_to_config(data: dict[str, Any]) -> Config:
    """Convert a dictionary to a Config object.

    Args:
        data: Dictionary with configuration keys.

    Returns:
        Config object with validated values.

    Raises:
        KeyError: If a required key is missing.
        TypeError: If a value has an unexpected type.
    """
    return Config(
        start_delay_s=float(data["start_delay_s"]),
        stop_delay_s=float(data["stop_delay_s"]),
        preroll_s=float(data["preroll_s"]),
        fade_out_s=float(data["fade_out_s"]),
        start_level=float(data["start_level"]),
        stop_level=float(data["stop_level"]),
        filter_type=data.get("filter_type"),
        filter_freq_hz=float(data["filter_freq_hz"]),
        owntone_pipe=str(data["owntone_pipe"]),
        queue_limit_s=float(data["queue_limit_s"]),
        owntone_timeout_s=float(data["owntone_timeout_s"]),
        speaker_name=data.get("speaker_name"),
        start_volume=float(data["start_volume"])
        if data.get("start_volume") is not None
        else None,
        now_playing_artwork_path=str(data["now_playing_artwork_path"]),
        now_playing_title_interval_s=float(data["now_playing_title_interval_s"]),
        now_playing_artist_interval_s=float(data["now_playing_artist_interval_s"]),
        now_playing_album_interval_s=float(data["now_playing_album_interval_s"]),
        sample_rate_hz=int(data["sample_rate_hz"]),
        bit_depth=int(data["bit_depth"]),
        channels=int(data["channels"]),
        status_port=int(data["status_port"]),
        log_level=str(data["log_level"]),
    )


def load_config() -> Config:
    """Load and merge configuration from default and device-specific files.

    Loads defaults from config/default.yaml (relative to project root), then
    optionally applies device-specific overrides from /etc/needle-drop/config.yaml.

    Returns:
        Config object with merged settings and validated constraints.

    Raises:
        FileNotFoundError: If the default config file doesn't exist.
        yaml.YAMLError: If either config file has invalid YAML syntax.
        ValueError: If validation fails.
        KeyError: If required fields are missing from the merged config.
    """
    # Load defaults
    project_root = _get_project_root()
    default_path = project_root / "config" / "default.yaml"

    if not default_path.exists():
        raise FileNotFoundError(f"Default config file not found at {default_path}")

    config_data = _load_yaml_file(default_path)

    # Load and merge device overrides (if present)
    device_path = Path("/etc/needle-drop/config.yaml")
    if device_path.exists():
        device_data = _load_yaml_file(device_path)
        config_data.update(device_data)

    # Convert to Config object
    config = _dict_to_config(config_data)

    # Validate critical constraints
    config.validate()

    return config
