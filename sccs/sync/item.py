# SCCS Sync Item
# Generic item representation for files and directories

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sccs.config.schema import ItemType, SyncCategory
from sccs.utils.hashing import directory_hash, file_hash, get_mtime
from sccs.utils.paths import expand_path, find_directories, find_files, matches_any_pattern


@dataclass
class SyncItem:
    """
    Generic item for synchronization.

    Can represent files, directories, or skills (directories with marker).
    """

    name: str
    category: str
    item_type: ItemType
    local_path: Optional[Path] = None
    repo_path: Optional[Path] = None
    content_hash: Optional[str] = None
    mtime: Optional[float] = None

    @property
    def exists_local(self) -> bool:
        """Check if item exists locally."""
        return self.local_path is not None and self.local_path.exists()

    @property
    def exists_repo(self) -> bool:
        """Check if item exists in repository."""
        return self.repo_path is not None and self.repo_path.exists()

    @property
    def exists_both(self) -> bool:
        """Check if item exists in both locations."""
        return self.exists_local and self.exists_repo

    @property
    def exists_either(self) -> bool:
        """Check if item exists in either location."""
        return self.exists_local or self.exists_repo

    def get_hash(self, source: str = "local") -> Optional[str]:
        """
        Get content hash for item from specified source.

        Args:
            source: "local" or "repo"

        Returns:
            Content hash or None.
        """
        path = self.local_path if source == "local" else self.repo_path
        if path is None or not path.exists():
            return None

        if self.item_type == ItemType.FILE:
            return file_hash(path)
        else:
            return directory_hash(path)

    def get_mtime(self, source: str = "local") -> Optional[float]:
        """
        Get modification time from specified source.

        Args:
            source: "local" or "repo"

        Returns:
            Modification time or None.
        """
        path = self.local_path if source == "local" else self.repo_path
        if path is None or not path.exists():
            return None
        return get_mtime(path)


def scan_items_for_category(
    category_name: str,
    category: SyncCategory,
    local_base: Path,
    repo_base: Path,
    global_exclude: Optional[list[str]] = None,
) -> list[SyncItem]:
    """
    Scan and discover items for a sync category.

    Args:
        category_name: Name of the category.
        category: Category configuration.
        local_base: Base path for local files (usually ~/.claude).
        repo_base: Base path for repository.
        global_exclude: Global exclude patterns.

    Returns:
        List of SyncItems found.
    """
    items: dict[str, SyncItem] = {}

    local_path = expand_path(category.local_path)
    repo_path = repo_base / category.repo_path

    # Combine excludes
    excludes = list(category.exclude)
    if global_exclude:
        excludes.extend(global_exclude)

    # Single file category (like starship.toml)
    if category.item_type == ItemType.FILE and not any(c in str(local_path) for c in ["*", "?"]):
        # Check if it's a single file path
        if not local_path.is_dir() and not str(category.local_path).endswith("/"):
            name = local_path.name
            item = SyncItem(
                name=name,
                category=category_name,
                item_type=ItemType.FILE,
                local_path=local_path if local_path.exists() else None,
                repo_path=repo_path if repo_path.exists() else None,
            )
            if item.exists_either:
                # Update paths to actual paths even if one doesn't exist
                item.local_path = local_path
                item.repo_path = repo_path
                return [item]
            return []

    # Scan based on item type
    if category.item_type == ItemType.DIRECTORY and category.item_marker:
        # Directory items with marker (like skills with SKILL.md)
        items = _scan_directory_items(
            category_name=category_name,
            local_path=local_path,
            repo_path=repo_path,
            marker=category.item_marker,
            include=category.include,
            exclude=excludes,
        )
    elif category.item_type == ItemType.FILE:
        # File items
        items = _scan_file_items(
            category_name=category_name,
            local_path=local_path,
            repo_path=repo_path,
            pattern=category.item_pattern,
            include=category.include,
            exclude=excludes,
        )
    elif category.item_type == ItemType.MIXED:
        # Mixed - scan both files and directories
        file_items = _scan_file_items(
            category_name=category_name,
            local_path=local_path,
            repo_path=repo_path,
            pattern=category.item_pattern,
            include=category.include,
            exclude=excludes,
        )
        dir_items = _scan_directory_items(
            category_name=category_name,
            local_path=local_path,
            repo_path=repo_path,
            marker=category.item_marker,
            include=category.include,
            exclude=excludes,
        )
        items = {**file_items, **dir_items}
    else:
        # Default: scan files
        items = _scan_file_items(
            category_name=category_name,
            local_path=local_path,
            repo_path=repo_path,
            pattern=category.item_pattern,
            include=category.include,
            exclude=excludes,
        )

    return list(items.values())


def _scan_file_items(
    category_name: str,
    local_path: Path,
    repo_path: Path,
    pattern: Optional[str],
    include: list[str],
    exclude: list[str],
) -> dict[str, SyncItem]:
    """Scan for file items in both locations."""
    items: dict[str, SyncItem] = {}

    # Enable recursive scanning when include patterns contain subdirectory paths
    needs_recursive = any("/" in p for p in include)

    # Scan local
    if local_path.exists() and local_path.is_dir():
        for file_path in find_files(
            local_path, pattern=pattern, include=include, exclude=exclude, recursive=needs_recursive
        ):
            rel_path = file_path.relative_to(local_path)
            name = str(rel_path)
            if name not in items:
                items[name] = SyncItem(
                    name=name,
                    category=category_name,
                    item_type=ItemType.FILE,
                )
            items[name].local_path = file_path

    # Scan repo
    if repo_path.exists() and repo_path.is_dir():
        for file_path in find_files(
            repo_path, pattern=pattern, include=include, exclude=exclude, recursive=needs_recursive
        ):
            rel_path = file_path.relative_to(repo_path)
            name = str(rel_path)
            if name not in items:
                items[name] = SyncItem(
                    name=name,
                    category=category_name,
                    item_type=ItemType.FILE,
                )
            items[name].repo_path = file_path

    # Set missing paths (for items that exist only in one location)
    for name, item in items.items():
        if item.local_path is None:
            item.local_path = local_path / name
        if item.repo_path is None:
            item.repo_path = repo_path / name

    return items


def _scan_directory_items(
    category_name: str,
    local_path: Path,
    repo_path: Path,
    marker: Optional[str],
    include: list[str],
    exclude: list[str],
) -> dict[str, SyncItem]:
    """Scan for directory items in both locations."""
    items: dict[str, SyncItem] = {}

    # Scan local
    if local_path.exists() and local_path.is_dir():
        for dir_path in find_directories(local_path, marker=marker, include=include, exclude=exclude):
            name = dir_path.name
            if name not in items:
                items[name] = SyncItem(
                    name=name,
                    category=category_name,
                    item_type=ItemType.DIRECTORY,
                )
            items[name].local_path = dir_path

    # Scan repo
    if repo_path.exists() and repo_path.is_dir():
        for dir_path in find_directories(repo_path, marker=marker, include=include, exclude=exclude):
            name = dir_path.name
            if name not in items:
                items[name] = SyncItem(
                    name=name,
                    category=category_name,
                    item_type=ItemType.DIRECTORY,
                )
            items[name].repo_path = dir_path

    # Set missing paths (for items that exist only in one location)
    for name, item in items.items():
        if item.local_path is None:
            item.local_path = local_path / name
        if item.repo_path is None:
            item.repo_path = repo_path / name

    return items
