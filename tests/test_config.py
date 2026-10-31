"""Tests for the settings file reader."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from needledrop.config import Config, load_config


@pytest.fixture
def default_config_data() -> dict:
    """Default configuration data matching config/default.yaml."""
    return {
        "start_delay_s": 1.0,
        "stop_delay_s": 25.0,
        "preroll_s": 1.5,
        "fade_out_s": 0.0,
        "start_level": -40.0,
        "stop_level": -50.0,
        "filter_type": None,
        "filter_freq_hz": 3000,
        "owntone_pipe": "/srv/music/vinyl.pipe",
        "queue_limit_s": 30,
        "owntone_timeout_s": 10,
        "speaker_name": None,
        "start_volume": None,
        "sample_rate_hz": 44100,
        "bit_depth": 16,
        "channels": 2,
        "status_port": 8099,
        "log_level": "INFO",
    }


class TestConfigLoading:
    """Tests for loading configuration files."""

    def test_load_default_config(self, default_config_data):
        """Test that the default config file loads successfully."""
        config = load_config()
        assert config.start_delay_s == default_config_data["start_delay_s"]
        assert config.stop_delay_s == default_config_data["stop_delay_s"]
        assert config.preroll_s == default_config_data["preroll_s"]
        assert config.start_level == default_config_data["start_level"]
        assert config.owntone_pipe == default_config_data["owntone_pipe"]
        assert config.status_port == default_config_data["status_port"]

    def test_config_has_all_required_fields(self):
        """Test that loaded config has all expected fields."""
        config = load_config()
        assert isinstance(config, Config)
        assert hasattr(config, "start_delay_s")
        assert hasattr(config, "stop_delay_s")
        assert hasattr(config, "preroll_s")
        assert hasattr(config, "start_level")
        assert hasattr(config, "stop_level")
        assert hasattr(config, "filter_type")
        assert hasattr(config, "owntone_pipe")
        assert hasattr(config, "speaker_name")
        assert hasattr(config, "sample_rate_hz")
        assert hasattr(config, "status_port")


class TestConfigMerging:
    """Tests for merging device overrides with defaults."""

    def test_device_override_single_value(self, default_config_data):
        """Test that device config can override a single setting."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            device_data = {"speaker_name": "HomePod"}
            yaml.dump(device_data, f)
            device_path = Path(f.name)

        try:
            with patch("needledrop.config.Path") as mock_path:

                def side_effect(arg):
                    if arg == "/etc/needle-drop/config.yaml":
                        return device_path
                    return Path(arg)

                mock_path.side_effect = side_effect

                # Also patch _get_project_root to use the real implementation
                config = load_config()
                assert config.speaker_name == "HomePod"
                # Other values should still come from defaults
                assert config.start_delay_s == default_config_data["start_delay_s"]
        finally:
            device_path.unlink()

    def test_device_override_multiple_values(self, default_config_data):
        """Test that device config can override multiple settings."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            device_data = {
                "speaker_name": "Kitchen HomePod",
                "start_volume": 75,
                "start_level": -35.0,
            }
            yaml.dump(device_data, f)
            device_path = Path(f.name)

        try:
            with patch("needledrop.config.Path") as mock_path:

                def side_effect(arg):
                    if arg == "/etc/needle-drop/config.yaml":
                        return device_path
                    return Path(arg)

                mock_path.side_effect = side_effect

                config = load_config()
                assert config.speaker_name == "Kitchen HomePod"
                assert config.start_volume == 75.0
                assert config.start_level == -35.0
                # Non-overridden values still from defaults
                assert config.stop_delay_s == default_config_data["stop_delay_s"]
        finally:
            device_path.unlink()

    def test_missing_device_config_uses_defaults(self, default_config_data):
        """Test that missing device config file doesn't break loading."""
        # Path that doesn't exist
        with patch("needledrop.config.Path") as mock_path:

            def side_effect(arg):
                if arg == "/etc/needle-drop/config.yaml":
                    # Return a Path object that reports not existing
                    mock_device_path = Path("/nonexistent/path")
                    return mock_device_path
                return Path(arg)

            mock_path.side_effect = side_effect

            config = load_config()
            # Should load all defaults successfully
            assert config.start_delay_s == default_config_data["start_delay_s"]
            assert config.speaker_name is None


class TestConfigValidation:
    """Tests for configuration validation."""

    def test_preroll_greater_than_start_delay_plus_half(self):
        """Test that preroll_s >= start_delay_s + 0.5 is enforced."""
        config = load_config()
        # This should pass because default config is valid
        assert config.preroll_s >= config.start_delay_s + 0.5

    def test_preroll_validation_fails_when_too_small(self, default_config_data):
        """Test that validation fails if preroll_s is too small."""
        config_data = default_config_data.copy()
        config_data["preroll_s"] = 1.0  # start_delay_s + 0.5 = 1.5, so 1.0 is too small

        config = Config(**config_data)
        with pytest.raises(ValueError, match="preroll_s"):
            config.validate()

    def test_preroll_validation_passes_at_boundary(self, default_config_data):
        """Test that preroll_s exactly at the minimum is valid."""
        config_data = default_config_data.copy()
        config_data["preroll_s"] = (
            config_data["start_delay_s"] + 0.5
        )  # Exactly at minimum

        config = Config(**config_data)
        config.validate()  # Should not raise

    def test_preroll_validation_passes_above_minimum(self, default_config_data):
        """Test that preroll_s above the minimum is valid."""
        config_data = default_config_data.copy()
        config_data["preroll_s"] = config_data["start_delay_s"] + 1.0  # Above minimum

        config = Config(**config_data)
        config.validate()  # Should not raise


class TestConfigTypes:
    """Tests for correct type handling."""

    def test_numeric_fields_are_floats(self):
        """Test that timing fields are correctly typed as floats."""
        config = load_config()
        assert isinstance(config.start_delay_s, float)
        assert isinstance(config.stop_delay_s, float)
        assert isinstance(config.preroll_s, float)
        assert isinstance(config.fade_out_s, float)

    def test_level_fields_are_floats(self):
        """Test that level fields are correctly typed as floats."""
        config = load_config()
        assert isinstance(config.start_level, float)
        assert isinstance(config.stop_level, float)

    def test_audio_fields_are_ints(self):
        """Test that audio parameter fields are correctly typed as ints."""
        config = load_config()
        assert isinstance(config.sample_rate_hz, int)
        assert isinstance(config.bit_depth, int)
        assert isinstance(config.channels, int)
        assert isinstance(config.status_port, int)

    def test_string_fields_are_strings(self):
        """Test that string fields are correctly typed."""
        config = load_config()
        assert isinstance(config.owntone_pipe, str)
        assert isinstance(config.log_level, str)

    def test_optional_fields_can_be_none(self):
        """Test that optional fields can be None."""
        config = load_config()
        # These are optional in the default config
        assert config.speaker_name is None or isinstance(config.speaker_name, str)
        assert config.start_volume is None or isinstance(config.start_volume, float)
        assert config.filter_type is None or isinstance(config.filter_type, str)


class TestConfigErrors:
    """Tests for error handling."""

    def test_missing_default_config_raises_error(self):
        """Test that missing default config file raises FileNotFoundError."""
        with patch("needledrop.config._get_project_root") as mock_root:
            # Point to a nonexistent directory
            mock_root.return_value = Path("/nonexistent/project")
            with pytest.raises(FileNotFoundError):
                load_config()

    def test_invalid_yaml_in_default_config_raises_error(self):
        """Test that invalid YAML in default config raises an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "config"
            config_dir.mkdir()

            # Write invalid YAML
            invalid_yaml = config_dir / "default.yaml"
            invalid_yaml.write_text("start_delay_s: 1.0\n  invalid: [unclosed list")

            with patch("needledrop.config._get_project_root") as mock_root:
                mock_root.return_value = tmpdir_path
                with pytest.raises(yaml.YAMLError):
                    load_config()

    def test_invalid_yaml_in_device_config_raises_error(self):
        """Test that invalid YAML in device config raises an error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            # Write invalid YAML
            f.write("speaker_name: HomePod\n  invalid: [unclosed list")
            device_path = Path(f.name)

        try:
            with patch("needledrop.config.Path") as mock_path:

                def side_effect(arg):
                    if arg == "/etc/needle-drop/config.yaml":
                        return device_path
                    return Path(arg)

                mock_path.side_effect = side_effect

                with pytest.raises(yaml.YAMLError):
                    load_config()
        finally:
            device_path.unlink()

    def test_missing_required_field_raises_error(self, default_config_data):
        """Test that missing a required field raises TypeError."""
        incomplete_data = default_config_data.copy()
        del incomplete_data["start_delay_s"]

        with pytest.raises(TypeError):
            Config(**incomplete_data)


class TestConfigDataclass:
    """Tests for the Config dataclass itself."""

    def test_config_can_be_instantiated(self, default_config_data):
        """Test that Config can be created with all required fields."""
        config = Config(**default_config_data)
        assert config.start_delay_s == default_config_data["start_delay_s"]

    def test_config_equality(self, default_config_data):
        """Test that two Config objects with same data are equal."""
        config1 = Config(**default_config_data)
        config2 = Config(**default_config_data)
        assert config1 == config2

    def test_config_repr(self, default_config_data):
        """Test that Config has a useful string representation."""
        config = Config(**default_config_data)
        repr_str = repr(config)
        assert "Config" in repr_str
        assert "start_delay_s" in repr_str
