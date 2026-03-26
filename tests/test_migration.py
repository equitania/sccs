# SCCS Migration Tests
# Tests for config migration detection, state management, and CLI integration

from pathlib import Path

import pytest
from click.testing import CliRunner

from sccs.config.defaults import DEFAULT_CONFIG
from sccs.config.migration import (
    MigrationState,
    MigrationStateManager,
    detect_new_categories,
    get_categories_to_offer,
)
from sccs.utils.platform import is_platform_match


def _platform_filtered_defaults() -> list[str]:
    """Return default category names filtered for the current platform."""
    return [name for name, cat in DEFAULT_CONFIG["sync_categories"].items() if is_platform_match(cat.get("platforms"))]


class TestDetectNewCategories:
    """Tests for detect_new_categories()."""

    def test_empty_user_data_returns_all_defaults(self):
        """Empty user config → all platform-matching default categories returned."""
        result = detect_new_categories({})
        expected = _platform_filtered_defaults()
        assert result == expected

    def test_no_sync_categories_key(self):
        """Missing sync_categories key → all platform-matching defaults."""
        result = detect_new_categories({"repository": {"path": "/tmp"}})
        expected = _platform_filtered_defaults()
        assert len(result) == len(expected)

    def test_partial_user_data(self):
        """User has some categories → only missing ones returned."""
        user_data = {
            "sync_categories": {
                "claude_framework": {"enabled": True},
                "claude_skills": {"enabled": True},
            }
        }
        result = detect_new_categories(user_data)
        assert "claude_framework" not in result
        assert "claude_skills" not in result
        # All other platform-matching defaults should be present
        expected_count = len(_platform_filtered_defaults()) - 2
        assert len(result) == expected_count

    def test_all_categories_present(self):
        """User has all categories → empty list."""
        user_data = {"sync_categories": {name: {"enabled": True} for name in DEFAULT_CONFIG["sync_categories"]}}
        result = detect_new_categories(user_data)
        assert result == []

    def test_preserves_default_config_order(self):
        """Results are in DEFAULT_CONFIG insertion order."""
        user_data = {"sync_categories": {}}
        result = detect_new_categories(user_data)
        expected = _platform_filtered_defaults()
        assert result == expected

    def test_custom_user_category_ignored(self):
        """Custom user categories don't affect detection."""
        user_data = {
            "sync_categories": {
                "my_custom_category": {"enabled": True},
            }
        }
        result = detect_new_categories(user_data)
        # All platform-matching defaults should be listed since user has none of them
        expected = _platform_filtered_defaults()
        assert len(result) == len(expected)


class TestMigrationState:
    """Tests for MigrationState dataclass."""

    def test_default_state(self):
        state = MigrationState()
        assert state.declined_categories == []
        assert state.last_checked is None

    def test_to_dict_empty(self):
        state = MigrationState()
        assert state.to_dict() == {}

    def test_to_dict_with_data(self):
        state = MigrationState(
            declined_categories=["cat_a", "cat_b"],
            last_checked="2026-03-22T10:00:00",
        )
        d = state.to_dict()
        assert d["declined_categories"] == ["cat_a", "cat_b"]
        assert d["last_checked"] == "2026-03-22T10:00:00"

    def test_roundtrip(self):
        state = MigrationState(
            declined_categories=["cat_a"],
            last_checked="2026-03-22T10:00:00",
        )
        restored = MigrationState.from_dict(state.to_dict())
        assert restored.declined_categories == state.declined_categories
        assert restored.last_checked == state.last_checked


class TestMigrationStateManager:
    """Tests for MigrationStateManager persistence."""

    @pytest.fixture
    def state_path(self, temp_dir: Path) -> Path:
        return temp_dir / ".migration_state.yaml"

    @pytest.fixture
    def mgr(self, state_path: Path) -> MigrationStateManager:
        return MigrationStateManager(state_path=state_path)

    def test_load_nonexistent_file(self, mgr: MigrationStateManager):
        state = mgr.load()
        assert state.declined_categories == []

    def test_save_and_load(self, mgr: MigrationStateManager, state_path: Path):
        mgr.mark_declined(["cat_a", "cat_b"])
        assert state_path.exists()

        # Load in a fresh manager
        mgr2 = MigrationStateManager(state_path=state_path)
        assert mgr2.state.declined_categories == ["cat_a", "cat_b"]
        assert mgr2.state.last_checked is not None

    def test_is_declined(self, mgr: MigrationStateManager):
        mgr.mark_declined(["cat_a"])
        assert mgr.is_declined("cat_a") is True
        assert mgr.is_declined("cat_b") is False

    def test_mark_declined_no_duplicates(self, mgr: MigrationStateManager):
        mgr.mark_declined(["cat_a"])
        mgr.mark_declined(["cat_a", "cat_b"])
        assert mgr.state.declined_categories == ["cat_a", "cat_b"]

    def test_mark_adopted_removes_from_declined(self, mgr: MigrationStateManager):
        mgr.mark_declined(["cat_a", "cat_b", "cat_c"])
        mgr.mark_adopted(["cat_b"])
        assert mgr.state.declined_categories == ["cat_a", "cat_c"]

    def test_mark_adopted_nonexistent(self, mgr: MigrationStateManager):
        """Adopting a non-declined category is a no-op."""
        mgr.mark_declined(["cat_a"])
        mgr.mark_adopted(["cat_x"])
        assert mgr.state.declined_categories == ["cat_a"]

    def test_corrupt_file_returns_empty_state(self, state_path: Path):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("not: [valid: yaml: {{", encoding="utf-8")
        mgr = MigrationStateManager(state_path=state_path)
        state = mgr.load()
        assert state.declined_categories == []


class TestGetCategoriesToOffer:
    """Tests for get_categories_to_offer() with declined filtering."""

    @pytest.fixture
    def mgr(self, temp_dir: Path) -> MigrationStateManager:
        return MigrationStateManager(state_path=temp_dir / ".migration_state.yaml")

    def test_filters_declined(self, mgr: MigrationStateManager):
        # Mark some as declined
        first_default = _platform_filtered_defaults()[0]
        mgr.mark_declined([first_default])

        result = get_categories_to_offer({}, mgr)
        assert first_default not in result
        # Still returns others
        assert len(result) == len(_platform_filtered_defaults()) - 1

    def test_no_new_categories(self, mgr: MigrationStateManager):
        user_data = {"sync_categories": {name: {} for name in DEFAULT_CONFIG["sync_categories"]}}
        result = get_categories_to_offer(user_data, mgr)
        assert result == []

    def test_returns_only_undeclined_new(self, mgr: MigrationStateManager):
        """Only categories that are both new AND not declined are offered."""
        default_names = list(DEFAULT_CONFIG["sync_categories"].keys())
        # User has first 3
        user_data = {"sync_categories": {name: {} for name in default_names[:3]}}
        # Decline the 4th
        mgr.mark_declined([default_names[3]])

        result = get_categories_to_offer(user_data, mgr)
        assert default_names[3] not in result
        assert default_names[4] in result


class TestAdoptNewCategories:
    """Tests for adopt_new_categories() writing to disk."""

    def test_adopt_writes_to_config(self, config_file: Path, monkeypatch):
        """Adopted categories appear in the saved config file."""
        monkeypatch.setenv("SCCS_CONFIG", str(config_file))

        from sccs.config.loader import adopt_new_categories, load_raw_user_data

        raw_before = load_raw_user_data(config_file)
        new_cats = detect_new_categories(raw_before)
        assert len(new_cats) > 0

        # Adopt one category
        cat_to_adopt = new_cats[0]
        adopt_new_categories([cat_to_adopt], config_file)

        # Verify it's now in the raw YAML
        raw_after = load_raw_user_data(config_file)
        assert cat_to_adopt in raw_after["sync_categories"]

    def test_adopt_does_not_overwrite_existing(self, config_file: Path, monkeypatch):
        """Existing categories are not modified by adoption."""
        monkeypatch.setenv("SCCS_CONFIG", str(config_file))

        from sccs.config.loader import adopt_new_categories, load_raw_user_data

        raw_before = load_raw_user_data(config_file)
        existing_cats = list(raw_before.get("sync_categories", {}).keys())

        # Adopt a new category
        new_cats = detect_new_categories(raw_before)
        if new_cats:
            adopt_new_categories([new_cats[0]], config_file)

        raw_after = load_raw_user_data(config_file)
        # Existing categories still present
        for cat in existing_cats:
            assert cat in raw_after["sync_categories"]

    def test_adopt_does_not_inflate_config(self, config_file: Path, monkeypatch):
        """Adopting one category must not add all default categories to the file."""
        monkeypatch.setenv("SCCS_CONFIG", str(config_file))

        from sccs.config.loader import adopt_new_categories, load_raw_user_data

        raw_before = load_raw_user_data(config_file)
        original_count = len(raw_before.get("sync_categories", {}))
        new_cats = detect_new_categories(raw_before)
        assert len(new_cats) > 1, "Need multiple new categories for this test"

        # Adopt only the first new category
        adopt_new_categories([new_cats[0]], config_file)

        raw_after = load_raw_user_data(config_file)
        after_count = len(raw_after.get("sync_categories", {}))

        # Should have exactly one more category, not all defaults
        assert after_count == original_count + 1


class TestLoadRawUserData:
    """Tests for load_raw_user_data()."""

    def test_returns_raw_dict(self, config_file: Path):
        from sccs.config.loader import load_raw_user_data

        data = load_raw_user_data(config_file)
        assert isinstance(data, dict)
        assert "sync_categories" in data

    def test_nonexistent_file_returns_empty(self, temp_dir: Path):
        from sccs.config.loader import load_raw_user_data

        data = load_raw_user_data(temp_dir / "nonexistent.yaml")
        assert data == {}

    def test_does_not_merge_defaults(self, config_file: Path):
        """Raw data should NOT contain categories from DEFAULT_CONFIG that aren't in the file."""
        from sccs.config.loader import load_raw_user_data

        data = load_raw_user_data(config_file)
        user_cats = set(data.get("sync_categories", {}).keys())

        # Should only have what's in the file, not all defaults
        assert len(user_cats) < len(DEFAULT_CONFIG["sync_categories"])


class TestCliNoMigrateFlag:
    """Tests for --no-migrate flag on sync command."""

    def test_no_migrate_flag_accepted(self):
        """The --no-migrate flag is accepted without error."""
        runner = CliRunner()
        from sccs.cli import cli

        # This will fail because no config exists, but the flag should be parsed
        result = runner.invoke(cli, ["sync", "--no-migrate", "--dry-run"])
        # Should not fail with "no such option" error
        assert "no such option" not in (result.output or "").lower()
