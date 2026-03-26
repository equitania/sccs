# SCCS Transfer UI
# questionary helpers for interactive export/import selection

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING

import questionary

if TYPE_CHECKING:
    from sccs.config.schema import SccsConfig, SyncCategory
    from sccs.sync.item import SyncItem
    from sccs.transfer.manifest import ExportManifest


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


def build_export_choices(
    scanned: dict[str, list[SyncItem]],
    config: SccsConfig,
    raw_config: dict,
) -> list[questionary.Choice | questionary.Separator]:
    """Build checkbox choices for export selection.

    Groups items by category with separators. Each item value uses
    the format "category_name::item_name" for later parsing.

    Args:
        scanned: Dict of category_name -> list of SyncItems (local only).
        config: Validated SCCS config.
        raw_config: Raw YAML config dict for platform hints.
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
    """Build checkbox choices for import selection from manifest.

    Args:
        manifest: Parsed export manifest from ZIP.
    """
    choices: list[questionary.Choice | questionary.Separator] = []

    for cat_name, cat_data in sorted(manifest.categories.items()):
        if not cat_data.items:
            continue

        platform_info = ""
        # Check if all items share the same platform hint
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
    """Parse 'category::item_name' values back to {category: [item_names]}.

    Args:
        selected_values: List of "category_name::item_name" strings.

    Returns:
        Dict mapping category names to lists of selected item names.
    """
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
