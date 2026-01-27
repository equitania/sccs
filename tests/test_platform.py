# SCCS Platform Detection Tests

import platform
from unittest.mock import patch

import pytest

from sccs.utils.platform import get_current_platform, is_platform_match


class TestGetCurrentPlatform:
    """Tests for get_current_platform()."""

    def test_returns_known_value(self):
        """Current platform should be a known value."""
        result = get_current_platform()
        assert result in ("macos", "linux", "windows")

    @patch("sccs.utils.platform.platform.system", return_value="Darwin")
    def test_darwin_maps_to_macos(self, mock_system):
        result = get_current_platform()
        assert result == "macos"

    @patch("sccs.utils.platform.platform.system", return_value="Linux")
    def test_linux_maps_to_linux(self, mock_system):
        result = get_current_platform()
        assert result == "linux"

    @patch("sccs.utils.platform.platform.system", return_value="Windows")
    def test_windows_maps_to_windows(self, mock_system):
        result = get_current_platform()
        assert result == "windows"

    @patch("sccs.utils.platform.platform.system", return_value="FreeBSD")
    def test_unknown_lowercased(self, mock_system):
        result = get_current_platform()
        assert result == "freebsd"


class TestIsPlatformMatch:
    """Tests for is_platform_match()."""

    def test_none_matches_all(self):
        """None platforms means all platforms match."""
        assert is_platform_match(None) is True

    def test_empty_list_matches_all(self):
        """Empty list means all platforms match."""
        assert is_platform_match([]) is True

    @patch("sccs.utils.platform.get_current_platform", return_value="macos")
    def test_current_platform_matches(self, mock_platform):
        assert is_platform_match(["macos"]) is True

    @patch("sccs.utils.platform.get_current_platform", return_value="macos")
    def test_other_platform_does_not_match(self, mock_platform):
        assert is_platform_match(["linux"]) is False

    @patch("sccs.utils.platform.get_current_platform", return_value="macos")
    def test_multiple_platforms_match(self, mock_platform):
        assert is_platform_match(["linux", "macos"]) is True

    @patch("sccs.utils.platform.get_current_platform", return_value="windows")
    def test_multiple_platforms_no_match(self, mock_platform):
        assert is_platform_match(["linux", "macos"]) is False


class TestPlatformFieldInSchema:
    """Tests for platforms field in SyncCategory schema."""

    def test_schema_accepts_platforms(self):
        """Pydantic should accept platforms field."""
        from sccs.config.schema import SyncCategory

        cat = SyncCategory(
            local_path="/tmp/test",
            repo_path="test",
            platforms=["macos"],
        )
        assert cat.platforms == ["macos"]

    def test_schema_platforms_default_none(self):
        """Platforms should default to None."""
        from sccs.config.schema import SyncCategory

        cat = SyncCategory(
            local_path="/tmp/test",
            repo_path="test",
        )
        assert cat.platforms is None

    def test_schema_accepts_multiple_platforms(self):
        from sccs.config.schema import SyncCategory

        cat = SyncCategory(
            local_path="/tmp/test",
            repo_path="test",
            platforms=["macos", "linux"],
        )
        assert cat.platforms == ["macos", "linux"]


class TestEngineFiltersByPlatform:
    """Tests for engine platform filtering."""

    @patch("sccs.sync.engine.is_platform_match")
    def test_engine_filters_by_platform(self, mock_match):
        """Engine should filter categories by platform."""
        from sccs.config.schema import SccsConfig, SyncCategory
        from sccs.sync.engine import SyncEngine

        # Mock: first category matches, second doesn't
        mock_match.side_effect = [True, False]

        config = SccsConfig(
            repository={"path": "/tmp/repo"},
            sync_categories={
                "cat_macos": SyncCategory(
                    local_path="/tmp/a",
                    repo_path="a",
                    platforms=["macos"],
                ),
                "cat_linux": SyncCategory(
                    local_path="/tmp/b",
                    repo_path="b",
                    platforms=["linux"],
                ),
            },
        )

        engine = SyncEngine(config)
        enabled = engine.get_enabled_categories()

        assert "cat_macos" in enabled
        assert "cat_linux" not in enabled

    @patch("sccs.sync.engine.is_platform_match", return_value=True)
    def test_engine_includes_no_platform_filter(self, mock_match):
        """Categories without platform filter should always be included."""
        from sccs.config.schema import SccsConfig, SyncCategory
        from sccs.sync.engine import SyncEngine

        config = SccsConfig(
            repository={"path": "/tmp/repo"},
            sync_categories={
                "cat_all": SyncCategory(
                    local_path="/tmp/a",
                    repo_path="a",
                    platforms=None,
                ),
            },
        )

        engine = SyncEngine(config)
        enabled = engine.get_enabled_categories()

        assert "cat_all" in enabled
