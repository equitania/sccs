# SCCS Settings Ensure
# Non-destructive JSON merge logic for ensuring settings entries exist

import json
from dataclasses import dataclass, field
from pathlib import Path

from sccs.config.schema import SettingsEnsure
from sccs.utils.paths import atomic_write, create_backup, ensure_dir


@dataclass
class SettingsEnsureResult:
    """Result of a settings ensure operation."""

    target_file: str
    keys_added: list[str] = field(default_factory=list)
    keys_skipped: list[str] = field(default_factory=list)
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
    if not config.entries:
        return result

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

    # Determine which keys to add vs skip
    for key, _value in config.entries.items():
        if key in existing:
            result.keys_skipped.append(key)
        else:
            result.keys_added.append(key)

    # Nothing to add - no modification needed
    if not result.keys_added:
        result.file_created = False
        return result

    result.file_modified = True

    # Dry run - report only, don't modify
    if dry_run:
        return result

    # Build merged settings (existing + new keys)
    merged = dict(existing)
    for key in result.keys_added:
        merged[key] = config.entries[key]

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
