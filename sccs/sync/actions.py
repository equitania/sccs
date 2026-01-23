# SCCS Sync Actions
# Action types and execution for synchronization

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from sccs.sync.item import SyncItem
from sccs.utils.paths import safe_copy, safe_delete, ensure_dir


class ActionType(str, Enum):
    """Types of sync actions."""

    # No action needed
    UNCHANGED = "unchanged"

    # Copy actions
    COPY_TO_REPO = "copy_to_repo"
    COPY_TO_LOCAL = "copy_to_local"

    # Conflict
    CONFLICT = "conflict"

    # New items
    NEW_LOCAL = "new_local"  # New item in local, copy to repo
    NEW_REPO = "new_repo"  # New item in repo, copy to local

    # Deleted items
    DELETED_LOCAL = "deleted_local"  # Deleted locally, delete from repo
    DELETED_REPO = "deleted_repo"  # Deleted from repo, delete locally

    # Skip (e.g., due to sync mode restrictions)
    SKIP = "skip"

    # Error during detection
    ERROR = "error"


@dataclass
class SyncAction:
    """
    A synchronization action to perform.

    Represents a specific action to take for a sync item,
    including source/destination and reason.
    """

    item: SyncItem
    action_type: ActionType
    source_path: Optional[Path] = None
    dest_path: Optional[Path] = None
    reason: str = ""
    error: Optional[str] = None

    @property
    def is_copy(self) -> bool:
        """Check if this is a copy action."""
        return self.action_type in (
            ActionType.COPY_TO_REPO,
            ActionType.COPY_TO_LOCAL,
            ActionType.NEW_LOCAL,
            ActionType.NEW_REPO,
        )

    @property
    def is_delete(self) -> bool:
        """Check if this is a delete action."""
        return self.action_type in (
            ActionType.DELETED_LOCAL,
            ActionType.DELETED_REPO,
        )

    @property
    def is_conflict(self) -> bool:
        """Check if this is a conflict."""
        return self.action_type == ActionType.CONFLICT

    @property
    def needs_action(self) -> bool:
        """Check if this action requires execution."""
        return self.action_type not in (
            ActionType.UNCHANGED,
            ActionType.SKIP,
            ActionType.ERROR,
        )

    @property
    def direction(self) -> str:
        """Get human-readable direction of action."""
        if self.action_type in (ActionType.COPY_TO_REPO, ActionType.NEW_LOCAL, ActionType.DELETED_REPO):
            return "local → repo"
        elif self.action_type in (ActionType.COPY_TO_LOCAL, ActionType.NEW_REPO, ActionType.DELETED_LOCAL):
            return "repo → local"
        else:
            return "—"


@dataclass
class ActionResult:
    """Result of executing an action."""

    action: SyncAction
    success: bool
    error: Optional[str] = None
    backup_path: Optional[Path] = None

    @property
    def item_name(self) -> str:
        """Get the item name."""
        return self.action.item.name


def execute_action(action: SyncAction, *, dry_run: bool = False) -> ActionResult:
    """
    Execute a sync action.

    Args:
        action: The action to execute.
        dry_run: If True, don't actually perform the action.

    Returns:
        ActionResult with success status.
    """
    if not action.needs_action:
        return ActionResult(action=action, success=True)

    if action.action_type == ActionType.CONFLICT:
        return ActionResult(
            action=action,
            success=False,
            error="Conflict must be resolved before execution",
        )

    if dry_run:
        return ActionResult(action=action, success=True)

    try:
        if action.is_copy:
            return _execute_copy(action)
        elif action.is_delete:
            return _execute_delete(action)
        else:
            return ActionResult(
                action=action,
                success=False,
                error=f"Unknown action type: {action.action_type}",
            )
    except Exception as e:
        return ActionResult(
            action=action,
            success=False,
            error=str(e),
        )


def _execute_copy(action: SyncAction, *, backup: bool = True) -> ActionResult:
    """Execute a copy action with optional backup."""
    if action.source_path is None or action.dest_path is None:
        return ActionResult(
            action=action,
            success=False,
            error="Source or destination path not set",
        )

    if not action.source_path.exists():
        return ActionResult(
            action=action,
            success=False,
            error=f"Source does not exist: {action.source_path}",
        )

    # Ensure destination directory exists
    ensure_dir(action.dest_path.parent)

    # Perform copy with backup
    backup_path = safe_copy(
        action.source_path,
        action.dest_path,
        backup=backup,
        backup_category=action.item.category,
    )

    if backup_path:
        return ActionResult(
            action=action,
            success=True,
            backup_path=backup_path,
        )

    return ActionResult(action=action, success=True)


def _execute_delete(action: SyncAction) -> ActionResult:
    """Execute a delete action."""
    # Determine which path to delete based on action type
    if action.action_type == ActionType.DELETED_LOCAL:
        # Local was deleted, delete from repo
        path_to_delete = action.item.repo_path
    elif action.action_type == ActionType.DELETED_REPO:
        # Repo was deleted, delete locally
        path_to_delete = action.item.local_path
    else:
        return ActionResult(
            action=action,
            success=False,
            error=f"Invalid delete action type: {action.action_type}",
        )

    if path_to_delete is None:
        return ActionResult(
            action=action,
            success=False,
            error="Path to delete not set",
        )

    if not path_to_delete.exists():
        # Already deleted, consider success
        return ActionResult(action=action, success=True)

    safe_delete(path_to_delete)
    return ActionResult(action=action, success=True)


def determine_action(
    item: SyncItem,
    last_hash: Optional[str],
    sync_mode: str,
) -> SyncAction:
    """
    Determine what action to take for an item.

    Args:
        item: The sync item.
        last_hash: Last known content hash from state.
        sync_mode: Sync mode (bidirectional, local_to_repo, repo_to_local).

    Returns:
        SyncAction describing what to do.
    """
    exists_local = item.exists_local
    exists_repo = item.exists_repo

    # Get current hashes
    local_hash = item.get_hash("local") if exists_local else None
    repo_hash = item.get_hash("repo") if exists_repo else None

    # Case 1: Neither exists
    if not exists_local and not exists_repo:
        return SyncAction(
            item=item,
            action_type=ActionType.SKIP,
            reason="Item doesn't exist in either location",
        )

    # Case 2: Only in local (new or deleted from repo)
    if exists_local and not exists_repo:
        if last_hash is not None:
            # Was in repo before, now deleted there
            if sync_mode == "local_to_repo":
                return SyncAction(
                    item=item,
                    action_type=ActionType.NEW_LOCAL,
                    source_path=item.local_path,
                    dest_path=item.repo_path,
                    reason="Re-create in repo (local_to_repo mode)",
                )
            else:
                return SyncAction(
                    item=item,
                    action_type=ActionType.DELETED_REPO,
                    reason="Deleted from repo",
                )
        else:
            # New in local
            if sync_mode == "repo_to_local":
                return SyncAction(
                    item=item,
                    action_type=ActionType.SKIP,
                    reason="New local item skipped (repo_to_local mode)",
                )
            return SyncAction(
                item=item,
                action_type=ActionType.NEW_LOCAL,
                source_path=item.local_path,
                dest_path=item.repo_path,
                reason="New item in local",
            )

    # Case 3: Only in repo (new or deleted locally)
    if not exists_local and exists_repo:
        if last_hash is not None:
            # Was in local before, now deleted there
            if sync_mode == "repo_to_local":
                return SyncAction(
                    item=item,
                    action_type=ActionType.NEW_REPO,
                    source_path=item.repo_path,
                    dest_path=item.local_path,
                    reason="Re-create locally (repo_to_local mode)",
                )
            else:
                return SyncAction(
                    item=item,
                    action_type=ActionType.DELETED_LOCAL,
                    reason="Deleted locally",
                )
        else:
            # New in repo
            if sync_mode == "local_to_repo":
                return SyncAction(
                    item=item,
                    action_type=ActionType.SKIP,
                    reason="New repo item skipped (local_to_repo mode)",
                )
            return SyncAction(
                item=item,
                action_type=ActionType.NEW_REPO,
                source_path=item.repo_path,
                dest_path=item.local_path,
                reason="New item in repo",
            )

    # Case 4: Both exist
    # Check if they're the same
    if local_hash == repo_hash:
        return SyncAction(
            item=item,
            action_type=ActionType.UNCHANGED,
            reason="Content identical",
        )

    # They're different - determine which changed
    local_changed = last_hash is None or local_hash != last_hash
    repo_changed = last_hash is None or repo_hash != last_hash

    if local_changed and repo_changed:
        # Both changed - conflict
        if sync_mode == "local_to_repo":
            return SyncAction(
                item=item,
                action_type=ActionType.COPY_TO_REPO,
                source_path=item.local_path,
                dest_path=item.repo_path,
                reason="Both changed, preferring local (local_to_repo mode)",
            )
        elif sync_mode == "repo_to_local":
            return SyncAction(
                item=item,
                action_type=ActionType.COPY_TO_LOCAL,
                source_path=item.repo_path,
                dest_path=item.local_path,
                reason="Both changed, preferring repo (repo_to_local mode)",
            )
        else:
            return SyncAction(
                item=item,
                action_type=ActionType.CONFLICT,
                reason="Both local and repo changed",
            )

    if local_changed:
        if sync_mode == "repo_to_local":
            return SyncAction(
                item=item,
                action_type=ActionType.SKIP,
                reason="Local changed but repo_to_local mode",
            )
        return SyncAction(
            item=item,
            action_type=ActionType.COPY_TO_REPO,
            source_path=item.local_path,
            dest_path=item.repo_path,
            reason="Local changed",
        )

    if repo_changed:
        if sync_mode == "local_to_repo":
            return SyncAction(
                item=item,
                action_type=ActionType.SKIP,
                reason="Repo changed but local_to_repo mode",
            )
        return SyncAction(
            item=item,
            action_type=ActionType.COPY_TO_LOCAL,
            source_path=item.repo_path,
            dest_path=item.local_path,
            reason="Repo changed",
        )

    # Should not reach here
    return SyncAction(
        item=item,
        action_type=ActionType.UNCHANGED,
        reason="No changes detected",
    )
