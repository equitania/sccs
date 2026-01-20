"""Command data model with metadata parsing and file tracking.

Commands are single Markdown files with optional YAML frontmatter.
Unlike Skills (which are directories), Commands are individual files.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Command:
    """Represents a Claude Code command with its metadata and content."""

    name: str
    path: Path
    description: str = ""
    tags: list[str] | None = None
    mtime: float = 0.0

    @classmethod
    def from_file(cls, path: Path) -> Command:
        """Create Command from a command markdown file.

        Args:
            path: Path to the command .md file

        Returns:
            Command instance with parsed metadata

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If YAML frontmatter is invalid
        """
        if not path.exists():
            raise FileNotFoundError(f"Command file not found: {path}")

        if not path.suffix == ".md":
            raise ValueError(f"Command file must be .md: {path}")

        # Parse YAML frontmatter
        name = path.stem  # filename without extension
        description, tags = cls._parse_frontmatter(path)

        # Get modification time
        mtime = path.stat().st_mtime

        return cls(
            name=name,
            path=path,
            description=description,
            tags=tags,
            mtime=mtime,
        )

    @staticmethod
    def _parse_frontmatter(path: Path) -> tuple[str, list[str] | None]:
        """Parse YAML frontmatter from command file.

        Args:
            path: Path to command file

        Returns:
            Tuple of (description, tags)
        """
        content = path.read_text(encoding="utf-8")

        # Match YAML frontmatter between --- markers
        frontmatter_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
        match = frontmatter_pattern.match(content)

        if not match:
            return "", None

        try:
            frontmatter = yaml.safe_load(match.group(1))
            if not isinstance(frontmatter, dict):
                return "", None

            description = frontmatter.get("description", "")
            tags = frontmatter.get("tags", None)
            if tags and not isinstance(tags, list):
                tags = [str(tags)]
            return str(description), tags
        except yaml.YAMLError:
            return "", None

    def get_content_hash(self) -> str:
        """Generate SHA256 hash of file contents.

        Returns:
            Hex digest of content hash
        """
        content = self.path.read_bytes()
        hasher = hashlib.sha256()
        hasher.update(self.path.name.encode("utf-8"))
        hasher.update(content)
        return hasher.hexdigest()

    def get_content(self) -> str:
        """Get the full content of the command file.

        Returns:
            File content as string
        """
        return self.path.read_text(encoding="utf-8")

    def __repr__(self) -> str:
        """String representation of Command."""
        return f"Command(name={self.name!r}, path={self.path!r}, mtime={self.mtime:.0f})"


def scan_commands_directory(path: Path) -> dict[str, Command]:
    """Scan a directory for command files.

    Args:
        path: Path to commands directory

    Returns:
        Dictionary mapping command name to Command instance
    """
    commands: dict[str, Command] = {}

    if not path.exists():
        return commands

    for item in path.iterdir():
        if item.is_file() and item.suffix == ".md" and not item.name.startswith("."):
            try:
                command = Command.from_file(item)
                commands[command.name] = command
            except (FileNotFoundError, ValueError):
                # Skip invalid command files
                pass

    return commands
