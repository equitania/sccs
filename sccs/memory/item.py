# SCCS Memory Item
# MemoryItem dataclass with YAML frontmatter serialization

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class MemoryCategory(str, Enum):
    """Category for memory items."""

    PROJECT = "project"
    DECISION = "decision"
    LEARNING = "learning"
    PATTERN = "pattern"
    PREFERENCE = "preference"
    REFERENCE = "reference"
    CONTEXT = "context"


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


@dataclass
class MemoryItem:
    """
    A single memory item with YAML frontmatter and Markdown body.

    Stored as ~/.claude/memory/<slug>/MEMORY.md
    """

    id: str
    title: str
    body: str = ""
    category: MemoryCategory = MemoryCategory.CONTEXT
    project: str | None = None
    tags: list[str] = field(default_factory=list)
    priority: int = 2  # 1 (low) - 5 (critical)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
    expires: datetime | None = None
    version: int = 1
    machine: str | None = None

    @property
    def slug(self) -> str:
        """Return the directory slug (same as id)."""
        return self.id

    @property
    def is_expired(self) -> bool:
        """Check if this item has expired."""
        if self.expires is None:
            return False
        return datetime.now() > self.expires

    def to_markdown(self) -> str:
        """Serialize to MEMORY.md format with YAML frontmatter."""
        frontmatter: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "category": self.category.value,
            "priority": self.priority,
            "version": self.version,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
        }
        if self.project:
            frontmatter["project"] = self.project
        if self.tags:
            frontmatter["tags"] = self.tags
        if self.expires:
            frontmatter["expires"] = self.expires.isoformat()
        else:
            frontmatter["expires"] = None
        if self.machine:
            frontmatter["machine"] = self.machine

        fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return f"---\n{fm_str}---\n\n# {self.title}\n\n{self.body}"

    @classmethod
    def from_markdown(cls, content: str) -> MemoryItem:
        """Parse a MEMORY.md file content into a MemoryItem."""
        match = FRONTMATTER_RE.match(content)
        if not match:
            raise ValueError("No valid YAML frontmatter found in memory file")

        fm_str, body = match.group(1), match.group(2).strip()
        fm: dict[str, Any] = yaml.safe_load(fm_str) or {}

        # Strip leading "# Title" heading from body if present
        if body.startswith(f"# {fm.get('title', '')}"):
            body = body[len(f"# {fm.get('title', '')}"):].strip()

        def parse_dt(val: Any) -> datetime | None:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            try:
                return datetime.fromisoformat(str(val))
            except (ValueError, TypeError):
                return None

        created = parse_dt(fm.get("created")) or datetime.now()
        updated = parse_dt(fm.get("updated")) or datetime.now()
        expires = parse_dt(fm.get("expires"))

        return cls(
            id=str(fm.get("id", "")),
            title=str(fm.get("title", "")),
            body=body,
            category=MemoryCategory(fm.get("category", MemoryCategory.CONTEXT.value)),
            project=fm.get("project"),
            tags=list(fm.get("tags") or []),
            priority=int(fm.get("priority", 2)),
            created=created,
            updated=updated,
            expires=expires,
            version=int(fm.get("version", 1)),
            machine=fm.get("machine"),
        )

    @classmethod
    def from_file(cls, path: Path) -> MemoryItem:
        """Load a MemoryItem from a MEMORY.md file path."""
        content = path.read_text(encoding="utf-8")
        return cls.from_markdown(content)

    def save_to_dir(self, memory_dir: Path) -> Path:
        """Save this item to memory_dir/<slug>/MEMORY.md, creating dirs as needed."""
        item_dir = memory_dir / self.slug
        item_dir.mkdir(parents=True, exist_ok=True)
        target = item_dir / "MEMORY.md"
        target.write_text(self.to_markdown(), encoding="utf-8")
        return target
