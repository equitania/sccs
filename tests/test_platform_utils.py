# SCCS Platform Utility Tests
# Covers shell availability detection and platform-skipped category reporting.

from __future__ import annotations

from unittest.mock import patch

import pytest

from sccs.config.schema import SccsConfig
from sccs.utils.platform import (
    detect_shell_for_category,
    get_current_platform,
    get_platform_skipped_categories,
    get_unavailable_shells_for_enabled_categories,
    is_platform_match,
    is_shell_available,
)


class TestPlatformBasics:
    def test_get_current_platform_returns_known(self) -> None:
        assert get_current_platform() in {"macos", "linux", "windows"}

    def test_is_platform_match_none_matches_all(self) -> None:
        assert is_platform_match(None) is True
        assert is_platform_match([]) is True

    def test_is_platform_match_explicit_list(self) -> None:
        # Whatever the current platform is, it must be in a list containing it.
        current = get_current_platform()
        assert is_platform_match([current]) is True
        assert is_platform_match([f"not-{current}"]) is False


class TestShellDetection:
    def test_detects_fish_from_path(self) -> None:
        assert detect_shell_for_category("fish_config", "~/.config/fish") == "fish"

    def test_detects_powershell_from_path(self) -> None:
        assert (
            detect_shell_for_category("powershell_profile", "~/Documents/PowerShell")
            == "powershell"
        )

    def test_returns_none_for_unrelated_category(self) -> None:
        assert detect_shell_for_category("claude_skills", "~/.claude/skills") is None

    @patch("sccs.utils.platform.shutil.which")
    def test_is_shell_available_true(self, mock_which) -> None:
        mock_which.return_value = "/usr/local/bin/fish"
        assert is_shell_available("fish") is True

    @patch("sccs.utils.platform.shutil.which")
    def test_is_shell_available_false(self, mock_which) -> None:
        mock_which.return_value = None
        assert is_shell_available("fish") is False

    @patch("sccs.utils.platform.shutil.which")
    def test_powershell_accepts_pwsh_or_powershell(self, mock_which) -> None:
        # Map: pwsh missing, powershell present → still True overall.
        mock_which.side_effect = lambda name: (
            "/usr/local/bin/powershell" if name == "powershell" else None
        )
        assert is_shell_available("powershell") is True


@pytest.fixture
def config_with_fish_and_ps(temp_home, mock_repo) -> SccsConfig:
    """Build a minimal config with fish_config + powershell_profile."""
    raw = {
        "repository": {"path": str(mock_repo)},
        "sync_categories": {
            "fish_config": {
                "enabled": True,
                "description": "Fish",
                "local_path": str(temp_home / ".config" / "fish"),
                "repo_path": ".config/fish",
                "sync_mode": "bidirectional",
                "item_type": "file",
                "platforms": ["macos", "linux"],
            },
            "powershell_profile": {
                "enabled": True,
                "description": "PowerShell",
                "local_path": str(temp_home / "Documents" / "PowerShell"),
                "repo_path": ".config/powershell",
                "sync_mode": "bidirectional",
                "item_type": "file",
                "platforms": ["windows"],
            },
            "claude_skills": {
                "enabled": True,
                "description": "Skills",
                "local_path": str(temp_home / ".claude" / "skills"),
                "repo_path": ".claude/skills",
                "sync_mode": "bidirectional",
                "item_type": "directory",
                "item_marker": "SKILL.md",
            },
        },
    }
    return SccsConfig.model_validate(raw)


class TestPlatformSkippedCategories:
    @patch("sccs.utils.platform.get_current_platform", return_value="windows")
    def test_windows_skips_fish(self, _mock, config_with_fish_and_ps) -> None:
        skipped = get_platform_skipped_categories(config_with_fish_and_ps)
        assert "fish" in skipped
        assert "fish_config" in skipped["fish"]
        # PowerShell is allowed on Windows, so it's not in the skip list.
        assert "powershell" not in skipped

    @patch("sccs.utils.platform.get_current_platform", return_value="macos")
    def test_macos_skips_powershell(self, _mock, config_with_fish_and_ps) -> None:
        skipped = get_platform_skipped_categories(config_with_fish_and_ps)
        assert "powershell" in skipped
        assert "powershell_profile" in skipped["powershell"]

    @patch("sccs.utils.platform.get_current_platform", return_value="linux")
    def test_linux_skips_powershell_keeps_fish(
        self, _mock, config_with_fish_and_ps
    ) -> None:
        skipped = get_platform_skipped_categories(config_with_fish_and_ps)
        assert "powershell" in skipped
        assert "fish" not in skipped

    def test_categories_without_platform_filter_never_skipped(
        self, config_with_fish_and_ps
    ) -> None:
        skipped = get_platform_skipped_categories(config_with_fish_and_ps)
        # claude_skills has no platforms list → never appears in skipped.
        for names in skipped.values():
            assert "claude_skills" not in names


class TestUnavailableShellsForEnabled:
    @patch("sccs.utils.platform.shutil.which", return_value=None)
    @patch("sccs.utils.platform.get_current_platform", return_value="linux")
    def test_reports_missing_fish(
        self, _plat, _which, config_with_fish_and_ps
    ) -> None:
        # On Linux fish_config is enabled (platforms includes linux), but the
        # binary isn't available. Should be reported.
        unavailable = get_unavailable_shells_for_enabled_categories(
            config_with_fish_and_ps
        )
        assert "fish" in unavailable
