"""Core synchronization engine for bidirectional skill and command sync."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from sccs.command import Command, scan_commands_directory
from sccs.config import (
    DATETIME_FORMAT,
    DEFAULT_LOCAL_COMMANDS_PATH,
    DEFAULT_LOCAL_PATH,
    DEFAULT_REPO_COMMANDS_PATH,
    DEFAULT_REPO_PATH,
)
from sccs.skill import Skill, scan_skills_directory
from sccs.state import SyncState


class ItemType(Enum):
    """Types of sync items."""

    SKILL = "skill"
    COMMAND = "command"


class ActionType(Enum):
    """Types of sync actions."""

    COPY_TO_REPO = "copy_to_repo"  # Local is newer → copy to repo
    COPY_TO_LOCAL = "copy_to_local"  # Repo is newer → copy to local
    CONFLICT = "conflict"  # Both changed since last sync
    NEW_LOCAL = "new_local"  # Item only exists locally
    NEW_REPO = "new_repo"  # Item only exists in repo
    DELETED_LOCAL = "deleted_local"  # Item deleted locally (was in state)
    DELETED_REPO = "deleted_repo"  # Item deleted in repo (was in state)
    UNCHANGED = "unchanged"  # No changes needed


@dataclass
class SyncAction:
    """Represents a sync operation to perform."""

    action_type: ActionType
    skill_name: str  # Also used for command_name (legacy naming)
    item_type: ItemType = ItemType.SKILL
    source: Optional[Path] = None
    destination: Optional[Path] = None
    reason: str = ""
    local_mtime: Optional[float] = None
    repo_mtime: Optional[float] = None
    local_skill: Optional[Skill] = None
    repo_skill: Optional[Skill] = None
    local_command: Optional[Command] = None
    repo_command: Optional[Command] = None

    @property
    def item_name(self) -> str:
        """Get the name of the item (skill or command)."""
        return self.skill_name

    def get_direction_arrow(self) -> str:
        """Get arrow indicating sync direction."""
        if self.action_type in (ActionType.COPY_TO_REPO, ActionType.NEW_LOCAL):
            return "local → repo"
        elif self.action_type in (ActionType.COPY_TO_LOCAL, ActionType.NEW_REPO):
            return "repo → local"
        elif self.action_type == ActionType.CONFLICT:
            return "⚠ conflict"
        elif self.action_type == ActionType.DELETED_LOCAL:
            return "✗ deleted locally"
        elif self.action_type == ActionType.DELETED_REPO:
            return "✗ deleted in repo"
        return "—"

    def get_item_type_label(self) -> str:
        """Get label for the item type."""
        return self.item_type.value.capitalize()


@dataclass
class SyncResult:
    """Result of sync operation."""

    success: bool = True
    actions_executed: list[SyncAction] = field(default_factory=list)
    actions_skipped: list[SyncAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_synced(self) -> int:
        """Count of successfully synced skills."""
        return len(self.actions_executed)

    @property
    def to_repo_count(self) -> int:
        """Count of skills synced to repo."""
        return sum(
            1 for a in self.actions_executed if a.action_type in (ActionType.COPY_TO_REPO, ActionType.NEW_LOCAL)
        )

    @property
    def to_local_count(self) -> int:
        """Count of skills synced to local."""
        return sum(
            1 for a in self.actions_executed if a.action_type in (ActionType.COPY_TO_LOCAL, ActionType.NEW_REPO)
        )


class SyncEngine:
    """Core engine for bidirectional skill and command synchronization."""

    def __init__(
        self,
        local_path: Optional[Path] = None,
        repo_path: Optional[Path] = None,
        local_commands_path: Optional[Path] = None,
        repo_commands_path: Optional[Path] = None,
        state: Optional[SyncState] = None,
        dry_run: bool = False,
    ):
        """Initialize sync engine.

        Args:
            local_path: Path to local skills directory
            repo_path: Path to repository skills directory
            local_commands_path: Path to local commands directory
            repo_commands_path: Path to repository commands directory
            state: Sync state (loaded from file if None)
            dry_run: If True, don't make any changes
        """
        self.local_path = local_path or DEFAULT_LOCAL_PATH
        self.repo_path = repo_path or DEFAULT_REPO_PATH
        self.local_commands_path = local_commands_path or DEFAULT_LOCAL_COMMANDS_PATH
        self.repo_commands_path = repo_commands_path or DEFAULT_REPO_COMMANDS_PATH
        self.state = state or SyncState.load()
        self.dry_run = dry_run
        self.local_skills: dict[str, Skill] = {}
        self.repo_skills: dict[str, Skill] = {}
        self.local_commands: dict[str, Command] = {}
        self.repo_commands: dict[str, Command] = {}

    def scan_skills(self) -> tuple[dict[str, Skill], dict[str, Skill]]:
        """Scan both locations and return skill dictionaries.

        Returns:
            Tuple of (local_skills, repo_skills)
        """
        self.local_skills = scan_skills_directory(self.local_path)
        self.repo_skills = scan_skills_directory(self.repo_path)
        return self.local_skills, self.repo_skills

    def scan_commands(self) -> tuple[dict[str, Command], dict[str, Command]]:
        """Scan both locations and return command dictionaries.

        Returns:
            Tuple of (local_commands, repo_commands)
        """
        self.local_commands = scan_commands_directory(self.local_commands_path)
        self.repo_commands = scan_commands_directory(self.repo_commands_path)
        return self.local_commands, self.repo_commands

    def scan_all(self) -> None:
        """Scan all skills and commands in both locations."""
        self.scan_skills()
        self.scan_commands()

    def detect_changes(self) -> list[SyncAction]:
        """Detect all changes and generate sync actions for skills only.

        Returns:
            List of SyncAction objects
        """
        if not self.local_skills and not self.repo_skills:
            self.scan_skills()

        actions: list[SyncAction] = []

        # Get all unique skill names
        all_names = set(self.local_skills.keys()) | set(self.repo_skills.keys()) | set(self.state.skills.keys())

        for name in sorted(all_names):
            action = self._classify_change(name)
            if action.action_type != ActionType.UNCHANGED:
                actions.append(action)

        return actions

    def detect_command_changes(self) -> list[SyncAction]:
        """Detect all changes and generate sync actions for commands.

        Returns:
            List of SyncAction objects for commands
        """
        if not self.local_commands and not self.repo_commands:
            self.scan_commands()

        actions: list[SyncAction] = []

        # Get all unique command names
        all_names = set(self.local_commands.keys()) | set(self.repo_commands.keys()) | set(self.state.commands.keys())

        for name in sorted(all_names):
            action = self._classify_command_change(name)
            if action.action_type != ActionType.UNCHANGED:
                actions.append(action)

        return actions

    def detect_all_changes(self) -> list[SyncAction]:
        """Detect all changes for both skills and commands.

        Returns:
            List of SyncAction objects for both skills and commands
        """
        self.scan_all()
        skill_actions = self.detect_changes()
        command_actions = self.detect_command_changes()
        return skill_actions + command_actions

    def _classify_change(self, name: str) -> SyncAction:
        """Classify change type for a skill.

        Args:
            name: Skill name

        Returns:
            SyncAction with appropriate type
        """
        local = self.local_skills.get(name)
        repo = self.repo_skills.get(name)
        prev_state = self.state.get_skill_state(name)

        # Case 1: Skill exists only locally
        if local and not repo:
            if prev_state:
                # Was synced before, now deleted in repo
                return SyncAction(
                    action_type=ActionType.DELETED_REPO,
                    skill_name=name,
                    source=local.path,
                    reason="Deleted in repository since last sync",
                    local_mtime=local.mtime,
                    local_skill=local,
                )
            else:
                # New local skill
                return SyncAction(
                    action_type=ActionType.NEW_LOCAL,
                    skill_name=name,
                    source=local.path,
                    destination=self.repo_path / name,
                    reason="New skill (local only)",
                    local_mtime=local.mtime,
                    local_skill=local,
                )

        # Case 2: Skill exists only in repo
        if repo and not local:
            if prev_state:
                # Was synced before, now deleted locally
                return SyncAction(
                    action_type=ActionType.DELETED_LOCAL,
                    skill_name=name,
                    source=repo.path,
                    reason="Deleted locally since last sync",
                    repo_mtime=repo.mtime,
                    repo_skill=repo,
                )
            else:
                # New repo skill
                return SyncAction(
                    action_type=ActionType.NEW_REPO,
                    skill_name=name,
                    source=repo.path,
                    destination=self.local_path / name,
                    reason="New skill (repository only)",
                    repo_mtime=repo.mtime,
                    repo_skill=repo,
                )

        # Case 3: Skill exists in both locations
        if local and repo:
            return self._classify_both_exist(name, local, repo, prev_state)

        # Case 4: Skill only in state (deleted on both sides)
        return SyncAction(
            action_type=ActionType.UNCHANGED,
            skill_name=name,
            reason="Deleted on both sides",
        )

    def _classify_both_exist(
        self, name: str, local: Skill, repo: Skill, prev_state: Optional[object]
    ) -> SyncAction:
        """Classify change when skill exists in both locations."""
        # Check if content is identical
        local_hash = local.get_content_hash()
        repo_hash = repo.get_content_hash()

        if local_hash == repo_hash:
            return SyncAction(
                action_type=ActionType.UNCHANGED,
                skill_name=name,
                reason="Content identical",
                local_mtime=local.mtime,
                repo_mtime=repo.mtime,
            )

        # Content differs - determine which is newer
        if prev_state:
            # We have previous state, check what changed
            prev = self.state.get_skill_state(name)
            if prev:
                local_changed = local.mtime > prev.mtime_local + 1  # 1s tolerance
                repo_changed = repo.mtime > prev.mtime_repo + 1

                if local_changed and repo_changed:
                    # Both changed - conflict!
                    return SyncAction(
                        action_type=ActionType.CONFLICT,
                        skill_name=name,
                        source=local.path,
                        destination=repo.path,
                        reason="Both local and repository changed since last sync",
                        local_mtime=local.mtime,
                        repo_mtime=repo.mtime,
                        local_skill=local,
                        repo_skill=repo,
                    )
                elif local_changed:
                    return SyncAction(
                        action_type=ActionType.COPY_TO_REPO,
                        skill_name=name,
                        source=local.path,
                        destination=repo.path,
                        reason="Local is newer",
                        local_mtime=local.mtime,
                        repo_mtime=repo.mtime,
                        local_skill=local,
                        repo_skill=repo,
                    )
                elif repo_changed:
                    return SyncAction(
                        action_type=ActionType.COPY_TO_LOCAL,
                        skill_name=name,
                        source=repo.path,
                        destination=local.path,
                        reason="Repository is newer",
                        local_mtime=local.mtime,
                        repo_mtime=repo.mtime,
                        local_skill=local,
                        repo_skill=repo,
                    )

        # No previous state or neither changed according to state
        # Fall back to mtime comparison
        if local.mtime > repo.mtime + 1:
            return SyncAction(
                action_type=ActionType.COPY_TO_REPO,
                skill_name=name,
                source=local.path,
                destination=repo.path,
                reason="Local is newer (by mtime)",
                local_mtime=local.mtime,
                repo_mtime=repo.mtime,
                local_skill=local,
                repo_skill=repo,
            )
        elif repo.mtime > local.mtime + 1:
            return SyncAction(
                action_type=ActionType.COPY_TO_LOCAL,
                skill_name=name,
                source=repo.path,
                destination=local.path,
                reason="Repository is newer (by mtime)",
                local_mtime=local.mtime,
                repo_mtime=repo.mtime,
                local_skill=local,
                repo_skill=repo,
            )
        else:
            # Same mtime but different content - treat as conflict
            return SyncAction(
                action_type=ActionType.CONFLICT,
                skill_name=name,
                source=local.path,
                destination=repo.path,
                reason="Content differs but timestamps are equal",
                local_mtime=local.mtime,
                repo_mtime=repo.mtime,
                local_skill=local,
                repo_skill=repo,
            )

    def _classify_command_change(self, name: str) -> SyncAction:
        """Classify change type for a command.

        Args:
            name: Command name

        Returns:
            SyncAction with appropriate type for command
        """
        local = self.local_commands.get(name)
        repo = self.repo_commands.get(name)
        prev_state = self.state.get_command_state(name)

        # Case 1: Command exists only locally
        if local and not repo:
            if prev_state:
                return SyncAction(
                    action_type=ActionType.DELETED_REPO,
                    skill_name=name,
                    item_type=ItemType.COMMAND,
                    source=local.path,
                    reason="Deleted in repository since last sync",
                    local_mtime=local.mtime,
                    local_command=local,
                )
            else:
                return SyncAction(
                    action_type=ActionType.NEW_LOCAL,
                    skill_name=name,
                    item_type=ItemType.COMMAND,
                    source=local.path,
                    destination=self.repo_commands_path / f"{name}.md",
                    reason="New command (local only)",
                    local_mtime=local.mtime,
                    local_command=local,
                )

        # Case 2: Command exists only in repo
        if repo and not local:
            if prev_state:
                return SyncAction(
                    action_type=ActionType.DELETED_LOCAL,
                    skill_name=name,
                    item_type=ItemType.COMMAND,
                    source=repo.path,
                    reason="Deleted locally since last sync",
                    repo_mtime=repo.mtime,
                    repo_command=repo,
                )
            else:
                return SyncAction(
                    action_type=ActionType.NEW_REPO,
                    skill_name=name,
                    item_type=ItemType.COMMAND,
                    source=repo.path,
                    destination=self.local_commands_path / f"{name}.md",
                    reason="New command (repository only)",
                    repo_mtime=repo.mtime,
                    repo_command=repo,
                )

        # Case 3: Command exists in both locations
        if local and repo:
            return self._classify_command_both_exist(name, local, repo, prev_state)

        # Case 4: Command only in state (deleted on both sides)
        return SyncAction(
            action_type=ActionType.UNCHANGED,
            skill_name=name,
            item_type=ItemType.COMMAND,
            reason="Deleted on both sides",
        )

    def _classify_command_both_exist(
        self, name: str, local: Command, repo: Command, prev_state: Optional[object]
    ) -> SyncAction:
        """Classify change when command exists in both locations."""
        # Check if content is identical
        local_hash = local.get_content_hash()
        repo_hash = repo.get_content_hash()

        if local_hash == repo_hash:
            return SyncAction(
                action_type=ActionType.UNCHANGED,
                skill_name=name,
                item_type=ItemType.COMMAND,
                reason="Content identical",
                local_mtime=local.mtime,
                repo_mtime=repo.mtime,
            )

        # Content differs - determine which is newer
        if prev_state:
            prev = self.state.get_command_state(name)
            if prev:
                local_changed = local.mtime > prev.mtime_local + 1
                repo_changed = repo.mtime > prev.mtime_repo + 1

                if local_changed and repo_changed:
                    return SyncAction(
                        action_type=ActionType.CONFLICT,
                        skill_name=name,
                        item_type=ItemType.COMMAND,
                        source=local.path,
                        destination=repo.path,
                        reason="Both local and repository changed since last sync",
                        local_mtime=local.mtime,
                        repo_mtime=repo.mtime,
                        local_command=local,
                        repo_command=repo,
                    )
                elif local_changed:
                    return SyncAction(
                        action_type=ActionType.COPY_TO_REPO,
                        skill_name=name,
                        item_type=ItemType.COMMAND,
                        source=local.path,
                        destination=repo.path,
                        reason="Local is newer",
                        local_mtime=local.mtime,
                        repo_mtime=repo.mtime,
                        local_command=local,
                        repo_command=repo,
                    )
                elif repo_changed:
                    return SyncAction(
                        action_type=ActionType.COPY_TO_LOCAL,
                        skill_name=name,
                        item_type=ItemType.COMMAND,
                        source=repo.path,
                        destination=local.path,
                        reason="Repository is newer",
                        local_mtime=local.mtime,
                        repo_mtime=repo.mtime,
                        local_command=local,
                        repo_command=repo,
                    )

        # Fall back to mtime comparison
        if local.mtime > repo.mtime + 1:
            return SyncAction(
                action_type=ActionType.COPY_TO_REPO,
                skill_name=name,
                item_type=ItemType.COMMAND,
                source=local.path,
                destination=repo.path,
                reason="Local is newer (by mtime)",
                local_mtime=local.mtime,
                repo_mtime=repo.mtime,
                local_command=local,
                repo_command=repo,
            )
        elif repo.mtime > local.mtime + 1:
            return SyncAction(
                action_type=ActionType.COPY_TO_LOCAL,
                skill_name=name,
                item_type=ItemType.COMMAND,
                source=repo.path,
                destination=local.path,
                reason="Repository is newer (by mtime)",
                local_mtime=local.mtime,
                repo_mtime=repo.mtime,
                local_command=local,
                repo_command=repo,
            )
        else:
            return SyncAction(
                action_type=ActionType.CONFLICT,
                skill_name=name,
                item_type=ItemType.COMMAND,
                source=local.path,
                destination=repo.path,
                reason="Content differs but timestamps are equal",
                local_mtime=local.mtime,
                repo_mtime=repo.mtime,
                local_command=local,
                repo_command=repo,
            )

    def execute_action(self, action: SyncAction, resolution: Optional[str] = None) -> bool:
        """Execute a single sync action.

        Args:
            action: The action to execute
            resolution: For conflicts/deletions - 'local', 'repo', 'skip', or 'delete'

        Returns:
            True if action was executed successfully
        """
        if self.dry_run:
            return True

        try:
            # Use appropriate copy/delete method based on item type
            if action.item_type == ItemType.COMMAND:
                return self._execute_command_action(action, resolution)
            else:
                return self._execute_skill_action(action, resolution)

        except Exception as e:
            raise RuntimeError(f"Failed to execute action for {action.skill_name}: {e}") from e

    def _execute_skill_action(self, action: SyncAction, resolution: Optional[str] = None) -> bool:
        """Execute a skill sync action."""
        if action.action_type == ActionType.COPY_TO_REPO:
            self._copy_skill(action.source, action.destination)
        elif action.action_type == ActionType.COPY_TO_LOCAL:
            self._copy_skill(action.source, action.destination)
        elif action.action_type == ActionType.NEW_LOCAL:
            self._copy_skill(action.source, action.destination)
        elif action.action_type == ActionType.NEW_REPO:
            self._copy_skill(action.source, action.destination)
        elif action.action_type == ActionType.CONFLICT:
            if resolution == "local":
                self._copy_skill(action.local_skill.path, self.repo_path / action.skill_name)
            elif resolution == "repo":
                self._copy_skill(action.repo_skill.path, self.local_path / action.skill_name)
            elif resolution == "skip":
                return True
            else:
                return False
        elif action.action_type == ActionType.DELETED_LOCAL:
            if resolution == "delete":
                self._delete_skill(action.source)
            elif resolution == "restore":
                self._copy_skill(action.source, self.local_path / action.skill_name)
            elif resolution == "skip":
                return True
            else:
                return False
        elif action.action_type == ActionType.DELETED_REPO:
            if resolution == "delete":
                self._delete_skill(action.source)
            elif resolution == "restore":
                self._copy_skill(action.source, self.repo_path / action.skill_name)
            elif resolution == "skip":
                return True
            else:
                return False

        self._update_state_after_action(action, resolution)
        return True

    def _execute_command_action(self, action: SyncAction, resolution: Optional[str] = None) -> bool:
        """Execute a command sync action."""
        name = action.skill_name

        if action.action_type == ActionType.COPY_TO_REPO:
            self._copy_command(action.source, action.destination)
        elif action.action_type == ActionType.COPY_TO_LOCAL:
            self._copy_command(action.source, action.destination)
        elif action.action_type == ActionType.NEW_LOCAL:
            self._copy_command(action.source, action.destination)
        elif action.action_type == ActionType.NEW_REPO:
            self._copy_command(action.source, action.destination)
        elif action.action_type == ActionType.CONFLICT:
            if resolution == "local":
                self._copy_command(
                    action.local_command.path,
                    self.repo_commands_path / f"{name}.md"
                )
            elif resolution == "repo":
                self._copy_command(
                    action.repo_command.path,
                    self.local_commands_path / f"{name}.md"
                )
            elif resolution == "skip":
                return True
            else:
                return False
        elif action.action_type == ActionType.DELETED_LOCAL:
            if resolution == "delete":
                self._delete_command(action.source)
            elif resolution == "restore":
                self._copy_command(action.source, self.local_commands_path / f"{name}.md")
            elif resolution == "skip":
                return True
            else:
                return False
        elif action.action_type == ActionType.DELETED_REPO:
            if resolution == "delete":
                self._delete_command(action.source)
            elif resolution == "restore":
                self._copy_command(action.source, self.repo_commands_path / f"{name}.md")
            elif resolution == "skip":
                return True
            else:
                return False

        self._update_command_state_after_action(action, resolution)
        return True

    def _copy_skill(self, source: Optional[Path], destination: Optional[Path]) -> None:
        """Copy a skill directory atomically.

        Args:
            source: Source directory
            destination: Destination directory
        """
        if not source or not destination:
            raise ValueError("Source and destination must be specified")

        # Ensure parent directory exists
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing destination
        if destination.exists():
            shutil.rmtree(destination)

        # Copy directory
        shutil.copytree(source, destination)

    def _delete_skill(self, path: Optional[Path]) -> None:
        """Delete a skill directory.

        Args:
            path: Path to skill directory
        """
        if path and path.exists():
            shutil.rmtree(path)

    def _copy_command(self, source: Optional[Path], destination: Optional[Path]) -> None:
        """Copy a command file.

        Args:
            source: Source file path
            destination: Destination file path
        """
        if not source or not destination:
            raise ValueError("Source and destination must be specified")

        # Ensure parent directory exists
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Copy file
        shutil.copy2(source, destination)

    def _delete_command(self, path: Optional[Path]) -> None:
        """Delete a command file.

        Args:
            path: Path to command file
        """
        if path and path.exists():
            path.unlink()

    def _update_state_after_action(self, action: SyncAction, resolution: Optional[str] = None) -> None:
        """Update sync state after executing a skill action."""
        name = action.skill_name

        # Handle deletions
        if action.action_type in (ActionType.DELETED_LOCAL, ActionType.DELETED_REPO):
            if resolution == "delete":
                self.state.remove_skill(name)
            return

        # Get the current state of the skill after sync
        local = scan_skills_directory(self.local_path).get(name)
        repo = scan_skills_directory(self.repo_path).get(name)

        if local and repo:
            content_hash = local.get_content_hash()
            self.state.update_skill(
                name=name,
                mtime_local=local.mtime,
                mtime_repo=repo.mtime,
                content_hash=content_hash,
            )

    def _update_command_state_after_action(self, action: SyncAction, resolution: Optional[str] = None) -> None:
        """Update sync state after executing a command action."""
        name = action.skill_name

        # Handle deletions
        if action.action_type in (ActionType.DELETED_LOCAL, ActionType.DELETED_REPO):
            if resolution == "delete":
                self.state.remove_command(name)
            return

        # Get the current state of the command after sync
        local = scan_commands_directory(self.local_commands_path).get(name)
        repo = scan_commands_directory(self.repo_commands_path).get(name)

        if local and repo:
            content_hash = local.get_content_hash()
            self.state.update_command(
                name=name,
                mtime_local=local.mtime,
                mtime_repo=repo.mtime,
                content_hash=content_hash,
            )

    def save_state(self) -> None:
        """Save current sync state to file."""
        if not self.dry_run:
            self.state.save()

    def generate_sync_log_entry(self, actions: list[SyncAction]) -> str:
        """Generate a SYNC_LOG.md entry for the sync operation.

        Args:
            actions: List of executed actions

        Returns:
            Markdown formatted log entry
        """
        now = datetime.now(timezone.utc).strftime(DATETIME_FORMAT)

        # Separate skill and command actions
        skill_actions = [a for a in actions if a.item_type == ItemType.SKILL and a.action_type != ActionType.UNCHANGED]
        command_actions = [a for a in actions if a.item_type == ItemType.COMMAND and a.action_type != ActionType.UNCHANGED]

        lines = [f"## {now}", ""]

        # Skills section
        if skill_actions:
            lines.extend([
                "### Synced Skills",
                "",
                "| Skill | Direction | Action | Files |",
                "|-------|-----------|--------|-------|",
            ])

            for action in skill_actions:
                direction = action.get_direction_arrow()
                action_name = action.action_type.value.replace("_", " ").title()

                files = ""
                if action.local_skill:
                    files = ", ".join(action.local_skill.get_file_list())
                elif action.repo_skill:
                    files = ", ".join(action.repo_skill.get_file_list())

                lines.append(f"| {action.skill_name} | {direction} | {action_name} | {files} |")

            lines.append("")

        # Commands section
        if command_actions:
            lines.extend([
                "### Synced Commands",
                "",
                "| Command | Direction | Action |",
                "|---------|-----------|--------|",
            ])

            for action in command_actions:
                direction = action.get_direction_arrow()
                action_name = action.action_type.value.replace("_", " ").title()
                lines.append(f"| {action.skill_name} | {direction} | {action_name} |")

            lines.append("")

        # Summary
        to_repo = sum(1 for a in actions if a.action_type in (ActionType.COPY_TO_REPO, ActionType.NEW_LOCAL))
        to_local = sum(1 for a in actions if a.action_type in (ActionType.COPY_TO_LOCAL, ActionType.NEW_REPO))
        conflicts = sum(1 for a in actions if a.action_type == ActionType.CONFLICT)

        total_skills = len(skill_actions)
        total_commands = len(command_actions)

        lines.extend([
            "### Summary",
            f"- **Total**: {len(actions)} items ({total_skills} skills, {total_commands} commands)",
            f"- **Local → Repo**: {to_repo}",
            f"- **Repo → Local**: {to_local}",
            f"- **Conflicts resolved**: {conflicts}",
            "",
            "---",
            "",
        ])

        return "\n".join(lines)
