# SCCS Memory Bridge
# Import/Export bridge between Claude Code and Claude.ai

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sccs.memory.item import MemoryItem

# Max characters for export block (soft limit)
DEFAULT_MAX_CHARS = 12000


class ClaudeAiBridge:
    """Bridge for exporting memory to Claude.ai and importing from Claude.ai exports."""

    @staticmethod
    def export_to_context_block(items: list[MemoryItem], max_chars: int = DEFAULT_MAX_CHARS) -> str:
        """
        Export memory items as a <memory>...</memory> block for Claude.ai.

        The block can be inserted as a system prompt or at the start of a conversation.
        Items are sorted by priority (highest first).
        """
        if not items:
            return ""

        sorted_items = sorted(items, key=lambda x: -x.priority)

        lines: list[str] = []
        total_chars = 0

        for item in sorted_items:
            header_parts = [f"[{item.category.value}"]
            if item.project:
                header_parts.append(f"project: {item.project}")
            header_parts[-1] += "]"  # Close bracket on last part
            # Build: [category / project: foo]
            if item.project:
                header = f"[{item.category.value} / project: {item.project}]"
            else:
                header = f"[{item.category.value}]"

            entry_lines = [
                f"{header} {item.title}",
                f"Updated: {item.updated.strftime('%Y-%m-%d')}",
                "",
                item.body.strip(),
                "",
                "---",
            ]
            entry = "\n".join(entry_lines)
            if total_chars + len(entry) > max_chars:
                lines.append("[... remaining items truncated to fit context limit ...]")
                break
            lines.append(entry)
            total_chars += len(entry)

        content = "\n".join(lines)
        # Remove trailing separator lines
        while content.endswith("---"):
            content = content[:-3].rstrip()
        content = content.strip()
        return f"<memory>\n{content}\n</memory>"

    @staticmethod
    def export_to_json(items: list[MemoryItem]) -> dict:
        """Export memory items as a structured JSON dict."""
        return {
            "exported_at": datetime.now().isoformat(),
            "count": len(items),
            "items": [
                {
                    "id": item.id,
                    "title": item.title,
                    "category": item.category.value,
                    "project": item.project,
                    "tags": item.tags,
                    "priority": item.priority,
                    "created": item.created.isoformat(),
                    "updated": item.updated.isoformat(),
                    "expires": item.expires.isoformat() if item.expires else None,
                    "body": item.body,
                }
                for item in items
            ],
        }

    @staticmethod
    def import_conversation(path: Path, interactive: bool = True) -> list[MemoryItem]:
        """
        Import memory candidates from a Claude.ai conversation export (JSON).

        Claude.ai exports conversations as JSON with a messages array.
        This function extracts structured content (headings, decisions, learnings)
        and returns MemoryItem candidates.

        Args:
            path: Path to the Claude.ai export JSON file.
            interactive: If True, prompt user to select which candidates to import.

        Returns:
            List of MemoryItem objects ready to be saved.
        """

        data = json.loads(path.read_text(encoding="utf-8"))
        candidates = ClaudeAiBridge._parse_claude_export(data)

        if not candidates:
            return []

        items = [ClaudeAiBridge._candidate_to_item(c) for c in candidates]

        if interactive and items:
            selected = []
            click_available = False
            try:
                import click

                click_available = True
            except ImportError:
                pass

            if click_available:
                import click

                click.echo(f"\nFound {len(items)} memory candidates:")
                for i, item in enumerate(items):
                    click.echo(f"  [{i + 1}] {item.title} ({item.category.value})")
                click.echo("")
                raw = click.prompt("Select items (e.g. '1,3,5' or 'all')", default="all")
                if raw.strip().lower() == "all":
                    selected = items
                else:
                    try:
                        indices = [int(x.strip()) - 1 for x in raw.split(",")]
                        selected = [items[i] for i in indices if 0 <= i < len(items)]
                    except (ValueError, IndexError):
                        selected = items
            else:
                selected = items

            return selected

        return items

    @staticmethod
    def _parse_claude_export(data: dict) -> list[dict]:
        """
        Parse Claude.ai conversation export JSON.

        Handles the format: {"chat_messages": [...]} or {"messages": [...]}
        Each message has "text" or "content" field.
        """
        candidates = []

        # Support multiple export formats
        messages = data.get("chat_messages") or data.get("messages") or []
        if not messages:
            # Maybe it's directly an array
            if isinstance(data, list):
                messages = data

        for msg in messages:
            # Extract text content
            text = ""
            if isinstance(msg, dict):
                text = msg.get("text") or msg.get("content") or ""
                if isinstance(text, list):
                    # Handle structured content blocks
                    text = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in text)

            if not text:
                continue

            extracted = ClaudeAiBridge._extract_memory_candidates(str(text))
            candidates.extend(extracted)

        return candidates

    @staticmethod
    def _extract_memory_candidates(text: str) -> list[dict]:
        """
        Identify structured content in a message that could be memory items.

        Looks for patterns like:
        - "Decision: ..."
        - "Key Learning: ..."
        - "## Section Title\n..."
        """
        candidates = []

        # Pattern 1: "Decision: title\n body"
        for m in re.finditer(
            r"(?:^|\n)(Decision|Key Learning|Learning|Pattern|Reference):\s*(.+?)(?=\n\n|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        ):
            kind = m.group(1).lower().replace(" ", "_")
            body = m.group(2).strip()
            if len(body) < 20:
                continue
            title_line, _, rest = body.partition("\n")
            candidates.append(
                {
                    "title": title_line.strip()[:80],
                    "body": rest.strip() or body,
                    "category": _kind_to_category(kind),
                }
            )

        # Pattern 2: Markdown H2/H3 headings with substantial body
        for m in re.finditer(r"(?:^|\n)#{2,3}\s+(.+?)\n((?:.+\n?){3,})", text):
            title = m.group(1).strip()
            body = m.group(2).strip()
            if len(body) < 50:
                continue
            candidates.append(
                {
                    "title": title[:80],
                    "body": body,
                    "category": "context",
                }
            )

        return candidates

    @staticmethod
    def _candidate_to_item(candidate: dict) -> MemoryItem:
        """Convert a raw candidate dict to a MemoryItem."""
        from sccs.memory.item import MemoryCategory, MemoryItem
        from sccs.memory.manager import _slugify

        title = candidate.get("title", "Untitled")
        body = candidate.get("body", "")
        cat_str = candidate.get("category", MemoryCategory.CONTEXT.value)

        try:
            category = MemoryCategory(cat_str)
        except ValueError:
            category = MemoryCategory.CONTEXT

        now = datetime.now()
        return MemoryItem(
            id=_slugify(title),
            title=title,
            body=body,
            category=category,
            created=now,
            updated=now,
        )


def _kind_to_category(kind: str) -> str:
    """Map extracted kind string to MemoryCategory value."""
    mapping = {
        "decision": "decision",
        "learning": "learning",
        "key_learning": "learning",
        "pattern": "pattern",
        "reference": "reference",
    }
    return mapping.get(kind, "context")
