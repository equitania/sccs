# SCCS Platform Detection Utilities
# Platform-aware category filtering for cross-platform sync

import platform

# Platform name mapping: system name -> SCCS platform name
_PLATFORM_MAP: dict[str, str] = {
    "Darwin": "macos",
    "Linux": "linux",
    "Windows": "windows",
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
