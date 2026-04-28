# SCCS CLI
# Command-line interface using Click

import sys
from pathlib import Path

import click

from sccs import __version__
from sccs.config import (
    adopt_new_categories,
    ensure_config_exists,
    generate_default_config,
    get_config_path,
    load_config,
    load_raw_user_data,
    update_category_enabled,
    validate_config_file,
)
from sccs.config.migration import (
    MigrationStateManager,
    detect_new_categories,
    get_categories_to_offer,
    get_category_info,
)
from sccs.git import commit, get_remote_status, has_uncommitted_changes, pull, push, stage_all
from sccs.git.resolve import (
    DivergenceStrategy,
    apply_divergence_strategy,
    prompt_divergence_strategy,
)
from sccs.output import Console, show_diff
from sccs.output.merge import edit_in_editor, interactive_merge
from sccs.sync import SyncEngine
from sccs.sync.actions import SyncAction
from sccs.sync.state import StateManager
from sccs.utils.logging import configure_logging
from sccs.utils.platform import (
    get_current_platform,
    get_platform_skipped_categories,
    is_shell_available,
)

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

    # Configure logging once per invocation. The log_file is best-effort: it
    # comes from config.output.log_file when a config exists, otherwise the
    # CLI just logs to the console stream at the chosen verbosity.
    log_file: str | None = None
    cfg = None
    try:
        cfg = load_config()
        log_file = cfg.output.log_file
    except Exception:  # noqa: BLE001 — config errors are surfaced elsewhere
        pass
    configure_logging(log_file=log_file, verbose=verbose)

    # One-shot platform hint: when categories are skipped on this OS due to
    # `platforms` filtering, surface that to interactive users so they don't
    # silently miss configurations. Skipped on pipe/CI to keep scripts clean.
    if cfg is not None and sys.stdout.isatty() and not no_color:
        _print_platform_hint(console, cfg)


@cli.command()
@click.option("-c", "--category", help="Sync specific category only")
@click.option("-n", "--dry-run", is_flag=True, help="Preview changes without executing")
@click.option(
    "-f",
    "--force",
    type=click.Choice(["local", "repo", "newer"]),
    help="Force direction: local, repo, or newer (by mtime)",
)
@click.option("-i", "--interactive", is_flag=True, help="Interactive mode for conflict resolution")
@click.option("--commit", "do_commit", is_flag=True, help="Commit changes (overrides auto_commit=false)")
@click.option("--no-commit", is_flag=True, help="Skip commit (overrides auto_commit=true)")
@click.option("--push", "do_push", is_flag=True, help="Push after commit (overrides auto_push=false)")
@click.option("--no-push", is_flag=True, help="Skip push (overrides auto_push=true)")
@click.option("--pull", "do_pull", is_flag=True, help="Pull remote changes before sync")
@click.option("--no-pull-check", is_flag=True, help="Skip remote status check before sync")
@click.option("--docs/--no-docs", "do_docs", default=None, help="Regenerate hub README after sync (auto when --commit)")
@click.option("--no-migrate", is_flag=True, help="Skip new-category migration check")
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
    do_docs: bool,
    no_migrate: bool,
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
        sccs sync --force newer      Keep newer version (by mtime)
    """
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    # Check for new default categories
    _run_migration_check(console, no_migrate, get_config_path())

    repo_path = Path(config.repository.path).expanduser()

    # Check remote status before sync (unless skipped or dry-run)
    if not dry_run and not no_pull_check:
        remote_status = get_remote_status(repo_path)

        if "error" in remote_status:
            # Non-fatal: just warn and continue
            console.print_warning(f"Could not check remote status: {remote_status['error']}")
        elif remote_status.get("diverged"):
            # Diverged: offer an interactive resolution prompt.
            # In non-TTY contexts the prompt auto-answers ABORT, preserving the
            # previous fail-loud behaviour for CI/pipe usage.
            ahead = remote_status.get("ahead", 0)
            behind = remote_status.get("behind", 0)
            console.print_warning(f"Repository diverged: {ahead} commit(s) ahead, {behind} commit(s) behind remote")
            strategy = prompt_divergence_strategy(
                ahead=ahead,
                behind=behind,
                remote=config.repository.remote,
            )
            if strategy is DivergenceStrategy.ABORT:
                console.print_info(
                    "Run 'sccs sync' in an interactive terminal to pick a strategy, "
                    "or resolve with git manually (pull --rebase, merge, or push --force-with-lease)."
                )
                sys.exit(1)
            if not apply_divergence_strategy(
                strategy,
                repo_path,
                console,
                remote=config.repository.remote,
            ):
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

    # Generate hub README: auto when committing, explicit with --docs, skip with --no-docs
    should_commit = (config.repository.auto_commit or do_commit) and not no_commit
    should_generate_docs = do_docs if do_docs is not None else should_commit
    if should_generate_docs and not dry_run and result.synced_items > 0:
        from sccs.docs.generator import DocsGenerator

        docs_gen = DocsGenerator(config)
        docs_result = docs_gen.generate()
        if docs_result.success:
            console.print_success(f"Hub README updated ({docs_result.readmes_found} docs linked)")
        else:
            console.print_warning(f"Hub README generation failed: {docs_result.error}")

    # Handle git operations
    if not dry_run and result.synced_items > 0:
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

    # Inline integration status (non-blocking)
    try:
        _show_integrations_inline(console, config)
    except Exception:
        pass


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


@config.command("upgrade")
@click.pass_context
def config_upgrade(ctx: click.Context) -> None:
    """Check for new default categories and add them to config.

    \b
    Compares your config.yaml against built-in defaults and offers
    to add any new categories. Previously declined categories are
    re-offered here.

    \b
    Examples:
        sccs config upgrade    Review and adopt new categories
    """
    console = ctx.obj["console"]

    config_path = get_config_path()
    if not config_path.exists():
        console.print_error(f"Config file not found: {config_path}")
        console.print_info("Run 'sccs config init' to create one")
        sys.exit(1)

    raw_data = load_raw_user_data(config_path)
    mgr = MigrationStateManager()

    # detect_new_categories (not get_categories_to_offer) — re-offer previously declined
    all_new = detect_new_categories(raw_data)

    if not all_new:
        console.print_success("Your config is up to date with all available categories.")
        return

    _interactive_migration_prompt(console, all_new, mgr, config_path)


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


@cli.group("convert")
def convert_group() -> None:
    """Convert configurations between shell formats.

    \b
    Generates PowerShell-equivalent profile files from your existing
    Fish shell configuration so the same aliases/env vars work on Windows.

    \b
    Source default depends on platform:
      - macOS/Linux: ~/.config/fish (your local Fish install)
      - Windows:    <repo>/.config/fish (the synced copy, since Fish is
                    not expected to be installed on Windows)

    \b
    Examples:
        sccs convert fish-to-pwsh              Convert default source to repo
        sccs convert fish-to-pwsh --dry-run    Preview without writing files
        sccs convert fish-to-pwsh --force      Overwrite existing PS files
    """


@convert_group.command("fish-to-pwsh")
@click.option(
    "--src",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Source Fish config dir (default: ~/.config/fish on macOS/Linux, <repo>/.config/fish on Windows)",
)
@click.option(
    "--dst",
    type=click.Path(path_type=Path),
    default=None,
    help="Destination dir (default: <repo>/.config/powershell)",
)
@click.option("--force", is_flag=True, help="Overwrite existing PowerShell files")
@click.option("-n", "--dry-run", is_flag=True, help="Preview without writing files")
@click.pass_context
def convert_fish_to_pwsh(
    ctx: click.Context,
    src: Path | None,
    dst: Path | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Generate a PowerShell profile from Fish shell configuration.

    \b
    Converts:
      - alias name=value             → Set-Alias / function with @args
      - set -gx VAR value            → $env:VAR = "value"
      - fish_add_path /some/dir      → duplicate-aware $env:PATH prepend
      - abbr -a name expansion       → Set-Alias / function

    \b
    Fish function bodies (~/.config/fish/functions/*.fish) are emitted
    as commented stubs because their syntax does not map to PowerShell
    automatically. Port them by hand in the generated functions/*.ps1
    files; the original Fish source is preserved as a reference.

    \b
    Files matching *.macos.fish, *.linux.fish or *.local.fish are skipped.
    """
    from sccs.convert import FishToPwshConverter

    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        console.print_info("Run 'sccs config init' first")
        sys.exit(1)

    repo_path = Path(config.repository.path).expanduser()
    if src is not None:
        src_path = src.expanduser()
    elif get_current_platform() == "windows":
        # On Windows, Fish is typically not installed locally — fall back to
        # the synced copy in the repository so users can build a PowerShell
        # profile from the configs they pushed from macOS/Linux.
        src_path = repo_path / ".config" / "fish"
    else:
        src_path = Path("~/.config/fish").expanduser()
    if dst is not None:
        dst_path = dst.expanduser()
    else:
        dst_path = repo_path / ".config" / "powershell"

    if not src_path.exists():
        console.print_error(f"Source directory not found: {src_path}")
        if src is None and get_current_platform() == "windows":
            console.print_info("Run 'sccs sync --pull' first to fetch fish configs from the repo,")
            console.print_info("or pass --src explicitly if Fish is installed locally.")
        sys.exit(1)

    # Refuse to clobber an existing destination unless --force or --dry-run.
    if not dry_run and dst_path.exists() and any(dst_path.iterdir()) and not force:
        console.print_warning(f"Destination is not empty: {dst_path}")
        console.print_info("Use --force to overwrite (creates .bak files), or --dry-run to preview")
        sys.exit(1)

    if dry_run:
        console.print_info("Dry run — no files will be written\n")

    console.print(f"[bold]Source:[/bold] {src_path}")
    console.print(f"[bold]Target:[/bold] {dst_path}\n")

    converter = FishToPwshConverter(src_path, dst_path)
    report = converter.convert_directory(dry_run=dry_run)

    # Summary table
    console.print("[bold]Conversion summary:[/bold]")
    console.print(f"  Files processed:       {report.files_processed}")
    console.print(f"  Files skipped:         {report.files_skipped}")
    console.print(f"  Aliases (Set-Alias):   {report.aliases_converted}")
    console.print(f"  Aliases (function):    {report.functions_wrapped}")
    console.print(f"  Env vars:              {report.env_vars_converted}")
    console.print(f"  PATH lines:            {report.path_lines_converted}")
    console.print(f"  Function stubs:        {report.functions_stubbed}")
    console.print(f"  Fish-only passthrough: {report.fish_lines_passthrough}")

    if report.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for warn in report.warnings:
            console.print(f"  • {warn}")

    if dry_run:
        console.print(f"\n[dim]Would write {len(report.written_files)} file(s) to {dst_path}[/dim]")
        return

    console.print_success(f"\nWrote {len(report.written_files)} file(s) to {dst_path}")
    console.print_info(
        "Next: `sccs categories enable powershell_profile` and `sccs sync --category powershell_profile` on Windows"
    )


@cli.group("docs")
def docs_group() -> None:
    """Documentation generation commands.

    \b
    Generate a hub README for the sync repository that links
    to all category READMEs and shows repository structure.

    \b
    Examples:
        sccs docs generate             Generate hub README
        sccs docs generate --dry-run   Preview without writing
    """
    pass


@docs_group.command("generate")
@click.option("-n", "--dry-run", is_flag=True, help="Preview without writing")
@click.option("--commit", "do_commit", is_flag=True, help="Commit after generation")
@click.option("--push", "do_push", is_flag=True, help="Push after commit")
@click.pass_context
def docs_generate(ctx: click.Context, dry_run: bool, do_commit: bool, do_push: bool) -> None:
    """Generate hub README for the sync repository.

    \b
    Scans all category paths for README files and generates
    a navigation hub at the repository root.

    \b
    Examples:
        sccs docs generate              Write README.md to repo root
        sccs docs generate --dry-run    Preview the generated content
        sccs docs generate --commit     Generate and commit
    """
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    from sccs.docs.generator import DocsGenerator

    gen = DocsGenerator(config)

    if dry_run:
        content = gen.render_readme()
        console.print(content)
        return

    result = gen.generate()

    if not result.success:
        console.print_error(f"Generation failed: {result.error}")
        sys.exit(1)

    console.print_success(f"Hub README generated: {result.readme_path}")
    console.print_info(f"  {result.readmes_found} documentation links, {result.categories_total} categories")

    # Git operations
    if do_commit:
        repo_path = Path(config.repository.path).expanduser()
        if has_uncommitted_changes(repo_path):
            stage_all(repo_path)
            commit_msg = f"{config.repository.commit_prefix} Update hub README"
            commit(commit_msg, repo_path)
            console.print_success(f"Committed: {commit_msg}")

            if do_push:
                if push(repo_path, remote=config.repository.remote):
                    console.print_success(f"Pushed to {config.repository.remote}")
                else:
                    console.print_warning("Push failed")


@cli.command("export")
@click.option("-o", "--output", "output_path", type=click.Path(path_type=Path), default=None, help="Output ZIP path")
@click.option("--all", "select_all", is_flag=True, help="Export all enabled categories without prompting")
@click.option("-c", "--category", "categories", multiple=True, help="Limit to specific categories (repeatable)")
@click.pass_context
def export_cmd(ctx: click.Context, output_path: Path | None, select_all: bool, categories: tuple[str, ...]) -> None:
    """Export selected items as ZIP archive.

    \b
    Creates a portable ZIP archive with selected skills, commands,
    hooks, and other configurations for deployment to other systems.

    \b
    Examples:
        sccs export                          Interactive selection
        sccs export --all                    Export everything
        sccs export -c claude_skills         Export only skills
        sccs export -o my-config.zip         Custom output path
        sccs export -c skills -c agents      Multiple categories
    """
    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    from sccs.transfer.exporter import Exporter, generate_export_filename
    from sccs.transfer.ui import interactive_export_selection

    raw_config = load_raw_user_data()
    exporter = Exporter(config)

    # Scan available items
    scanned = exporter.scan_available_items()

    if not scanned:
        console.print_warning("No local items found to export")
        sys.exit(1)

    # Apply category filter if specified
    if categories:
        scanned = {k: v for k, v in scanned.items() if k in categories}
        if not scanned:
            console.print_error(f"No items found for categories: {', '.join(categories)}")
            sys.exit(1)

    if select_all:
        # Export everything without UI
        selections = exporter.build_selections_all(scanned)
    else:
        # Two-stage interactive selection
        if not sys.stdout.isatty():
            console.print_error("Interactive mode requires a TTY. Use --all for non-interactive export.")
            sys.exit(1)

        parsed = interactive_export_selection(scanned, config, raw_config, console=console)

        if not parsed:
            console.print_warning("No items selected")
            sys.exit(0)

        selections = exporter.build_selections_from_parsed(parsed, scanned)

    if not selections:
        console.print_warning("No items selected for export")
        sys.exit(0)

    # Resolve output path
    if output_path is None:
        output_path = Path.cwd() / generate_export_filename()

    result = exporter.export_to_zip(selections, output_path, raw_config)

    if result.success:
        console.print_success(f"Exported {result.total_items} items from {result.total_categories} categories")
        console.print_info(f"  Archive: {result.output_path}")
    else:
        console.print_error(f"Export failed: {result.error}")
        sys.exit(1)


@cli.command("import")
@click.argument("zip_path", type=click.Path(exists=True, path_type=Path))
@click.option("-n", "--dry-run", is_flag=True, help="Preview what would be written without writing")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files without prompting")
@click.option("--no-backup", is_flag=True, help="Skip backup before overwriting")
@click.option("--all", "select_all", is_flag=True, help="Import all items without prompting")
@click.pass_context
def import_cmd(
    ctx: click.Context, zip_path: Path, dry_run: bool, overwrite: bool, no_backup: bool, select_all: bool
) -> None:
    """Import items from an SCCS export archive.

    \b
    Extracts selected items from a ZIP archive and places them
    in the appropriate local paths.

    \b
    Examples:
        sccs import config.zip               Interactive selection
        sccs import config.zip --all         Import everything
        sccs import config.zip --dry-run     Preview only
        sccs import config.zip --overwrite   Overwrite existing files
    """
    console = ctx.obj["console"]

    from sccs.transfer.importer import Importer
    from sccs.transfer.ui import interactive_import_selection

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        console.print_info("Run 'sccs config init' before importing — a local config is required for path validation")
        sys.exit(1)

    importer = Importer(zip_path, config=config)

    try:
        manifest = importer.load_manifest()
    except (ValueError, FileNotFoundError) as e:
        console.print_error(str(e))
        sys.exit(1)

    # Show manifest summary
    console.print("\n[bold]SCCS Export Archive[/bold]")
    console.print(f"  Created: {manifest.created_at}")
    console.print(f"  Platform: {manifest.created_on}")
    console.print(f"  SCCS version: {manifest.sccs_version}")
    console.print(f"  Categories: {manifest.total_categories}")
    console.print(f"  Items: {manifest.total_items}\n")

    if select_all:
        selections = importer.build_selections_all()
    else:
        if not sys.stdout.isatty():
            console.print_error("Interactive mode requires a TTY. Use --all for non-interactive import.")
            sys.exit(1)

        parsed = interactive_import_selection(manifest, console=console)

        if not parsed:
            console.print_warning("No items selected")
            sys.exit(0)

        selections = importer.build_selections_from_parsed(parsed)

    if not selections:
        console.print_warning("No items selected for import")
        sys.exit(0)

    if dry_run:
        console.print_info("Dry run — no files will be written\n")

    result = importer.apply(
        selections,
        dry_run=dry_run,
        overwrite=overwrite,
        backup=not no_backup,
    )

    if result.success:
        action = "Would write" if dry_run else "Written"
        console.print_success(f"{action}: {result.written} items")
        if result.skipped > 0:
            console.print_info(f"  Skipped (already exist): {result.skipped}")
            if not overwrite:
                console.print_info("  Tip: Use --overwrite to replace existing files")
        if result.backed_up > 0:
            console.print_info(f"  Backed up: {result.backed_up}")
    else:
        console.print_error("Import completed with errors:")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")
        sys.exit(1)


_PLATFORM_HINT_PRINTED: bool = False


def _print_platform_hint(console: Console, cfg) -> None:
    """
    Print a one-line hint when platform-restricted categories are skipped.

    Only emits the hint once per process (subcommands invoked through
    Click's nested groups otherwise repeat it). Stays silent when no
    categories are filtered out.
    """
    global _PLATFORM_HINT_PRINTED
    if _PLATFORM_HINT_PRINTED:
        return
    _PLATFORM_HINT_PRINTED = True

    skipped = get_platform_skipped_categories(cfg)
    if not skipped:
        return

    current = get_current_platform()
    parts: list[str] = []
    extra_tip: str | None = None
    for shell, names in skipped.items():
        names_str = ", ".join(sorted(names))
        if shell == "other":
            parts.append(f"Übersprungen (Plattform-Filter): {names_str}")
            continue

        shell_label = "Fish" if shell == "fish" else "PowerShell" if shell == "powershell" else shell
        if is_shell_available(shell):
            # Shell is installed locally — categories are skipped purely
            # because their `platforms` filter excludes the current OS.
            parts.append(f"{shell_label}-Kategorien plattformspezifisch übersprungen: {names_str}")
        else:
            parts.append(f"{shell_label} nicht verfügbar — übersprungen: {names_str}")
            if shell == "fish" and current == "windows":
                extra_tip = "Tipp: `sccs convert fish-to-pwsh` generiert PowerShell-Aliasse aus den Fish-Configs"

    console.print(f"[dim]ℹ Plattform: {current} — {'; '.join(parts)}[/dim]")
    if extra_tip:
        console.print(f"[dim]  {extra_tip}[/dim]")


def _run_migration_check(
    console: Console,
    no_migrate: bool,
    config_path: Path | None = None,
) -> None:
    """
    Check for new default categories and prompt user to adopt them.

    Non-blocking: sync continues whether or not user adopts anything.
    In non-TTY mode (CI), only prints a notice without interaction.
    """
    if no_migrate:
        return

    raw_data = load_raw_user_data(config_path)
    mgr = MigrationStateManager()
    is_tty = sys.stdout.isatty()

    if is_tty:
        to_offer = get_categories_to_offer(raw_data, mgr)
        if not to_offer:
            return
        _interactive_migration_prompt(console, to_offer, mgr, config_path)
    else:
        # Non-TTY (CI): notify about ALL new categories, no state write
        to_offer = detect_new_categories(raw_data)
        if to_offer:
            count = len(to_offer)
            names = ", ".join(to_offer)
            console.print_info(
                f"Notice: {count} new categor{'y' if count == 1 else 'ies'} "
                f"available ({names}). Run 'sccs config upgrade' to review."
            )


def _interactive_migration_prompt(
    console: Console,
    to_offer: list[str],
    mgr: MigrationStateManager,
    config_path: Path | None = None,
) -> None:
    """
    Interactive prompt to adopt new default categories.

    Displays available categories and lets the user choose which to add.
    Declined categories are remembered in MigrationState.
    """
    count = len(to_offer)
    console.print(f"\n[bold cyan]New categories available ({count})[/bold cyan]")
    console.print("[dim]These categories exist in the defaults but not in your config.yaml.[/dim]\n")

    for i, name in enumerate(to_offer, 1):
        cat = get_category_info(name)
        enabled = cat.get("enabled", True)
        enabled_label = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
        description = cat.get("description", "")
        local_path = cat.get("local_path", "")
        repo_path = cat.get("repo_path", "")

        console.print(f"  [cyan]{i}[/cyan] [bold]{name}[/bold] - {description}")
        console.print(f"      local: [dim]{local_path}[/dim]  repo: [dim]{repo_path}[/dim]  (default: {enabled_label})")

    console.print()

    adopted: list[str] = []
    declined: list[str] = []

    # Offer "add all" shortcut
    if console.confirm(f"Add all {count} categories at once? (No = decide individually)", default=False):
        adopted = list(to_offer)
    else:
        for name in to_offer:
            cat = get_category_info(name)
            default_yes = cat.get("enabled", True)
            if console.confirm(f"  Add '{name}'?", default=default_yes):
                adopted.append(name)
            else:
                declined.append(name)

    if adopted:
        adopt_new_categories(adopted, config_path)
        mgr.mark_adopted(adopted)
        n = len(adopted)
        console.print_success(f"Added {n} categor{'y' if n == 1 else 'ies'}: {', '.join(adopted)}")

    if declined:
        mgr.mark_declined(declined)
        console.print(
            f"[dim]Skipped: {', '.join(declined)} (won't ask again; run 'sccs config upgrade' to review)[/dim]"
        )

    console.print()


def _show_integrations_inline(console: Console, config) -> None:
    """Show integration status inline in sccs status output."""
    from sccs.integrations.detectors import AntigravityDetector, ClaudeDesktopDetector

    ag_detector = AntigravityDetector()
    ag_info = ag_detector.get_info()
    ag_gaps = ag_detector.get_skill_gaps() if ag_info else []

    cd_detector = ClaudeDesktopDetector()
    cd_info = cd_detector.get_info()
    repo_trusted = False
    if cd_info and hasattr(config, "repository"):
        repo_trusted = cd_detector.is_repo_trusted(config.repository.path)

    console.print_integrations_status(ag_info, ag_gaps, cd_info, repo_trusted)


# --- Integrations command group ---


@cli.group("integrations")
def integrations_group() -> None:
    """Integration status and migration commands.

    \b
    Detect and manage integrations with Antigravity IDE
    and Claude Desktop.

    \b
    Examples:
        sccs integrations status            Show integration status
        sccs integrations migrate-skills    Copy skills to Antigravity prompts
        sccs integrations trust-repo        Register SCCS repo as trusted
    """


@integrations_group.command("status")
@click.pass_context
def integrations_status(ctx: click.Context) -> None:
    """Show detailed integration status."""
    from sccs.integrations.detectors import AntigravityDetector, ClaudeDesktopDetector

    console = ctx.obj["console"]

    ag_detector = AntigravityDetector()
    ag_info = ag_detector.get_info()
    ag_gaps = ag_detector.get_skill_gaps() if ag_info else []

    cd_detector = ClaudeDesktopDetector()
    cd_info = cd_detector.get_info()

    repo_trusted = False
    try:
        config = load_config()
        if cd_info:
            repo_trusted = cd_detector.is_repo_trusted(config.repository.path)
    except FileNotFoundError:
        pass

    if ag_info is None and cd_info is None:
        console.print("[dim]No integrations detected[/dim]")
        return

    console.print_integrations_status(ag_info, ag_gaps, cd_info, repo_trusted)

    # Detailed gap list
    if ag_info and ag_gaps:
        console.print(f"\n[bold]Antigravity skill gaps ({len(ag_gaps)}):[/bold]")
        for gap in ag_gaps:
            label = "[yellow]outdated[/yellow]" if gap.needs_update else "[red]missing[/red]"
            console.print(f"  {gap.name} — {label}")


@integrations_group.command("migrate-skills")
@click.option("-n", "--dry-run", is_flag=True, help="Preview changes without executing")
@click.option("--overwrite/--no-overwrite", default=True, help="Update existing prompts (default: yes)")
@click.option("-s", "--skill", "skills", multiple=True, help="Limit to specific skill (repeatable)")
@click.pass_context
def integrations_migrate_skills(
    ctx: click.Context,
    dry_run: bool,
    overwrite: bool,
    skills: tuple[str, ...],
) -> None:
    """Migrate Claude Code skills to Antigravity prompts.

    \b
    Copies SKILL.md content from ~/.claude/skills/<name>/
    to ~/.antigravity/prompts/<name>.md

    \b
    Examples:
        sccs integrations migrate-skills                Migrate all
        sccs integrations migrate-skills --dry-run      Preview only
        sccs integrations migrate-skills -s astro -s sccs   Specific skills
        sccs integrations migrate-skills --no-overwrite     Skip existing
    """
    from sccs.integrations.antigravity import migrate_skills_to_prompts
    from sccs.integrations.detectors import AntigravityDetector

    console = ctx.obj["console"]

    detector = AntigravityDetector()
    if not detector.is_installed():
        console.print_error("Antigravity is not installed (~/.antigravity/ not found)")
        sys.exit(1)

    gaps = detector.get_skill_gaps()
    if not gaps:
        console.print_success("All skills are already available in Antigravity prompts")
        return

    selected = list(skills) if skills else None

    if dry_run:
        console.print_info("Dry run — no files will be written\n")

    result = migrate_skills_to_prompts(
        gaps,
        dry_run=dry_run,
        overwrite_existing=overwrite,
        selected=selected,
    )

    verb = "Would create" if dry_run else "Created"
    verb_upd = "Would update" if dry_run else "Updated"

    if result.prompts_dir_created:
        action = "Would create" if dry_run else "Created"
        console.print_info(f"{action} ~/.antigravity/prompts/")

    if result.created:
        console.print_success(f"{verb}: {len(result.created)} skills")
        if ctx.obj["verbose"]:
            for name in result.created:
                console.print(f"  [green]+[/green] {name}")

    if result.updated:
        console.print_success(f"{verb_upd}: {len(result.updated)} skills")
        if ctx.obj["verbose"]:
            for name in result.updated:
                console.print(f"  [yellow]~[/yellow] {name}")

    if result.skipped:
        console.print(f"[dim]Skipped: {len(result.skipped)} (already exist, use --overwrite)[/dim]")

    if result.errors:
        console.print_error(f"Errors: {len(result.errors)}")
        for name, error in result.errors.items():
            console.print(f"  [red]✗[/red] {name}: {error}")
        sys.exit(1)


@integrations_group.command("trust-repo")
@click.option("-n", "--dry-run", is_flag=True, help="Preview changes without executing")
@click.pass_context
def integrations_trust_repo(ctx: click.Context, dry_run: bool) -> None:
    """Register SCCS repository as trusted in Claude Desktop.

    \b
    Adds the configured repository path to Claude Desktop's
    localAgentModeTrustedFolders list.

    \b
    Examples:
        sccs integrations trust-repo            Register repo
        sccs integrations trust-repo --dry-run  Preview only
    """
    from sccs.integrations.claude_desktop import register_trusted_folder
    from sccs.integrations.detectors import ClaudeDesktopDetector

    console = ctx.obj["console"]

    detector = ClaudeDesktopDetector()
    if not detector.is_installed():
        console.print_error("Claude Desktop is not installed")
        sys.exit(1)

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print_error(str(e))
        sys.exit(1)

    if dry_run:
        console.print_info("Dry run — no files will be written\n")

    result = register_trusted_folder(
        config.repository.path,
        dry_run=dry_run,
    )

    if result.already_trusted:
        console.print_success(f"Already trusted: {result.repo_path}")
        return

    if result.success:
        verb = "Would register" if dry_run else "Registered"
        console.print_success(f"{verb}: {result.repo_path}")
        if not dry_run:
            console.print_info("Restart Claude Desktop to apply changes")
    else:
        console.print_error(result.error or "Unknown error")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
