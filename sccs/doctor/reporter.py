# SCCS Doctor Reporter
# Rich-based status table for `sccs doctor check` and the inline summary
# shown by `sccs status`.

from __future__ import annotations

from rich.table import Table

from sccs.doctor.detectors import (
    ClaudeCliStatus,
    NodeStatus,
    NpxToolStatus,
    PluginStatus,
)
from sccs.doctor.installer import ExecuteResult
from sccs.output.console import Console

# Status icons reused across the reporter.
_OK = "[green]OK[/green]"
_MISSING = "[red]MISSING[/red]"
_OUTDATED = "[yellow]OUTDATED[/yellow]"
_MANUAL = "[blue]MANUAL[/blue]"
_UNKNOWN = "[dim]?[/dim]"


def _node_row(status: NodeStatus, min_major: int) -> tuple[str, str, str]:
    if not status.installed:
        return ("Node.js", _MISSING, f"need >= {min_major}.x")
    if not status.meets_minimum:
        return ("Node.js", _OUTDATED, f"v{status.version} < {min_major}.x")
    return ("Node.js", _OK, f"v{status.version}")


def _claude_cli_row(status: ClaudeCliStatus) -> tuple[str, str, str]:
    if not status.installed:
        return ("Claude CLI", _MISSING, "binary 'claude' not on PATH")
    return ("Claude CLI", _OK, status.binary_path or "found")


def _plugin_row(status: PluginStatus) -> tuple[str, str, str]:
    label = status.spec.install_target
    if not status.installed:
        return (f"plugin: {label}", _MISSING, "not in `claude plugin list`")
    if status.detection_source == "alternative" and status.found_marketplace:
        return (
            f"plugin: {label}",
            _OUTDATED,
            f"installed via {status.found_marketplace}",
        )
    if status.detection_source == "bare":
        return (f"plugin: {label}", _OK, "installed (no marketplace shown)")
    return (f"plugin: {label}", _OK, "installed")


def _npx_row(status: NpxToolStatus) -> tuple[str, str, str]:
    label = f"npx: {status.spec.name}"
    if not status.available:
        if status.spec.detect_via_state:
            return (label, _MISSING, "no successful run on record")
        return (label, _MISSING, "binary not on PATH")
    if status.detection_source == "state":
        mark_detail = "installed (last run cached)"
        return (label, _OK, mark_detail)
    return (label, _OK, status.binary_path or "found")


def render_doctor_report(
    console: Console,
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    min_node_major: int,
) -> None:
    """Print the full doctor status table."""
    table = Table(title="SCCS Doctor — System & Plugin Status", show_lines=False)
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Detail", style="dim")

    table.add_row(*_node_row(node, min_node_major))
    table.add_row(*_claude_cli_row(claude_cli))
    for st in plugins:
        table.add_row(*_plugin_row(st))
    for st in npx_tools:
        table.add_row(*_npx_row(st))

    console.print(table)
    console.print(f"[dim]Platform: {node.platform}[/dim]")


def has_problems(
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
) -> bool:
    """Return True if any component is missing or outdated."""
    if not (node.installed and node.meets_minimum):
        return True
    if not claude_cli.installed:
        return True
    if any(not p.installed for p in plugins):
        return True
    return any(not t.available for t in npx_tools)


def render_inline_summary(
    console: Console,
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
) -> None:
    """One-line summary used by `sccs status`."""
    parts: list[str] = []
    if not node.installed:
        parts.append("[red]node missing[/red]")
    elif not node.meets_minimum:
        parts.append(f"[yellow]node v{node.version} outdated[/yellow]")
    else:
        parts.append(f"[green]node v{node.version}[/green]")

    if not claude_cli.installed:
        parts.append("[red]claude CLI missing[/red]")

    missing_plugins = [p.spec.name for p in plugins if not p.installed]
    if missing_plugins:
        parts.append(f"[red]plugins missing: {len(missing_plugins)}[/red]")
    alt_plugins = [p for p in plugins if p.detection_source == "alternative"]
    if alt_plugins:
        parts.append(f"[yellow]alt marketplace: {len(alt_plugins)}[/yellow]")

    missing_tools = [t.spec.name for t in npx_tools if not t.available]
    if missing_tools:
        parts.append(f"[red]npx tools missing: {len(missing_tools)}[/red]")

    console.print(f"[bold]doctor:[/bold] {' · '.join(parts)}")


def render_execute_result(console: Console, result: ExecuteResult) -> None:
    """Print the outcome summary of an executed plan."""
    if result.executed:
        console.print_success(f"Executed: {len(result.executed)}")
        for o in result.executed:
            console.print(f"  [green]+[/green] {o.label}")
    if result.printed:
        console.print(f"[blue]Manual blocks shown:[/blue] {len(result.printed)}")
        for o in result.printed:
            console.print(f"  [blue]i[/blue] {o.label}")
    if result.skipped:
        console.print(f"[dim]Skipped: {len(result.skipped)}[/dim]")
        for o in result.skipped:
            console.print(f"  [dim]·[/dim] {o.label}")
    if result.failed:
        console.print_error(f"Failed: {len(result.failed)}")
        for o in result.failed:
            console.print(f"  [red]x[/red] {o.label} — {o.detail}")


__all__ = [
    "_MANUAL",
    "_MISSING",
    "_OK",
    "_OUTDATED",
    "_UNKNOWN",
    "has_problems",
    "render_doctor_report",
    "render_execute_result",
    "render_inline_summary",
]
