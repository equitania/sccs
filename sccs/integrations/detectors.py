# SCCS Integration Detectors
# Read-only detection of Antigravity IDE and Claude Desktop installations

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sccs.utils.platform import get_current_platform


@dataclass
class AntigravityInfo:
    """Information about Antigravity IDE installation."""

    installed: bool
    base_dir: Path
    prompts_dir: Path
    prompts_dir_exists: bool


@dataclass
class AntigravitySkillGap:
    """A Claude Code skill missing or outdated in Antigravity prompts."""

    name: str
    skill_md_path: Path
    prompt_path: Path
    prompt_exists: bool
    needs_update: bool


class AntigravityDetector:
    """Detects Antigravity IDE and compares skill availability."""

    _DEFAULT_EXCLUDES = ["_archive", "_deprecated"]

    def __init__(
        self,
        base_dir: Path | None = None,
        skills_dir: Path | None = None,
    ) -> None:
        self._base_dir = base_dir or Path.home() / ".antigravity"
        self._skills_dir = skills_dir or Path.home() / ".claude" / "skills"

    def is_installed(self) -> bool:
        return self._base_dir.is_dir()

    def get_info(self) -> AntigravityInfo | None:
        if not self.is_installed():
            return None
        prompts_dir = self._base_dir / "prompts"
        return AntigravityInfo(
            installed=True,
            base_dir=self._base_dir,
            prompts_dir=prompts_dir,
            prompts_dir_exists=prompts_dir.is_dir(),
        )

    def get_skill_gaps(self, exclude: list[str] | None = None) -> list[AntigravitySkillGap]:
        """
        Find Claude Code skills missing or outdated in Antigravity prompts.

        Args:
            exclude: Directory names to skip (defaults to _archive, _deprecated).

        Returns:
            List of skill gaps sorted by name.
        """
        if not self.is_installed():
            return []

        excludes = exclude if exclude is not None else self._DEFAULT_EXCLUDES
        prompts_dir = self._base_dir / "prompts"
        gaps: list[AntigravitySkillGap] = []

        if not self._skills_dir.is_dir():
            return gaps

        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name in excludes or skill_dir.name.startswith("."):
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue

            prompt_path = prompts_dir / f"{skill_dir.name}.md"
            prompt_exists = prompt_path.is_file()
            needs_update = False

            if prompt_exists:
                try:
                    skill_content = skill_md.read_text(encoding="utf-8")
                    prompt_content = prompt_path.read_text(encoding="utf-8")
                    needs_update = skill_content != prompt_content
                except OSError:
                    needs_update = True

            if not prompt_exists or needs_update:
                gaps.append(
                    AntigravitySkillGap(
                        name=skill_dir.name,
                        skill_md_path=skill_md,
                        prompt_path=prompt_path,
                        prompt_exists=prompt_exists,
                        needs_update=needs_update,
                    )
                )

        return gaps


@dataclass
class ClaudeDesktopInfo:
    """Information about Claude Desktop installation."""

    installed: bool
    app_path: Path | None = None
    config_dir: Path | None = None
    config_file: Path | None = None
    trusted_folders: list[str] = field(default_factory=list)


class ClaudeDesktopDetector:
    """Detects Claude Desktop and reads trusted folder configuration."""

    def __init__(
        self,
        app_path: Path | None = None,
        config_dir: Path | None = None,
    ) -> None:
        self._app_path = app_path or Path("/Applications/Claude.app")
        self._config_dir = config_dir or Path.home() / "Library" / "Application Support" / "Claude"

    def is_installed(self) -> bool:
        if get_current_platform() != "macos":
            return False
        return self._app_path.is_dir()

    def get_info(self) -> ClaudeDesktopInfo | None:
        if not self.is_installed():
            return None

        config_file = self._config_dir / "claude_desktop_config.json"
        trusted_folders: list[str] = []

        if config_file.is_file():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                trusted_folders = data.get("preferences", {}).get("localAgentModeTrustedFolders", [])
            except (json.JSONDecodeError, OSError):
                pass

        return ClaudeDesktopInfo(
            installed=True,
            app_path=self._app_path,
            config_dir=self._config_dir,
            config_file=config_file if config_file.is_file() else None,
            trusted_folders=trusted_folders,
        )

    def is_repo_trusted(self, repo_path: str) -> bool:
        """Check if a repository path is in the trusted folders list."""
        info = self.get_info()
        if info is None:
            return False
        resolved = str(Path(repo_path).expanduser().resolve())
        return resolved in info.trusted_folders
