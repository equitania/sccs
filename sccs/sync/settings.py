# SCCS Settings Ensure
# Non-destructive JSON merge logic for ensuring settings entries exist

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sccs.config.schema import SettingsEnsure
from sccs.utils.paths import atomic_write, create_backup, ensure_dir
from sccs.utils.platform import get_current_platform


@dataclass
class SettingsEnsureResult:
    """Result of a settings ensure operation."""

    target_file: str
    keys_added: list[str] = field(default_factory=list)
    keys_skipped: list[str] = field(default_factory=list)
    keys_overridden: list[str] = field(default_factory=list)
    file_created: bool = False
    file_modified: bool = False
    backup_path: Path | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        """Check if operation completed without errors."""
        return self.error is None


def ensure_settings(
    config: SettingsEnsure,
    *,
    dry_run: bool = False,
    category_name: str = "unknown",
) -> SettingsEnsureResult:
    """
    Ensure JSON settings file contains required entries.

    Non-destructive: missing keys are added, existing keys are NEVER overwritten.

    Args:
        config: Settings ensure configuration.
        dry_run: If True, only report changes without modifying files.
        category_name: Category name for backup organization.

    Returns:
        SettingsEnsureResult with details of what was done.
    """
    target = Path(config.target_file)
    result = SettingsEnsureResult(target_file=str(target))

    # No entries configured - nothing to do
    if not config.entries and not config.platform_overrides:
        return result

    # Resolve effective entries by deep-merging the platform override (if any)
    # over the base entries. Only the override for the current platform applies.
    overrides_for_platform = config.platform_overrides.get(get_current_platform(), {})

    # Read existing settings or start fresh
    existing: dict = {}
    file_exists = target.exists()

    if file_exists:
        try:
            raw = target.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            result.error = f"Malformed JSON in {target}: {e}"
            return result
        except PermissionError:
            result.error = f"Permission denied reading {target}"
            return result

        if not isinstance(parsed, dict):
            result.error = f"JSON root is not an object in {target}"
            return result

        existing = parsed
    else:
        if not config.create_if_missing:
            return result
        result.file_created = True

    # Classify base entries: missing → add, present → skip (non-destructive).
    for key in config.entries:
        if key in existing:
            result.keys_skipped.append(key)
        else:
            result.keys_added.append(key)

    # Platform overrides ALWAYS apply for the current platform — they're an
    # explicit per-OS choice, so they overwrite even if the key already exists.
    for key in overrides_for_platform:
        if key in existing:
            result.keys_overridden.append(key)
        elif key not in result.keys_added:
            result.keys_added.append(key)

    # Nothing to do - no modification needed
    if not result.keys_added and not result.keys_overridden:
        result.file_created = False
        return result

    result.file_modified = True

    # Dry run - report only, don't modify
    if dry_run:
        return result

    # Build merged settings: existing → new keys → platform overrides on top.
    merged: dict[str, Any] = dict(existing)
    for key in result.keys_added:
        if key in config.entries:
            merged[key] = config.entries[key]
    for key, value in overrides_for_platform.items():
        merged[key] = _deep_merge(merged.get(key), value)

    # Create backup before modifying existing file
    if config.backup_before_modify and file_exists:
        try:
            result.backup_path = create_backup(target, category=category_name)
        except Exception as e:
            result.error = f"Failed to create backup: {e}"
            return result

    # Write merged settings atomically
    try:
        ensure_dir(target.parent)
        content = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
        atomic_write(target, content)
    except PermissionError:
        result.error = f"Permission denied writing {target}"
        return result
    except Exception as e:
        result.error = f"Failed to write {target}: {e}"
        return result

    return result


def _deep_merge(base: Any, override: Any) -> Any:
    """
    Deep-merge ``override`` into ``base``, returning a new value.

    - When both are dicts, keys are merged recursively (override wins on leaf).
    - Otherwise ``override`` replaces ``base`` entirely.

    Used so that platform overrides like ``{"statusLine": {"command": "..."}}``
    can replace a single nested key without dropping siblings already present
    in the existing settings.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        result: dict[str, Any] = dict(base)
        for key, value in override.items():
            result[key] = _deep_merge(result.get(key), value)
        return result
    return override
