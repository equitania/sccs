# SCCS Settings Ensure Tests
# Tests for non-destructive JSON merge logic

import json
from pathlib import Path

import pytest

from sccs.config.schema import SettingsEnsure
from sccs.sync.settings import ensure_settings


@pytest.fixture
def settings_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for settings files."""
    d = tmp_path / ".claude"
    d.mkdir()
    return d


@pytest.fixture
def settings_file(settings_dir: Path) -> Path:
    """Create a settings.json with existing content."""
    f = settings_dir / "settings.json"
    f.write_text(json.dumps({"existingKey": "existingValue"}, indent=2) + "\n", encoding="utf-8")
    return f


def _make_config(target: Path, entries: dict, **kwargs) -> SettingsEnsure:
    """Helper to create SettingsEnsure config."""
    return SettingsEnsure(
        target_file=str(target),
        entries=entries,
        create_if_missing=kwargs.get("create_if_missing", True),
        backup_before_modify=kwargs.get("backup_before_modify", True),
    )


class TestAddMissingKey:
    """Test that missing keys are inserted."""

    def test_add_missing_key(self, settings_file: Path) -> None:
        config = _make_config(settings_file, {"statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}})
        result = ensure_settings(config)

        assert result.success
        assert "statusLine" in result.keys_added
        assert result.file_modified

        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["statusLine"] == {"type": "command", "command": "~/.claude/statusline.sh"}
        assert data["existingKey"] == "existingValue"


class TestSkipExistingKey:
    """Test that existing keys are never overwritten."""

    def test_skip_existing_key(self, settings_file: Path) -> None:
        config = _make_config(settings_file, {"existingKey": "newValue"})
        result = ensure_settings(config)

        assert result.success
        assert "existingKey" in result.keys_skipped
        assert not result.file_modified

        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["existingKey"] == "existingValue"

    def test_skip_existing_key_different_value(self, settings_file: Path) -> None:
        config = _make_config(settings_file, {"existingKey": {"completely": "different"}})
        result = ensure_settings(config)

        assert result.success
        assert "existingKey" in result.keys_skipped
        assert not result.file_modified

        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["existingKey"] == "existingValue"


class TestCreateFile:
    """Test file creation behavior."""

    def test_create_file_when_missing(self, settings_dir: Path) -> None:
        target = settings_dir / "new_settings.json"
        config = _make_config(target, {"statusLine": {"type": "command"}})
        result = ensure_settings(config)

        assert result.success
        assert result.file_created
        assert result.file_modified
        assert "statusLine" in result.keys_added

        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["statusLine"] == {"type": "command"}

    def test_no_create_when_disabled(self, settings_dir: Path) -> None:
        target = settings_dir / "nonexistent.json"
        config = _make_config(target, {"key": "val"}, create_if_missing=False)
        result = ensure_settings(config)

        assert result.success
        assert not result.file_created
        assert not result.file_modified
        assert not target.exists()


class TestErrorHandling:
    """Test error handling for malformed files."""

    def test_malformed_json_error(self, settings_dir: Path) -> None:
        target = settings_dir / "broken.json"
        target.write_text("{not valid json", encoding="utf-8")

        config = _make_config(target, {"key": "val"})
        result = ensure_settings(config)

        assert not result.success
        assert result.error is not None
        assert "Malformed JSON" in result.error

        # File should not be modified
        assert target.read_text(encoding="utf-8") == "{not valid json"

    def test_non_object_json_error(self, settings_dir: Path) -> None:
        target = settings_dir / "array.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")

        config = _make_config(target, {"key": "val"})
        result = ensure_settings(config)

        assert not result.success
        assert result.error is not None
        assert "not an object" in result.error


class TestDryRun:
    """Test dry run behavior."""

    def test_dry_run_no_modifications(self, settings_file: Path) -> None:
        original_content = settings_file.read_text(encoding="utf-8")
        config = _make_config(settings_file, {"newKey": "newValue"})
        result = ensure_settings(config, dry_run=True)

        assert result.success
        assert "newKey" in result.keys_added
        assert result.file_modified  # Reports what would happen

        # File must not have changed
        assert settings_file.read_text(encoding="utf-8") == original_content

    def test_dry_run_create_file(self, settings_dir: Path) -> None:
        target = settings_dir / "dry_run_new.json"
        config = _make_config(target, {"key": "val"})
        result = ensure_settings(config, dry_run=True)

        assert result.success
        assert result.file_created
        assert result.file_modified
        assert not target.exists()


class TestBackup:
    """Test backup creation."""

    def test_backup_created(self, settings_file: Path) -> None:
        config = _make_config(settings_file, {"newKey": "newValue"}, backup_before_modify=True)
        result = ensure_settings(config, category_name="test_cat")

        assert result.success
        assert result.backup_path is not None
        assert result.backup_path.exists()

        # Backup should contain original content
        backup_data = json.loads(result.backup_path.read_text(encoding="utf-8"))
        assert backup_data == {"existingKey": "existingValue"}

    def test_no_backup_for_new_file(self, settings_dir: Path) -> None:
        target = settings_dir / "brand_new.json"
        config = _make_config(target, {"key": "val"}, backup_before_modify=True)
        result = ensure_settings(config)

        assert result.success
        assert result.backup_path is None


class TestMultipleEntries:
    """Test handling of multiple entries."""

    def test_multiple_entries_mixed(self, settings_file: Path) -> None:
        config = _make_config(
            settings_file,
            {
                "existingKey": "should be skipped",
                "newKey1": "value1",
                "newKey2": {"nested": True},
            },
        )
        result = ensure_settings(config)

        assert result.success
        assert "existingKey" in result.keys_skipped
        assert "newKey1" in result.keys_added
        assert "newKey2" in result.keys_added
        assert result.file_modified

        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["existingKey"] == "existingValue"
        assert data["newKey1"] == "value1"
        assert data["newKey2"] == {"nested": True}


class TestPreservesStructure:
    """Test that existing JSON structure is fully preserved."""

    def test_preserves_json_structure(self, settings_dir: Path) -> None:
        target = settings_dir / "complex.json"
        original = {
            "deep": {"nested": {"structure": [1, 2, 3]}},
            "array": [{"a": 1}, {"b": 2}],
            "number": 42,
            "boolean": True,
            "null_val": None,
        }
        target.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

        config = _make_config(target, {"newKey": "added"})
        result = ensure_settings(config)

        assert result.success
        data = json.loads(target.read_text(encoding="utf-8"))

        # All original keys preserved exactly
        assert data["deep"] == {"nested": {"structure": [1, 2, 3]}}
        assert data["array"] == [{"a": 1}, {"b": 2}]
        assert data["number"] == 42
        assert data["boolean"] is True
        assert data["null_val"] is None
        assert data["newKey"] == "added"


class TestUnicode:
    """Test UTF-8 content handling."""

    def test_unicode_preserved(self, settings_dir: Path) -> None:
        target = settings_dir / "unicode.json"
        original = {"beschreibung": "Umlaut-Test: aou", "emoji": "rocket"}
        target.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        config = _make_config(target, {"neu": "Wert mit Sonderzeichen"})
        result = ensure_settings(config)

        assert result.success
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["beschreibung"] == "Umlaut-Test: aou"
        assert data["neu"] == "Wert mit Sonderzeichen"


class TestEmptyEntries:
    """Test empty entries behavior."""

    def test_empty_entries_no_op(self, settings_file: Path) -> None:
        original_content = settings_file.read_text(encoding="utf-8")
        config = _make_config(settings_file, {})
        result = ensure_settings(config)

        assert result.success
        assert not result.file_modified
        assert not result.keys_added
        assert not result.keys_skipped
        assert settings_file.read_text(encoding="utf-8") == original_content


class TestPlatformOverrides:
    """Per-platform overrides take precedence over base entries on a match."""

    def _make_with_override(
        self,
        target: Path,
        entries: dict,
        platform_overrides: dict,
    ) -> SettingsEnsure:
        return SettingsEnsure(
            target_file=str(target),
            entries=entries,
            platform_overrides=platform_overrides,
            create_if_missing=True,
            backup_before_modify=False,
        )

    def test_override_replaces_existing_value_on_matching_platform(
        self, settings_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = settings_dir / "settings.json"
        target.write_text(
            json.dumps(
                {
                    "statusLine": {
                        "type": "command",
                        "command": "~/.claude/statusline.sh",
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("sccs.sync.settings.get_current_platform", lambda: "windows")

        config = self._make_with_override(
            target,
            entries={"statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}},
            platform_overrides={
                "windows": {
                    "statusLine": {
                        "type": "command",
                        "command": "pwsh -File ~/.claude/statusline.ps1",
                    }
                }
            },
        )

        result = ensure_settings(config)

        assert result.success
        assert "statusLine" in result.keys_overridden
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["statusLine"]["command"] == "pwsh -File ~/.claude/statusline.ps1"

    def test_override_ignored_on_non_matching_platform(
        self, settings_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = settings_dir / "settings.json"
        target.write_text(
            json.dumps(
                {
                    "statusLine": {
                        "type": "command",
                        "command": "~/.claude/statusline.sh",
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("sccs.sync.settings.get_current_platform", lambda: "macos")

        config = self._make_with_override(
            target,
            entries={"statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}},
            platform_overrides={
                "windows": {
                    "statusLine": {
                        "type": "command",
                        "command": "pwsh -File ~/.claude/statusline.ps1",
                    }
                }
            },
        )

        result = ensure_settings(config)

        assert result.success
        assert "statusLine" not in result.keys_overridden
        data = json.loads(target.read_text(encoding="utf-8"))
        # Existing macOS value untouched.
        assert data["statusLine"]["command"] == "~/.claude/statusline.sh"

    def test_override_deep_merges_nested_dict(self, settings_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = settings_dir / "settings.json"
        target.write_text(
            json.dumps(
                {
                    "statusLine": {
                        "type": "command",
                        "command": "~/.claude/statusline.sh",
                        "extra": "preserve me",
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("sccs.sync.settings.get_current_platform", lambda: "windows")

        config = self._make_with_override(
            target,
            entries={},
            platform_overrides={"windows": {"statusLine": {"command": "pwsh -File ~/.claude/statusline.ps1"}}},
        )

        result = ensure_settings(config)

        assert result.success
        data = json.loads(target.read_text(encoding="utf-8"))
        # Override replaces "command" but preserves siblings.
        assert data["statusLine"]["command"] == "pwsh -File ~/.claude/statusline.ps1"
        assert data["statusLine"]["type"] == "command"
        assert data["statusLine"]["extra"] == "preserve me"

    def test_override_creates_key_if_missing(self, settings_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = settings_dir / "settings.json"
        target.write_text("{}\n", encoding="utf-8")

        monkeypatch.setattr("sccs.sync.settings.get_current_platform", lambda: "windows")

        config = self._make_with_override(
            target,
            entries={},
            platform_overrides={"windows": {"winOnly": {"foo": "bar"}}},
        )

        result = ensure_settings(config)

        assert result.success
        assert "winOnly" in result.keys_added
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["winOnly"] == {"foo": "bar"}

    def test_no_overrides_means_legacy_behaviour(self, settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # When no platform_overrides are set, behaviour matches the original
        # non-destructive merge (existing keys never overwritten).
        monkeypatch.setattr("sccs.sync.settings.get_current_platform", lambda: "windows")
        existing = json.loads(settings_file.read_text(encoding="utf-8"))
        existing["existingKey"] = {"original": True}
        settings_file.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

        config = SettingsEnsure(
            target_file=str(settings_file),
            entries={"existingKey": {"new": True}},
            backup_before_modify=False,
        )
        result = ensure_settings(config)

        assert result.success
        assert "existingKey" in result.keys_skipped
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["existingKey"] == {"original": True}


class TestResolveEffectiveSettingsEnsure:
    """Verify the default-fallback logic that heals pre-v2.20 user configs."""

    def _stub_default(self, monkeypatch, block):
        from sccs.sync import category as cat_module

        monkeypatch.setattr(cat_module, "get_default_settings_ensure", lambda name: block)

    def test_user_block_none_with_default_adopts_default(self, monkeypatch):
        from sccs.sync.category import _resolve_effective_settings_ensure

        default_block = {
            "target_file": "~/.claude/settings.json",
            "entries": {"statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}},
            "platform_overrides": {"windows": {"statusLine": {"command": "pwsh -File ~/.claude/statusline.ps1"}}},
        }
        self._stub_default(monkeypatch, default_block)

        effective = _resolve_effective_settings_ensure("claude_statusline", None)

        assert effective is not None
        assert effective.entries["statusLine"]["command"] == "~/.claude/statusline.sh"
        assert "windows" in effective.platform_overrides
        assert effective.platform_overrides["windows"]["statusLine"]["command"].startswith("pwsh")

    def test_user_block_none_without_default_returns_none(self, monkeypatch):
        from sccs.sync.category import _resolve_effective_settings_ensure

        self._stub_default(monkeypatch, None)
        assert _resolve_effective_settings_ensure("custom_cat", None) is None

    def test_user_block_without_overrides_inherits_default_overrides(self, tmp_path, monkeypatch):
        from sccs.sync.category import _resolve_effective_settings_ensure

        default_block = {
            "target_file": "~/.claude/settings.json",
            "entries": {"statusLine": {"command": "~/.claude/statusline.sh"}},
            "platform_overrides": {"windows": {"statusLine": {"command": "pwsh -File ~/.claude/statusline.ps1"}}},
        }
        self._stub_default(monkeypatch, default_block)

        user_block = SettingsEnsure(
            target_file=str(tmp_path / "settings.json"),
            entries={"statusLine": {"command": "/custom/path/statusline.sh"}},
        )

        effective = _resolve_effective_settings_ensure("claude_statusline", user_block)

        assert effective is not None
        # User's entries are preserved.
        assert effective.entries["statusLine"]["command"] == "/custom/path/statusline.sh"
        # User's target_file is preserved.
        assert effective.target_file == str(tmp_path / "settings.json")
        # Missing platform_overrides are filled in from the default.
        assert "windows" in effective.platform_overrides
        assert effective.platform_overrides["windows"]["statusLine"]["command"].startswith("pwsh")

    def test_user_per_platform_override_wins(self, tmp_path, monkeypatch):
        from sccs.sync.category import _resolve_effective_settings_ensure

        default_block = {
            "target_file": "~/.claude/settings.json",
            "entries": {"statusLine": {"command": "default.sh"}},
            "platform_overrides": {
                "windows": {"statusLine": {"command": "default.ps1"}},
                "macos": {"statusLine": {"command": "default-mac.sh"}},
            },
        }
        self._stub_default(monkeypatch, default_block)

        user_block = SettingsEnsure(
            target_file=str(tmp_path / "settings.json"),
            entries={"statusLine": {"command": "user.sh"}},
            platform_overrides={"windows": {"statusLine": {"command": "user-custom.ps1"}}},
        )

        effective = _resolve_effective_settings_ensure("claude_statusline", user_block)

        assert effective is not None
        # User's per-platform override wins for Windows.
        assert effective.platform_overrides["windows"]["statusLine"]["command"] == "user-custom.ps1"
        # macOS comes from default, since user didn't define it.
        assert effective.platform_overrides["macos"]["statusLine"]["command"] == "default-mac.sh"

    def test_user_block_returned_unchanged_when_no_default(self, tmp_path, monkeypatch):
        from sccs.sync.category import _resolve_effective_settings_ensure

        self._stub_default(monkeypatch, None)

        user_block = SettingsEnsure(
            target_file=str(tmp_path / "settings.json"),
            entries={"foo": "bar"},
            platform_overrides={"windows": {"foo": "baz"}},
        )

        effective = _resolve_effective_settings_ensure("custom_cat", user_block)
        assert effective is user_block

    def test_user_block_returned_unchanged_when_default_has_no_overrides(self, tmp_path, monkeypatch):
        from sccs.sync.category import _resolve_effective_settings_ensure

        self._stub_default(
            monkeypatch,
            {"target_file": "~/x", "entries": {"k": "v"}, "platform_overrides": {}},
        )

        user_block = SettingsEnsure(
            target_file=str(tmp_path / "settings.json"),
            entries={"foo": "bar"},
        )

        effective = _resolve_effective_settings_ensure("claude_statusline", user_block)
        assert effective is user_block
