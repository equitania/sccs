"""Configuration constants for SCCS."""

import os
from pathlib import Path
from typing import Optional

# Repository root - configurable via environment variable
_REPO_ROOT_ENV = os.environ.get("SCCS_REPO")

# Cache for repo root to avoid repeated lookups
_cached_repo_root: Optional[Path] = None


def _find_repo_root() -> Path:
    """Find the repository root by looking for .git directory.

    Priority order:
    1. SCCS_REPO environment variable
    2. User config repo_path (from ~/.config/sccs/config.json)
    3. Search from cwd upward for .git + .claude directory
    4. Last resort: current working directory

    Returns:
        Path to repository root
    """
    global _cached_repo_root
    if _cached_repo_root is not None:
        return _cached_repo_root

    # 1. Environment variable has highest priority
    if _REPO_ROOT_ENV:
        _cached_repo_root = Path(_REPO_ROOT_ENV)
        return _cached_repo_root

    # 2. User config repo_path - import here to avoid circular import at module level
    from sccs.user_config import get_config

    user_config = get_config()

    # Try repo_path first
    if user_config.repo_path:
        repo_path = Path(user_config.repo_path).expanduser()
        if repo_path.exists():
            _cached_repo_root = repo_path
            return _cached_repo_root

    # Fallback: repo_url might be a local path (migration from old configs)
    if user_config.repo_url and not user_config.repo_url.startswith(
        ("http://", "https://", "git@", "ssh://")
    ):
        repo_path = Path(user_config.repo_url).expanduser()
        if repo_path.exists():
            _cached_repo_root = repo_path
            return _cached_repo_root

    # 3. Search from cwd upward for .git directory with .claude
    current = Path.cwd()
    while current != current.parent:
        if (current / ".git").exists() and (current / ".claude").exists():
            _cached_repo_root = current
            return _cached_repo_root
        current = current.parent

    # 4. Last resort: use cwd (will likely fail later but provides clear error)
    return Path.cwd()


def clear_repo_root_cache() -> None:
    """Clear the cached repo root.

    Call this after configuration changes to force re-detection.
    """
    global _cached_repo_root
    _cached_repo_root = None


# Default LOCAL paths (static - always the same)
DEFAULT_LOCAL_PATH = Path.home() / ".claude" / "skills"
DEFAULT_LOCAL_COMMANDS_PATH = Path.home() / ".claude" / "commands"


def get_default_repo_skills_path() -> Path:
    """Get the default repository skills path.

    Uses lazy evaluation to ensure user config is checked.
    """
    return _find_repo_root() / ".claude" / "skills"


def get_default_repo_commands_path() -> Path:
    """Get the default repository commands path.

    Uses lazy evaluation to ensure user config is checked.
    """
    return _find_repo_root() / ".claude" / "commands"


# State and log files (relative to repo root)
STATE_FILE_NAME = ".sync_state.json"
SYNC_LOG_FILE = "SYNC_LOG.md"

# Skill file patterns
SKILL_FILE = "SKILL.md"
CONTENT_FILE = "content.md"

# Git configuration
AUTO_COMMIT = False  # Set to True to enable auto-commit by default
AUTO_PUSH = False  # Set to True to enable auto-push by default
GIT_REMOTE = "origin"  # Default remote for push operations
COMMIT_PREFIX = "[CHG]"  # Commit message prefix ([ADD], [CHG], [FIX])

# Time format for logs
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def get_repo_root() -> Path:
    """Get the repository root directory."""
    return _find_repo_root()


def get_state_file_path() -> Path:
    """Get the path to the sync state file."""
    return get_repo_root() / STATE_FILE_NAME


def get_sync_log_path() -> Path:
    """Get the path to the sync log file."""
    return get_repo_root() / SYNC_LOG_FILE


def get_local_skills_path() -> Path:
    """Get the local skills path, respecting user config."""
    from sccs.user_config import get_config

    user_config = get_config()
    if user_config.local_skills_path:
        return Path(user_config.local_skills_path).expanduser()
    return DEFAULT_LOCAL_PATH


def get_local_commands_path() -> Path:
    """Get the local commands path, respecting user config."""
    from sccs.user_config import get_config

    user_config = get_config()
    if user_config.local_commands_path:
        return Path(user_config.local_commands_path).expanduser()
    return DEFAULT_LOCAL_COMMANDS_PATH


def get_repo_skills_path() -> Path:
    """Get the repository skills path."""
    return get_repo_root() / ".claude" / "skills"


def get_repo_commands_path() -> Path:
    """Get the repository commands path."""
    return get_repo_root() / ".claude" / "commands"
