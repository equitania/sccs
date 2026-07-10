# SCCS Transfer UI Tests
# Covers questionary helpers, two-stage selection, and choice builders.
# questionary interaction is mocked — no TTY / real prompts are exercised.

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import questionary

from sccs.config.schema import ItemType, SccsConfig
from sccs.sync.item import SyncItem
from sccs.transfer.manifest import ExportManifest, ManifestCategory, ManifestItem
from sccs.transfer.ui import (
    CategoryGroup,
    _build_group_item_choices,
    _build_import_groups,
    _build_import_item_choices,
    _get_group_name,
    _get_platform_label,
    _sccs_style,
    build_category_groups,
    build_export_choices,
    build_import_choices,
    checkbox_with_separators,
    interactive_export_selection,
    interactive_import_selection,
    parse_selections,
)

# ── Helpers ─────────────────────────────────────────────────────


def _item(name: str) -> SyncItem:
    return SyncItem(name=name, category="test", item_type=ItemType.FILE)


def _manifest_item(name: str, platform_hint: str | None = None) -> ManifestItem:
    return ManifestItem(name=name, zip_path=f"c/{name}", item_type="file", platform_hint=platform_hint)


def _manifest(categories: dict[str, ManifestCategory]) -> ExportManifest:
    return ExportManifest(
        sccs_version="2.36.1",
        created_at="2026-06-07",
        created_on="macos",
        categories=categories,
    )


class _FakeConsole:
    """Records print_info calls."""

    def __init__(self) -> None:
        self.infos: list[str] = []

    def print_info(self, msg: str) -> None:
        self.infos.append(msg)


# ── _sccs_style / _get_platform_label / _get_group_name ─────────


def test_sccs_style_returns_style():
    assert isinstance(_sccs_style(), questionary.Style)


def test_get_group_name_prefix_and_fallback():
    assert _get_group_name("claude_skills") == "Claude Code"
    assert _get_group_name("fish_config") == "Fish Shell"
    assert _get_group_name("starship_config") == "Shell Tools"
    assert _get_group_name("git_config") == "Shell Tools"
    assert _get_group_name("totally_unknown") == "Other"


def test_get_platform_label():
    cat_with = MagicMock(platforms=["macos", "linux"])
    cat_without = MagicMock(platforms=None)
    assert _get_platform_label(cat_with) == " (macos, linux only)"
    assert _get_platform_label(cat_without) == ""


# ── CategoryGroup.label ─────────────────────────────────────────


class TestCategoryGroupLabel:
    def test_plural_no_platform(self):
        g = CategoryGroup(name="Claude Code", item_count=3)
        assert g.label == "Claude Code  (3 items)"

    def test_singular(self):
        g = CategoryGroup(name="Fish Shell", item_count=1)
        assert g.label == "Fish Shell  (1 item)"

    def test_with_platform(self):
        g = CategoryGroup(name="Fish Shell", item_count=2, platform="macos")
        assert g.label == "Fish Shell — macos-specific  (2 items)"


# ── build_category_groups ───────────────────────────────────────


class TestBuildCategoryGroups:
    def test_skips_zero_count(self):
        groups = build_category_groups({"claude_skills": 0})
        assert groups == []

    def test_groups_by_prefix(self):
        groups = build_category_groups({"claude_skills": 2, "claude_commands": 3})
        assert len(groups) == 1
        assert groups[0].name == "Claude Code"
        assert groups[0].item_count == 5

    def test_platform_specific_gets_own_group(self):
        raw = {
            "repository": {"path": "/tmp/repo"},
            "sync_categories": {
                "fish_config": {
                    "enabled": True,
                    "description": "Fish",
                    "local_path": "~/.config/fish",
                    "repo_path": ".config/fish",
                    "item_type": "file",
                    "platforms": ["macos"],
                },
            },
        }
        config = SccsConfig.model_validate(raw)
        groups = build_category_groups({"fish_config": 4}, config)
        assert len(groups) == 1
        assert groups[0].platform == "macos"
        assert "(macos)" in groups[0].name


# ── checkbox_with_separators ────────────────────────────────────


class TestCheckboxWithSeparators:
    def test_returns_selected_values(self):
        fake_cb = MagicMock()
        fake_cb.ask.return_value = ["a", "b"]
        with patch("sccs.transfer.ui.questionary.checkbox", return_value=fake_cb) as cb:
            result = checkbox_with_separators("pick", choices=["a", "b", "c"])
        assert result == ["a", "b"]
        cb.assert_called_once()

    def test_none_result_raises_systemexit(self):
        fake_cb = MagicMock()
        fake_cb.ask.return_value = None  # Ctrl-C
        with patch("sccs.transfer.ui.questionary.checkbox", return_value=fake_cb), pytest.raises(SystemExit):
            checkbox_with_separators("pick", choices=["a"])

    def test_patches_indicators_during_prompt(self):
        """The context manager restores indicator constants afterwards."""
        import questionary.constants as constants

        before = constants.INDICATOR_SELECTED
        fake_cb = MagicMock()
        fake_cb.ask.return_value = []
        with patch("sccs.transfer.ui.questionary.checkbox", return_value=fake_cb):
            checkbox_with_separators("pick", choices=["a"])
        assert before == constants.INDICATOR_SELECTED  # restored


# ── interactive_export_selection ────────────────────────────────


@pytest.fixture
def export_config() -> SccsConfig:
    raw = {
        "repository": {"path": "/tmp/repo"},
        "sync_categories": {
            "claude_skills": {
                "enabled": True,
                "description": "Skills",
                "local_path": "~/.claude/skills",
                "repo_path": ".claude/skills",
                "item_type": "directory",
                "item_marker": "SKILL.md",
            },
        },
    }
    return SccsConfig.model_validate(raw)


class TestInteractiveExportSelection:
    def test_no_groups_returns_empty(self, export_config):
        # scanned has only zero-count categories -> no groups
        result = interactive_export_selection({"claude_skills": []}, export_config, {})
        assert result == {}

    def test_no_group_selected_returns_empty(self, export_config):
        scanned = {"claude_skills": [_item("a"), _item("b")]}
        with patch("sccs.transfer.ui.checkbox_with_separators", return_value=[]):
            result = interactive_export_selection(scanned, export_config, {})
        assert result == {}

    def test_small_group_auto_includes_all(self, export_config):
        scanned = {"claude_skills": [_item("a"), _item("b")]}  # 2 <= threshold
        console = _FakeConsole()
        with patch("sccs.transfer.ui.checkbox_with_separators", return_value=["Claude Code"]):
            result = interactive_export_selection(scanned, export_config, console=console)
        assert result == {"claude_skills": ["a", "b"]}
        assert console.infos  # print_info was called for the small group

    def test_large_group_shows_item_checkbox(self, export_config):
        scanned = {"claude_skills": [_item(f"s{i}") for i in range(6)]}  # 6 > threshold
        # Stage 1 selects the group; Stage 2 selects two items.
        side = [["Claude Code"], ["claude_skills::s0", "claude_skills::s3"]]
        with patch("sccs.transfer.ui.checkbox_with_separators", side_effect=side):
            result = interactive_export_selection(scanned, export_config, {})
        assert result == {"claude_skills": ["s0", "s3"]}


# ── interactive_import_selection ────────────────────────────────


def _import_manifest(n: int, platform_hint: str | None = None) -> ExportManifest:
    return _manifest(
        {
            "claude_skills": ManifestCategory(
                description="Skills",
                item_type="directory",
                local_path="~/.claude/skills",
                items=[_manifest_item(f"s{i}", platform_hint) for i in range(n)],
            )
        }
    )


class TestInteractiveImportSelection:
    def test_no_groups_returns_empty(self):
        manifest = _manifest({})
        assert interactive_import_selection(manifest) == {}

    def test_no_group_selected_returns_empty(self):
        manifest = _import_manifest(2)
        with patch("sccs.transfer.ui.checkbox_with_separators", return_value=[]):
            assert interactive_import_selection(manifest) == {}

    def test_small_group_auto_includes_all(self):
        manifest = _import_manifest(2)
        console = _FakeConsole()
        with patch("sccs.transfer.ui.checkbox_with_separators", return_value=["Claude Code"]):
            result = interactive_import_selection(manifest, console=console)
        assert result == {"claude_skills": ["s0", "s1"]}
        assert console.infos

    def test_large_group_shows_item_checkbox(self):
        manifest = _import_manifest(6)
        side = [["Claude Code"], ["claude_skills::s1", "claude_skills::s4"]]
        with patch("sccs.transfer.ui.checkbox_with_separators", side_effect=side):
            result = interactive_import_selection(manifest)
        assert result == {"claude_skills": ["s1", "s4"]}


# ── Choice builders ─────────────────────────────────────────────


def test_build_group_item_choices(export_config):
    scanned = {"claude_skills": [_item("b"), _item("a")], "empty_cat": []}
    choices = _build_group_item_choices(scanned, export_config)
    # One separator + two item choices (empty_cat skipped)
    values = [c.value for c in choices if not isinstance(c, questionary.Separator)]
    assert values == ["claude_skills::a", "claude_skills::b"]  # sorted by name


def test_build_import_item_choices_with_platform_hint():
    cats = {
        "fish_config": ManifestCategory(
            description="Fish",
            item_type="file",
            local_path="~/.config/fish",
            items=[_manifest_item("conf", platform_hint="macos")],
        ),
        "empty": ManifestCategory(description="E", item_type="file", local_path="~/x", items=[]),
    }
    choices = _build_import_item_choices(cats)
    titles = [c.title for c in choices if not isinstance(c, questionary.Separator)]
    assert any("macos only" in t for t in titles)


def test_build_import_groups_detects_platform():
    manifest = _import_manifest(2, platform_hint="linux")
    groups = _build_import_groups(manifest)
    assert len(groups) == 1
    assert groups[0].platform == "linux"
    assert "(linux)" in groups[0].name


def test_build_import_groups_skips_empty():
    manifest = _manifest({"empty": ManifestCategory(description="E", item_type="file", local_path="~/x", items=[])})
    assert _build_import_groups(manifest) == []


# ── Legacy flat builders ────────────────────────────────────────


def test_build_export_choices_skips_unknown_and_empty(export_config):
    # "ghost" is not in config (skipped); "claude_empty" has no items (skipped).
    scanned = {"claude_skills": [_item("a")], "ghost": [_item("x")], "claude_empty": []}
    choices = build_export_choices(scanned, export_config, {})
    values = [c.value for c in choices if not isinstance(c, questionary.Separator)]
    assert values == ["claude_skills::a"]


def test_build_export_choices_platform_label():
    raw = {
        "repository": {"path": "/tmp/repo"},
        "sync_categories": {
            "fish_config": {
                "enabled": True,
                "description": "Fish",
                "local_path": "~/.config/fish",
                "repo_path": ".config/fish",
                "item_type": "file",
                "platforms": ["macos"],
            },
        },
    }
    config = SccsConfig.model_validate(raw)
    choices = build_export_choices({"fish_config": [_item("conf")]}, config, {})
    titles = [c.title for c in choices if not isinstance(c, questionary.Separator)]
    assert any("macos only" in t for t in titles)


def test_build_import_choices_with_hints():
    cats = {
        "fish_config": ManifestCategory(
            description="Fish",
            item_type="file",
            local_path="~/.config/fish",
            items=[_manifest_item("conf", platform_hint="macos")],
        ),
        "empty": ManifestCategory(description="E", item_type="file", local_path="~/x", items=[]),
    }
    manifest = _manifest(cats)
    choices = build_import_choices(manifest)
    titles = [c.title for c in choices if not isinstance(c, questionary.Separator)]
    assert any("macos only" in t for t in titles)


# ── parse_selections ────────────────────────────────────────────


def test_parse_selections_groups_and_ignores_malformed():
    values = ["cat1::a", "cat1::b", "cat2::c", "no_separator"]
    result = parse_selections(values)
    assert result == {"cat1": ["a", "b"], "cat2": ["c"]}
