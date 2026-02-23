# SCCS Memory Manager
# CRUD layer for ~/.claude/memory/ directory

from __future__ import annotations

import re
import socket
from datetime import datetime
from pathlib import Path

from sccs.memory.item import MemoryCategory, MemoryItem

MEMORY_DIR = Path.home() / ".claude" / "memory"
ARCHIVE_DIR = "_archive"
MEMORY_MARKER = "MEMORY.md"


def _slugify(title: str) -> str:
    """Convert a title to a filesystem-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:60].strip("-")


class MemoryManager:
    """
    CRUD operations for memory items stored in a directory.

    Default directory: ~/.claude/memory/
    Items are stored as <memory_dir>/<slug>/MEMORY.md
    """

    def __init__(self, memory_dir: Path | None = None):
        self.memory_dir = (memory_dir or MEMORY_DIR).expanduser()

    def _item_path(self, slug: str) -> Path:
        return self.memory_dir / slug / MEMORY_MARKER

    def _archive_path(self, slug: str) -> Path:
        return self.memory_dir / ARCHIVE_DIR / slug / MEMORY_MARKER

    def exists(self, slug: str) -> bool:
        """Check if a memory item exists."""
        return self._item_path(slug).exists()

    def list_slugs(self, include_archived: bool = False) -> list[str]:
        """List all item slugs in memory directory."""
        if not self.memory_dir.exists():
            return []
        slugs = []
        for item_dir in sorted(self.memory_dir.iterdir()):
            if not item_dir.is_dir():
                continue
            if item_dir.name.startswith("_") and not include_archived:
                continue
            if (item_dir / MEMORY_MARKER).exists():
                slugs.append(item_dir.name)
        return slugs

    def load(self, slug: str) -> MemoryItem:
        """Load a memory item by slug."""
        path = self._item_path(slug)
        if not path.exists():
            raise FileNotFoundError(f"Memory item not found: {slug}")
        return MemoryItem.from_file(path)

    def load_all(self, include_archived: bool = False) -> list[MemoryItem]:
        """Load all memory items."""
        items = []
        for slug in self.list_slugs(include_archived=include_archived):
            try:
                items.append(self.load(slug))
            except Exception:
                pass
        return items

    def add(
        self,
        title: str,
        body: str = "",
        *,
        category: MemoryCategory = MemoryCategory.CONTEXT,
        project: str | None = None,
        tags: list[str] | None = None,
        priority: int = 2,
        expires: datetime | None = None,
        slug: str | None = None,
    ) -> MemoryItem:
        """Create and save a new memory item. Returns the created item."""
        now = datetime.now()
        item_slug = slug or _slugify(title)

        # Ensure unique slug
        base_slug = item_slug
        counter = 1
        while self.exists(item_slug):
            item_slug = f"{base_slug}-{counter}"
            counter += 1

        item = MemoryItem(
            id=item_slug,
            title=title,
            body=body,
            category=category,
            project=project,
            tags=tags or [],
            priority=priority,
            created=now,
            updated=now,
            expires=expires,
            machine=socket.gethostname(),
        )
        item.save_to_dir(self.memory_dir)
        return item

    def update(
        self,
        slug: str,
        *,
        title: str | None = None,
        body: str | None = None,
        extend_body: str | None = None,
        category: MemoryCategory | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        priority: int | None = None,
        expires: datetime | None = None,
        bump_version: bool = False,
    ) -> MemoryItem:
        """Update an existing memory item. Returns the updated item."""
        item = self.load(slug)

        if title is not None:
            item.title = title
        if body is not None:
            item.body = body
        if extend_body is not None:
            sep = "\n\n" if item.body else ""
            item.body = f"{item.body}{sep}{extend_body}"
        if category is not None:
            item.category = category
        if project is not None:
            item.project = project
        if tags is not None:
            item.tags = tags
        if priority is not None:
            item.priority = priority
        if expires is not None:
            item.expires = expires
        if bump_version:
            item.version += 1

        item.updated = datetime.now()
        item.save_to_dir(self.memory_dir)
        return item

    def delete(self, slug: str) -> bool:
        """
        Move item to _archive/ directory (soft delete).
        Returns True if successful.
        """
        path = self._item_path(slug)
        if not path.exists():
            return False

        archive_dir = self.memory_dir / ARCHIVE_DIR / slug
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / MEMORY_MARKER

        import shutil

        shutil.move(str(path), str(archive_path))

        # Remove empty item dir
        item_dir = self.memory_dir / slug
        try:
            item_dir.rmdir()
        except OSError:
            pass

        return True

    def search(self, query: str, project: str | None = None) -> list[MemoryItem]:
        """Simple text search across title, body, and tags."""
        query_lower = query.lower()
        results = []
        for item in self.load_all():
            if project and item.project != project:
                continue
            searchable = f"{item.title} {item.body} {' '.join(item.tags)}".lower()
            if query_lower in searchable:
                results.append(item)
        return results

    def expire_items(self) -> list[MemoryItem]:
        """
        Archive all expired items.
        Returns list of archived items.
        """
        expired = []
        for item in self.load_all():
            if item.is_expired:
                self.delete(item.slug)
                expired.append(item)
        return expired

    def stats(self) -> dict:
        """Return statistics about the memory directory."""
        items = self.load_all()
        by_category: dict[str, int] = {}
        by_project: dict[str, int] = {}

        for item in items:
            cat = item.category.value
            by_category[cat] = by_category.get(cat, 0) + 1
            if item.project:
                by_project[item.project] = by_project.get(item.project, 0) + 1

        return {
            "total": len(items),
            "by_category": by_category,
            "by_project": by_project,
            "expired": sum(1 for i in items if i.is_expired),
            "archived": len(self.list_slugs(include_archived=True)) - len(items),
        }
