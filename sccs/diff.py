"""Diff generation and display for conflict resolution."""

from __future__ import annotations

import difflib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

if TYPE_CHECKING:
    from sccs.command import Command
    from sccs.skill import Skill


class ConflictResolution(Enum):
    """Resolution options for conflicts."""

    USE_LOCAL = "local"
    USE_REPO = "repo"
    SKIP = "skip"
    ABORT = "abort"


class DeletionResolution(Enum):
    """Resolution options for deletions."""

    DELETE = "delete"
    RESTORE = "restore"
    SKIP = "skip"
    ABORT = "abort"


class DiffGenerator:
    """Generate and display diffs for conflict resolution."""

    def __init__(self, console: Console | None = None):
        """Initialize diff generator.

        Args:
            console: Rich Console instance
        """
        self.console = console or Console()

    def generate_diff(self, file1: Path, file2: Path) -> str:
        """Generate unified diff between two files.

        Args:
            file1: First file (local)
            file2: Second file (repo)

        Returns:
            Unified diff string
        """
        content1 = file1.read_text(encoding="utf-8").splitlines(keepends=True)
        content2 = file2.read_text(encoding="utf-8").splitlines(keepends=True)

        diff = difflib.unified_diff(
            content2,
            content1,
            fromfile=f"repo/{file2.name}",
            tofile=f"local/{file1.name}",
            lineterm="",
        )

        return "".join(diff)

    def display_diff(self, local: "Skill", repo: "Skill") -> None:
        """Display colored diff in terminal.

        Args:
            local: Local skill
            repo: Repository skill
        """
        self.console.print()
        self.console.print(Panel(f"[bold cyan]Skill: {local.name}[/bold cyan]", title="Conflict Detected"))

        # Show file-by-file diff
        local_files = {f.name: f for f in local.files}
        repo_files = {f.name: f for f in repo.files}

        all_files = sorted(set(local_files.keys()) | set(repo_files.keys()))

        for filename in all_files:
            local_file = local_files.get(filename)
            repo_file = repo_files.get(filename)

            if local_file and repo_file:
                # Both exist - show diff
                diff = self.generate_diff(local_file, repo_file)
                if diff:
                    self.console.print(f"\n[bold]{filename}:[/bold]")
                    self._display_colored_diff(diff)
            elif local_file:
                self.console.print(f"\n[green]+ {filename}[/green] (only in local)")
            else:
                self.console.print(f"\n[red]- {filename}[/red] (only in repo)")

        # Show timestamps
        self.console.print()
        local_time = datetime.fromtimestamp(local.mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        repo_time = datetime.fromtimestamp(repo.mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.console.print(f"[dim]Local modified:  {local_time}[/dim]")
        self.console.print(f"[dim]Repo modified:   {repo_time}[/dim]")

    def display_command_diff(self, local: "Command", repo: "Command") -> None:
        """Display colored diff for command files.

        Args:
            local: Local command
            repo: Repository command
        """
        self.console.print()
        self.console.print(Panel(f"[bold cyan]Command: {local.name}[/bold cyan]", title="Conflict Detected"))

        # Show diff between the two command files
        diff = self.generate_diff(local.path, repo.path)
        if diff:
            self.console.print(f"\n[bold]{local.path.name}:[/bold]")
            self._display_colored_diff(diff)

        # Show timestamps
        self.console.print()
        local_time = datetime.fromtimestamp(local.mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        repo_time = datetime.fromtimestamp(repo.mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.console.print(f"[dim]Local modified:  {local_time}[/dim]")
        self.console.print(f"[dim]Repo modified:   {repo_time}[/dim]")

    def display_text_diff(self, text1: str, text2: str, label1: str = "A", label2: str = "B") -> None:
        """Display colored diff between two text strings.

        Args:
            text1: First text
            text2: Second text
            label1: Label for first text
            label2: Label for second text
        """
        lines1 = text1.splitlines(keepends=True)
        lines2 = text2.splitlines(keepends=True)

        diff = difflib.unified_diff(
            lines1,
            lines2,
            fromfile=label1,
            tofile=label2,
            lineterm="",
        )

        diff_text = "".join(diff)
        if diff_text:
            self._display_colored_diff(diff_text)
        else:
            self.console.print("[dim]No differences[/dim]")

    def _display_colored_diff(self, diff: str) -> None:
        """Display diff with syntax highlighting."""
        lines = diff.split("\n")
        for line in lines:
            if line.startswith("+++") or line.startswith("---"):
                self.console.print(f"[bold]{line}[/bold]")
            elif line.startswith("+"):
                self.console.print(f"[green]{line}[/green]")
            elif line.startswith("-"):
                self.console.print(f"[red]{line}[/red]")
            elif line.startswith("@@"):
                self.console.print(f"[cyan]{line}[/cyan]")
            else:
                self.console.print(f"[dim]{line}[/dim]")

    def show_conflict_menu(
        self, skill_name: str, local_mtime: datetime, repo_mtime: datetime, item_type: str = "skill"
    ) -> ConflictResolution:
        """Interactive menu for conflict resolution.

        Args:
            skill_name: Name of the skill or command
            local_mtime: Local modification time
            repo_mtime: Repo modification time
            item_type: Type of item ('skill' or 'command')

        Returns:
            ConflictResolution choice
        """
        self.console.print()
        self.console.print("[bold yellow]Choose resolution:[/bold yellow]")
        self.console.print("  [cyan]l[/cyan] - Use [green]local[/green] version (overwrite repo)")
        self.console.print("  [cyan]r[/cyan] - Use [blue]repo[/blue] version (overwrite local)")
        self.console.print(f"  [cyan]s[/cyan] - [dim]Skip[/dim] this {item_type} (no changes)")
        self.console.print("  [cyan]a[/cyan] - [red]Abort[/red] sync entirely")
        self.console.print()

        while True:
            choice = Prompt.ask("Your choice", choices=["l", "r", "s", "a"], default="s")
            if choice == "l":
                return ConflictResolution.USE_LOCAL
            elif choice == "r":
                return ConflictResolution.USE_REPO
            elif choice == "s":
                return ConflictResolution.SKIP
            elif choice == "a":
                return ConflictResolution.ABORT

    def show_deletion_menu(
        self, skill_name: str, deleted_from: str, skill: "Skill"
    ) -> DeletionResolution:
        """Interactive menu for deletion resolution.

        Args:
            skill_name: Name of the skill
            deleted_from: Where the skill was deleted ('local' or 'repo')
            skill: The remaining skill

        Returns:
            DeletionResolution choice
        """
        self.console.print()
        self.console.print(
            Panel(
                f"[bold cyan]Skill: {skill_name}[/bold cyan]\n"
                f"Deleted from: [yellow]{deleted_from}[/yellow]\n"
                f"Files: {', '.join(skill.get_file_list())}",
                title="Deletion Detected",
            )
        )

        self.console.print()
        self.console.print("[bold yellow]Choose action:[/bold yellow]")
        self.console.print("  [cyan]d[/cyan] - [red]Delete[/red] from remaining location too")
        self.console.print("  [cyan]r[/cyan] - [green]Restore[/green] to deleted location")
        self.console.print("  [cyan]s[/cyan] - [dim]Skip[/dim] (leave as is)")
        self.console.print("  [cyan]a[/cyan] - [red]Abort[/red] sync entirely")
        self.console.print()

        while True:
            choice = Prompt.ask("Your choice", choices=["d", "r", "s", "a"], default="s")
            if choice == "d":
                return DeletionResolution.DELETE
            elif choice == "r":
                return DeletionResolution.RESTORE
            elif choice == "s":
                return DeletionResolution.SKIP
            elif choice == "a":
                return DeletionResolution.ABORT

    def show_command_deletion_menu(
        self, command_name: str, deleted_from: str, command: Optional["Command"]
    ) -> DeletionResolution:
        """Interactive menu for command deletion resolution.

        Args:
            command_name: Name of the command
            deleted_from: Where the command was deleted ('local' or 'repo')
            command: The remaining command (may be None)

        Returns:
            DeletionResolution choice
        """
        self.console.print()

        description = command.description if command else "No description"
        self.console.print(
            Panel(
                f"[bold cyan]Command: {command_name}[/bold cyan]\n"
                f"Deleted from: [yellow]{deleted_from}[/yellow]\n"
                f"Description: {description}",
                title="Command Deletion Detected",
            )
        )

        self.console.print()
        self.console.print("[bold yellow]Choose action:[/bold yellow]")
        self.console.print("  [cyan]d[/cyan] - [red]Delete[/red] from remaining location too")
        self.console.print("  [cyan]r[/cyan] - [green]Restore[/green] to deleted location")
        self.console.print("  [cyan]s[/cyan] - [dim]Skip[/dim] (leave as is)")
        self.console.print("  [cyan]a[/cyan] - [red]Abort[/red] sync entirely")
        self.console.print()

        while True:
            choice = Prompt.ask("Your choice", choices=["d", "r", "s", "a"], default="s")
            if choice == "d":
                return DeletionResolution.DELETE
            elif choice == "r":
                return DeletionResolution.RESTORE
            elif choice == "s":
                return DeletionResolution.SKIP
            elif choice == "a":
                return DeletionResolution.ABORT


def show_skill_diff(skill_name: str, local_path: Path, repo_path: Path, console: Console | None = None) -> None:
    """Show diff for a specific skill.

    Args:
        skill_name: Name of the skill
        local_path: Path to local skills directory
        repo_path: Path to repo skills directory
        console: Rich Console instance
    """
    from sccs.skill import Skill

    console = console or Console()
    diff_gen = DiffGenerator(console)

    local_skill_path = local_path / skill_name
    repo_skill_path = repo_path / skill_name

    if not local_skill_path.exists() and not repo_skill_path.exists():
        console.print(f"[red]Skill '{skill_name}' not found in either location[/red]")
        return

    if not local_skill_path.exists():
        console.print(f"[yellow]Skill '{skill_name}' only exists in repository[/yellow]")
        return

    if not repo_skill_path.exists():
        console.print(f"[yellow]Skill '{skill_name}' only exists locally[/yellow]")
        return

    local = Skill.from_directory(local_skill_path)
    repo = Skill.from_directory(repo_skill_path)

    diff_gen.display_diff(local, repo)


def show_command_diff(command_name: str, local_path: Path, repo_path: Path, console: Console | None = None) -> None:
    """Show diff for a specific command.

    Args:
        command_name: Name of the command (without .md extension)
        local_path: Path to local commands directory
        repo_path: Path to repo commands directory
        console: Rich Console instance
    """
    from sccs.command import Command

    console = console or Console()
    diff_gen = DiffGenerator(console)

    local_command_path = local_path / f"{command_name}.md"
    repo_command_path = repo_path / f"{command_name}.md"

    if not local_command_path.exists() and not repo_command_path.exists():
        console.print(f"[red]Command '{command_name}' not found in either location[/red]")
        return

    if not local_command_path.exists():
        console.print(f"[yellow]Command '{command_name}' only exists in repository[/yellow]")
        return

    if not repo_command_path.exists():
        console.print(f"[yellow]Command '{command_name}' only exists locally[/yellow]")
        return

    local = Command.from_file(local_command_path)
    repo = Command.from_file(repo_command_path)

    diff_gen.display_command_diff(local, repo)
