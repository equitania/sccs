# SCCS Memory Filter
# MemoryFilter dataclass and matching logic for memory items

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sccs.memory.item import MemoryItem


class MemoryPriority(int, Enum):
    """Priority levels for memory items."""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    IMPORTANT = 4
    CRITICAL = 5


@dataclass
class MemoryFilter:
    """
    Filter criteria for selecting memory items.

    All criteria are combined with AND logic. None/empty means "no filter".
    """

    project: str | None = None
    tags: list[str] = field(default_factory=list)
    category: str | None = None
    min_priority: int = 1
    include_expired: bool = False
    max_age_days: int | None = None

    def matches(self, item: MemoryItem) -> bool:
        """Return True if item matches all filter criteria."""
        # Project filter
        if self.project and item.project != self.project:
            return False

        # Category filter
        if self.category and item.category.value != self.category:
            return False

        # Priority filter
        if item.priority < self.min_priority:
            return False

        # Expired filter
        if not self.include_expired and item.is_expired:
            return False

        # Tag filter (any matching tag)
        if self.tags:
            item_tags_lower = [t.lower() for t in item.tags]
            if not any(t.lower() in item_tags_lower for t in self.tags):
                return False

        # Max age filter
        if self.max_age_days is not None:
            age = (datetime.now() - item.updated).days
            if age > self.max_age_days:
                return False

        return True

    def apply(self, items: list[MemoryItem]) -> list[MemoryItem]:
        """Filter and sort items by priority (descending), then updated (newest first)."""
        filtered = [i for i in items if self.matches(i)]
        return sorted(filtered, key=lambda x: (-x.priority, x.updated), reverse=False)
