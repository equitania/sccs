# SCCS Interactive Merge
# Hunk-by-hunk conflict resolution with syntax highlighting

import difflib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from sccs.sync.actions import SyncAction
from sccs.utils.paths import atomic_write, create_backup


@dataclass
class DiffHunk:
    """A single hunk of differences between two files."""

    tag: str  # 'equal', 'replace', 'insert', 'delete'
    local_lines: list[str]
    repo_lines: list[str]
    local_start: int
    local_end: int
    repo_start: int
    repo_end: int

    @property
    def is_equal(self) -> bool:
        return self.tag == "equal"

    @property
    def is_addition(self) -> bool:
        return self.tag == "insert"

    @property
    def is_deletion(self) -> bool:
        return self.tag == "delete"

    @property
    def is_modification(self) -> bool:
        return self.tag == "replace"

    @property
    def is_change(self) -> bool:
        return not self.is_equal


@dataclass
class MergeResult:
    """Result of an interactive merge operation."""

    merged_content: str = ""
    hunks_total: int = 0
    hunks_local: int = 0
    hunks_repo: int = 0
    hunks_both: int = 0
    hunks_edited: int = 0
    aborted: bool = False

    @property
    def is_complete(self) -> bool:
        return not self.aborted and bool(self.merged_content)


def _detect_syntax(path: str) -> str:
    """
    Detect syntax type from file extension.

    Args:
        path: File path or name.

    Returns:
        Syntax identifier for Rich: "fish", "markdown", "yaml", "python", "text".
    """
    ext = Path(path).suffix.lower()
    syntax_map = {
        ".fish": "bash",  # Rich doesn't have fish, bash is close
        ".md": "markdown",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".py": "python",
        ".sh": "bash",
        ".json": "json",
        ".toml": "toml",
    }
    return syntax_map.get(ext, "text")


def split_into_hunks(
    local_content: str,
    repo_content: str,
) -> list[DiffHunk]:
    """
    Split two file contents into hunks using SequenceMatcher.

    Args:
        local_content: Local file content.
        repo_content: Repository file content.

    Returns:
        List of DiffHunk objects. Equal hunks are included for context.
    """
    local_lines = local_content.splitlines(keepends=True)
    repo_lines = repo_content.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, repo_lines, local_lines)
    hunks: list[DiffHunk] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        hunk = DiffHunk(
            tag=tag,
            repo_lines=repo_lines[i1:i2],
            local_lines=local_lines[j1:j2],
            repo_start=i1,
            repo_end=i2,
            local_start=j1,
            local_end=j2,
        )
        hunks.append(hunk)

    return hunks


def show_hunk(
    hunk: DiffHunk,
    index: int,
    total: int,
    console: RichConsole,
    *,
    syntax: str = "text",
) -> None:
    """
    Display a single hunk with syntax highlighting.

    Args:
        hunk: The diff hunk to display.
        index: Current hunk index (1-based).
        total: Total number of change hunks.
        console: Rich console for output.
        syntax: Syntax identifier for highlighting.
    """
    title = f"Hunk {index}/{total}"

    if hunk.is_modification:
        title += " [yellow](modified)[/yellow]"
    elif hunk.is_addition:
        title += " [green](added in local)[/green]"
    elif hunk.is_deletion:
        title += " [red](removed in local)[/red]"

    # Build diff display
    diff_lines = []
    for line in hunk.repo_lines:
        diff_lines.append(f"- {line.rstrip()}")
    for line in hunk.local_lines:
        diff_lines.append(f"+ {line.rstrip()}")

    diff_text = "\n".join(diff_lines)

    console.print(
        Panel(
            Syntax(diff_text, "diff", theme="monokai"),
            title=title,
            border_style="yellow",
        )
    )


def prompt_hunk_resolution(console: RichConsole) -> str:
    """
    Prompt user for hunk resolution choice.

    Args:
        console: Rich console for I/O.

    Returns:
        One of: "local", "repo", "both", "edit", "skip".
    """
    console.print("[bold]Choose:[/bold]")
    console.print("  [yellow]l[/yellow] - Use [bold]local[/bold] version")
    console.print("  [cyan]r[/cyan] - Use [bold]repo[/bold] version")
    console.print("  [green]b[/green] - Keep [bold]both[/bold] (repo first, then local)")
    console.print("  [magenta]e[/magenta] - [bold]Edit[/bold] manually")
    console.print("  [dim]s[/dim] - [bold]Skip[/bold] (keep repo version)")

    while True:
        choice = console.input("[bold]Choice [l/r/b/e/s]: [/bold]").strip().lower()

        if choice in ("l", "local"):
            return "local"
        elif choice in ("r", "repo"):
            return "repo"
        elif choice in ("b", "both"):
            return "both"
        elif choice in ("e", "edit"):
            return "edit"
        elif choice in ("s", "skip"):
            return "skip"
        else:
            console.print("[red]Invalid choice. Please enter l, r, b, e, or s.[/red]")


def edit_in_editor(content: str, suffix: str = ".txt") -> Optional[str]:
    """
    Open content in external editor for manual editing.

    Args:
        content: Content to edit.
        suffix: File suffix for syntax detection.

    Returns:
        Edited content, or None if editor failed or content unchanged.
    """
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))
    if not editor:
        # Try common editors
        for candidate in ["nano", "vim", "vi"]:
            try:
                subprocess.run(["which", candidate], capture_output=True, check=True)
                editor = candidate
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

    if not editor:
        return None

    try:
        fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix="sccs_merge_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)

        result = subprocess.run([editor, temp_path])

        if result.returncode != 0:
            return None

        with open(temp_path, "r", encoding="utf-8") as f:
            edited = f.read()

        return edited
    except Exception:
        return None
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _show_file_metadata(
    action: SyncAction,
    console: RichConsole,
) -> None:
    """
    Show metadata comparison for conflicting files.

    Args:
        action: The sync action with conflict.
        console: Rich console for output.
    """
    item = action.item
    table = Table(title="File Comparison", show_header=True, header_style="bold")
    table.add_column("Property")
    table.add_column("Local", style="yellow")
    table.add_column("Repo", style="cyan")

    # Size
    local_size = "N/A"
    repo_size = "N/A"
    if item.local_path and item.local_path.exists() and item.local_path.is_file():
        local_size = f"{item.local_path.stat().st_size:,} bytes"
    if item.repo_path and item.repo_path.exists() and item.repo_path.is_file():
        repo_size = f"{item.repo_path.stat().st_size:,} bytes"
    table.add_row("Size", local_size, repo_size)

    # Modification time
    local_mtime = "N/A"
    repo_mtime = "N/A"
    local_ts = 0.0
    repo_ts = 0.0
    if item.local_path and item.local_path.exists():
        local_ts = item.local_path.stat().st_mtime
        from datetime import datetime

        local_mtime = datetime.fromtimestamp(local_ts).strftime("%Y-%m-%d %H:%M:%S")
    if item.repo_path and item.repo_path.exists():
        repo_ts = item.repo_path.stat().st_mtime
        from datetime import datetime

        repo_mtime = datetime.fromtimestamp(repo_ts).strftime("%Y-%m-%d %H:%M:%S")
    table.add_row("Modified", local_mtime, repo_mtime)

    # Newer indicator
    if local_ts > 0 and repo_ts > 0:
        if local_ts > repo_ts:
            table.add_row("Newer", "[bold yellow]◄ LOCAL[/bold yellow]", "")
        elif repo_ts > local_ts:
            table.add_row("Newer", "", "[bold cyan]REPO ►[/bold cyan]")
        else:
            table.add_row("Newer", "[dim]same time[/dim]", "[dim]same time[/dim]")

    console.print(table)


def interactive_merge(
    action: SyncAction,
    console: RichConsole,
) -> MergeResult:
    """
    Perform interactive hunk-by-hunk merge for a conflict.

    Args:
        action: The conflicting sync action.
        console: Rich console for I/O.

    Returns:
        MergeResult with merged content and statistics.
    """
    item = action.item
    result = MergeResult()

    # Read contents
    local_content = ""
    repo_content = ""

    if item.local_path and item.local_path.exists():
        try:
            local_content = item.local_path.read_text(encoding="utf-8")
        except Exception as e:
            console.print(f"[red]Error reading local file: {e}[/red]")
            result.aborted = True
            return result

    if item.repo_path and item.repo_path.exists():
        try:
            repo_content = item.repo_path.read_text(encoding="utf-8")
        except Exception as e:
            console.print(f"[red]Error reading repo file: {e}[/red]")
            result.aborted = True
            return result

    # Show metadata
    _show_file_metadata(action, console)
    console.print()

    # Split into hunks
    hunks = split_into_hunks(local_content, repo_content)
    change_hunks = [h for h in hunks if h.is_change]
    result.hunks_total = len(change_hunks)

    if not change_hunks:
        console.print("[green]No differences found.[/green]")
        result.merged_content = local_content
        return result

    console.print(f"\n[bold]{len(change_hunks)} change(s) found.[/bold]\n")

    # Detect syntax for highlighting
    syntax = _detect_syntax(item.name)

    # Build merged content
    merged_lines: list[str] = []
    change_index = 0

    for hunk in hunks:
        if hunk.is_equal:
            merged_lines.extend(hunk.local_lines)
            continue

        change_index += 1

        # Show hunk
        show_hunk(hunk, change_index, len(change_hunks), console, syntax=syntax)

        # Prompt for resolution
        choice = prompt_hunk_resolution(console)

        if choice == "local":
            merged_lines.extend(hunk.local_lines)
            result.hunks_local += 1
        elif choice == "repo":
            merged_lines.extend(hunk.repo_lines)
            result.hunks_repo += 1
        elif choice == "both":
            merged_lines.extend(hunk.repo_lines)
            merged_lines.extend(hunk.local_lines)
            result.hunks_both += 1
        elif choice == "edit":
            # Prepare content for editor
            edit_content = "".join(hunk.local_lines)
            edited = edit_in_editor(edit_content, suffix=Path(item.name).suffix)
            if edited is not None:
                merged_lines.extend(edited.splitlines(keepends=True))
                result.hunks_edited += 1
            else:
                console.print("[yellow]Editor failed, keeping local version.[/yellow]")
                merged_lines.extend(hunk.local_lines)
                result.hunks_local += 1
        elif choice == "skip":
            merged_lines.extend(hunk.repo_lines)
            result.hunks_repo += 1

        console.print()

    result.merged_content = "".join(merged_lines)

    # Show preview
    console.print(
        Panel(
            Syntax(result.merged_content, syntax, theme="monokai", line_numbers=True),
            title="Merge Result Preview",
            border_style="green",
        )
    )

    # Confirm
    confirm = console.input("\n[bold]Accept merge result? [Y/n]: [/bold]").strip().lower()
    if confirm in ("n", "no", "nein"):
        result.aborted = True
        console.print("[yellow]Merge aborted.[/yellow]")
        return result

    # Create backup and write
    if item.local_path:
        create_backup(item.local_path, category="merge")
        atomic_write(item.local_path, result.merged_content)
        console.print(f"[green]Merged content written to local: {item.local_path}[/green]")

    if item.repo_path:
        create_backup(item.repo_path, category="merge")
        atomic_write(item.repo_path, result.merged_content)
        console.print(f"[green]Merged content written to repo: {item.repo_path}[/green]")

    return result
