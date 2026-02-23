# SCCS Memory CLI Commands
# Click command group for memory bridge operations

from __future__ import annotations

import sys
from pathlib import Path

import click

from sccs.memory.filter import MemoryFilter
from sccs.memory.item import MemoryCategory, MemoryItem
from sccs.memory.manager import MemoryManager


def _get_manager(ctx: click.Context) -> MemoryManager:
    """Get MemoryManager, respecting custom memory_dir from context."""
    memory_dir = ctx.obj.get("memory_dir") if ctx.obj else None
    return MemoryManager(memory_dir=Path(memory_dir) if memory_dir else None)


def _print_item_summary(item: MemoryItem, console: object) -> None:
    """Print a one-line summary of a memory item using Rich console."""
    from rich.console import Console as RichConsole

    c: RichConsole = getattr(console, "_console", console)  # type: ignore[assignment]
    priority_color = {1: "dim", 2: "white", 3: "yellow", 4: "orange1", 5: "red"}
    color = priority_color.get(item.priority, "white")
    expired_marker = " [red][expired][/red]" if item.is_expired else ""
    project_tag = f" [dim]({item.project})[/dim]" if item.project else ""
    tags_str = " ".join(f"[cyan]#{t}[/cyan]" for t in item.tags) if item.tags else ""
    c.print(
        f"  [{color}]●[/{color}] [bold]{item.id}[/bold]{project_tag}"
        f" — {item.title}{expired_marker}"
        f"  [dim]{item.category.value} p{item.priority}[/dim]"
        + (f"  {tags_str}" if tags_str else "")
    )


@click.group("memory")
@click.pass_context
def memory_group(ctx: click.Context) -> None:
    """Memory Bridge – persistent context between Claude Code and Claude.ai.

    \b
    Memory items are stored as ~/.claude/memory/<slug>/MEMORY.md
    and synced via the claude_memory SCCS category.

    \b
    Quick start:
        sccs memory add "My Decision" --content "..." --tag decision
        sccs memory list
        sccs memory export
    """
    ctx.ensure_object(dict)


@memory_group.command("add")
@click.argument("title")
@click.option("--content", "-c", default="", help="Initial content (Markdown)")
@click.option("--from-stdin", is_flag=True, help="Read content from stdin")
@click.option("--from-file", type=click.Path(exists=True), help="Read content from file")
@click.option("--tag", "-t", multiple=True, help="Tags (can repeat: -t foo -t bar)")
@click.option("--project", "-p", default=None, help="Project name")
@click.option(
    "--priority",
    type=click.IntRange(1, 5),
    default=2,
    show_default=True,
    help="Priority 1 (low) – 5 (critical)",
)
@click.option("--expires", default=None, help="Expiry date (ISO format: 2026-12-31)")
@click.option(
    "--category",
    "cat",
    type=click.Choice([c.value for c in MemoryCategory]),
    default=MemoryCategory.CONTEXT.value,
    show_default=True,
)
@click.pass_context
def memory_add(
    ctx: click.Context,
    title: str,
    content: str,
    from_stdin: bool,
    from_file: str | None,
    tag: tuple[str, ...],
    project: str | None,
    priority: int,
    expires: str | None,
    cat: str,
) -> None:
    """Add a new memory item."""
    console = ctx.obj.get("console") if ctx.obj else None

    # Resolve content
    body = content
    if from_stdin:
        body = sys.stdin.read()
    elif from_file:
        body = Path(from_file).read_text(encoding="utf-8")

    # Parse expires
    expiry = None
    if expires:
        from datetime import datetime

        try:
            expiry = datetime.fromisoformat(expires)
        except ValueError:
            click.echo(f"Error: Invalid date format for --expires: {expires}", err=True)
            sys.exit(1)

    manager = _get_manager(ctx)
    item = manager.add(
        title=title,
        body=body,
        category=MemoryCategory(cat),
        project=project,
        tags=list(tag),
        priority=priority,
        expires=expiry,
    )

    if console:
        console.print_success(f"Memory item created: {item.id}")
        console.print(f"  Path: {manager.memory_dir / item.slug / 'MEMORY.md'}")
    else:
        click.echo(f"Created: {item.id}")


@memory_group.command("list")
@click.option("--project", "-p", default=None, help="Filter by project")
@click.option("--tag", "-t", multiple=True, help="Filter by tag")
@click.option("--category", "cat", default=None, help="Filter by category")
@click.option("--min-priority", type=click.IntRange(1, 5), default=1, help="Minimum priority")
@click.option("--expired", is_flag=True, help="Include expired items")
@click.pass_context
def memory_list(
    ctx: click.Context,
    project: str | None,
    tag: tuple[str, ...],
    cat: str | None,
    min_priority: int,
    expired: bool,
) -> None:
    """List memory items."""
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    filt = MemoryFilter(
        project=project,
        tags=list(tag),
        category=cat,
        min_priority=min_priority,
        include_expired=expired,
    )
    items = filt.apply(manager.load_all())

    if not items:
        msg = "No memory items found"
        if console:
            console.print_info(msg)
        else:
            click.echo(msg)
        return

    if console:
        console.print(f"\n[bold]Memory items ({len(items)}):[/bold]")
        for item in items:
            _print_item_summary(item, console)
    else:
        for item in items:
            click.echo(f"  {item.id}: {item.title} [p{item.priority}]")


@memory_group.command("show")
@click.argument("slug")
@click.option("--raw", is_flag=True, help="Show raw Markdown including frontmatter")
@click.pass_context
def memory_show(ctx: click.Context, slug: str, raw: bool) -> None:
    """Show a memory item."""
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    try:
        item = manager.load(slug)
    except FileNotFoundError:
        msg = f"Memory item not found: {slug}"
        if console:
            console.print_error(msg)
        else:
            click.echo(f"Error: {msg}", err=True)
        sys.exit(1)

    if raw:
        path = manager._item_path(slug)
        click.echo(path.read_text(encoding="utf-8"))
        return

    if console:
        console.print(f"\n[bold cyan]{item.title}[/bold cyan]  [dim]({item.id})[/dim]")
        console.print(f"  Category: {item.category.value}  Priority: {item.priority}")
        if item.project:
            console.print(f"  Project: {item.project}")
        if item.tags:
            console.print(f"  Tags: {', '.join(item.tags)}")
        console.print(f"  Updated: {item.updated.strftime('%Y-%m-%d %H:%M')}")
        if item.expires:
            console.print(f"  Expires: {item.expires.strftime('%Y-%m-%d')}")
        console.print(f"\n{item.body}")
    else:
        click.echo(f"# {item.title} ({item.id})")
        click.echo(f"Category: {item.category.value} | Priority: {item.priority}")
        click.echo("")
        click.echo(item.body)


@memory_group.command("edit")
@click.argument("slug")
@click.pass_context
def memory_edit(ctx: click.Context, slug: str) -> None:
    """Open a memory item in $EDITOR."""
    import os
    import shutil
    import subprocess

    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    if not manager.exists(slug):
        msg = f"Memory item not found: {slug}"
        if console:
            console.print_error(msg)
        else:
            click.echo(f"Error: {msg}", err=True)
        sys.exit(1)

    editor = os.environ.get("EDITOR", "nano")
    if not shutil.which(editor):
        click.echo(f"Error: Editor not found: {editor}", err=True)
        sys.exit(1)

    path = manager._item_path(slug)
    subprocess.run([editor, str(path)], check=False)


@memory_group.command("update")
@click.argument("slug")
@click.option("--extend", "extend_body", default=None, help="Append content to body")
@click.option("--tag", "-t", multiple=True, help="Replace tags")
@click.option("--priority", type=click.IntRange(1, 5), default=None, help="New priority")
@click.option("--bump-version", is_flag=True, help="Increment version number")
@click.option("--project", "-p", default=None, help="New project name")
@click.pass_context
def memory_update(
    ctx: click.Context,
    slug: str,
    extend_body: str | None,
    tag: tuple[str, ...],
    priority: int | None,
    bump_version: bool,
    project: str | None,
) -> None:
    """Update an existing memory item."""
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    try:
        item = manager.update(
            slug,
            extend_body=extend_body,
            tags=list(tag) if tag else None,
            priority=priority,
            bump_version=bump_version,
            project=project,
        )
        if console:
            console.print_success(f"Updated: {item.id} (v{item.version})")
        else:
            click.echo(f"Updated: {item.id}")
    except FileNotFoundError:
        msg = f"Memory item not found: {slug}"
        if console:
            console.print_error(msg)
        else:
            click.echo(f"Error: {msg}", err=True)
        sys.exit(1)


@memory_group.command("delete")
@click.argument("slug")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def memory_delete(ctx: click.Context, slug: str, force: bool) -> None:
    """Archive (soft-delete) a memory item."""
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    if not manager.exists(slug):
        msg = f"Memory item not found: {slug}"
        if console:
            console.print_error(msg)
        else:
            click.echo(f"Error: {msg}", err=True)
        sys.exit(1)

    if not force:
        confirmed = click.confirm(f"Archive memory item '{slug}'?", default=False)
        if not confirmed:
            click.echo("Aborted.")
            return

    if manager.delete(slug):
        msg = f"Archived: {slug}"
        if console:
            console.print_success(msg)
        else:
            click.echo(msg)
    else:
        click.echo(f"Error: Failed to archive {slug}", err=True)
        sys.exit(1)


@memory_group.command("search")
@click.argument("query")
@click.option("--project", "-p", default=None, help="Filter by project")
@click.pass_context
def memory_search(ctx: click.Context, query: str, project: str | None) -> None:
    """Search memory items by text query."""
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    results = manager.search(query, project=project)

    if not results:
        msg = f"No results for: {query}"
        if console:
            console.print_info(msg)
        else:
            click.echo(msg)
        return

    if console:
        console.print(f"\n[bold]Search results ({len(results)}):[/bold]")
        for item in results:
            _print_item_summary(item, console)
    else:
        for item in results:
            click.echo(f"  {item.id}: {item.title}")


@memory_group.command("export")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["claude_block", "markdown", "json"]),
    default="claude_block",
    show_default=True,
)
@click.option("--project", "-p", default=None, help="Filter by project")
@click.option("--tag", "-t", multiple=True, help="Filter by tag")
@click.option("--out", type=click.Path(), default=None, help="Write output to file")
@click.option("--api", is_flag=True, help="Upload to Anthropic Files API")
@click.option("--min-priority", type=click.IntRange(1, 5), default=1, help="Minimum priority")
@click.pass_context
def memory_export(
    ctx: click.Context,
    fmt: str,
    project: str | None,
    tag: tuple[str, ...],
    out: str | None,
    api: bool,
    min_priority: int,
) -> None:
    """Export memory items for use in Claude.ai.

    \b
    Formats:
        claude_block  <memory>...</memory> block for Claude.ai system prompt
        markdown      Plain Markdown
        json          Machine-readable JSON
    """
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    filt = MemoryFilter(project=project, tags=list(tag), min_priority=min_priority)
    items = filt.apply(manager.load_all())

    if not items:
        msg = "No memory items to export"
        if console:
            console.print_info(msg)
        else:
            click.echo(msg)
        return

    from sccs.memory.bridge import ClaudeAiBridge

    if fmt == "claude_block":
        output = ClaudeAiBridge.export_to_context_block(items)
    elif fmt == "markdown":
        lines = []
        for item in items:
            lines.append(f"## {item.title}")
            lines.append(f"*{item.category.value} | Priority: {item.priority}*\n")
            lines.append(item.body)
            lines.append("")
        output = "\n".join(lines)
    else:  # json
        import json

        output = json.dumps(ClaudeAiBridge.export_to_json(items), ensure_ascii=False, indent=2)

    if out:
        Path(out).write_text(output, encoding="utf-8")
        msg = f"Exported {len(items)} items to {out}"
        if console:
            console.print_success(msg)
        else:
            click.echo(msg)
    else:
        click.echo(output)

    if api:
        try:
            from sccs.memory.api import AnthropicMemorySync

            sync = AnthropicMemorySync()
            result = sync.sync_to_api(items)
            msg = f"API: {len(result['uploaded'])} uploaded, {len(result['failed'])} failed"
            if console:
                console.print_info(msg)
            else:
                click.echo(msg)
        except RuntimeError as e:
            if console:
                console.print_error(str(e))
            else:
                click.echo(f"Error: {e}", err=True)
            sys.exit(1)


@memory_group.command("import")
@click.argument("path", type=click.Path(exists=True))
@click.option("--preview", is_flag=True, help="Show candidates without saving")
@click.pass_context
def memory_import(ctx: click.Context, path: str, preview: bool) -> None:
    """Import memory items from a Claude.ai conversation export."""
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    from sccs.memory.bridge import ClaudeAiBridge

    try:
        candidates = ClaudeAiBridge.import_conversation(Path(path), interactive=not preview)
    except Exception as e:
        msg = f"Import failed: {e}"
        if console:
            console.print_error(msg)
        else:
            click.echo(f"Error: {msg}", err=True)
        sys.exit(1)

    if preview:
        if console:
            console.print(f"\n[bold]Import candidates ({len(candidates)}):[/bold]")
            for item in candidates:
                _print_item_summary(item, console)
        else:
            for item in candidates:
                click.echo(f"  {item.id}: {item.title}")
        return

    for item in candidates:
        item.save_to_dir(manager.memory_dir)

    msg = f"Imported {len(candidates)} memory items"
    if console:
        console.print_success(msg)
    else:
        click.echo(msg)


@memory_group.command("expire")
@click.pass_context
def memory_expire(ctx: click.Context) -> None:
    """Archive all expired memory items."""
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    expired = manager.expire_items()

    if not expired:
        msg = "No expired items found"
        if console:
            console.print_info(msg)
        else:
            click.echo(msg)
        return

    msg = f"Archived {len(expired)} expired items"
    if console:
        console.print_success(msg)
        for item in expired:
            console.print(f"  [dim]→ {item.id}[/dim]")
    else:
        click.echo(msg)
        for item in expired:
            click.echo(f"  → {item.id}")


@memory_group.command("stats")
@click.pass_context
def memory_stats(ctx: click.Context) -> None:
    """Show memory statistics."""
    console = ctx.obj.get("console") if ctx.obj else None
    manager = _get_manager(ctx)

    stats = manager.stats()

    if console:
        console.print("\n[bold]Memory Statistics:[/bold]")
        console.print(f"  Total items: {stats['total']}")
        console.print(f"  Archived:    {stats['archived']}")
        console.print(f"  Expired:     {stats['expired']}")
        if stats["by_category"]:
            console.print("\n  [bold]By Category:[/bold]")
            for cat, count in sorted(stats["by_category"].items()):
                console.print(f"    {cat}: {count}")
        if stats["by_project"]:
            console.print("\n  [bold]By Project:[/bold]")
            for proj, count in sorted(stats["by_project"].items()):
                console.print(f"    {proj}: {count}")
    else:
        click.echo(f"Total: {stats['total']}  Archived: {stats['archived']}  Expired: {stats['expired']}")
        for cat, count in sorted(stats["by_category"].items()):
            click.echo(f"  {cat}: {count}")
