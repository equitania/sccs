# SCCS Config Tests
# Tests for configuration loading and validation

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from sccs.config.defaults import DEFAULT_CONFIG, generate_default_config
from sccs.config.loader import _merge_with_defaults, load_config, save_config, validate_config_file
from sccs.config.schema import ItemType, SccsConfig, SyncCategory, SyncMode


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

    def test_load_config_preserves_doctor_override(self, temp_dir: Path, sample_config: dict):
        """User-supplied `doctor:` blocks must survive _merge_with_defaults.

        Regression for a bug where _merge_with_defaults silently dropped the
        entire `doctor` key because it had no merge branch — the resulting
        DoctorConfig fell back to its bundled defaults and every user
        override (plugins, npx_tools, permission_checks, …) was ignored.
        """
        # 24 is deliberately NOT the bundled default (22) so a loader that
        # dropped the doctor block would fall back to 22 and fail this assert.
        sample_config["doctor"] = {
            "min_node_major": 24,
            "plugins": [
                {"name": "skill-creator", "marketplace": "claude-plugins-official"},
            ],
        }
        config_path = temp_dir / "doctor-override.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(sample_config, f, default_flow_style=False)

        config = load_config(config_path)
        assert config.doctor.min_node_major == 24
        assert config.doctor.plugins is not None
        assert [p.name for p in config.doctor.plugins] == ["skill-creator"]

    def test_merge_with_defaults_does_not_mutate_default_config(self, sample_config: dict):
        """Regression: _merge_with_defaults must never poison DEFAULT_CONFIG.

        `result = DEFAULT_CONFIG.copy()` used to be a shallow copy, so
        `result["sync_categories"]` was the SAME dict object as
        `DEFAULT_CONFIG["sync_categories"]`. Merging a user category that
        also exists in the defaults (claude_commands, here, with
        `sample_config`'s temp-dir local_path) then assigned into that
        shared object — permanently overwriting the module-level default
        for the rest of the process. This bug's entire signature was
        invisible except through test *ordering*: the corruption only shows
        up in whichever unrelated test happens to run `load_config()` next.
        """
        before = copy.deepcopy(DEFAULT_CONFIG["sync_categories"]["claude_commands"])

        merged = _merge_with_defaults(sample_config)

        # The merge did pick up the user's override (sanity check the test
        # itself exercises the mutating code path)...
        assert (
            merged["sync_categories"]["claude_commands"]["local_path"]
            == sample_config["sync_categories"]["claude_commands"]["local_path"]
        )
        # ...but the shipped default must be untouched.
        assert DEFAULT_CONFIG["sync_categories"]["claude_commands"] == before

    def test_successive_load_config_calls_do_not_leak_overrides(self, temp_dir: Path):
        """User-visible consequence of the aliasing bug above.

        A first `load_config()` call whose config overrides `claude_commands`
        must not change what a second, unrelated `load_config()` call (with
        no `claude_commands` override at all) sees as the default.

        The override path is deliberately something no `~`-expansion of the
        real default could ever produce (a `poisoned-by-first-config`
        segment, outside `.claude` entirely) — otherwise, under a `HOME` that
        happens to coincide with both configs' base directory, the leaked
        value and the correct default could accidentally be the same string
        and the assertion would pass for the wrong reason.
        """
        overriding_config = {
            "repository": {"path": str(temp_dir / "repo1")},
            "sync_categories": {
                "claude_commands": {
                    "local_path": str(temp_dir / "poisoned-by-first-config"),
                    "repo_path": ".claude/commands",
                    "item_type": "file",
                    "item_pattern": "*.md",
                },
            },
        }
        overriding_path = temp_dir / "overriding.yaml"
        with open(overriding_path, "w", encoding="utf-8") as f:
            yaml.dump(overriding_config, f, default_flow_style=False)
        load_config(overriding_path)  # Poisoned DEFAULT_CONFIG before the fix.

        plain_config = {
            "repository": {"path": str(temp_dir / "repo2")},
            "sync_categories": {
                "claude_skills": {
                    "local_path": "~/.claude/skills",
                    "repo_path": ".claude/skills",
                    "item_type": "directory",
                    "item_marker": "SKILL.md",
                },
            },
        }
        plain_path = temp_dir / "plain.yaml"
        with open(plain_path, "w", encoding="utf-8") as f:
            yaml.dump(plain_config, f, default_flow_style=False)

        second = load_config(plain_path)

        assert second.sync_categories["claude_commands"].local_path == str(Path("~/.claude/commands").expanduser())
        assert "poisoned-by-first-config" not in second.sync_categories["claude_commands"].local_path

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


class TestOptionalBlockPassthrough:
    """Every optional top-level block must survive the defaults merge.

    Regression guard. `_merge_with_defaults` used to carry one hand-written
    branch per block, and a block whose branch nobody added was dropped in
    silence — no error, just settings that had no effect. It happened to
    `doctor:` and again to `pi:` (fixed in v2.53.0). The merge now derives
    the pass-through set from SccsConfig itself; this test fails if that
    ever regresses to an allowlist.
    """

    @pytest.mark.parametrize(
        ("block", "payload", "check"),
        [
            ("statusline", {"active": "builtin"}, lambda c: c.statusline.active == "builtin"),
            ("profiles", {"mine": {"skills": ["x-*"]}}, lambda c: c.profiles["mine"].skills == ["x-*"]),
            ("doctor", {"min_node_major": 24}, lambda c: c.doctor.min_node_major == 24),
            ("pi", {"exclude": ["pi-*"]}, lambda c: c.pi.exclude == ["pi-*"]),
            ("codex", {"exclude": ["cx-*"]}, lambda c: c.codex.exclude == ["cx-*"]),
            ("opencode", {"exclude": ["oc-*"]}, lambda c: c.opencode.exclude == ["oc-*"]),
        ],
    )
    def test_optional_block_reaches_the_model(self, tmp_path, sample_config, block, payload, check):
        cfg = dict(sample_config)
        cfg[block] = payload
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(cfg), encoding="utf-8")

        assert check(load_config(path)), f"{block!r} was dropped by _merge_with_defaults"

    def test_unknown_block_is_still_ignored(self, tmp_path, sample_config):
        """Pass-through is driven by the model, not by 'anything goes'."""
        cfg = dict(sample_config)
        cfg["not_a_real_block"] = {"x": 1}
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(cfg), encoding="utf-8")

        config = load_config(path)
        assert not hasattr(config, "not_a_real_block")


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


class TestRemoteValidation:
    """Block option-like remote names that would trigger git argument injection."""

    @pytest.mark.parametrize(
        "bad_remote",
        [
            "--upload-pack=/tmp/evil",
            "-u",
            "--exec=whoami",
            "origin; rm -rf /",
            "origin space",
            "",
        ],
    )
    def test_rejects_option_like_remote(self, temp_dir: Path, bad_remote: str):
        with pytest.raises(ValidationError):
            SccsConfig(
                repository={"path": str(temp_dir), "remote": bad_remote},
                sync_categories={},
            )

    @pytest.mark.parametrize(
        "good_remote",
        ["origin", "upstream", "fork-2", "my_remote", "remote.prod", "a"],
    )
    def test_accepts_normal_remote(self, temp_dir: Path, good_remote: str):
        config = SccsConfig(
            repository={"path": str(temp_dir), "remote": good_remote},
            sync_categories={},
        )
        assert config.repository.remote == good_remote


class TestSaveStatuslineActive:
    """`sccs statusline use/install` records the chosen preset in config.yaml.

    settings.json is machine state; `statusline.active` is the preference that
    survives a rebuild and is what `doctor install` consults before offering
    the installer (v2.58.2).
    """

    def _write(self, temp_dir: Path, sample_config: dict, statusline: dict | None = None) -> Path:
        if statusline is not None:
            sample_config["statusline"] = statusline
        path = temp_dir / "config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(sample_config, f, default_flow_style=False)
        return path

    def test_writes_the_preset_name(self, temp_dir: Path, sample_config: dict):
        from sccs.config.loader import save_statusline_active

        path = self._write(temp_dir, sample_config)
        result = save_statusline_active("claude-code-statusline", path)

        assert result is not None
        assert result.statusline.active == "claude-code-statusline"
        with open(path, encoding="utf-8") as f:
            assert yaml.safe_load(f)["statusline"]["active"] == "claude-code-statusline"

    def test_keeps_user_presets_in_the_block(self, temp_dir: Path, sample_config: dict):
        """Only `active` may change — a custom preset must survive the write."""
        from sccs.config.loader import save_statusline_active

        path = self._write(
            temp_dir,
            sample_config,
            {"active": "builtin", "presets": {"mine": {"command": "/my/own", "description": "x"}}},
        )
        save_statusline_active("claude-code-statusline", path)

        with open(path, encoding="utf-8") as f:
            block = yaml.safe_load(f)["statusline"]
        assert block["active"] == "claude-code-statusline"
        assert block["presets"]["mine"]["command"] == "/my/own"

    def test_unchanged_value_is_a_no_op(self, temp_dir: Path, sample_config: dict):
        """Re-serializing YAML drops the user's comments — so don't rewrite
        the file when the value is already what we would write."""
        from sccs.config.loader import save_statusline_active

        path = self._write(temp_dir, sample_config, {"active": "builtin"})
        before = path.read_bytes()

        assert save_statusline_active("builtin", path) is None
        assert path.read_bytes() == before

    def test_missing_config_file_is_not_an_error(self, temp_dir: Path):
        """Setting a statusline must not fail just because config.yaml is absent."""
        from sccs.config.loader import save_statusline_active

        assert save_statusline_active("builtin", temp_dir / "nope.yaml") is None
