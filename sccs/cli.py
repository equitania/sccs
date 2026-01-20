"""Click-based CLI for SCCS - Skills, Commands, Configs Sync."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.prompt import Confirm

from sccs import __version__
from sccs.command import scan_commands_directory
from sccs.config import (
    AUTO_COMMIT,
    AUTO_PUSH,
    COMMIT_PREFIX,
    DEFAULT_LOCAL_COMMANDS_PATH,
    DEFAULT_LOCAL_PATH,
    GIT_REMOTE,
    clear_repo_root_cache,
    get_default_repo_commands_path,
    get_default_repo_skills_path,
    get_repo_root,
    get_sync_log_path,
)
from sccs.config_sync import (
    ConfigActionType,
    ConfigSyncEngine,
    ConfigSyncState,
    DIRECT_SYNC_FILES,
    PathTransformer,
    TRANSFORM_FILES,
    sync_hooks_directory,
)
from sccs.git import auto_commit_and_push, is_git_repo
from sccs.diff import ConflictResolution, DeletionResolution, DiffGenerator, show_command_diff, show_skill_diff
from sccs.logger import SyncLogger
from sccs.skill import scan_skills_directory
from sccs.state import SyncState
from sccs.sync_engine import ActionType, ItemType, SyncAction, SyncEngine, SyncResult
from sccs.user_config import ensure_configured


console = Console()
logger = SyncLogger(console)


@click.group()
@click.version_option(version=__version__, prog_name="sccs")
def cli() -> None:
    """SCCS - Skills, Commands, Configs Sync for Claude Code.

    Bidirectional synchronization of skills and commands between local ~/.claude/ and repository.

    \b
    Skills:   ~/.claude/skills/   <-> .claude/skills/
    Commands: ~/.claude/commands/ <-> .claude/commands/
    """
    pass


@cli.command()
@click.option("--dry-run", "-n", is_flag=True, help="Preview changes without applying")
@click.option(
    "--force",
    "-f",
    type=click.Choice(["local", "repo"]),
    help="Force direction without prompts (local=local wins, repo=repo wins)",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--skills-only", is_flag=True, help="Only sync skills, skip commands")
@click.option("--commands-only", is_flag=True, help="Only sync commands, skip skills")
@click.option("--local-path", type=click.Path(exists=True, path_type=Path), help="Override local skills path")
@click.option("--repo-path", type=click.Path(path_type=Path), help="Override repository skills path")
@click.option("--local-commands-path", type=click.Path(exists=True, path_type=Path), help="Override local commands path")
@click.option("--repo-commands-path", type=click.Path(path_type=Path), help="Override repository commands path")
@click.option(
    "--auto-commit/--no-auto-commit",
    default=None,
    help="Automatically commit changes after sync (default: disabled)",
)
@click.option(
    "--auto-push/--no-auto-push",
    default=None,
    help="Automatically push after commit (requires --auto-commit)",
)
@click.option(
    "--remote",
    default=None,
    help=f"Git remote for push (default: {GIT_REMOTE})",
)
def sync(
    dry_run: bool,
    force: Optional[str],
    verbose: bool,
    skills_only: bool,
    commands_only: bool,
    local_path: Optional[Path],
    repo_path: Optional[Path],
    local_commands_path: Optional[Path],
    repo_commands_path: Optional[Path],
    auto_commit: Optional[bool],
    auto_push: Optional[bool],
    remote: Optional[str],
) -> None:
    """Synchronize skills and commands between local and repository.

    Detects changes in both directions and syncs accordingly.
    Conflicts (both sides changed) are resolved interactively.
    """
    # Ensure configured - clear cache to pick up any new config
    config = ensure_configured()
    clear_repo_root_cache()

    local = local_path or DEFAULT_LOCAL_PATH
    repo = repo_path or get_default_repo_skills_path()
    local_cmds = local_commands_path or DEFAULT_LOCAL_COMMANDS_PATH
    repo_cmds = repo_commands_path or get_default_repo_commands_path()

    # Ensure repo directories exist
    repo.mkdir(parents=True, exist_ok=True)
    repo_cmds.mkdir(parents=True, exist_ok=True)

    sync_logger = SyncLogger(console, verbose=verbose)

    sync_logger.info(f"Skills:   {local} <-> {repo}")
    sync_logger.info(f"Commands: {local_cmds} <-> {repo_cmds}")

    # Initialize sync engine
    state = SyncState.load()
    engine = SyncEngine(
        local_path=local,
        repo_path=repo,
        local_commands_path=local_cmds,
        repo_commands_path=repo_cmds,
        state=state,
        dry_run=dry_run,
    )

    # Scan and detect changes
    actions: list[SyncAction] = []

    if not commands_only:
        engine.scan_skills()
        actions.extend(engine.detect_changes())

    if not skills_only:
        engine.scan_commands()
        actions.extend(engine.detect_command_changes())

    if not actions:
        sync_logger.success("Everything is in sync!")
        return

    # Show planned actions
    sync_logger.show_actions_table(actions, dry_run=dry_run)

    if dry_run:
        sync_logger.info("Dry-run mode - no changes applied")
        return

    # Confirm before proceeding
    if not force and not Confirm.ask("Proceed with sync?", default=True):
        sync_logger.warning("Sync cancelled")
        return

    # Execute actions
    result = SyncResult()
    diff_gen = DiffGenerator(console)

    for action in actions:
        try:
            resolution = None

            if action.action_type == ActionType.CONFLICT:
                if force == "local":
                    resolution = "local"
                elif force == "repo":
                    resolution = "repo"
                else:
                    # Interactive conflict resolution
                    if action.item_type == ItemType.COMMAND:
                        diff_gen.display_command_diff(action.local_command, action.repo_command)
                    else:
                        diff_gen.display_diff(action.local_skill, action.repo_skill)

                    choice = diff_gen.show_conflict_menu(
                        action.skill_name,
                        datetime.fromtimestamp(action.local_mtime or 0, tz=timezone.utc),
                        datetime.fromtimestamp(action.repo_mtime or 0, tz=timezone.utc),
                        item_type=action.item_type.value,
                    )
                    if choice == ConflictResolution.ABORT:
                        sync_logger.error("Sync aborted by user")
                        return
                    elif choice == ConflictResolution.SKIP:
                        result.actions_skipped.append(action)
                        sync_logger.warning(f"Skipped: {action.skill_name}")
                        continue
                    resolution = choice.value

            elif action.action_type in (ActionType.DELETED_LOCAL, ActionType.DELETED_REPO):
                if force:
                    resolution = "skip"  # Skip deletions in force mode
                else:
                    # Interactive deletion resolution
                    deleted_from = "local" if action.action_type == ActionType.DELETED_LOCAL else "repo"

                    if action.item_type == ItemType.COMMAND:
                        cmd = action.repo_command if action.action_type == ActionType.DELETED_LOCAL else action.local_command
                        choice = diff_gen.show_command_deletion_menu(action.skill_name, deleted_from, cmd)
                    else:
                        skill = action.repo_skill if action.action_type == ActionType.DELETED_LOCAL else action.local_skill
                        choice = diff_gen.show_deletion_menu(action.skill_name, deleted_from, skill)

                    if choice == DeletionResolution.ABORT:
                        sync_logger.error("Sync aborted by user")
                        return
                    elif choice == DeletionResolution.SKIP:
                        result.actions_skipped.append(action)
                        sync_logger.warning(f"Skipped: {action.skill_name}")
                        continue
                    resolution = choice.value

            # Execute the action
            success = engine.execute_action(action, resolution)
            if success:
                result.actions_executed.append(action)
                sync_logger.action(action)
            else:
                result.actions_skipped.append(action)

        except Exception as e:
            result.errors.append(f"{action.skill_name}: {e}")
            result.success = False

    # Save state
    engine.save_state()

    # Update SYNC_LOG.md
    if result.actions_executed:
        _update_sync_log(engine.generate_sync_log_entry(result.actions_executed))

    # Git operations (auto-commit and push)
    should_commit = auto_commit if auto_commit is not None else AUTO_COMMIT
    should_push = auto_push if auto_push is not None else AUTO_PUSH
    git_remote = remote or GIT_REMOTE

    if should_commit and result.actions_executed and not dry_run:
        if not is_git_repo():
            sync_logger.warning("Not a git repository - skipping auto-commit")
        else:
            # Collect synced item names
            skills_synced = [
                a.skill_name for a in result.actions_executed
                if a.item_type == ItemType.SKILL
            ]
            commands_synced = [
                a.skill_name for a in result.actions_executed
                if a.item_type == ItemType.COMMAND
            ]

            sync_logger.info("Committing changes...")
            git_result = auto_commit_and_push(
                skills_synced=skills_synced,
                commands_synced=commands_synced,
                auto_push=should_push,
                remote=git_remote,
                prefix=COMMIT_PREFIX,
            )

            if git_result.success:
                if git_result.commit_hash:
                    sync_logger.success(f"Git: {git_result.message}")
                else:
                    sync_logger.info(f"Git: {git_result.message}")
            else:
                for error in git_result.errors:
                    sync_logger.error(f"Git error: {error}")

    # Show summary
    sync_logger.summary(result)


@cli.command()
@click.option("--local-path", type=click.Path(exists=True, path_type=Path), help="Override local skills path")
@click.option("--repo-path", type=click.Path(path_type=Path), help="Override repository skills path")
@click.option("--local-commands-path", type=click.Path(exists=True, path_type=Path), help="Override local commands path")
@click.option("--repo-commands-path", type=click.Path(path_type=Path), help="Override repository commands path")
def status(
    local_path: Optional[Path],
    repo_path: Optional[Path],
    local_commands_path: Optional[Path],
    repo_commands_path: Optional[Path],
) -> None:
    """Show current sync status without making changes."""
    # Ensure configured - clear cache to pick up any new config
    config = ensure_configured()
    clear_repo_root_cache()

    local = local_path or DEFAULT_LOCAL_PATH
    repo = repo_path or get_default_repo_skills_path()
    local_cmds = local_commands_path or DEFAULT_LOCAL_COMMANDS_PATH
    repo_cmds = repo_commands_path or get_default_repo_commands_path()

    # Show user configuration
    from sccs.user_config import CONFIG_FILE

    logger.info(f"Config:   {CONFIG_FILE}")
    if config.repo_path:
        logger.info(f"Repo:     {config.repo_path}")
    elif config.repo_url:
        logger.info(f"Repo URL: {config.repo_url}")
    console.print()

    logger.info(f"Skills:   {local} <-> {repo}")
    logger.info(f"Commands: {local_cmds} <-> {repo_cmds}")

    # Scan skills and commands
    local_skills = scan_skills_directory(local)
    repo_skills = scan_skills_directory(repo)
    local_commands = scan_commands_directory(local_cmds)
    repo_commands = scan_commands_directory(repo_cmds)
    state = SyncState.load()

    # Initialize engine to detect changes
    engine = SyncEngine(
        local_path=local,
        repo_path=repo,
        local_commands_path=local_cmds,
        repo_commands_path=repo_cmds,
        state=state,
        dry_run=True,
    )
    engine.local_skills = local_skills
    engine.repo_skills = repo_skills
    engine.local_commands = local_commands
    engine.repo_commands = repo_commands

    skill_actions = engine.detect_changes()
    command_actions = engine.detect_command_changes()
    all_actions = skill_actions + command_actions

    # Show status tables
    logger.show_status(local_skills, repo_skills, state)
    logger.show_commands_status(local_commands, repo_commands, state)

    # Show pending changes
    if all_actions:
        logger.show_actions_table(all_actions, dry_run=True)
    else:
        logger.success("Everything is in sync!")


@cli.command("diff")
@click.argument("name")
@click.option("--command", "-c", is_flag=True, help="Show diff for a command instead of skill")
@click.option("--local-path", type=click.Path(exists=True, path_type=Path), help="Override local skills path")
@click.option("--repo-path", type=click.Path(exists=True, path_type=Path), help="Override repository skills path")
@click.option("--local-commands-path", type=click.Path(exists=True, path_type=Path), help="Override local commands path")
@click.option("--repo-commands-path", type=click.Path(exists=True, path_type=Path), help="Override repository commands path")
def show_diff(
    name: str,
    command: bool,
    local_path: Optional[Path],
    repo_path: Optional[Path],
    local_commands_path: Optional[Path],
    repo_commands_path: Optional[Path],
) -> None:
    """Show diff for a specific skill or command.

    NAME is the name of the skill or command to compare.
    Use --command flag for commands.
    """
    if command:
        local = local_commands_path or DEFAULT_LOCAL_COMMANDS_PATH
        repo = repo_commands_path or get_default_repo_commands_path()
        show_command_diff(name, local, repo, console)
    else:
        local = local_path or DEFAULT_LOCAL_PATH
        repo = repo_path or get_default_repo_skills_path()
        show_skill_diff(name, local, repo, console)


@cli.command()
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def log(lines: int) -> None:
    """Show recent sync operations from SYNC_LOG.md."""
    sync_log_path = get_sync_log_path()

    if not sync_log_path.exists():
        logger.info("No sync log found. Run 'sync' first.")
        return

    content = sync_log_path.read_text(encoding="utf-8")
    log_lines = content.split("\n")

    # Show last N lines
    display_lines = log_lines[-lines:] if len(log_lines) > lines else log_lines
    console.print("\n".join(display_lines))


@cli.command()
def init() -> None:
    """Initialize repository for skills and commands sync.

    Creates the necessary directory structure and initial state file.
    """
    # Ensure configured - clear cache to pick up any new config
    ensure_configured()
    clear_repo_root_cache()

    skills_repo = get_default_repo_skills_path()
    commands_repo = get_default_repo_commands_path()

    if not skills_repo.exists():
        skills_repo.mkdir(parents=True)
        logger.success(f"Created skills directory: {skills_repo}")

    if not commands_repo.exists():
        commands_repo.mkdir(parents=True)
        logger.success(f"Created commands directory: {commands_repo}")

    state_path = skills_repo.parent.parent / ".sync_state.json"
    if not state_path.exists():
        state = SyncState()
        state.save()
        logger.success(f"Created sync state file: {state_path}")

    sync_log_path = get_sync_log_path()
    if not sync_log_path.exists():
        sync_log_path.write_text("# Skills & Commands Synchronization Log\n\n", encoding="utf-8")
        logger.success(f"Created sync log: {sync_log_path}")

    logger.success("Repository initialized for skills and commands sync!")


def _update_sync_log(entry: str) -> None:
    """Append entry to SYNC_LOG.md.

    Args:
        entry: Markdown formatted log entry
    """
    sync_log_path = get_sync_log_path()

    if sync_log_path.exists():
        existing = sync_log_path.read_text(encoding="utf-8")
        # Insert after header
        if existing.startswith("# "):
            header_end = existing.find("\n\n") + 2
            new_content = existing[:header_end] + entry + existing[header_end:]
        else:
            new_content = entry + existing
    else:
        new_content = "# Skills Synchronization Log\n\n" + entry

    sync_log_path.write_text(new_content, encoding="utf-8")


# ============================================================================
# Configuration Synchronization Commands
# ============================================================================


@cli.group()
def config() -> None:
    """Configuration file synchronization commands.

    Sync Claude Code configuration files between local (~/.claude/) and repository.

    \b
    Synced files:
    - settings.json (with path transformation)
    - CLAUDE.md, COMMANDS.md, FLAGS.md, etc.
    - hooks/ directory

    \b
    Path placeholders:
    - {{HOME}}         -> /Users/username or /home/username
    - {{CLAUDE_DIR}}   -> ~/.claude
    - {{WORKSPACE_DIR}} -> ~/gitbase (or CLAUDE_WORKSPACE_DIR env var)
    """
    pass


@config.command("sync")
@click.option("--dry-run", "-n", is_flag=True, help="Preview changes without applying")
@click.option(
    "--direction",
    "-d",
    type=click.Choice(["auto", "export", "import"]),
    default="auto",
    help="Sync direction: auto (detect), export (local->repo), import (repo->local)",
)
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompts")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--include-hooks", is_flag=True, help="Also sync hooks directory")
def config_sync(
    dry_run: bool,
    direction: str,
    force: bool,
    verbose: bool,
    include_hooks: bool,
) -> None:
    """Synchronize configuration files between local and repository.

    Detects changes and syncs settings.json (with path transformation)
    and framework files (CLAUDE.md, etc.).

    \b
    Examples:
        sccs config sync              # Auto-detect direction
        sccs config sync -d export    # Export local to repo
        sccs config sync -d import    # Import repo to local
        sccs config sync --dry-run    # Preview changes
    """
    local_dir = Path.home() / ".claude"
    repo_dir = get_repo_root() / ".claude" / "config"

    sync_logger = SyncLogger(console, verbose=verbose)

    sync_logger.info(f"Local:  {local_dir}")
    sync_logger.info(f"Repo:   {repo_dir}")
    console.print()

    # Ensure repo directory exists
    if not dry_run:
        repo_dir.mkdir(parents=True, exist_ok=True)

    # Load state
    state_path = get_repo_root() / ".config_sync_state.json"
    state = ConfigSyncState.load(state_path)

    # Initialize engine
    engine = ConfigSyncEngine(
        local_claude_dir=local_dir,
        repo_config_dir=repo_dir,
        state=state,
        dry_run=dry_run,
    )

    # Detect changes
    actions = engine.detect_changes()

    # Filter by direction if specified
    if direction == "export":
        actions = [
            a
            for a in actions
            if a.action_type
            in (ConfigActionType.EXPORT, ConfigActionType.NEW_LOCAL, ConfigActionType.CONFLICT)
        ]
        for a in actions:
            if a.action_type == ConfigActionType.CONFLICT:
                a.action_type = ConfigActionType.EXPORT
    elif direction == "import":
        actions = [
            a
            for a in actions
            if a.action_type
            in (ConfigActionType.IMPORT, ConfigActionType.NEW_REPO, ConfigActionType.CONFLICT)
        ]
        for a in actions:
            if a.action_type == ConfigActionType.CONFLICT:
                a.action_type = ConfigActionType.IMPORT

    # Filter out unchanged
    pending = [a for a in actions if a.action_type != ConfigActionType.UNCHANGED]

    if not pending:
        sync_logger.success("Configuration is in sync!")
        return

    # Show planned actions
    _show_config_actions_table(pending, dry_run, console)

    if dry_run:
        sync_logger.info("Dry-run mode - no changes applied")
        return

    # Confirm
    if not force:
        if not Confirm.ask("Proceed with config sync?", default=True):
            sync_logger.warning("Config sync cancelled")
            return

    # Execute actions
    executed = 0
    errors = []

    for action in pending:
        try:
            resolution = None
            if action.action_type == ConfigActionType.CONFLICT:
                # In auto mode, ask user
                console.print(f"\n[yellow]Conflict:[/yellow] {action.file_name}")
                console.print(f"  Local:  {datetime.fromtimestamp(action.local_mtime or 0, tz=timezone.utc)}")
                console.print(f"  Repo:   {datetime.fromtimestamp(action.repo_mtime or 0, tz=timezone.utc)}")
                choice = click.prompt(
                    "  Resolution",
                    type=click.Choice(["local", "repo", "skip"]),
                    default="local" if (action.local_mtime or 0) > (action.repo_mtime or 0) else "repo",
                )
                if choice == "skip":
                    continue
                resolution = choice

            if engine.execute_action(action, resolution):
                executed += 1
                action_str = _get_action_verb(action.action_type, resolution)
                sync_logger.success(f"{action_str}: {action.file_name}")
            else:
                errors.append(f"{action.file_name}: {action.details}")

        except Exception as e:
            errors.append(f"{action.file_name}: {e}")
            sync_logger.error(f"Error: {action.file_name} - {e}")

    # Sync hooks if requested
    if include_hooks:
        local_hooks = local_dir / "hooks"
        repo_hooks = repo_dir / "hooks"

        if direction in ("auto", "export") and local_hooks.exists():
            sync_logger.info("Syncing hooks (export)...")
            synced = sync_hooks_directory(local_hooks, repo_hooks, "export", dry_run)
            if synced:
                executed += len(synced)
                for name in synced:
                    sync_logger.success(f"Exported hook: {name}")
        elif direction == "import" and repo_hooks.exists():
            sync_logger.info("Syncing hooks (import)...")
            synced = sync_hooks_directory(local_hooks, repo_hooks, "import", dry_run)
            if synced:
                executed += len(synced)
                for name in synced:
                    sync_logger.success(f"Imported hook: {name}")

    # Save state
    if not dry_run:
        engine.save_state(state_path)

    # Summary
    console.print()
    if executed > 0:
        sync_logger.success(f"Config sync complete: {executed} file(s) synchronized")
    if errors:
        for err in errors:
            sync_logger.error(err)


@config.command("status")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
def config_status(verbose: bool) -> None:
    """Show configuration sync status."""
    local_dir = Path.home() / ".claude"
    repo_dir = get_repo_root() / ".claude" / "config"

    logger.info(f"Local:  {local_dir}")
    logger.info(f"Repo:   {repo_dir}")
    console.print()

    # Check what files exist
    console.print("[bold]Syncable Files:[/bold]")
    console.print()

    from rich.table import Table

    table = Table(show_header=True)
    table.add_column("File", style="cyan")
    table.add_column("Local", style="green")
    table.add_column("Repo", style="blue")
    table.add_column("Transform", style="magenta")

    all_files = set(DIRECT_SYNC_FILES + TRANSFORM_FILES)

    for file_name in sorted(all_files):
        local_exists = (local_dir / file_name).exists()
        repo_exists = (repo_dir / file_name).exists() or (
            repo_dir / file_name.replace(".json", ".template.json")
        ).exists()
        needs_transform = file_name in TRANSFORM_FILES

        local_str = "✓" if local_exists else "✗"
        repo_str = "✓" if repo_exists else "✗"
        transform_str = "Yes" if needs_transform else "No"

        table.add_row(file_name, local_str, repo_str, transform_str)

    console.print(table)

    # Show pending changes
    state_path = get_repo_root() / ".config_sync_state.json"
    state = ConfigSyncState.load(state_path)
    engine = ConfigSyncEngine(
        local_claude_dir=local_dir,
        repo_config_dir=repo_dir,
        state=state,
        dry_run=True,
    )

    actions = engine.detect_changes()
    pending = [a for a in actions if a.action_type != ConfigActionType.UNCHANGED]

    console.print()
    if pending:
        _show_config_actions_table(pending, dry_run=True, console_obj=console)
    else:
        logger.success("Configuration is in sync!")

    # Show last sync time
    if state.last_sync_time:
        console.print(f"\n[dim]Last config sync: {state.last_sync_time}[/dim]")


@config.command("export")
@click.argument("file", required=False)
@click.option("--dry-run", "-n", is_flag=True, help="Preview without applying")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files")
def config_export(file: Optional[str], dry_run: bool, force: bool) -> None:
    """Export local config to repository.

    FILE: Specific file to export (optional, exports all if not specified)

    \b
    Examples:
        sccs config export                    # Export all
        sccs config export settings.json      # Export specific file
        sccs config export CLAUDE.md          # Export framework file
    """
    local_dir = Path.home() / ".claude"
    repo_dir = get_repo_root() / ".claude" / "config"

    if not dry_run:
        repo_dir.mkdir(parents=True, exist_ok=True)

    if file:
        files_to_export = [file]
    else:
        files_to_export = DIRECT_SYNC_FILES + TRANSFORM_FILES

    exported = 0
    for file_name in files_to_export:
        local_path = local_dir / file_name
        if not local_path.exists():
            if file:  # Only warn if specific file requested
                logger.warning(f"File not found: {local_path}")
            continue

        content = local_path.read_text(encoding="utf-8")

        if file_name in TRANSFORM_FILES:
            content = PathTransformer.to_placeholders(content)
            repo_path = repo_dir / file_name.replace(".json", ".template.json")
        else:
            repo_path = repo_dir / file_name

        if repo_path.exists() and not force:
            if not dry_run and not Confirm.ask(f"Overwrite {repo_path.name}?", default=True):
                continue

        if dry_run:
            logger.info(f"Would export: {file_name} -> {repo_path.name}")
        else:
            repo_path.write_text(content, encoding="utf-8")
            logger.success(f"Exported: {file_name} -> {repo_path.name}")

        exported += 1

    if exported == 0:
        logger.warning("No files exported")
    elif not dry_run:
        logger.success(f"Exported {exported} file(s)")


@config.command("import")
@click.argument("file", required=False)
@click.option("--dry-run", "-n", is_flag=True, help="Preview without applying")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files")
def config_import(file: Optional[str], dry_run: bool, force: bool) -> None:
    """Import config from repository to local.

    FILE: Specific file to import (optional, imports all if not specified)

    \b
    Examples:
        sccs config import                    # Import all
        sccs config import settings.json      # Import specific file
    """
    local_dir = Path.home() / ".claude"
    repo_dir = get_repo_root() / ".claude" / "config"

    if not repo_dir.exists():
        logger.error(f"Repository config directory not found: {repo_dir}")
        return

    if file:
        files_to_import = [file]
    else:
        # Scan repo directory for available files
        files_to_import = []
        for item in repo_dir.iterdir():
            if item.is_file():
                if item.name.endswith(".template.json"):
                    files_to_import.append(item.name.replace(".template.json", ".json"))
                elif item.name in DIRECT_SYNC_FILES:
                    files_to_import.append(item.name)

    imported = 0
    for file_name in files_to_import:
        if file_name in TRANSFORM_FILES:
            repo_path = repo_dir / file_name.replace(".json", ".template.json")
        else:
            repo_path = repo_dir / file_name

        if not repo_path.exists():
            if file:  # Only warn if specific file requested
                logger.warning(f"File not found: {repo_path}")
            continue

        content = repo_path.read_text(encoding="utf-8")

        if file_name in TRANSFORM_FILES:
            content = PathTransformer.from_placeholders(content)

        local_path = local_dir / file_name

        if local_path.exists() and not force:
            if not dry_run and not Confirm.ask(f"Overwrite {local_path.name}?", default=True):
                continue

        if dry_run:
            logger.info(f"Would import: {repo_path.name} -> {file_name}")
        else:
            local_path.write_text(content, encoding="utf-8")
            logger.success(f"Imported: {repo_path.name} -> {file_name}")

        imported += 1

    if imported == 0:
        logger.warning("No files imported")
    elif not dry_run:
        logger.success(f"Imported {imported} file(s)")


@config.command("show-paths")
def config_show_paths() -> None:
    """Show current path placeholder values.

    Displays what each placeholder resolves to on this machine.
    """
    from rich.table import Table
    from sccs.config_sync import PLACEHOLDERS

    table = Table(title="Path Placeholders", show_header=True)
    table.add_column("Placeholder", style="cyan")
    table.add_column("Value", style="green")

    for placeholder, value_func in sorted(PLACEHOLDERS.items()):
        table.add_row(placeholder, value_func())

    console.print(table)


@config.command("check")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
def config_check(file: Path) -> None:
    """Check a file for untransformed absolute paths.

    Useful to verify that a template file doesn't contain
    machine-specific paths.

    \b
    Example:
        sccs config check .claude/config/settings.template.json
    """
    content = file.read_text(encoding="utf-8")
    paths = PathTransformer.detect_absolute_paths(content)

    if paths:
        logger.warning(f"Found {len(paths)} absolute path(s) that may need transformation:")
        for path in sorted(set(paths)):
            console.print(f"  [yellow]{path}[/yellow]")
        console.print()
        console.print("[dim]These paths will not work on other machines.[/dim]")
        console.print("[dim]Consider using placeholders like {{HOME}} or {{CLAUDE_DIR}}[/dim]")
    else:
        logger.success("No absolute paths detected - file is portable!")


def _show_config_actions_table(
    actions: list, dry_run: bool, console_obj: Console
) -> None:
    """Display config sync actions in a table."""
    from rich.table import Table

    title = "Planned Config Actions" if dry_run else "Config Sync Actions"
    table = Table(title=title, show_header=True)
    table.add_column("Action", style="cyan")
    table.add_column("File", style="green")
    table.add_column("Transform", style="magenta")

    for action in actions:
        action_str = _get_action_str(action.action_type)
        transform_str = "Yes" if action.requires_transform else "No"
        table.add_row(action_str, action.file_name, transform_str)

    console_obj.print()
    console_obj.print(table)
    console_obj.print()


def _get_action_str(action_type: ConfigActionType) -> str:
    """Get display string for action type."""
    mapping = {
        ConfigActionType.EXPORT: "[green]EXPORT[/green] (local→repo)",
        ConfigActionType.IMPORT: "[blue]IMPORT[/blue] (repo→local)",
        ConfigActionType.NEW_LOCAL: "[green]NEW[/green] (export)",
        ConfigActionType.NEW_REPO: "[blue]NEW[/blue] (import)",
        ConfigActionType.CONFLICT: "[yellow]CONFLICT[/yellow]",
        ConfigActionType.UNCHANGED: "[dim]unchanged[/dim]",
    }
    return mapping.get(action_type, str(action_type))


def _get_action_verb(action_type: ConfigActionType, resolution: Optional[str] = None) -> str:
    """Get verb for completed action."""
    if resolution == "local" or action_type in (ConfigActionType.EXPORT, ConfigActionType.NEW_LOCAL):
        return "Exported"
    elif resolution == "repo" or action_type in (ConfigActionType.IMPORT, ConfigActionType.NEW_REPO):
        return "Imported"
    return "Synced"


if __name__ == "__main__":
    cli()
