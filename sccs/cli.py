# SCCS CLI
# Command-line interface using Click

import sys
from pathlib import Path
from typing import Optional

import click

from sccs import __version__
from sccs.config import (
    load_config,
    ensure_config_exists,
    get_config_path,
    validate_config_file,
    generate_default_config,
    update_category_enabled,
)
from sccs.sync import SyncEngine
from sccs.sync.state import StateManager
from sccs.output import Console, show_diff
from sccs.git import commit, push, stage_all, has_uncommitted_changes


# Global console instance
_console: Optional[Console] = None


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
    Quick examples:
      sccs sync                  Sync all enabled categories
      sccs sync --commit --push  Sync with git commit and push
      sccs sync --dry-run        Preview changes only
      sccs status                Show sync status
      sccs config show           Show configuration
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
@click.option("--commit", "do_commit", is_flag=True, help="Commit changes (overrides auto_commit=false)")
@click.option("--no-commit", is_flag=True, help="Skip commit (overrides auto_commit=true)")
@click.option("--push", "do_push", is_flag=True, help="Push after commit (overrides auto_push=false)")
@click.option("--no-push", is_flag=True, help="Skip push (overrides auto_push=true)")
@click.pass_context
def sync(
    ctx: click.Context,
    category: Optional[str],
    dry_run: bool,
    force: Optional[str],
    do_commit: bool,
    no_commit: bool,
    do_push: bool,
    no_push: bool,
) -> None:
    """Synchronize files between local and repository."""
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    engine = SyncEngine(config)

    if dry_run:
        console.print_info("Dry run - no changes will be made")

    # Perform sync
    result = engine.sync(
        category_name=category,
        dry_run=dry_run,
        force_direction=force,
    )

    # Display results
    console.print_sync_result(result)

    # Handle git operations
    if not dry_run and result.synced_items > 0:
        repo_path = Path(config.repository.path).expanduser()

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

    if result.conflicts > 0:
        console.print_warning(f"{result.conflicts} conflicts need manual resolution")

    sys.exit(0 if result.success else 1)


@cli.command()
@click.option("-c", "--category", help="Show status for specific category only")
@click.pass_context
def status(ctx: click.Context, category: Optional[str]) -> None:
    """Show synchronization status."""
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
@click.argument("item_name")
@click.option("-c", "--category", required=True, help="Category of the item")
@click.pass_context
def diff(ctx: click.Context, item_name: str, category: str) -> None:
    """Show diff for a specific item."""
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    engine = SyncEngine(config)
    handler = engine.get_handler(category)

    if handler is None:
        console.print_error(f"Category '{category}' not found")
        sys.exit(1)

    # Find the item
    items = handler.scan_items()
    item = next((i for i in items if i.name == item_name), None)

    if item is None:
        console.print_error(f"Item '{item_name}' not found in category '{category}'")
        sys.exit(1)

    show_diff(item, console=console._console)


@cli.command()
@click.option("--last", type=int, default=10, help="Number of entries to show")
@click.pass_context
def log(ctx: click.Context, last: int) -> None:
    """Show sync history."""
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

    console.print(f"\n[bold]Recent items:[/bold]")
    for item in sorted_items:
        action = item.last_action or "unknown"
        console.print(f"  {item.category}:{item.name} - {action} ({item.last_synced})")


# Config subcommands
@cli.group()
def config() -> None:
    """Configuration management commands."""
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
    import subprocess

    config_path = get_config_path()
    console = ctx.obj["console"]

    if not config_path.exists():
        console.print_warning("Config file not found. Creating default...")
        ensure_config_exists()

    editor = os.environ.get("EDITOR", "nano")

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
    """Category management commands."""
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
        name: cat.enabled for name, cat in config.sync_categories.items()
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
