# SCCS Console Output
# Rich-based console output for user-friendly display

from pathlib import Path
from typing import Optional

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from sccs.sync.actions import ActionType, SyncAction
from sccs.sync.category import CategoryStatus, CategorySyncResult
from sccs.sync.engine import SyncResult
from sccs.sync.settings import SettingsEnsureResult


class Console:
    """
    Console output manager using Rich.

    Provides formatted output for sync operations.
    """

    def __init__(self, *, verbose: bool = False, colored: bool = True):
        """
        Initialize console.

        Args:
            verbose: Enable verbose output.
            colored: Enable colored output.
        """
        self.verbose = verbose
        self._console = RichConsole(force_terminal=colored, no_color=not colored)

    def print(self, *args, **kwargs) -> None:
        """Print to console."""
        self._console.print(*args, **kwargs)

    def print_error(self, message: str) -> None:
        """Print error message."""
        self._console.print(f"[red]Error:[/red] {message}")

    def print_warning(self, message: str) -> None:
        """Print warning message."""
        self._console.print(f"[yellow]Warning:[/yellow] {message}")

    def print_success(self, message: str) -> None:
        """Print success message."""
        self._console.print(f"[green]{message}[/green]")

    def print_info(self, message: str) -> None:
        """Print info message."""
        self._console.print(f"[blue]{message}[/blue]")

    def print_status(self, statuses: dict[str, CategoryStatus]) -> None:
        """
        Print status for multiple categories.

        Args:
            statuses: Dict of category name to status.
        """
        if not statuses:
            self._console.print("[dim]No categories to display[/dim]")
            return

        for name, status in statuses.items():
            self._print_category_status(name, status)

    def _print_category_status(self, name: str, status: CategoryStatus) -> None:
        """Print status for a single category."""
        # Category header with optional platform info
        enabled_marker = "[green]●[/green]" if status.enabled else "[dim]○[/dim]"
        platform_info = ""
        if status.platforms:
            platform_info = f" [dim]({', '.join(status.platforms)})[/dim]"
        self._console.print(f"\n{enabled_marker} [bold]{name}[/bold]{platform_info}")

        if not status.enabled:
            self._console.print("  [dim]Disabled[/dim]")
            return

        if status.total_items == 0:
            self._console.print("  [dim]No items found[/dim]")
            return

        # Summary line
        parts = []
        if status.unchanged > 0:
            parts.append(f"[green]{status.unchanged} unchanged[/green]")
        if status.to_sync > 0:
            parts.append(f"[yellow]{status.to_sync} to sync[/yellow]")
        if status.conflicts > 0:
            parts.append(f"[red]{status.conflicts} conflicts[/red]")
        if status.errors > 0:
            parts.append(f"[red]{status.errors} errors[/red]")

        summary = ", ".join(parts) if parts else "[dim]no changes[/dim]"
        self._console.print(f"  {status.total_items} items: {summary}")

        # Detailed list if verbose or has changes
        if self.verbose or status.has_changes:
            self._print_action_details(status)

    def _print_action_details(self, status: CategoryStatus) -> None:
        """Print detailed action list."""
        for action in status.actions:
            if action.action_type == ActionType.UNCHANGED and not self.verbose:
                continue

            icon = self._get_action_icon(action.action_type)
            item_name = action.item.name

            if action.action_type == ActionType.CONFLICT:
                self._console.print(f"    {icon} [red]{item_name}[/red] - {action.reason}")
            elif action.action_type in (ActionType.COPY_TO_REPO, ActionType.NEW_LOCAL):
                self._console.print(f"    {icon} [yellow]{item_name}[/yellow] → repo")
            elif action.action_type in (ActionType.COPY_TO_LOCAL, ActionType.NEW_REPO):
                self._console.print(f"    {icon} [cyan]{item_name}[/cyan] ← repo")
            elif action.action_type == ActionType.UNCHANGED:
                self._console.print(f"    {icon} [dim]{item_name}[/dim]")
            elif action.action_type == ActionType.SKIP:
                self._console.print(f"    {icon} [dim]{item_name} (skipped)[/dim]")
            elif action.action_type in (ActionType.DELETED_LOCAL, ActionType.DELETED_REPO):
                self._console.print(f"    {icon} [red]{item_name}[/red] (deleted)")

    def _get_action_icon(self, action_type: ActionType) -> str:
        """Get icon for action type."""
        icons = {
            ActionType.UNCHANGED: "[green]✓[/green]",
            ActionType.COPY_TO_REPO: "[yellow]↑[/yellow]",
            ActionType.COPY_TO_LOCAL: "[cyan]↓[/cyan]",
            ActionType.NEW_LOCAL: "[yellow]+[/yellow]",
            ActionType.NEW_REPO: "[cyan]+[/cyan]",
            ActionType.DELETED_LOCAL: "[red]×[/red]",
            ActionType.DELETED_REPO: "[red]×[/red]",
            ActionType.CONFLICT: "[red]![/red]",
            ActionType.SKIP: "[dim]○[/dim]",
            ActionType.ERROR: "[red]✗[/red]",
        }
        return icons.get(action_type, "?")

    def print_sync_result(self, result: SyncResult, *, dry_run: bool = False) -> None:
        """
        Print sync result summary.

        Args:
            result: Sync result to display.
            dry_run: Whether this was a dry run (changes wording).
        """
        self._console.print()

        # Per-category results
        for name, cat_result in result.category_results.items():
            self._print_category_result(name, cat_result, dry_run=dry_run)

        # Overall summary
        self._console.print()

        # Choose wording based on dry_run
        sync_verb = "would sync" if dry_run else "synced"
        status_text = "Dry run completed" if dry_run else "Sync completed"

        if result.success:
            self._console.print(
                Panel(
                    f"[green]{status_text}[/green]\n"
                    f"Categories: {result.synced_categories}/{result.total_categories}\n"
                    f"Items: {result.synced_items} {sync_verb}, {result.conflicts} conflicts, {result.errors} errors",
                    title="Summary",
                    border_style="green" if not result.has_issues else "yellow",
                )
            )
        else:
            self._console.print(
                Panel(
                    f"[red]{status_text} with errors[/red]\n"
                    f"Categories: {result.synced_categories}/{result.total_categories}\n"
                    f"Items: {result.synced_items} {sync_verb}, {result.conflicts} conflicts, {result.errors} errors",
                    title="Summary",
                    border_style="red",
                )
            )

    def _print_category_result(self, name: str, result: CategorySyncResult, *, dry_run: bool = False) -> None:
        """Print result for a single category."""
        sync_verb = "would sync" if dry_run else "synced"

        if result.success and result.synced == 0 and result.conflicts == 0:
            self._console.print(f"[green]✓[/green] [bold]{name}[/bold] - no changes")
            return

        if result.success:
            self._console.print(f"[green]✓[/green] [bold]{name}[/bold] - {result.synced} {sync_verb}")
        else:
            self._console.print(
                f"[red]✗[/red] [bold]{name}[/bold] - {result.synced} {sync_verb}, {result.errors} errors"
            )

        # Show details if verbose or has issues
        if self.verbose or result.errors > 0 or result.conflicts > 0:
            for action_result in result.results:
                action = action_result.action
                if action_result.success:
                    self._console.print(f"    [green]✓[/green] {action.item.name}")
                else:
                    self._console.print(f"    [red]✗[/red] {action.item.name}: {action_result.error}")
                    # Add resolution hints for common errors
                    if "Conflict" in (action_result.error or ""):
                        self._console.print(f"        [dim]→ View diff: sccs diff {action.item.name} -c {name}[/dim]")
                        self._console.print(f"        [dim]→ Keep local: sccs sync -c {name} --force local[/dim]")
                        self._console.print(f"        [dim]→ Keep repo:  sccs sync -c {name} --force repo[/dim]")

        # Print settings ensure result if present
        if result.settings_result is not None:
            self._print_settings_ensure_result(result.settings_result, dry_run=dry_run)

    def _print_settings_ensure_result(self, result: SettingsEnsureResult, *, dry_run: bool = False) -> None:
        """Print settings ensure result details."""
        target = Path(result.target_file).name

        if result.error:
            self._console.print(f"    [red]✗[/red] {target}: {result.error}")
            return

        verb_add = "would add" if dry_run else "added"
        verb_create = "would create" if dry_run else "created"

        for key in result.keys_added:
            suffix = f" ({verb_create})" if result.file_created else ""
            self._console.print(f"    [green]✓[/green] {target}: {verb_add} [{key}]{suffix}")

        if self.verbose:
            for key in result.keys_skipped:
                self._console.print(f"    [dim]○[/dim] {target}: skipped [{key}] (already exists)")

    def print_categories_list(
        self,
        categories: dict[str, dict],
        *,
        show_all: bool = False,
    ) -> None:
        """
        Print list of categories.

        Args:
            categories: Dict of category name to info dict with keys:
                        enabled (bool), description (str), platforms (Optional[list[str]]).
            show_all: Show all categories including disabled.
        """
        table = Table(show_header=True, header_style="bold")
        table.add_column("Category")
        table.add_column("Status")
        table.add_column("Platforms", style="dim")
        table.add_column("Description", style="dim")

        for name, info in sorted(categories.items()):
            enabled = info.get("enabled", False)
            if not show_all and not enabled:
                continue

            status = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
            platforms = ", ".join(info.get("platforms") or []) or "all"
            description = info.get("description", "")
            table.add_row(name, status, platforms, description)

        self._console.print(table)

    def print_config_summary(self, config_path: str, categories_count: int) -> None:
        """Print configuration summary."""
        self._console.print(
            Panel(
                f"Config: {config_path}\n" f"Categories: {categories_count}",
                title="SCCS Configuration",
                border_style="blue",
            )
        )

    def confirm(self, message: str, default: bool = False) -> bool:
        """
        Ask for confirmation.

        Args:
            message: Confirmation message.
            default: Default value if user just presses enter.

        Returns:
            True if confirmed.
        """
        suffix = " [Y/n]" if default else " [y/N]"
        response = self._console.input(f"{message}{suffix}: ").strip().lower()

        if not response:
            return default

        return response in ("y", "yes", "j", "ja")

    def resolve_conflict(self, action: SyncAction, category_name: str) -> str:
        """
        Interactive menu to resolve a conflict.

        Args:
            action: The conflicting action.
            category_name: Category name for context.

        Returns:
            Resolution choice: "local", "repo", "diff", "merge", "editor", "skip", or "abort"
        """
        item_name = action.item.name

        self._console.print(f"\n[bold red]Conflict detected:[/bold red] {category_name}/{item_name}")
        self._console.print(f"  Both local and repository versions have changed.\n")

        self._console.print("[bold]Options:[/bold]")
        self._console.print("  [cyan]1[/cyan] - Keep [bold]local[/bold] version (overwrite repo)")
        self._console.print("  [cyan]2[/cyan] - Keep [bold]repo[/bold] version (overwrite local)")
        self._console.print("  [cyan]3[/cyan] - View [bold]diff[/bold] first")
        self._console.print("  [cyan]4[/cyan] - [bold]Interactive merge[/bold] (hunk-by-hunk)")
        self._console.print("  [cyan]5[/cyan] - Open in [bold]external editor[/bold]")
        self._console.print("  [cyan]6[/cyan] - [bold]Skip[/bold] this item")
        self._console.print("  [cyan]7[/cyan] - [bold]Abort[/bold] sync")

        while True:
            choice = self._console.input("\nYour choice [1-7]: ").strip()

            if choice == "1":
                return "local"
            elif choice == "2":
                return "repo"
            elif choice == "3":
                return "diff"
            elif choice == "4":
                return "merge"
            elif choice == "5":
                return "editor"
            elif choice == "6":
                return "skip"
            elif choice == "7":
                return "abort"
            else:
                self._console.print("[yellow]Please enter 1, 2, 3, 4, or 5, 6, or 7[/yellow]")


def create_console(*, verbose: bool = False, colored: bool = True) -> Console:
    """
    Create a console instance.

    Args:
        verbose: Enable verbose output.
        colored: Enable colored output.

    Returns:
        Console instance.
    """
    return Console(verbose=verbose, colored=colored)
