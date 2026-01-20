"""Configuration synchronization for Claude Code settings.

This module handles synchronization of Claude Code configuration files
between the local ~/.claude/ directory and a repository with support for
path placeholder transformation.

Supported files:
- settings.json (with path transformation)
- CLAUDE.md, COMMANDS.md, FLAGS.md, etc. (direct copy)
- hooks/ directory (with path validation)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# Path placeholders for cross-platform compatibility
PLACEHOLDERS = {
    "{{HOME}}": lambda: str(Path.home()),
    "{{CLAUDE_DIR}}": lambda: str(Path.home() / ".claude"),
    "{{WORKSPACE_DIR}}": lambda: os.environ.get(
        "CLAUDE_WORKSPACE_DIR", str(Path.home() / "gitbase")
    ),
    "{{USERNAME}}": lambda: os.environ.get("USER", os.environ.get("USERNAME", "user")),
}

# Files that should be synced directly (no transformation needed)
DIRECT_SYNC_FILES = [
    "CLAUDE.md",
    "COMMANDS.md",
    "FLAGS.md",
    "MCP.md",
    "MODES.md",
    "ORCHESTRATOR.md",
    "PERSONAS.md",
    "PRINCIPLES.md",
    "RULES.md",
]

# Files that require path transformation
TRANSFORM_FILES = [
    "settings.json",
]

# Files that should NEVER be synced (sensitive/local-only)
EXCLUDED_FILES = [
    "credentials.json",
    "history.jsonl",
    ".DS_Store",
]

# Directories that should NEVER be synced
EXCLUDED_DIRS = [
    "projects",
    "cache",
    "debug",
    "logs",
    "file-history",
    "paste-cache",
    "plans",
    "ide",
    "local",  # Contains local node installation
]

# Directories that can be synced
SYNCABLE_DIRS = [
    "hooks",
    "commands",  # Already handled by main sync, but included for completeness
]


class ConfigActionType(Enum):
    """Type of configuration sync action."""

    UNCHANGED = "unchanged"
    EXPORT = "export"  # Local -> Repo (with transformation)
    IMPORT = "import"  # Repo -> Local (with transformation)
    CONFLICT = "conflict"
    NEW_LOCAL = "new_local"
    NEW_REPO = "new_repo"
    DELETED_LOCAL = "deleted_local"
    DELETED_REPO = "deleted_repo"


@dataclass
class ConfigSyncAction:
    """Represents a configuration sync action."""

    file_name: str
    action_type: ConfigActionType
    local_path: Optional[Path] = None
    repo_path: Optional[Path] = None
    local_mtime: Optional[float] = None
    repo_mtime: Optional[float] = None
    requires_transform: bool = False
    details: str = ""


@dataclass
class ConfigSyncState:
    """State for configuration sync tracking."""

    version: str = "1.0"
    last_sync_time: Optional[str] = None
    files: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "ConfigSyncState":
        """Load state from file."""
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                state = cls(
                    version=data.get("version", "1.0"),
                    last_sync_time=data.get("last_sync_time"),
                    files=data.get("files", {}),
                )
                return state
            except (json.JSONDecodeError, KeyError):
                pass
        return cls()

    def save(self, path: Path) -> None:
        """Save state to file."""
        data = {
            "version": self.version,
            "last_sync_time": self.last_sync_time,
            "files": self.files,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class PathTransformer:
    """Handles path placeholder transformation."""

    @staticmethod
    def to_placeholders(content: str) -> str:
        """Convert absolute paths to placeholders.

        This is used when exporting from local to repository.
        """
        result = content

        # Sort by length (longest first) to avoid partial replacements
        sorted_placeholders = sorted(
            PLACEHOLDERS.items(), key=lambda x: len(x[1]()), reverse=True
        )

        for placeholder, value_func in sorted_placeholders:
            value = value_func()
            # Escape special regex characters in the path
            escaped_value = re.escape(value)
            # Replace the actual path with the placeholder
            result = re.sub(escaped_value, placeholder, result)

        return result

    @staticmethod
    def from_placeholders(content: str) -> str:
        """Convert placeholders to actual paths.

        This is used when importing from repository to local.
        """
        result = content

        for placeholder, value_func in PLACEHOLDERS.items():
            value = value_func()
            result = result.replace(placeholder, value)

        return result

    @staticmethod
    def detect_absolute_paths(content: str) -> list[str]:
        """Detect potential absolute paths that might need transformation.

        Returns a list of detected paths for user review.
        """
        patterns = [
            r"/Users/[a-zA-Z0-9_-]+",  # macOS
            r"/home/[a-zA-Z0-9_-]+",  # Linux
            r"C:\\Users\\[a-zA-Z0-9_-]+",  # Windows
            r"/opt/[a-zA-Z0-9_-]+",  # Common installation paths
        ]

        found = []
        for pattern in patterns:
            matches = re.findall(pattern, content)
            found.extend(matches)

        return list(set(found))

    @staticmethod
    def has_untransformed_paths(content: str) -> bool:
        """Check if content contains paths that weren't transformed."""
        # After transformation, there should be no absolute user paths
        # Only placeholders should remain
        absolute_paths = PathTransformer.detect_absolute_paths(content)
        return len(absolute_paths) > 0


class ConfigSyncEngine:
    """Engine for synchronizing Claude Code configuration files."""

    def __init__(
        self,
        local_claude_dir: Optional[Path] = None,
        repo_config_dir: Optional[Path] = None,
        state: Optional[ConfigSyncState] = None,
        dry_run: bool = False,
    ):
        """Initialize the config sync engine.

        Args:
            local_claude_dir: Path to local ~/.claude directory
            repo_config_dir: Path to repository config directory
            state: Sync state (loaded or new)
            dry_run: If True, don't make actual changes
        """
        self.local_dir = local_claude_dir or Path.home() / ".claude"
        self.repo_dir = repo_config_dir or self._find_repo_config_dir()
        self.state = state or ConfigSyncState()
        self.dry_run = dry_run
        self.transformer = PathTransformer()

    def _find_repo_config_dir(self) -> Path:
        """Find the repository config directory."""
        # Try to find repo root
        current = Path.cwd()
        while current != current.parent:
            if (current / ".git").exists():
                config_dir = current / ".claude" / "config"
                return config_dir
            current = current.parent

        # Fallback
        return Path.cwd() / ".claude" / "config"

    def scan_files(self) -> tuple[dict[str, Path], dict[str, Path]]:
        """Scan local and repo directories for syncable files.

        Returns:
            Tuple of (local_files, repo_files) dictionaries
        """
        local_files = {}
        repo_files = {}

        # Scan local directory
        if self.local_dir.exists():
            for item in self.local_dir.iterdir():
                if item.is_file():
                    if item.name in EXCLUDED_FILES:
                        continue
                    if item.name in DIRECT_SYNC_FILES or item.name in TRANSFORM_FILES:
                        local_files[item.name] = item

        # Scan repo directory
        if self.repo_dir.exists():
            for item in self.repo_dir.iterdir():
                if item.is_file():
                    if item.name.endswith(".template.json"):
                        # Map template to actual file name
                        actual_name = item.name.replace(".template", "")
                        repo_files[actual_name] = item
                    elif item.name in DIRECT_SYNC_FILES:
                        repo_files[item.name] = item

        return local_files, repo_files

    def detect_changes(self) -> list[ConfigSyncAction]:
        """Detect changes between local and repo config files.

        Returns:
            List of sync actions needed
        """
        local_files, repo_files = self.scan_files()
        actions = []

        all_files = set(local_files.keys()) | set(repo_files.keys())

        for file_name in sorted(all_files):
            local_path = local_files.get(file_name)
            repo_path = repo_files.get(file_name)

            requires_transform = file_name in TRANSFORM_FILES

            if local_path and repo_path:
                # Both exist - compare
                local_mtime = local_path.stat().st_mtime
                repo_mtime = repo_path.stat().st_mtime

                # Check content hash for comparison
                local_content = local_path.read_text(encoding="utf-8")
                repo_content = repo_path.read_text(encoding="utf-8")

                # For transform files, normalize before comparison
                if requires_transform:
                    local_normalized = self.transformer.to_placeholders(local_content)
                    repo_normalized = repo_content
                else:
                    local_normalized = local_content
                    repo_normalized = repo_content

                local_hash = hashlib.sha256(local_normalized.encode()).hexdigest()
                repo_hash = hashlib.sha256(repo_normalized.encode()).hexdigest()

                # Get last sync info
                file_state = self.state.files.get(file_name, {})
                last_hash = file_state.get("content_hash")

                if local_hash == repo_hash:
                    action_type = ConfigActionType.UNCHANGED
                elif last_hash is None:
                    # First sync - use newer
                    if local_mtime > repo_mtime:
                        action_type = ConfigActionType.EXPORT
                    else:
                        action_type = ConfigActionType.IMPORT
                elif local_hash != last_hash and repo_hash != last_hash:
                    # Both changed since last sync
                    action_type = ConfigActionType.CONFLICT
                elif local_hash != last_hash:
                    action_type = ConfigActionType.EXPORT
                else:
                    action_type = ConfigActionType.IMPORT

                actions.append(
                    ConfigSyncAction(
                        file_name=file_name,
                        action_type=action_type,
                        local_path=local_path,
                        repo_path=repo_path,
                        local_mtime=local_mtime,
                        repo_mtime=repo_mtime,
                        requires_transform=requires_transform,
                    )
                )

            elif local_path and not repo_path:
                # Only local exists
                actions.append(
                    ConfigSyncAction(
                        file_name=file_name,
                        action_type=ConfigActionType.NEW_LOCAL,
                        local_path=local_path,
                        local_mtime=local_path.stat().st_mtime,
                        requires_transform=requires_transform,
                    )
                )

            elif repo_path and not local_path:
                # Only repo exists
                actions.append(
                    ConfigSyncAction(
                        file_name=file_name,
                        action_type=ConfigActionType.NEW_REPO,
                        repo_path=repo_path,
                        repo_mtime=repo_path.stat().st_mtime,
                        requires_transform=requires_transform,
                    )
                )

        return actions

    def execute_action(
        self, action: ConfigSyncAction, resolution: Optional[str] = None
    ) -> bool:
        """Execute a sync action.

        Args:
            action: The action to execute
            resolution: For conflicts, "local" or "repo"

        Returns:
            True if successful
        """
        if self.dry_run:
            return True

        try:
            if action.action_type == ConfigActionType.UNCHANGED:
                return True

            elif action.action_type in (
                ConfigActionType.EXPORT,
                ConfigActionType.NEW_LOCAL,
            ):
                return self._export_to_repo(action)

            elif action.action_type in (
                ConfigActionType.IMPORT,
                ConfigActionType.NEW_REPO,
            ):
                return self._import_from_repo(action)

            elif action.action_type == ConfigActionType.CONFLICT:
                if resolution == "local":
                    return self._export_to_repo(action)
                elif resolution == "repo":
                    return self._import_from_repo(action)
                return False

            return False

        except Exception as e:
            action.details = str(e)
            return False

    def _export_to_repo(self, action: ConfigSyncAction) -> bool:
        """Export local file to repository (with transformation if needed)."""
        if not action.local_path:
            return False

        content = action.local_path.read_text(encoding="utf-8")

        if action.requires_transform:
            content = self.transformer.to_placeholders(content)
            # Save as template file
            repo_path = self.repo_dir / f"{action.file_name.replace('.json', '.template.json')}"
        else:
            repo_path = self.repo_dir / action.file_name

        # Ensure directory exists
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        repo_path.write_text(content, encoding="utf-8")

        # Update state
        self._update_state(action.file_name, content)

        return True

    def _import_from_repo(self, action: ConfigSyncAction) -> bool:
        """Import file from repository to local (with transformation if needed)."""
        if not action.repo_path:
            return False

        content = action.repo_path.read_text(encoding="utf-8")

        if action.requires_transform:
            content = self.transformer.from_placeholders(content)

        local_path = self.local_dir / action.file_name

        # Ensure directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")

        # For state tracking, use the template content (with placeholders)
        if action.requires_transform:
            template_content = action.repo_path.read_text(encoding="utf-8")
            self._update_state(action.file_name, template_content)
        else:
            self._update_state(action.file_name, content)

        return True

    def _update_state(self, file_name: str, content: str) -> None:
        """Update sync state for a file."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.state.files[file_name] = {
            "content_hash": content_hash,
            "last_sync": datetime.now(timezone.utc).isoformat(),
        }

    def save_state(self, path: Optional[Path] = None) -> None:
        """Save sync state."""
        if path is None:
            path = self.repo_dir.parent.parent / ".config_sync_state.json"

        self.state.last_sync_time = datetime.now(timezone.utc).isoformat()
        self.state.save(path)


def sync_hooks_directory(
    local_hooks: Path,
    repo_hooks: Path,
    direction: str = "export",
    dry_run: bool = False,
) -> list[str]:
    """Synchronize the hooks directory.

    Args:
        local_hooks: Path to ~/.claude/hooks/
        repo_hooks: Path to repository hooks/
        direction: "export" (local->repo) or "import" (repo->local)
        dry_run: If True, don't make actual changes

    Returns:
        List of synced file names
    """
    synced = []

    if direction == "export":
        source = local_hooks
        dest = repo_hooks
    else:
        source = repo_hooks
        dest = local_hooks

    if not source.exists():
        return synced

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    for item in source.iterdir():
        if item.is_file():
            dest_file = dest / item.name
            if not dry_run:
                content = item.read_text(encoding="utf-8")
                # Transform paths if exporting
                if direction == "export":
                    content = PathTransformer.to_placeholders(content)
                else:
                    content = PathTransformer.from_placeholders(content)
                dest_file.write_text(content, encoding="utf-8")
                # Preserve executable permission
                if os.access(item, os.X_OK):
                    os.chmod(dest_file, item.stat().st_mode)
            synced.append(item.name)

    return synced


def generate_settings_template(settings_path: Path) -> str:
    """Generate a template from existing settings.json.

    Args:
        settings_path: Path to the local settings.json

    Returns:
        Template content with placeholders
    """
    if not settings_path.exists():
        return "{}"

    content = settings_path.read_text(encoding="utf-8")
    return PathTransformer.to_placeholders(content)


def apply_settings_template(template_path: Path, output_path: Path) -> None:
    """Apply a settings template to create local settings.json.

    Args:
        template_path: Path to settings.template.json
        output_path: Path to write settings.json
    """
    content = template_path.read_text(encoding="utf-8")
    resolved = PathTransformer.from_placeholders(content)

    # Validate JSON
    try:
        json.loads(resolved)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON after transformation: {e}") from e

    output_path.write_text(resolved, encoding="utf-8")
