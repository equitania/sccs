"""Sync state management for tracking last synchronization."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sccs.config import ISO_FORMAT, get_state_file_path


@dataclass
class SkillState:
    """State of a skill at last sync."""

    name: str
    mtime_local: float
    mtime_repo: float
    content_hash: str
    last_sync: str  # ISO format datetime string

    @classmethod
    def create(cls, name: str, mtime_local: float, mtime_repo: float, content_hash: str) -> SkillState:
        """Create a new SkillState with current timestamp."""
        return cls(
            name=name,
            mtime_local=mtime_local,
            mtime_repo=mtime_repo,
            content_hash=content_hash,
            last_sync=datetime.now(timezone.utc).strftime(ISO_FORMAT),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SkillState:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            mtime_local=data["mtime_local"],
            mtime_repo=data["mtime_repo"],
            content_hash=data["content_hash"],
            last_sync=data["last_sync"],
        )


@dataclass
class CommandState:
    """State of a command at last sync."""

    name: str
    mtime_local: float
    mtime_repo: float
    content_hash: str
    last_sync: str  # ISO format datetime string

    @classmethod
    def create(cls, name: str, mtime_local: float, mtime_repo: float, content_hash: str) -> "CommandState":
        """Create a new CommandState with current timestamp."""
        return cls(
            name=name,
            mtime_local=mtime_local,
            mtime_repo=mtime_repo,
            content_hash=content_hash,
            last_sync=datetime.now(timezone.utc).strftime(ISO_FORMAT),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CommandState":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            mtime_local=data["mtime_local"],
            mtime_repo=data["mtime_repo"],
            content_hash=data["content_hash"],
            last_sync=data["last_sync"],
        )


@dataclass
class SyncState:
    """Persistent state tracking last sync for all skills and commands."""

    version: str = "1.0"
    last_sync_time: str = ""
    skills: dict[str, SkillState] = field(default_factory=dict)
    commands: dict[str, CommandState] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> SyncState:
        """Load state from JSON file.

        Args:
            path: Path to state file, or None for default

        Returns:
            SyncState instance (empty if file doesn't exist)
        """
        if path is None:
            path = get_state_file_path()

        if not path.exists():
            return cls()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            skills = {}
            for name, skill_data in data.get("skills", {}).items():
                skill_data["name"] = name
                skills[name] = SkillState.from_dict(skill_data)

            commands = {}
            for name, command_data in data.get("commands", {}).items():
                command_data["name"] = name
                commands[name] = CommandState.from_dict(command_data)

            return cls(
                version=data.get("version", "1.0"),
                last_sync_time=data.get("last_sync_time", ""),
                skills=skills,
                commands=commands,
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            # Corrupted state file, return empty state
            return cls()

    def save(self, path: Optional[Path] = None) -> None:
        """Persist state to JSON file.

        Args:
            path: Path to state file, or None for default
        """
        if path is None:
            path = get_state_file_path()

        # Update last sync time
        self.last_sync_time = datetime.now(timezone.utc).strftime(ISO_FORMAT)

        # Convert to JSON-serializable dict
        data = {
            "version": self.version,
            "last_sync_time": self.last_sync_time,
            "skills": {},
            "commands": {},
        }

        for name, skill_state in self.skills.items():
            skill_dict = skill_state.to_dict()
            del skill_dict["name"]  # Name is the key
            data["skills"][name] = skill_dict

        for name, command_state in self.commands.items():
            command_dict = command_state.to_dict()
            del command_dict["name"]  # Name is the key
            data["commands"][name] = command_dict

        # Write with backup
        if path.exists():
            backup_path = path.with_suffix(".json.bak")
            backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get_skill_state(self, name: str) -> Optional[SkillState]:
        """Get state for a specific skill.

        Args:
            name: Skill name

        Returns:
            SkillState or None if not found
        """
        return self.skills.get(name)

    def update_skill(self, name: str, mtime_local: float, mtime_repo: float, content_hash: str) -> None:
        """Update state for a skill after successful sync.

        Args:
            name: Skill name
            mtime_local: Local modification time
            mtime_repo: Repository modification time
            content_hash: Content hash after sync
        """
        self.skills[name] = SkillState.create(
            name=name,
            mtime_local=mtime_local,
            mtime_repo=mtime_repo,
            content_hash=content_hash,
        )

    def remove_skill(self, name: str) -> None:
        """Remove a skill from state.

        Args:
            name: Skill name to remove
        """
        self.skills.pop(name, None)

    def has_skill(self, name: str) -> bool:
        """Check if skill exists in state.

        Args:
            name: Skill name

        Returns:
            True if skill is tracked
        """
        return name in self.skills

    # Command state methods
    def get_command_state(self, name: str) -> Optional[CommandState]:
        """Get state for a specific command.

        Args:
            name: Command name

        Returns:
            CommandState or None if not found
        """
        return self.commands.get(name)

    def update_command(self, name: str, mtime_local: float, mtime_repo: float, content_hash: str) -> None:
        """Update state for a command after successful sync.

        Args:
            name: Command name
            mtime_local: Local modification time
            mtime_repo: Repository modification time
            content_hash: Content hash after sync
        """
        self.commands[name] = CommandState.create(
            name=name,
            mtime_local=mtime_local,
            mtime_repo=mtime_repo,
            content_hash=content_hash,
        )

    def remove_command(self, name: str) -> None:
        """Remove a command from state.

        Args:
            name: Command name to remove
        """
        self.commands.pop(name, None)

    def has_command(self, name: str) -> bool:
        """Check if command exists in state.

        Args:
            name: Command name

        Returns:
            True if command is tracked
        """
        return name in self.commands
