# SCCS Sync Engine
# Main synchronization engine coordinating all categories

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sccs.config.schema import SccsConfig
from sccs.sync.actions import SyncAction
from sccs.sync.category import CategoryHandler, CategoryStatus, CategorySyncResult
from sccs.sync.state import StateManager
from sccs.utils.platform import is_platform_match


@dataclass
class SyncResult:
    """Result of a complete sync operation."""

    success: bool
    total_categories: int = 0
    synced_categories: int = 0
    total_items: int = 0
    synced_items: int = 0
    conflicts: int = 0
    errors: int = 0
    settings_ensured: int = 0
    aborted: bool = False
    category_results: dict[str, CategorySyncResult] = field(default_factory=dict)

    @property
    def has_issues(self) -> bool:
        """Check if there are any conflicts or errors."""
        return self.conflicts > 0 or self.errors > 0


class SyncEngine:
    """
    Main synchronization engine.

    Coordinates sync across all enabled categories.
    """

    def __init__(self, config: SccsConfig, state_manager: StateManager | None = None):
        """
        Initialize sync engine.

        Args:
            config: SCCS configuration.
            state_manager: Optional state manager (creates new one if not provided).
        """
        self.config = config
        self.repo_base = Path(config.repository.path).expanduser()
        self.state_manager = state_manager or StateManager()
        self._handlers: dict[str, CategoryHandler] = {}

    def get_handler(self, category_name: str) -> CategoryHandler | None:
        """
        Get handler for a category.

        Args:
            category_name: Name of the category.

        Returns:
            CategoryHandler or None if category doesn't exist.
        """
        if category_name in self._handlers:
            return self._handlers[category_name]

        category = self.config.get_category(category_name)
        if category is None:
            return None

        handler = CategoryHandler(
            name=category_name,
            category=category,
            repo_base=self.repo_base,
            state_manager=self.state_manager,
            global_exclude=self.config.global_exclude,
        )
        self._handlers[category_name] = handler
        return handler

    def get_enabled_categories(self) -> list[str]:
        """Get list of enabled category names, filtered by current platform."""
        return [name for name, cat in self.config.get_enabled_categories().items() if is_platform_match(cat.platforms)]

    def get_all_categories(self) -> list[str]:
        """Get list of all category names."""
        return list(self.config.sync_categories.keys())

    def get_status(self, category_name: str | None = None) -> dict[str, CategoryStatus]:
        """
        Get status for categories.

        Args:
            category_name: Optional specific category. If None, returns all enabled.

        Returns:
            Dict of category name to status.
        """
        statuses: dict[str, CategoryStatus] = {}

        if category_name:
            handler = self.get_handler(category_name)
            if handler:
                statuses[category_name] = handler.get_status()
        else:
            for name in self.get_enabled_categories():
                handler = self.get_handler(name)
                if handler:
                    statuses[name] = handler.get_status()

        return statuses

    def sync(
        self,
        *,
        category_name: str | None = None,
        dry_run: bool = False,
        force_direction: str | None = None,
        conflict_resolver: Callable[[SyncAction, str], str] | None = None,
    ) -> SyncResult:
        """
        Synchronize categories.

        Args:
            category_name: Optional specific category. If None, syncs all enabled.
            dry_run: If True, don't perform actual operations.
            force_direction: Force sync direction ("local" or "repo").
            conflict_resolver: Optional callback for interactive conflict resolution.

        Returns:
            SyncResult with details of what was done.
        """
        result = SyncResult(success=True)

        # Determine which categories to sync
        if category_name:
            categories = [category_name]
        else:
            categories = self.get_enabled_categories()

        result.total_categories = len(categories)

        for name in categories:
            handler = self.get_handler(name)
            if handler is None:
                continue

            # Sync category
            cat_result = handler.sync(
                dry_run=dry_run,
                force_direction=force_direction,
                conflict_resolver=conflict_resolver,
            )

            result.category_results[name] = cat_result
            result.total_items += cat_result.total
            result.synced_items += cat_result.synced
            result.conflicts += cat_result.conflicts
            result.errors += cat_result.errors

            if cat_result.settings_result and cat_result.settings_result.file_modified:
                result.settings_ensured += 1

            if cat_result.aborted:
                result.aborted = True
                result.success = False
                break

            if cat_result.success:
                result.synced_categories += 1
            else:
                result.success = False

        return result

    def sync_all(
        self,
        *,
        dry_run: bool = False,
        force_direction: str | None = None,
    ) -> SyncResult:
        """
        Synchronize all enabled categories.

        Args:
            dry_run: If True, don't perform actual operations.
            force_direction: Force sync direction ("local" or "repo").

        Returns:
            SyncResult with details of what was done.
        """
        return self.sync(dry_run=dry_run, force_direction=force_direction)

    def sync_category(
        self,
        category_name: str,
        *,
        dry_run: bool = False,
        force_direction: str | None = None,
    ) -> CategorySyncResult:
        """
        Synchronize a specific category.

        Args:
            category_name: Name of the category.
            dry_run: If True, don't perform actual operations.
            force_direction: Force sync direction ("local" or "repo").

        Returns:
            CategorySyncResult with details of what was done.

        Raises:
            KeyError: If category doesn't exist.
        """
        handler = self.get_handler(category_name)
        if handler is None:
            raise KeyError(f"Category '{category_name}' not found")

        return handler.sync(dry_run=dry_run, force_direction=force_direction)

    def get_category_status(self, category_name: str) -> CategoryStatus:
        """
        Get status for a specific category.

        Args:
            category_name: Name of the category.

        Returns:
            CategoryStatus.

        Raises:
            KeyError: If category doesn't exist.
        """
        handler = self.get_handler(category_name)
        if handler is None:
            raise KeyError(f"Category '{category_name}' not found")

        return handler.get_status()

    def reset_state(self, category_name: str | None = None) -> None:
        """
        Reset sync state.

        Args:
            category_name: Optional specific category. If None, resets all.
        """
        if category_name:
            self.state_manager.clear_category(category_name)
            if category_name in self._handlers:
                self._handlers[category_name].reset_cache()
        else:
            self.state_manager.reset()
            self._handlers.clear()

    def ensure_repo_structure(self) -> list[Path]:
        """
        Ensure repository directory structure exists.

        Creates directories for all enabled categories.

        Returns:
            List of created directories.
        """
        created: list[Path] = []

        for name in self.get_enabled_categories():
            category = self.config.get_category(name)
            if category is None:
                continue

            repo_path = self.repo_base / category.repo_path

            # For directory categories, just ensure parent exists
            if not repo_path.exists():
                repo_path.mkdir(parents=True, exist_ok=True)
                created.append(repo_path)

        return created
