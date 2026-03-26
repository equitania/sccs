# SCCS Transfer UI
# questionary helpers for interactive export/import selection
# Two-stage navigation: groups first, then items per group

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import questionary

if TYPE_CHECKING:
    from sccs.config.schema import SccsConfig, SyncCategory
    from sccs.sync.item import SyncItem
    from sccs.transfer.manifest import ExportManifest, ManifestCategory

# Threshold: groups with <= this many items skip the item-level checkbox
SMALL_GROUP_THRESHOLD = 5

# Prefix-to-group mapping for category grouping
_GROUP_PREFIXES = [
    ("claude_", "Claude Code"),
    ("fish_", "Fish Shell"),
    ("starship_", "Shell Tools"),
    ("git_", "Shell Tools"),
]


def _sccs_style() -> questionary.Style:
    """Consistent questionary style for SCCS prompts."""
    return questionary.Style(
        [
            ("qmark", "fg:green bold"),
            ("question", "fg:white bold"),
            ("answer", "fg:green"),
            ("pointer", "fg:green bold"),
            ("highlighted", "fg:green bold"),
            ("selected", "fg:green bold"),
            ("instruction", "fg:white"),
        ]
    )


@contextmanager
def _patch_checkbox_indicators():
    """Patch questionary checkbox indicators for dark terminal visibility."""
    import questionary.constants as _constants
    import questionary.prompts.common as _common

    orig = (_constants.INDICATOR_SELECTED, _constants.INDICATOR_UNSELECTED)
    _constants.INDICATOR_SELECTED = "[✔]"
    _constants.INDICATOR_UNSELECTED = "[ ]"
    _common.INDICATOR_SELECTED = "[✔]"
    _common.INDICATOR_UNSELECTED = "[ ]"
    try:
        yield
    finally:
        _constants.INDICATOR_SELECTED, _constants.INDICATOR_UNSELECTED = orig
        _common.INDICATOR_SELECTED, _common.INDICATOR_UNSELECTED = orig


def checkbox_with_separators(
    message: str,
    choices: Sequence[questionary.Choice | questionary.Separator],
    instruction: str = "(Space: toggle, Enter: confirm)",
) -> list[str]:
    """Interactive multi-select checkbox with separators and patched indicators.

    Returns:
        List of selected values.

    Raises:
        SystemExit: On Ctrl-C (user abort).
    """
    with _patch_checkbox_indicators():
        result = questionary.checkbox(
            message,
            choices=choices,
            style=_sccs_style(),
            instruction=instruction,
        ).ask()
    if result is None:
        raise SystemExit(0)
    return list(result)


# ── Category Grouping ──────────────────────────────────────────


@dataclass
class CategoryGroup:
    """Logical group of categories for the first selection stage."""

    name: str
    categories: list[str] = field(default_factory=list)
    item_count: int = 0
    platform: str | None = None

    @property
    def label(self) -> str:
        """Build display label with item count."""
        suffix = f"  ({self.item_count} item{'s' if self.item_count != 1 else ''})"
        if self.platform:
            return f"{self.name} — {self.platform}-specific{suffix}"
        return f"{self.name}{suffix}"


def _get_group_name(cat_name: str) -> str:
    """Determine group name for a category by prefix matching."""
    for prefix, group_name in _GROUP_PREFIXES:
        if cat_name.startswith(prefix):
            return group_name
    return "Other"


def build_category_groups(
    category_items: dict[str, int],
    config: SccsConfig | None = None,
) -> list[CategoryGroup]:
    """Build logical groups from categories.

    Categories with platform filters get their own sub-group.

    Args:
        category_items: Dict of category_name -> item count.
        config: Optional config for platform detection.

    Returns:
        Sorted list of CategoryGroup objects.
    """
    groups: dict[str, CategoryGroup] = {}

    for cat_name, count in sorted(category_items.items()):
        if count == 0:
            continue

        # Detect platform restriction
        platform = None
        if config:
            category = config.sync_categories.get(cat_name)
            if category and category.platforms:
                platform = category.platforms[0]

        base_group = _get_group_name(cat_name)

        # Platform-specific categories get their own group
        if platform:
            group_key = f"{base_group}|{platform}"
            group_name = f"{base_group} ({platform})"
        else:
            group_key = base_group
            group_name = base_group

        if group_key not in groups:
            groups[group_key] = CategoryGroup(name=group_name, platform=platform)

        groups[group_key].categories.append(cat_name)
        groups[group_key].item_count += count

    # Sort: main groups first, platform-specific after
    return sorted(groups.values(), key=lambda g: (g.platform or "", g.name))


# ── Two-Stage Export Selection ─────────────────────────────────


def interactive_export_selection(
    scanned: dict[str, list[SyncItem]],
    config: SccsConfig,
    raw_config: dict,
    console: object | None = None,
) -> dict[str, list[str]]:
    """Two-stage interactive selection for export.

    Stage 1: Select category groups (Claude Code, Fish Shell, etc.)
    Stage 2: Select individual items within each chosen group (if >5 items)

    Args:
        scanned: Dict of category_name -> list of SyncItems.
        config: Validated SCCS config.
        raw_config: Raw YAML config dict.
        console: Optional Console for info messages.

    Returns:
        Parsed selections {category: [item_names]}.

    Raises:
        SystemExit: On Ctrl-C.
    """
    # Build groups
    category_counts = {cat: len(items) for cat, items in scanned.items()}
    groups = build_category_groups(category_counts, config)

    if not groups:
        return {}

    # Stage 1: Select groups
    group_choices: list[questionary.Choice] = []
    for group in groups:
        group_choices.append(questionary.Choice(title=group.label, value=group.name, checked=True))

    selected_group_names = checkbox_with_separators(
        "Select areas to export:",
        choices=group_choices,
        instruction="(Space: toggle, Enter: confirm)",
    )

    if not selected_group_names:
        return {}

    selected_groups = [g for g in groups if g.name in selected_group_names]

    # Stage 2: Select items per group
    all_selections: dict[str, list[str]] = {}

    for group in selected_groups:
        # Collect all items for this group
        group_scanned = {cat: scanned[cat] for cat in group.categories if cat in scanned}
        total = sum(len(items) for items in group_scanned.values())

        if total <= SMALL_GROUP_THRESHOLD:
            # Small group: include everything, just show info
            if console and hasattr(console, "print_info"):
                names = ", ".join(item.name for items in group_scanned.values() for item in items)
                console.print_info(f"  Including {group.name}: {names} ({total} item{'s' if total != 1 else ''})")  # type: ignore[union-attr]
            for cat_name, items in group_scanned.items():
                all_selections[cat_name] = [item.name for item in items]
        else:
            # Large group: show item-level checkbox
            choices = _build_group_item_choices(group_scanned, config)
            selected_values = checkbox_with_separators(
                f"Select {group.name} items to export ({total} available):",
                choices=choices,
                instruction="(Space: toggle, Enter: confirm)",
            )
            parsed = parse_selections(selected_values)
            all_selections.update(parsed)

    return all_selections


# ── Two-Stage Import Selection ─────────────────────────────────


def interactive_import_selection(
    manifest: ExportManifest,
    console: object | None = None,
) -> dict[str, list[str]]:
    """Two-stage interactive selection for import.

    Stage 1: Select category groups from manifest
    Stage 2: Select individual items within each chosen group (if >5 items)

    Args:
        manifest: Parsed export manifest from ZIP.
        console: Optional Console for info messages.

    Returns:
        Parsed selections {category: [item_names]}.

    Raises:
        SystemExit: On Ctrl-C.
    """
    # Build groups from manifest (no config available, uses platform hints)
    groups = _build_import_groups(manifest)

    if not groups:
        return {}

    # Stage 1: Select groups
    group_choices: list[questionary.Choice] = []
    for group in groups:
        group_choices.append(questionary.Choice(title=group.label, value=group.name, checked=True))

    selected_group_names = checkbox_with_separators(
        "Select areas to import:",
        choices=group_choices,
        instruction="(Space: toggle, Enter: confirm)",
    )

    if not selected_group_names:
        return {}

    selected_groups = [g for g in groups if g.name in selected_group_names]

    # Stage 2: Select items per group
    all_selections: dict[str, list[str]] = {}

    for group in selected_groups:
        group_cats = {cat: manifest.categories[cat] for cat in group.categories if cat in manifest.categories}
        total = sum(len(data.items) for data in group_cats.values())

        if total <= SMALL_GROUP_THRESHOLD:
            if console and hasattr(console, "print_info"):
                names = ", ".join(item.name for data in group_cats.values() for item in data.items)
                console.print_info(f"  Including {group.name}: {names} ({total} item{'s' if total != 1 else ''})")  # type: ignore[union-attr]
            for cat_name, data in group_cats.items():
                all_selections[cat_name] = [item.name for item in data.items]
        else:
            choices = _build_import_item_choices(group_cats)
            selected_values = checkbox_with_separators(
                f"Select {group.name} items to import ({total} available):",
                choices=choices,
                instruction="(Space: toggle, Enter: confirm)",
            )
            parsed = parse_selections(selected_values)
            all_selections.update(parsed)

    return all_selections


# ── Item Choice Builders ───────────────────────────────────────


def _build_group_item_choices(
    group_scanned: dict[str, list[SyncItem]],
    config: SccsConfig,
) -> list[questionary.Choice | questionary.Separator]:
    """Build item-level checkbox choices for a single group."""
    choices: list[questionary.Choice | questionary.Separator] = []

    for cat_name, items in sorted(group_scanned.items()):
        if not items:
            continue

        category = config.sync_categories.get(cat_name)
        description = (category.description if category else cat_name) or cat_name
        choices.append(questionary.Separator(f"── {description} ({len(items)}) ──"))

        for item in sorted(items, key=lambda i: i.name):
            value = f"{cat_name}::{item.name}"
            choices.append(questionary.Choice(title=item.name, value=value, checked=True))

    return choices


def _build_import_item_choices(
    group_cats: dict[str, ManifestCategory],
) -> list[questionary.Choice | questionary.Separator]:
    """Build item-level checkbox choices for import within a group."""
    choices: list[questionary.Choice | questionary.Separator] = []

    for cat_name, cat_data in sorted(group_cats.items()):
        if not cat_data.items:
            continue

        choices.append(questionary.Separator(f"── {cat_data.description} ({len(cat_data.items)}) ──"))

        for item in sorted(cat_data.items, key=lambda i: i.name):
            label = item.name
            if item.platform_hint:
                label += f"  ({item.platform_hint} only)"
            value = f"{cat_name}::{item.name}"
            choices.append(questionary.Choice(title=label, value=value, checked=True))

    return choices


def _build_import_groups(manifest: ExportManifest) -> list[CategoryGroup]:
    """Build category groups from manifest (no config available)."""
    groups: dict[str, CategoryGroup] = {}

    for cat_name, cat_data in sorted(manifest.categories.items()):
        if not cat_data.items:
            continue

        # Detect platform from item hints
        platform = None
        hints = {item.platform_hint for item in cat_data.items if item.platform_hint}
        if hints:
            platform = sorted(hints)[0]

        base_group = _get_group_name(cat_name)

        if platform:
            group_key = f"{base_group}|{platform}"
            group_name = f"{base_group} ({platform})"
        else:
            group_key = base_group
            group_name = base_group

        if group_key not in groups:
            groups[group_key] = CategoryGroup(name=group_name, platform=platform)

        groups[group_key].categories.append(cat_name)
        groups[group_key].item_count += len(cat_data.items)

    return sorted(groups.values(), key=lambda g: (g.platform or "", g.name))


# ── Legacy/Utility Functions ───────────────────────────────────


def build_export_choices(
    scanned: dict[str, list[SyncItem]],
    config: SccsConfig,
    raw_config: dict,
) -> list[questionary.Choice | questionary.Separator]:
    """Build flat checkbox choices for export selection (legacy, used in tests).

    Groups items by category with separators. Each item value uses
    the format "category_name::item_name" for later parsing.
    """
    choices: list[questionary.Choice | questionary.Separator] = []

    for cat_name, items in sorted(scanned.items()):
        if not items:
            continue

        category = config.sync_categories.get(cat_name)
        if category is None:
            continue

        description = category.description or cat_name
        platform_info = _get_platform_label(category)
        separator_label = f"{description}{platform_info}"
        choices.append(questionary.Separator(f"── {separator_label} ──"))

        for item in sorted(items, key=lambda i: i.name):
            label = item.name
            if platform_info:
                label += f"  {platform_info}"
            value = f"{cat_name}::{item.name}"
            choices.append(questionary.Choice(title=label, value=value, checked=True))

    return choices


def build_import_choices(
    manifest: ExportManifest,
) -> list[questionary.Choice | questionary.Separator]:
    """Build flat checkbox choices for import selection (legacy, used in tests)."""
    choices: list[questionary.Choice | questionary.Separator] = []

    for cat_name, cat_data in sorted(manifest.categories.items()):
        if not cat_data.items:
            continue

        platform_info = ""
        hints = {item.platform_hint for item in cat_data.items if item.platform_hint}
        if hints:
            platform_info = f" ({', '.join(sorted(hints))} only)"

        separator_label = f"{cat_data.description}{platform_info}"
        choices.append(questionary.Separator(f"── {separator_label} ──"))

        for item in sorted(cat_data.items, key=lambda i: i.name):
            label = item.name
            if item.platform_hint:
                label += f"  ({item.platform_hint} only)"
            value = f"{cat_name}::{item.name}"
            choices.append(questionary.Choice(title=label, value=value, checked=True))

    return choices


def parse_selections(selected_values: list[str]) -> dict[str, list[str]]:
    """Parse 'category::item_name' values back to {category: [item_names]}."""
    result: dict[str, list[str]] = {}
    for value in selected_values:
        if "::" not in value:
            continue
        cat_name, item_name = value.split("::", 1)
        result.setdefault(cat_name, []).append(item_name)
    return result


def _get_platform_label(category: SyncCategory) -> str:
    """Get platform label string for display."""
    if category.platforms:
        return f" ({', '.join(category.platforms)} only)"
    return ""
