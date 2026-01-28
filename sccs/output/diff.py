# SCCS Diff Display
# Diff generation and display for sync items

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from sccs.sync.actions import SyncAction
from sccs.sync.item import SyncItem


@dataclass
class DiffResult:
    """Result of a diff operation."""

    item_name: str
    has_diff: bool
    local_exists: bool
    repo_exists: bool
    local_content: Optional[str] = None
    repo_content: Optional[str] = None
    diff_lines: list[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.diff_lines is None:
            self.diff_lines = []


def read_content(path: Path) -> Optional[str]:
    """
    Read content from a file.

    Args:
        path: Path to file.

    Returns:
        Content string or None if unreadable.
    """
    if not path.exists():
        return None

    try:
        # Handle directories by reading a marker file or returning placeholder
        if path.is_dir():
            # For directories, try to read a common marker file
            for marker in ["SKILL.md", "README.md", "index.md"]:
                marker_path = path / marker
                if marker_path.exists():
                    return marker_path.read_text(encoding="utf-8")
            return f"[Directory: {path.name}]"

        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "[Binary file]"
    except Exception as e:
        return f"[Error reading: {e}]"


def generate_diff(
    local_content: Optional[str],
    repo_content: Optional[str],
    *,
    context_lines: int = 3,
) -> list[str]:
    """
    Generate unified diff between two contents.

    Args:
        local_content: Local file content.
        repo_content: Repository file content.
        context_lines: Number of context lines.

    Returns:
        List of diff lines.
    """
    local_lines = (local_content or "").splitlines(keepends=True)
    repo_lines = (repo_content or "").splitlines(keepends=True)

    diff = difflib.unified_diff(
        repo_lines,
        local_lines,
        fromfile="repo",
        tofile="local",
        lineterm="",
        n=context_lines,
    )

    return list(diff)


def show_diff(
    item: SyncItem,
    *,
    console: Optional[RichConsole] = None,
    context_lines: int = 3,
) -> DiffResult:
    """
    Show diff for a sync item.

    Args:
        item: Sync item to diff.
        console: Optional Rich console for output.
        context_lines: Number of context lines.

    Returns:
        DiffResult with diff information.
    """
    if console is None:
        console = RichConsole()

    result = DiffResult(
        item_name=item.name,
        has_diff=False,
        local_exists=item.exists_local,
        repo_exists=item.exists_repo,
    )

    # Read content
    if item.local_path:
        result.local_content = read_content(item.local_path)
    if item.repo_path:
        result.repo_content = read_content(item.repo_path)

    # Handle cases where only one exists
    if not result.local_exists and not result.repo_exists:
        result.error = "Item doesn't exist in either location"
        console.print(f"[red]{result.error}[/red]")
        return result

    if not result.local_exists:
        result.has_diff = True
        console.print(
            Panel(
                f"[cyan]Only in repo:[/cyan] {item.name}\n\n" f"{result.repo_content or '[Empty]'}",
                title=f"Diff: {item.name}",
                border_style="cyan",
            )
        )
        return result

    if not result.repo_exists:
        result.has_diff = True
        console.print(
            Panel(
                f"[yellow]Only in local:[/yellow] {item.name}\n\n" f"{result.local_content or '[Empty]'}",
                title=f"Diff: {item.name}",
                border_style="yellow",
            )
        )
        return result

    # Generate diff
    result.diff_lines = generate_diff(
        result.local_content,
        result.repo_content,
        context_lines=context_lines,
    )

    result.has_diff = len(result.diff_lines) > 0

    if not result.has_diff:
        console.print(f"[green]No differences:[/green] {item.name}")
        return result

    # Display diff with syntax highlighting
    diff_text = "\n".join(result.diff_lines)

    console.print(
        Panel(
            Syntax(diff_text, "diff", theme="monokai", line_numbers=True),
            title=f"Diff: {item.name}",
            border_style="yellow",
        )
    )

    return result


def show_conflict(
    action: SyncAction,
    *,
    console: Optional[RichConsole] = None,
) -> Optional[str]:
    """
    Show conflict details and prompt for resolution.

    Args:
        action: Conflict action.
        console: Optional Rich console for output.

    Returns:
        Resolution choice: "local", "repo", "skip", or None if cancelled.
    """
    if console is None:
        console = RichConsole()

    item = action.item

    console.print()
    console.print(
        Panel(
            f"[red bold]Conflict:[/red bold] {item.name}\n"
            f"Both local and repository have changes.\n\n"
            f"[bold]Reason:[/bold] {action.reason}",
            title="Conflict Detected",
            border_style="red",
        )
    )

    # Show diff
    show_diff(item, console=console)

    # Prompt for resolution
    console.print()
    console.print("[bold]Resolution options:[/bold]")
    console.print("  [yellow]l[/yellow] - Use local version (overwrite repo)")
    console.print("  [cyan]r[/cyan] - Use repo version (overwrite local)")
    console.print("  [green]m[/green] - Interactive merge (hunk-by-hunk)")
    console.print("  [magenta]e[/magenta] - Open in external editor")
    console.print("  [blue]d[/blue] - Show diff again")
    console.print("  [dim]s[/dim] - Skip this item")
    console.print("  [dim]q[/dim] - Quit/Cancel")
    console.print()

    while True:
        choice = console.input("[bold]Choose [l/r/m/e/d/s/q]:[/bold] ").strip().lower()

        if choice in ("l", "local"):
            return "local"
        elif choice in ("r", "repo"):
            return "repo"
        elif choice in ("m", "merge"):
            return "merge"
        elif choice in ("e", "editor", "edit"):
            return "editor"
        elif choice in ("d", "diff"):
            return "diff"
        elif choice in ("s", "skip"):
            return "skip"
        elif choice in ("q", "quit", "cancel"):
            return None
        else:
            console.print("[red]Invalid choice. Please enter l, r, m, e, d, s, or q.[/red]")


def format_diff_summary(result: DiffResult) -> str:
    """
    Format a brief diff summary.

    Args:
        result: Diff result.

    Returns:
        Summary string.
    """
    if result.error:
        return f"Error: {result.error}"

    if not result.has_diff:
        return "No differences"

    if not result.local_exists:
        return "Only in repo"

    if not result.repo_exists:
        return "Only in local"

    # Count additions and deletions
    additions = sum(1 for line in result.diff_lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in result.diff_lines if line.startswith("-") and not line.startswith("---"))

    parts = []
    if additions > 0:
        parts.append(f"+{additions}")
    if deletions > 0:
        parts.append(f"-{deletions}")

    return ", ".join(parts) if parts else "Changed"
