"""Rich console output for sync operations."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sccs.sync_engine import ActionType, ItemType, SyncAction, SyncResult

if TYPE_CHECKING:
    from sccs.command import Command
    from sccs.state import SyncState


class SyncLogger:
    """Rich console output for sync operations."""

    def __init__(self, console: Optional[Console] = None, verbose: bool = False):
        """Initialize logger.

        Args:
            console: Rich Console instance
            verbose: Enable verbose output
        """
        self.console = console or Console()
        self.verbose = verbose

    def info(self, message: str) -> None:
        """Blue info message."""
        self.console.print(f"[blue]ℹ[/blue] {message}")

    def success(self, message: str) -> None:
        """Green success message."""
        self.console.print(f"[green]✓[/green] {message}")

    def warning(self, message: str) -> None:
        """Yellow warning message."""
        self.console.print(f"[yellow]⚠[/yellow] {message}")

    def error(self, message: str) -> None:
        """Red error message."""
        self.console.print(f"[red]✗[/red] {message}")

    def action(self, action: SyncAction) -> None:
        """Display action with appropriate styling."""
        style_map = {
            ActionType.COPY_TO_REPO: ("green", "→ repo"),
            ActionType.COPY_TO_LOCAL: ("blue", "← local"),
            ActionType.NEW_LOCAL: ("green", "+ repo"),
            ActionType.NEW_REPO: ("blue", "+ local"),
            ActionType.CONFLICT: ("yellow", "⚠ conflict"),
            ActionType.DELETED_LOCAL: ("red", "✗ local"),
            ActionType.DELETED_REPO: ("red", "✗ repo"),
            ActionType.UNCHANGED: ("dim", "= unchanged"),
        }

        color, direction = style_map.get(action.action_type, ("white", "?"))

        # Format timestamps
        local_time = ""
        repo_time = ""
        if action.local_mtime:
            local_time = datetime.fromtimestamp(action.local_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        if action.repo_mtime:
            repo_time = datetime.fromtimestamp(action.repo_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

        # Build output
        text = Text()
        text.append(f"  [{direction:>12}] ", style=color)
        text.append(action.skill_name, style="cyan bold")

        if self.verbose and action.reason:
            text.append(f" - {action.reason}", style="dim")

        if self.verbose and (local_time or repo_time):
            times = []
            if local_time:
                times.append(f"local: {local_time}")
            if repo_time:
                times.append(f"repo: {repo_time}")
            text.append(f" ({', '.join(times)})", style="dim")

        self.console.print(text)

    def show_actions_table(self, actions: list[SyncAction], dry_run: bool = False) -> None:
        """Display actions in a table format."""
        if not actions:
            self.info("No changes detected")
            return

        title = "Planned Changes (dry-run)" if dry_run else "Changes to Apply"

        table = Table(title=title, show_header=True, header_style="bold")
        table.add_column("Type", style="magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Direction", justify="center")
        table.add_column("Action", style="dim")
        table.add_column("Reason")

        for action in actions:
            if action.action_type == ActionType.UNCHANGED:
                continue

            direction = action.get_direction_arrow()
            action_name = action.action_type.value.replace("_", " ")
            item_type = action.get_item_type_label()

            # Color coding
            if action.action_type in (ActionType.COPY_TO_REPO, ActionType.NEW_LOCAL):
                direction_style = "[green]" + direction + "[/green]"
            elif action.action_type in (ActionType.COPY_TO_LOCAL, ActionType.NEW_REPO):
                direction_style = "[blue]" + direction + "[/blue]"
            elif action.action_type == ActionType.CONFLICT:
                direction_style = "[yellow]" + direction + "[/yellow]"
            else:
                direction_style = "[red]" + direction + "[/red]"

            table.add_row(item_type, action.skill_name, direction_style, action_name, action.reason)

        self.console.print()
        self.console.print(table)
        self.console.print()

    def summary(self, result: SyncResult) -> None:
        """Display final sync summary."""
        if result.success:
            status = "[green]✓ Sync completed successfully[/green]"
        else:
            status = "[red]✗ Sync completed with errors[/red]"

        summary_text = f"""
{status}

[bold]Summary:[/bold]
  • Total synced: [cyan]{result.total_synced}[/cyan]
  • Local → Repo: [green]{result.to_repo_count}[/green]
  • Repo → Local: [blue]{result.to_local_count}[/blue]
  • Skipped: [dim]{len(result.actions_skipped)}[/dim]
"""

        if result.errors:
            summary_text += "\n[red]Errors:[/red]\n"
            for err in result.errors:
                summary_text += f"  • {err}\n"

        panel = Panel(summary_text.strip(), title="Sync Result", border_style="green" if result.success else "red")
        self.console.print(panel)

    def show_status(self, local_skills: dict, repo_skills: dict, state: "SyncState") -> None:
        """Display current skill sync status."""
        all_names = sorted(set(local_skills.keys()) | set(repo_skills.keys()))

        if not all_names:
            self.info("No skills found")
            return

        table = Table(title="Skills Status", show_header=True, header_style="bold")
        table.add_column("Skill", style="cyan")
        table.add_column("Local", justify="center")
        table.add_column("Repo", justify="center")
        table.add_column("Last Sync")

        for name in all_names:
            local = "✓" if name in local_skills else "✗"
            repo = "✓" if name in repo_skills else "✗"

            local_style = "[green]" if name in local_skills else "[red]"
            repo_style = "[green]" if name in repo_skills else "[red]"

            skill_state = state.get_skill_state(name)
            last_sync = skill_state.last_sync[:10] if skill_state else "Never"

            table.add_row(name, f"{local_style}{local}[/]", f"{repo_style}{repo}[/]", last_sync)

        self.console.print()
        self.console.print(table)
        self.console.print()

    def show_commands_status(self, local_commands: dict, repo_commands: dict, state: "SyncState") -> None:
        """Display current command sync status."""
        all_names = sorted(set(local_commands.keys()) | set(repo_commands.keys()))

        if not all_names:
            self.info("No commands found")
            return

        table = Table(title="Commands Status", show_header=True, header_style="bold")
        table.add_column("Command", style="cyan")
        table.add_column("Local", justify="center")
        table.add_column("Repo", justify="center")
        table.add_column("Last Sync")

        for name in all_names:
            local = "✓" if name in local_commands else "✗"
            repo = "✓" if name in repo_commands else "✗"

            local_style = "[green]" if name in local_commands else "[red]"
            repo_style = "[green]" if name in repo_commands else "[red]"

            command_state = state.get_command_state(name)
            last_sync = command_state.last_sync[:10] if command_state else "Never"

            table.add_row(name, f"{local_style}{local}[/]", f"{repo_style}{repo}[/]", last_sync)

        self.console.print()
        self.console.print(table)
        self.console.print()
