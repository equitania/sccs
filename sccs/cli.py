# SCCS CLI
# Command-line interface using Click

import sys
from pathlib import Path

import click

from sccs import __version__
from sccs.config import (
    ensure_config_exists,
    generate_default_config,
    get_config_path,
    load_config,
    update_category_enabled,
    validate_config_file,
)
from sccs.git import commit, get_remote_status, has_uncommitted_changes, pull, push, stage_all
from sccs.output import Console, show_diff
from sccs.output.merge import edit_in_editor, interactive_merge
from sccs.sync import SyncEngine
from sccs.sync.actions import SyncAction
from sccs.sync.state import StateManager

# Global console instance
_console: Console | None = None


def get_console() -> Console:
    """Get or create console instance."""
    global _console
    if _console is None:
        _console = Console()
    return _console


def set_console(console: Console) -> None:
    """Set console instance."""
    global _console
    _console = console


@click.group(epilog="Use 'sccs <command> --help' for detailed options of each command.")
@click.version_option(version=__version__, prog_name="sccs")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, no_color: bool) -> None:
    """SCCS - SkillsCommandsConfigsSync

    Bidirectional synchronization for Claude Code files.

    \b
    Workflows:
      Publisher (share your configs):
        sccs sync --commit --push    Sync, commit and push to remote
        sccs sync --dry-run          Preview what would change
        sccs sync -c skills --push   Push only skills category

    \b
      Subscriber (receive shared configs):
        sccs sync --pull             Pull latest and sync to local
        sccs sync --force repo       Overwrite local with repo version
        sccs sync -c skills --pull   Pull only skills category

    \b
    Quick start:
        sccs config init             Create configuration
        sccs status                  Show what's changed
        sccs categories list --all   List all available categories
    """
    ctx.ensure_object(dict)
    console = Console(verbose=verbose, colored=not no_color)
    set_console(console)
    ctx.obj["console"] = console
    ctx.obj["verbose"] = verbose


@cli.command()
@click.option("-c", "--category", help="Sync specific category only")
@click.option("-n", "--dry-run", is_flag=True, help="Preview changes without executing")
@click.option("-f", "--force", type=click.Choice(["local", "repo"]), help="Force sync direction")
@click.option("-i", "--interactive", is_flag=True, help="Interactive mode for conflict resolution")
@click.option("--commit", "do_commit", is_flag=True, help="Commit changes (overrides auto_commit=false)")
@click.option("--no-commit", is_flag=True, help="Skip commit (overrides auto_commit=true)")
@click.option("--push", "do_push", is_flag=True, help="Push after commit (overrides auto_push=false)")
@click.option("--no-push", is_flag=True, help="Skip push (overrides auto_push=true)")
@click.option("--pull", "do_pull", is_flag=True, help="Pull remote changes before sync")
@click.option("--no-pull-check", is_flag=True, help="Skip remote status check before sync")
@click.pass_context
def sync(
    ctx: click.Context,
    category: str | None,
    dry_run: bool,
    force: str | None,
    interactive: bool,
    do_commit: bool,
    no_commit: bool,
    do_push: bool,
    no_push: bool,
    do_pull: bool,
    no_pull_check: bool,
) -> None:
    """Synchronize files between local and repository.

    \b
    Compares local files (e.g. ~/.claude/skills) with the repo copy
    and syncs changes in the configured direction.

    \b
    Publish local changes:
        sccs sync --commit --push    Sync all, then commit and push
        sccs sync -c skills --push   Sync and push specific category
        sccs sync --dry-run          Preview changes before syncing

    \b
    Receive repo changes:
        sccs sync --pull             Pull remote first, then sync
        sccs sync --force repo       Force repo version to local

    \b
    Conflict handling:
        sccs sync -i                 Interactive conflict resolution
        sccs sync --force local      Keep local version on conflicts
        sccs sync --force repo       Keep repo version on conflicts
    """
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    repo_path = Path(config.repository.path).expanduser()

    # Check remote status before sync (unless skipped or dry-run)
    if not dry_run and not no_pull_check:
        remote_status = get_remote_status(repo_path)

        if "error" in remote_status:
            # Non-fatal: just warn and continue
            console.print_warning(f"Could not check remote status: {remote_status['error']}")
        elif remote_status.get("diverged"):
            # Diverged: require manual intervention
            ahead = remote_status.get("ahead", 0)
            behind = remote_status.get("behind", 0)
            console.print_error(f"Repository is diverged: {ahead} commit(s) ahead, {behind} commit(s) behind remote")
            console.print_info("Please merge or rebase manually before syncing")
            sys.exit(1)
        elif remote_status.get("behind", 0) > 0:
            behind = remote_status["behind"]
            console.print_warning(f"Repository is {behind} commit(s) behind remote")

            # Determine if we should auto-pull
            should_pull = do_pull or config.repository.auto_pull

            if should_pull:
                console.print_info("Pulling remote changes...")
                if pull(repo_path):
                    console.print_success("Pull successful")
                else:
                    console.print_error("Pull failed")
                    sys.exit(1)
            else:
                console.print_info("Use '--pull' flag or set 'auto_pull: true' in config")
                console.print_info("Or use '--no-pull-check' to skip this check")
                sys.exit(1)
        elif remote_status.get("up_to_date"):
            if ctx.obj.get("verbose"):
                console.print_info("Repository is up to date with remote")

    engine = SyncEngine(config)

    if dry_run:
        console.print_info("Dry run - no changes will be made")

    # Create conflict resolver if interactive mode
    conflict_resolver = None
    if interactive and not dry_run and not force:

        def conflict_resolver(action: SyncAction, category_name: str) -> str:
            """Interactive conflict resolution callback."""
            while True:
                resolution = console.resolve_conflict(action, category_name)
                if resolution == "diff":
                    # Show diff and ask again
                    show_diff(action.item, console=console._console)
                    continue
                elif resolution == "merge":
                    # Interactive hunk-by-hunk merge
                    merge_result = interactive_merge(action, console._console)
                    if merge_result.aborted:
                        continue  # Re-show menu
                    return "merged"
                elif resolution == "editor":
                    # Open in external editor
                    item = action.item
                    if item.local_path and item.local_path.exists():
                        content = item.local_path.read_text(encoding="utf-8")
                        suffix = item.local_path.suffix or ".txt"
                        edited = edit_in_editor(content, suffix=suffix)
                        if edited is not None:
                            from sccs.utils.paths import atomic_write, create_backup

                            create_backup(item.local_path, category="editor")
                            atomic_write(item.local_path, edited)
                            if item.repo_path:
                                create_backup(item.repo_path, category="editor")
                                atomic_write(item.repo_path, edited)
                            console.print_success(f"Editor changes saved for {item.name}")
                            return "merged"
                        else:
                            console.print_warning("Editor returned no changes")
                            continue
                    else:
                        console.print_error("No local file to edit")
                        continue
                return resolution  # type: ignore[no-any-return]

    # Perform sync
    result = engine.sync(
        category_name=category,
        dry_run=dry_run,
        force_direction=force,
        conflict_resolver=conflict_resolver,
    )

    # Display results
    console.print_sync_result(result, dry_run=dry_run)

    # Handle git operations
    if not dry_run and result.synced_items > 0:
        # Commit if: (auto_commit OR --commit) AND NOT --no-commit
        should_commit = (config.repository.auto_commit or do_commit) and not no_commit

        if should_commit and has_uncommitted_changes(repo_path):
            stage_all(repo_path)
            commit_msg = f"{config.repository.commit_prefix} Sync {result.synced_items} items"
            commit(commit_msg, repo_path)
            console.print_success(f"Committed: {commit_msg}")

            # Push if: (auto_push OR --push) AND NOT --no-push
            should_push = (config.repository.auto_push or do_push) and not no_push

            if should_push:
                if push(repo_path, remote=config.repository.remote):
                    console.print_success(f"Pushed to {config.repository.remote}")
                else:
                    console.print_warning("Push failed")

    if result.aborted:
        console.print_warning("Sync aborted by user")
        sys.exit(1)

    if result.conflicts > 0:
        console.print_warning(f"{result.conflicts} conflicts need manual resolution")
        console.print_info("Tip: Use 'sccs sync -i' for interactive conflict resolution")
        console.print_info("     Or use '--force local' / '--force repo' to resolve all at once")

    if result.errors > 0 and result.conflicts == 0:
        console.print_info("Tip: Run 'sccs sync -v' for more details on errors")

    sys.exit(0 if result.success else 1)


@cli.command()
@click.option("-c", "--category", help="Show status for specific category only")
@click.pass_context
def status(ctx: click.Context, category: str | None) -> None:
    """Show synchronization status.

    \b
    Displays which items have changed since last sync,
    including new, modified, and deleted items per category.

    \b
    Examples:
        sccs status                  All enabled categories
        sccs status -c skills        Only skills category
    """
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    engine = SyncEngine(config)
    statuses = engine.get_status(category_name=category)

    if not statuses:
        if category:
            console.print_error(f"Category '{category}' not found or not enabled")
        else:
            console.print_warning("No enabled categories found")
        sys.exit(1)

    console.print_status(statuses)


@cli.command()
@click.argument("item_name", required=False)
@click.option("-c", "--category", help="Category to show diffs for")
@click.pass_context
def diff(ctx: click.Context, item_name: str | None, category: str | None) -> None:
    """Show diff for items.

    \b
    Examples:
      sccs diff -c claude_skills           Show all diffs in category
      sccs diff my-skill -c claude_skills  Show diff for specific item
      sccs diff                            Show all diffs in all categories
    """
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    engine = SyncEngine(config)

    # Determine which categories to check
    if category:
        handler = engine.get_handler(category)
        if handler is None:
            console.print_error(f"Category '{category}' not found")
            sys.exit(1)
        categories_to_check = [(category, handler)]
    else:
        categories_to_check = []
        for name in engine.get_enabled_categories():
            handler = engine.get_handler(name)
            if handler is not None:
                categories_to_check.append((name, handler))

    if not categories_to_check:
        console.print_warning("No categories to check")
        sys.exit(1)

    diff_count = 0

    for cat_name, handler in categories_to_check:
        items = handler.scan_items()

        # Filter to specific item if provided
        if item_name:
            items = [i for i in items if i.name == item_name]
            if not items and category:
                console.print_error(f"Item '{item_name}' not found in category '{category}'")
                sys.exit(1)

        # Show diffs for items that have changes
        for item in items:
            if item.local_path and item.repo_path:
                # Check if there are actual differences
                if item.local_path.exists() and item.repo_path.exists():
                    local_content = item.local_path.read_text(encoding="utf-8") if item.local_path.is_file() else ""
                    repo_content = item.repo_path.read_text(encoding="utf-8") if item.repo_path.is_file() else ""
                    if local_content != repo_content:
                        console.print(f"\n[bold cyan]{cat_name}[/bold cyan] → [yellow]{item.name}[/yellow]")
                        show_diff(item, console=console._console)
                        diff_count += 1
                elif item.local_path.exists() or item.repo_path.exists():
                    # One side exists, the other doesn't
                    console.print(f"\n[bold cyan]{cat_name}[/bold cyan] → [yellow]{item.name}[/yellow]")
                    show_diff(item, console=console._console)
                    diff_count += 1

    if diff_count == 0:
        console.print_info("No differences found")


@cli.command()
@click.option("--last", type=int, default=10, help="Number of entries to show")
@click.pass_context
def log(ctx: click.Context, last: int) -> None:
    """Show sync history.

    \b
    Displays recently synced items with timestamps and actions.

    \b
    Examples:
        sccs log                     Show last 10 entries
        sccs log --last 20           Show last 20 entries
    """
    console = ctx.obj["console"]

    state_manager = StateManager()
    state = state_manager.state

    if not state.items:
        console.print_info("No sync history found")
        return

    console.print(f"\n[bold]Last sync:[/bold] {state.last_sync or 'Never'}")
    console.print(f"[bold]Total items:[/bold] {len(state.items)}")

    # Show recent items
    sorted_items = sorted(
        state.items.values(),
        key=lambda x: x.last_synced or "",
        reverse=True,
    )[:last]

    console.print("\n[bold]Recent items:[/bold]")
    for item in sorted_items:
        action = item.last_action or "unknown"
        console.print(f"  {item.category}:{item.name} - {action} ({item.last_synced})")


# Config subcommands
@cli.group()
def config() -> None:
    """Configuration management commands.

    \b
    Config file: ~/.config/sccs/config.yaml

    \b
    Key settings:
        repository.path          Path to your sync repository
        repository.auto_commit   Auto-commit after sync (default: false)
        repository.auto_push     Auto-push after commit (default: false)
        repository.auto_pull     Auto-pull before sync (default: false)
    """
    pass


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show current configuration."""
    console = ctx.obj["console"]
    config_path = get_config_path()

    if not config_path.exists():
        console.print_warning(f"Config file not found: {config_path}")
        console.print_info("Run 'sccs config init' to create one")
        return

    console.print(f"[bold]Config file:[/bold] {config_path}")

    try:
        cfg = load_config()
        console.print(f"\n[bold]Repository:[/bold] {cfg.repository.path}")
        console.print(f"[bold]Auto-commit:[/bold] {cfg.repository.auto_commit}")
        console.print(f"[bold]Auto-push:[/bold] {cfg.repository.auto_push}")

        enabled = cfg.get_enabled_categories()
        console.print(f"\n[bold]Enabled categories ({len(enabled)}):[/bold]")
        for name in sorted(enabled.keys()):
            cat = enabled[name]
            console.print(f"  [green]●[/green] {name}: {cat.description}")

        disabled = [n for n in cfg.sync_categories if n not in enabled]
        if disabled:
            console.print(f"\n[bold]Disabled categories ({len(disabled)}):[/bold]")
            for name in sorted(disabled):
                cat = cfg.sync_categories[name]
                console.print(f"  [dim]○[/dim] {name}: {cat.description}")

    except Exception as e:
        console.print_error(f"Error loading config: {e}")


@config.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing config")
@click.pass_context
def config_init(ctx: click.Context, force: bool) -> None:
    """Initialize configuration file."""
    console = ctx.obj["console"]
    config_path = get_config_path()

    if config_path.exists() and not force:
        console.print_warning(f"Config already exists: {config_path}")
        console.print_info("Use --force to overwrite")
        return

    # Interactive setup
    console.print("[bold]SCCS Configuration Setup[/bold]\n")

    # Repository path
    default_repo = "~/gitbase/sccs-sync"
    repo_path = click.prompt("Repository path", default=default_repo)

    # Generate config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    default_yaml = generate_default_config()

    # Update repo path in config
    default_yaml = default_yaml.replace(
        "path: ~/gitbase/sccs-sync",
        f"path: {repo_path}",
    )

    config_path.write_text(default_yaml, encoding="utf-8")
    console.print_success(f"Config created: {config_path}")

    # Ask about enabling/disabling categories
    console.print("\n[bold]Default category settings applied.[/bold]")
    console.print("Edit the config file to customize enabled categories.")


@config.command("edit")
@click.pass_context
def config_edit(ctx: click.Context) -> None:
    """Open configuration in editor."""
    import os
    import shutil
    import subprocess

    config_path = get_config_path()
    console = ctx.obj["console"]

    if not config_path.exists():
        console.print_warning("Config file not found. Creating default...")
        ensure_config_exists()

    editor = os.environ.get("EDITOR", "nano")

    if not shutil.which(editor):
        console.print_error(f"Editor not found: {editor}")
        console.print_info(f"Set EDITOR environment variable or open manually: {config_path}")
        return

    try:
        subprocess.run([editor, str(config_path)], check=True)
    except FileNotFoundError:
        console.print_error(f"Editor not found: {editor}")
        console.print_info(f"Set EDITOR environment variable or open manually: {config_path}")


@config.command("validate")
@click.pass_context
def config_validate(ctx: click.Context) -> None:
    """Validate configuration file."""
    console = ctx.obj["console"]

    is_valid, errors = validate_config_file()

    if is_valid:
        console.print_success("Configuration is valid")
    else:
        console.print_error("Configuration has errors:")
        for error in errors:
            console.print(f"  [red]•[/red] {error}")
        sys.exit(1)


# Categories subcommands
@cli.group()
def categories() -> None:
    """Category management commands.

    \b
    Categories control what gets synced (skills, commands, hooks, etc.).
    Enable only what you need.

    \b
    Examples:
        sccs categories list         List enabled categories
        sccs categories list --all   List all (incl. disabled)
        sccs categories enable fish  Enable fish shell config sync
    """
    pass


@categories.command("list")
@click.option("--all", "show_all", is_flag=True, help="Show all categories including disabled")
@click.pass_context
def categories_list(ctx: click.Context, show_all: bool) -> None:
    """List all categories."""
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    categories_dict = {
        name: {
            "enabled": cat.enabled,
            "description": cat.description,
            "platforms": cat.platforms,
        }
        for name, cat in config.sync_categories.items()
    }

    console.print_categories_list(categories_dict, show_all=show_all)


@categories.command("enable")
@click.argument("category_name")
@click.pass_context
def categories_enable(ctx: click.Context, category_name: str) -> None:
    """Enable a category."""
    console = ctx.obj["console"]

    try:
        update_category_enabled(category_name, True)
        console.print_success(f"Enabled: {category_name}")
    except KeyError:
        console.print_error(f"Category not found: {category_name}")
        sys.exit(1)
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)


@categories.command("disable")
@click.argument("category_name")
@click.pass_context
def categories_disable(ctx: click.Context, category_name: str) -> None:
    """Disable a category."""
    console = ctx.obj["console"]

    try:
        update_category_enabled(category_name, False)
        console.print_success(f"Disabled: {category_name}")
    except KeyError:
        console.print_error(f"Category not found: {category_name}")
        sys.exit(1)
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
