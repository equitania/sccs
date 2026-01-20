"""Skill data model with metadata parsing and file tracking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from sccs.config import CONTENT_FILE, SKILL_FILE


@dataclass
class Skill:
    """Represents a Claude Code skill with its metadata and content."""

    name: str
    path: Path
    skill_md_path: Path
    content_md_path: Optional[Path] = None
    description: str = ""
    mtime: float = 0.0
    files: list[Path] = field(default_factory=list)

    @classmethod
    def from_directory(cls, path: Path) -> Skill:
        """Create Skill from a skill directory.

        Args:
            path: Path to the skill directory

        Returns:
            Skill instance with parsed metadata

        Raises:
            FileNotFoundError: If SKILL.md doesn't exist
            ValueError: If YAML frontmatter is invalid
        """
        skill_md_path = path / SKILL_FILE
        if not skill_md_path.exists():
            raise FileNotFoundError(f"SKILL.md not found in {path}")

        content_md_path = path / CONTENT_FILE
        if not content_md_path.exists():
            content_md_path = None

        # Parse YAML frontmatter
        name, description = cls._parse_frontmatter(skill_md_path)
        if not name:
            name = path.name

        # Collect all files and calculate mtime
        files = cls._collect_files(path)
        mtime = cls._calculate_mtime(files)

        return cls(
            name=name,
            path=path,
            skill_md_path=skill_md_path,
            content_md_path=content_md_path,
            description=description,
            mtime=mtime,
            files=files,
        )

    @staticmethod
    def _parse_frontmatter(skill_md_path: Path) -> tuple[str, str]:
        """Parse YAML frontmatter from SKILL.md.

        Args:
            skill_md_path: Path to SKILL.md file

        Returns:
            Tuple of (name, description)
        """
        content = skill_md_path.read_text(encoding="utf-8")

        # Match YAML frontmatter between --- markers
        frontmatter_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
        match = frontmatter_pattern.match(content)

        if not match:
            return "", ""

        try:
            frontmatter = yaml.safe_load(match.group(1))
            if not isinstance(frontmatter, dict):
                return "", ""

            name = frontmatter.get("name", "")
            description = frontmatter.get("description", "")
            return str(name), str(description)
        except yaml.YAMLError:
            return "", ""

    @staticmethod
    def _collect_files(path: Path) -> list[Path]:
        """Collect all files in the skill directory.

        Args:
            path: Path to skill directory

        Returns:
            List of file paths
        """
        files = []
        for item in path.iterdir():
            if item.is_file() and not item.name.startswith("."):
                files.append(item)
        return sorted(files)

    @staticmethod
    def _calculate_mtime(files: list[Path]) -> float:
        """Calculate the most recent modification time.

        Args:
            files: List of file paths

        Returns:
            Most recent mtime as float timestamp
        """
        if not files:
            return 0.0
        return max(f.stat().st_mtime for f in files)

    def get_content_hash(self) -> str:
        """Generate SHA256 hash of all file contents.

        Returns:
            Hex digest of combined content hash
        """
        hasher = hashlib.sha256()
        for file_path in sorted(self.files):
            content = file_path.read_bytes()
            hasher.update(file_path.name.encode("utf-8"))
            hasher.update(content)
        return hasher.hexdigest()

    def get_file_list(self) -> list[str]:
        """Get list of file names in this skill.

        Returns:
            List of file names
        """
        return [f.name for f in self.files]

    def __repr__(self) -> str:
        """String representation of Skill."""
        files_str = ", ".join(self.get_file_list())
        return f"Skill(name={self.name!r}, files=[{files_str}], mtime={self.mtime:.0f})"


def scan_skills_directory(path: Path) -> dict[str, Skill]:
    """Scan a directory for skills.

    Args:
        path: Path to skills directory

    Returns:
        Dictionary mapping skill name to Skill instance
    """
    skills: dict[str, Skill] = {}

    if not path.exists():
        return skills

    for item in path.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            skill_md = item / SKILL_FILE
            if skill_md.exists():
                try:
                    skill = Skill.from_directory(item)
                    skills[skill.name] = skill
                except (FileNotFoundError, ValueError):
                    # Skip invalid skills
                    pass

    return skills
