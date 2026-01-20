"""Configuration constants for SCCS."""

import os
from pathlib import Path
from typing import Optional

from sccs.user_config import get_config

# Repository root - configurable via environment variable or auto-detected
_REPO_ROOT_ENV = os.environ.get("SCCS_REPO")


def _find_repo_root() -> Path:
    """Find the repository root by looking for .git directory.

    Searches from current working directory upward.
    Falls back to user config repo_path if not found.
    """
    if _REPO_ROOT_ENV:
        return Path(_REPO_ROOT_ENV)

    # Search from cwd upward for .git directory
    current = Path.cwd()
    while current != current.parent:
        if (current / ".git").exists() and (current / ".claude").exists():
            return current
        current = current.parent

    # Try user config
    user_config = get_config()
    if user_config.repo_path:
        repo_path = Path(user_config.repo_path).expanduser()
        if repo_path.exists():
            return repo_path

    # Last resort: use cwd
    return Path.cwd()


# Default paths for skills
DEFAULT_LOCAL_PATH = Path.home() / ".claude" / "skills"
DEFAULT_REPO_PATH = _find_repo_root() / ".claude" / "skills"

# Default paths for commands
DEFAULT_LOCAL_COMMANDS_PATH = Path.home() / ".claude" / "commands"
DEFAULT_REPO_COMMANDS_PATH = _find_repo_root() / ".claude" / "commands"

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
    user_config = get_config()
    if user_config.local_skills_path:
        return Path(user_config.local_skills_path).expanduser()
    return DEFAULT_LOCAL_PATH


def get_local_commands_path() -> Path:
    """Get the local commands path, respecting user config."""
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
