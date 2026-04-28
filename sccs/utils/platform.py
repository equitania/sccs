# SCCS Platform Detection Utilities
# Platform-aware category filtering and shell-availability checks

from __future__ import annotations

import platform
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sccs.config.schema import SccsConfig

# Platform name mapping: system name -> SCCS platform name
_PLATFORM_MAP: dict[str, str] = {
    "Darwin": "macos",
    "Linux": "linux",
    "Windows": "windows",
}

# Mapping from SCCS category name fragments / local_path fragments to the
# shell binary that needs to be on PATH for the category to be useful.
# Keys are lower-cased substrings tested against `local_path` and category name.
_SHELL_HINTS: dict[str, tuple[str, ...]] = {
    "fish": ("fish",),
    "powershell": ("pwsh", "powershell"),
    "bash": ("bash",),
    "zsh": ("zsh",),
}


def get_current_platform() -> str:
    """
    Get the current platform identifier.

    Returns:
        Platform string: "macos", "linux", or "windows".
    """
    system = platform.system()
    return _PLATFORM_MAP.get(system, system.lower())


def is_platform_match(platforms: list[str] | None) -> bool:
    """
    Check if the current platform matches the given platform filter.

    Args:
        platforms: List of platform names to match against.
                   None or empty list means all platforms match.

    Returns:
        True if current platform is in the list, or if list is None/empty.
    """
    if not platforms:
        return True
    return get_current_platform() in platforms


def is_shell_available(shell: str) -> bool:
    """
    Check if a shell binary is available in PATH.

    For "powershell" we accept either `pwsh` (PowerShell 7+) or the legacy
    `powershell` (Windows PowerShell 5.x).
    """
    candidates = _SHELL_HINTS.get(shell.lower(), (shell,))
    return any(shutil.which(c) is not None for c in candidates)


def detect_shell_for_category(category_name: str, local_path: str) -> str | None:
    """
    Heuristically determine which shell a category targets.

    Returns the shell key (e.g. "fish", "powershell") if the category name
    or local_path mentions a known shell, otherwise None.
    """
    haystack = f"{category_name.lower()} {local_path.lower()}"
    for shell in _SHELL_HINTS:
        if shell in haystack:
            return shell
    return None


def get_unavailable_shells_for_enabled_categories(
    config: SccsConfig,
) -> dict[str, list[str]]:
    """
    Return shells that are referenced by *enabled* categories on this platform
    but whose binaries are not available in PATH.

    Returns:
        Mapping of shell name -> list of affected category names.
        Empty dict if all referenced shells are available (or no shells
        are referenced at all).
    """
    affected: dict[str, list[str]] = {}
    enabled = config.get_enabled_categories()
    for name, cat in enabled.items():
        shell = detect_shell_for_category(name, cat.local_path)
        if shell is None:
            continue
        if is_shell_available(shell):
            continue
        affected.setdefault(shell, []).append(name)
    return affected


def get_platform_skipped_categories(config: SccsConfig) -> dict[str, list[str]]:
    """
    Return categories that are configured (enabled in YAML) but skipped on
    the current platform because their `platforms` filter excludes it.

    Returns:
        Mapping of shell-or-platform-name -> list of category names that were
        skipped. Categories without a detectable shell are grouped under
        the literal key "other".
    """
    current = get_current_platform()
    skipped: dict[str, list[str]] = {}

    for name, cat in config.sync_categories.items():
        if not cat.enabled:
            continue
        if not cat.platforms:
            continue
        if current in cat.platforms:
            continue

        # Group by the shell hinted by the category, fall back to "other"
        shell = detect_shell_for_category(name, cat.local_path) or "other"
        skipped.setdefault(shell, []).append(name)

    return skipped
