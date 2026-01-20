"""User configuration management for SCCS.

Handles user-specific configuration stored in ~/.config/sccs/config.json.
Provides first-run setup prompts and configuration persistence.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# Default configuration directory
CONFIG_DIR = Path.home() / ".config" / "sccs"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class UserConfig:
    """User configuration for SCCS."""

    # Repository settings
    repo_url: str = ""
    repo_path: str = ""  # Local clone path, empty = auto-detect

    # Local paths (can override defaults)
    local_skills_path: str = ""  # Empty = ~/.claude/skills
    local_commands_path: str = ""  # Empty = ~/.claude/commands

    # Sync behavior
    auto_commit: bool = False
    auto_push: bool = False
    git_remote: str = "origin"
    commit_prefix: str = "[CHG]"

    # UI settings
    verbose: bool = False

    @classmethod
    def load(cls) -> "UserConfig":
        """Load configuration from file.

        Returns:
            UserConfig instance (with defaults if file doesn't exist)
        """
        if not CONFIG_FILE.exists():
            return cls()

        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cls(
                repo_url=data.get("repo_url", ""),
                repo_path=data.get("repo_path", ""),
                local_skills_path=data.get("local_skills_path", ""),
                local_commands_path=data.get("local_commands_path", ""),
                auto_commit=data.get("auto_commit", False),
                auto_push=data.get("auto_push", False),
                git_remote=data.get("git_remote", "origin"),
                commit_prefix=data.get("commit_prefix", "[CHG]"),
                verbose=data.get("verbose", False),
            )
        except (json.JSONDecodeError, KeyError):
            return cls()

    def save(self) -> None:
        """Save configuration to file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def is_configured(self) -> bool:
        """Check if basic configuration exists.

        Returns:
            True if repo_url or repo_path is set
        """
        return bool(self.repo_url or self.repo_path)

    def get_repo_path(self) -> Optional[Path]:
        """Get the repository path.

        Priority:
        1. repo_path if set
        2. repo_url if it looks like a local path (not a URL)
        3. Auto-detect from current directory

        Returns:
            Path to repository root, or None if not found
        """
        # Check repo_path first
        if self.repo_path:
            path = Path(self.repo_path).expanduser()
            if path.exists():
                return path

        # Check if repo_url is actually a local path (migration from old configs)
        if self.repo_url and not self.repo_url.startswith(("http://", "https://", "git@", "ssh://")):
            path = Path(self.repo_url).expanduser()
            if path.exists():
                return path

        # Try to find repo from cwd
        return _find_repo_root()

    def get_local_skills_path(self) -> Path:
        """Get the local skills path."""
        if self.local_skills_path:
            return Path(self.local_skills_path).expanduser()
        return Path.home() / ".claude" / "skills"

    def get_local_commands_path(self) -> Path:
        """Get the local commands path."""
        if self.local_commands_path:
            return Path(self.local_commands_path).expanduser()
        return Path.home() / ".claude" / "commands"


def _find_repo_root() -> Optional[Path]:
    """Find repository root by looking for .git directory.

    Searches from current working directory upward.

    Returns:
        Path to repository root, or None if not found
    """
    current = Path.cwd()
    while current != current.parent:
        if (current / ".git").exists():
            # Check if it has .claude directory (skills repo indicator)
            if (current / ".claude").exists():
                return current
        current = current.parent

    return None


def prompt_first_run_setup() -> UserConfig:
    """Interactive first-run configuration setup.

    Prompts user for repository URL and saves configuration.

    Returns:
        Configured UserConfig instance
    """
    from rich.console import Console
    from rich.prompt import Prompt

    console = Console()
    config = UserConfig()

    console.print()
    console.print("[bold cyan]SCCS First-Run Setup[/bold cyan]")
    console.print()
    console.print("SCCS needs to know where your skills/commands repository is located.")
    console.print("This repository will store your synchronized skills and commands.")
    console.print()

    # Check if we're already in a repo with .claude directory
    detected_repo = _find_repo_root()
    if detected_repo:
        console.print(f"[yellow]Detected repository:[/yellow] {detected_repo}")
        console.print("[dim]This repository has a .claude directory.[/dim]")
        console.print()
        use_detected = Prompt.ask(
            "Use this repository for sync?",
            choices=["y", "n"],
            default="n"  # Default to NO - user should explicitly choose
        )
        if use_detected.lower() == "y":
            config.repo_path = str(detected_repo)
            config.save()
            console.print()
            console.print("[green]✓ Configuration saved![/green]")
            console.print(f"[dim]Config file: {CONFIG_FILE}[/dim]")
            return config

    # Ask for repo path - this is the main path
    console.print()
    console.print("[bold]Enter your skills repository path:[/bold]")
    console.print("[dim]This should be a local Git repository where skills/commands will be stored.[/dim]")
    console.print("[dim]Examples:[/dim]")
    console.print("[dim]  ~/gitbase/my-claude-skills[/dim]")
    console.print("[dim]  /Users/picard/projects/superclaude[/dim]")
    console.print()

    repo_input = Prompt.ask("Repository path", default="")

    if repo_input:
        expanded_path = Path(repo_input).expanduser()
        if expanded_path.exists():
            config.repo_path = str(expanded_path)
            console.print(f"[green]✓ Found repository at:[/green] {expanded_path}")
        else:
            console.print(f"[yellow]Path does not exist yet:[/yellow] {expanded_path}")
            create_it = Prompt.ask("Create this directory?", choices=["y", "n"], default="y")
            if create_it.lower() == "y":
                expanded_path.mkdir(parents=True, exist_ok=True)
                config.repo_path = str(expanded_path)
                console.print(f"[green]✓ Created directory:[/green] {expanded_path}")
            else:
                config.repo_path = str(expanded_path)  # Save anyway, user can create later

    if not config.repo_path:
        console.print("[yellow]⚠ No repository path configured.[/yellow]")
        console.print("[dim]You can run 'sccs init' later to set up the repository.[/dim]")
    else:
        config.save()
        console.print()
        console.print("[green]✓ Configuration saved![/green]")
        console.print(f"[dim]Config file: {CONFIG_FILE}[/dim]")
        console.print(f"[dim]Repository:  {config.repo_path}[/dim]")

    return config


def ensure_configured() -> UserConfig:
    """Ensure SCCS is configured, prompting if necessary.

    Returns:
        Configured UserConfig instance
    """
    config = UserConfig.load()

    if not config.is_configured():
        config = prompt_first_run_setup()

    return config


def get_config() -> UserConfig:
    """Get the current user configuration.

    Does NOT prompt for first-run setup. Use ensure_configured() for that.

    Returns:
        UserConfig instance
    """
    return UserConfig.load()
