# SCCS Category Handler
# Handles synchronization for a single category

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sccs.config.schema import SyncCategory
from sccs.sync.actions import (
    ActionResult,
    ActionType,
    SyncAction,
    determine_action,
    execute_action,
)
from sccs.sync.item import SyncItem, scan_items_for_category
from sccs.sync.state import StateManager

if TYPE_CHECKING:
    from sccs.sync.settings import SettingsEnsureResult


@dataclass
class CategoryStatus:
    """Status summary for a category."""

    name: str
    enabled: bool
    total_items: int = 0
    unchanged: int = 0
    to_sync: int = 0
    conflicts: int = 0
    errors: int = 0
    items: list[SyncItem] = field(default_factory=list)
    actions: list[SyncAction] = field(default_factory=list)
    platforms: list[str] | None = None

    @property
    def has_changes(self) -> bool:
        """Check if there are any changes to sync."""
        return self.to_sync > 0 or self.conflicts > 0

    @property
    def has_issues(self) -> bool:
        """Check if there are conflicts or errors."""
        return self.conflicts > 0 or self.errors > 0


@dataclass
class CategorySyncResult:
    """Result of syncing a category."""

    name: str
    success: bool
    total: int = 0
    synced: int = 0
    skipped: int = 0
    conflicts: int = 0
    errors: int = 0
    aborted: bool = False
    results: list[ActionResult] = field(default_factory=list)
    error_message: str | None = None
    settings_result: SettingsEnsureResult | None = None


class CategoryHandler:
    """
    Handles synchronization for a single category.

    Manages item discovery, change detection, and action execution.
    """

    def __init__(
        self,
        name: str,
        category: SyncCategory,
        repo_base: Path,
        state_manager: StateManager,
        global_exclude: list[str] | None = None,
    ):
        """
        Initialize category handler.

        Args:
            name: Category name.
            category: Category configuration.
            repo_base: Base path for repository.
            state_manager: State manager for persistence.
            global_exclude: Global exclude patterns.
        """
        self.name = name
        self.category = category
        self.repo_base = repo_base
        self.state_manager = state_manager
        self.global_exclude = global_exclude or []
        self._items: list[SyncItem] | None = None
        self._actions: list[SyncAction] | None = None

    @property
    def local_path(self) -> Path:
        """Get local path for category."""
        return Path(self.category.local_path).expanduser()

    @property
    def repo_path(self) -> Path:
        """Get repository path for category."""
        return self.repo_base / self.category.repo_path

    def scan_items(self) -> list[SyncItem]:
        """Scan and return all items for this category."""
        if self._items is None:
            self._items = scan_items_for_category(
                category_name=self.name,
                category=self.category,
                local_base=self.local_path.parent,
                repo_base=self.repo_base,
                global_exclude=self.global_exclude,
            )
        return self._items

    def detect_changes(self) -> list[SyncAction]:
        """Detect changes and return actions needed."""
        if self._actions is not None:
            return self._actions

        items = self.scan_items()
        actions: list[SyncAction] = []

        for item in items:
            # Get last known hash
            last_hash = self.state_manager.get_item_hash(self.name, item.name)

            # Determine action
            action = determine_action(
                item=item,
                last_hash=last_hash,
                sync_mode=self.category.sync_mode.value,
            )
            actions.append(action)

        self._actions = actions
        return actions

    def get_status(self) -> CategoryStatus:
        """Get current status for this category."""
        items = self.scan_items()
        actions = self.detect_changes()

        status = CategoryStatus(
            name=self.name,
            enabled=self.category.enabled,
            total_items=len(items),
            items=items,
            actions=actions,
            platforms=self.category.platforms,
        )

        for action in actions:
            if action.action_type == ActionType.UNCHANGED:
                status.unchanged += 1
            elif action.action_type == ActionType.CONFLICT:
                status.conflicts += 1
            elif action.action_type == ActionType.ERROR:
                status.errors += 1
            elif action.action_type == ActionType.SKIP:
                pass  # Don't count skips
            else:
                status.to_sync += 1

        return status

    def sync(
        self,
        *,
        dry_run: bool = False,
        force_direction: str | None = None,
        conflict_resolver: Callable[[SyncAction, str], str] | None = None,
    ) -> CategorySyncResult:
        """
        Synchronize this category.

        Args:
            dry_run: If True, don't perform actual operations.
            force_direction: Force sync direction ("local" or "repo").
            conflict_resolver: Optional callback for interactive conflict resolution.
                               Receives (action, category_name) and returns "local", "repo", "skip", or "abort".

        Returns:
            CategorySyncResult with details of what was done.
        """
        actions = self.detect_changes()

        result = CategorySyncResult(
            name=self.name,
            success=True,
            total=len(actions),
        )

        for action in actions:
            # Handle conflicts
            if action.action_type == ActionType.CONFLICT:
                if force_direction:
                    action = self._resolve_conflict(action, force_direction)
                elif conflict_resolver and not dry_run:
                    resolution = conflict_resolver(action, self.name)
                    if resolution == "abort":
                        result.aborted = True
                        result.success = False
                        break
                    elif resolution == "skip":
                        result.skipped += 1
                        continue
                    elif resolution == "merged":
                        # Files already written by merge handler, just update state
                        self._update_state_for_action(action)
                        result.synced += 1
                        continue
                    elif resolution in ("local", "repo"):
                        action = self._resolve_conflict(action, resolution)
                    # If "diff", the resolver should handle showing diff and re-prompt

            # Skip non-actionable items
            if not action.needs_action:
                if action.action_type == ActionType.UNCHANGED:
                    pass  # Normal
                elif action.action_type == ActionType.SKIP:
                    result.skipped += 1
                elif action.action_type == ActionType.CONFLICT:
                    result.conflicts += 1
                continue

            # Execute action
            action_result = execute_action(action, dry_run=dry_run)
            result.results.append(action_result)

            if action_result.success:
                result.synced += 1
                # Update state
                if not dry_run:
                    self._update_state_for_action(action)
            else:
                result.errors += 1
                result.success = False

        # Run settings ensure hook if configured
        if self.category.settings_ensure is not None:
            from sccs.sync.settings import ensure_settings

            result.settings_result = ensure_settings(
                self.category.settings_ensure,
                dry_run=dry_run,
                category_name=self.name,
            )

        return result

    def _resolve_conflict(self, action: SyncAction, force_direction: str) -> SyncAction:
        """Resolve a conflict by forcing a direction."""
        if force_direction == "local":
            return SyncAction(
                item=action.item,
                action_type=ActionType.COPY_TO_REPO,
                source_path=action.item.local_path,
                dest_path=action.item.repo_path,
                reason="Conflict resolved: force local",
            )
        else:
            return SyncAction(
                item=action.item,
                action_type=ActionType.COPY_TO_LOCAL,
                source_path=action.item.repo_path,
                dest_path=action.item.local_path,
                reason="Conflict resolved: force repo",
            )

    def _update_state_for_action(self, action: SyncAction) -> None:
        """Update state after executing an action."""
        item = action.item

        if action.is_delete:
            self.state_manager.remove_item(self.name, item.name)
        else:
            # Get current hash (after copy)
            content_hash = item.get_hash("local")
            local_mtime = item.get_mtime("local")
            repo_mtime = item.get_mtime("repo")

            self.state_manager.update_item(
                category=self.name,
                name=item.name,
                content_hash=content_hash,
                local_mtime=local_mtime,
                repo_mtime=repo_mtime,
                action=action.action_type.value,
            )

    def reset_cache(self) -> None:
        """Reset cached items and actions."""
        self._items = None
        self._actions = None
