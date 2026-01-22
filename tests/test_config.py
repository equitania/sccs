# SCCS Config Tests
# Tests for configuration loading and validation

from pathlib import Path

import pytest
import yaml

from sccs.config.schema import SccsConfig, SyncCategory, SyncMode, ItemType
from sccs.config.loader import load_config, save_config, validate_config_file
from sccs.config.defaults import DEFAULT_CONFIG, generate_default_config


class TestSccsConfig:
    """Tests for SccsConfig schema."""

    def test_minimal_config(self, temp_dir: Path):
        """Test minimal valid configuration."""
        config = SccsConfig(
            repository={"path": str(temp_dir)},
            sync_categories={},
        )
        assert config.repository.path == str(temp_dir)
        assert len(config.sync_categories) == 0

    def test_full_config(self, sample_config: dict):
        """Test full configuration loading."""
        config = SccsConfig.model_validate(sample_config)

        assert config.repository.auto_commit is False
        assert "claude_framework" in config.sync_categories
        assert "claude_skills" in config.sync_categories

    def test_get_enabled_categories(self, sample_config: dict):
        """Test getting only enabled categories."""
        config = SccsConfig.model_validate(sample_config)
        enabled = config.get_enabled_categories()

        assert "claude_framework" in enabled
        assert "claude_skills" in enabled

    def test_sync_mode_enum(self):
        """Test sync mode enum values."""
        assert SyncMode.BIDIRECTIONAL.value == "bidirectional"
        assert SyncMode.LOCAL_TO_REPO.value == "local_to_repo"
        assert SyncMode.REPO_TO_LOCAL.value == "repo_to_local"

    def test_item_type_enum(self):
        """Test item type enum values."""
        assert ItemType.FILE.value == "file"
        assert ItemType.DIRECTORY.value == "directory"
        assert ItemType.MIXED.value == "mixed"


class TestSyncCategory:
    """Tests for SyncCategory schema."""

    def test_category_defaults(self):
        """Test category with default values."""
        cat = SyncCategory(
            local_path="~/.claude",
            repo_path=".claude",
        )
        assert cat.enabled is True
        assert cat.sync_mode == SyncMode.BIDIRECTIONAL
        assert cat.item_type == ItemType.FILE

    def test_category_with_marker(self):
        """Test directory category with marker."""
        cat = SyncCategory(
            local_path="~/.claude/skills",
            repo_path=".claude/skills",
            item_type=ItemType.DIRECTORY,
            item_marker="SKILL.md",
        )
        assert cat.item_marker == "SKILL.md"

    def test_path_expansion(self, temp_home: Path):
        """Test that ~ is expanded in paths."""
        cat = SyncCategory(
            local_path="~/.claude",
            repo_path=".claude",
        )
        # Path should be expanded
        assert "~" not in cat.local_path


class TestConfigLoader:
    """Tests for config loading and saving."""

    def test_load_config(self, config_file: Path, monkeypatch: pytest.MonkeyPatch):
        """Test loading configuration from file."""
        monkeypatch.setenv("SCCS_CONFIG", str(config_file))

        config = load_config(config_file)
        assert config is not None
        assert "claude_framework" in config.sync_categories

    def test_load_missing_config(self, temp_dir: Path):
        """Test loading missing configuration."""
        with pytest.raises(FileNotFoundError):
            load_config(temp_dir / "nonexistent.yaml")

    def test_save_config(self, temp_dir: Path, sample_config: dict):
        """Test saving configuration."""
        config = SccsConfig.model_validate(sample_config)
        config_path = temp_dir / "test_config.yaml"

        save_config(config, config_path)

        assert config_path.exists()

        # Load and verify
        with open(config_path, encoding="utf-8") as f:
            saved = yaml.safe_load(f)

        assert "repository" in saved
        assert "sync_categories" in saved

    def test_validate_valid_config(self, config_file: Path):
        """Test validating a valid configuration."""
        is_valid, errors = validate_config_file(config_file)
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_invalid_yaml(self, temp_dir: Path):
        """Test validating invalid YAML."""
        bad_file = temp_dir / "bad.yaml"
        bad_file.write_text("{ invalid yaml [", encoding="utf-8")

        is_valid, errors = validate_config_file(bad_file)
        assert is_valid is False
        assert len(errors) > 0


class TestDefaults:
    """Tests for default configuration."""

    def test_default_config_structure(self):
        """Test default config has required structure."""
        assert "repository" in DEFAULT_CONFIG
        assert "sync_categories" in DEFAULT_CONFIG
        assert "global_exclude" in DEFAULT_CONFIG

    def test_default_categories(self):
        """Test default categories exist."""
        categories = DEFAULT_CONFIG["sync_categories"]

        assert "claude_framework" in categories
        assert "claude_skills" in categories
        assert "claude_commands" in categories
        assert "fish_config" in categories

    def test_generate_default_config(self):
        """Test YAML generation."""
        yaml_str = generate_default_config()

        assert "repository:" in yaml_str
        assert "sync_categories:" in yaml_str
        assert "claude_framework:" in yaml_str

        # Should be valid YAML
        parsed = yaml.safe_load(yaml_str)
        assert parsed is not None
        assert "repository" in parsed
