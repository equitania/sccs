# SCCS Doctor Reporter
# Rich-based status table for `sccs doctor check` and the inline summary
# shown by `sccs status`.

from __future__ import annotations

from rich.table import Table

from sccs.doctor.detectors import (
    BrowserBundleStatus,
    BundledSkillStatus,
    ClaudeCliStatus,
    MarketplaceStatus,
    NodeStatus,
    NpxToolStatus,
    PathPrefixStatus,
    PermissionStatus,
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


def _marketplace_row(status: MarketplaceStatus) -> tuple[str, str, str]:
    label = f"marketplace: {status.name}"
    if status.skipped_reason:
        return (label, _UNKNOWN, status.skipped_reason)
    if status.registered:
        return (label, _OK, "registered")
    if status.suggested_source:
        return (label, _MISSING, f"not registered — try `claude plugin marketplace add {status.suggested_source}`")
    return (label, _MISSING, "not registered — no marketplace_source configured")


def _path_prefix_row(status: PathPrefixStatus) -> tuple[str, str, str]:
    label = f"path: {status.spec.identifier}"
    if status.skipped_reason:
        return (label, _UNKNOWN, status.skipped_reason)
    if status.in_path:
        return (label, _OK, status.expected_path)
    return (label, _MISSING, f"{status.expected_path} not on $PATH")


def _permission_row(status: PermissionStatus) -> tuple[str, str, str]:
    label = f"perm: {status.spec.path}"
    if status.skipped_reason:
        return (label, _UNKNOWN, status.skipped_reason)
    if not status.exists:
        return (label, _OK, "will be created on first use")
    if status.ok:
        return (label, _OK, "user-owned, writable")
    bits: list[str] = []
    if not status.is_writable:
        bits.append("not writable")
    if status.offending_paths:
        bits.append(f"{len(status.offending_paths)}+ foreign-owned")
    return (label, _MISSING, ", ".join(bits) or "permission issue")


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


def _bundled_skill_row(status: BundledSkillStatus) -> tuple[str, str, str]:
    label = f"skill: {status.spec.name}"
    if status.skill_md_present:
        return (label, _OK, f"{status.target_path}/SKILL.md")
    return (label, _MISSING, f"SKILL.md missing at {status.target_path}")


def _browser_bundle_row(status: BrowserBundleStatus) -> tuple[str, str, str]:
    label = f"browsers: {status.spec.name}"
    declared = list(status.present.keys())
    if status.all_present:
        return (label, _OK, ", ".join(declared))
    if not status.cache_dir_exists:
        return (label, _MISSING, f"cache dir not found: {status.cache_dir}")
    missing = [name for name, ok in status.present.items() if not ok]
    return (label, _MISSING, f"missing: {', '.join(missing)}")


def render_doctor_report(
    console: Console,
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    min_node_major: int,
    permissions: list[PermissionStatus] | None = None,
    path_prefixes: list[PathPrefixStatus] | None = None,
    marketplaces: list[MarketplaceStatus] | None = None,
    bundled_skills: list[BundledSkillStatus] | None = None,
    browser_bundles: list[BrowserBundleStatus] | None = None,
) -> None:
    """Print the full doctor status table."""
    table = Table(title="SCCS Doctor — System & Plugin Status", show_lines=False)
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Detail", style="dim")

    table.add_row(*_node_row(node, min_node_major))
    table.add_row(*_claude_cli_row(claude_cli))
    if marketplaces:
        for market_st in marketplaces:
            table.add_row(*_marketplace_row(market_st))
    for plugin_st in plugins:
        table.add_row(*_plugin_row(plugin_st))
    for npx_st in npx_tools:
        table.add_row(*_npx_row(npx_st))
    if bundled_skills:
        for skill_st in bundled_skills:
            table.add_row(*_bundled_skill_row(skill_st))
    if browser_bundles:
        for browser_st in browser_bundles:
            table.add_row(*_browser_bundle_row(browser_st))
    if permissions:
        for perm_st in permissions:
            table.add_row(*_permission_row(perm_st))
    if path_prefixes:
        for path_st in path_prefixes:
            table.add_row(*_path_prefix_row(path_st))

    console.print(table)
    console.print(f"[dim]Platform: {node.platform}[/dim]")

    # Detailed remediation block for permission issues — shown below the table
    # so the user gets the exact `sudo chown` command to copy.
    if permissions:
        bad = [p for p in permissions if not p.ok]
        if bad:
            console.print()
            console.print("[yellow]Permission issues — run manually (SCCS never invokes sudo):[/yellow]")
            for p in bad:
                console.print(f"  [dim]{p.spec.purpose}[/dim]")
                if p.offending_paths:
                    sample = "\n    ".join(p.offending_paths[:3])
                    console.print(f"    Examples:\n    {sample}")
                if p.fix_command:
                    console.print(f"  [bold]{p.fix_command}[/bold]")
                console.print()


def has_problems(
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    permissions: list[PermissionStatus] | None = None,
    path_prefixes: list[PathPrefixStatus] | None = None,
    marketplaces: list[MarketplaceStatus] | None = None,
    bundled_skills: list[BundledSkillStatus] | None = None,
    browser_bundles: list[BrowserBundleStatus] | None = None,
) -> bool:
    """Return True if any component is missing/outdated or has a permission issue."""
    if not (node.installed and node.meets_minimum):
        return True
    if not claude_cli.installed:
        return True
    if any(not p.installed for p in plugins):
        return True
    if any(not t.available for t in npx_tools):
        return True
    if permissions and any(not p.ok for p in permissions):
        return True
    if path_prefixes and any(not p.ok for p in path_prefixes):
        return True
    if marketplaces and any(not m.ok for m in marketplaces):
        return True
    if bundled_skills and any(not s.skill_md_present for s in bundled_skills):
        return True
    return bool(browser_bundles and any(not b.all_present for b in browser_bundles))


def render_inline_summary(
    console: Console,
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    permissions: list[PermissionStatus] | None = None,
    path_prefixes: list[PathPrefixStatus] | None = None,
    bundled_skills: list[BundledSkillStatus] | None = None,
    browser_bundles: list[BrowserBundleStatus] | None = None,
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

    if permissions:
        bad = [p for p in permissions if not p.ok]
        if bad:
            parts.append(f"[red]perm issues: {len(bad)}[/red]")

    if path_prefixes:
        bad_paths = [p for p in path_prefixes if not p.ok]
        if bad_paths:
            parts.append(f"[red]PATH issues: {len(bad_paths)}[/red]")

    if bundled_skills:
        missing_skills = [s.spec.name for s in bundled_skills if not s.skill_md_present]
        if missing_skills:
            parts.append(f"[red]skills missing: {len(missing_skills)}[/red]")

    if browser_bundles:
        missing_browsers = [b.spec.name for b in browser_bundles if not b.all_present]
        if missing_browsers:
            parts.append(f"[red]browsers missing: {len(missing_browsers)}[/red]")

    console.print(f"[bold]doctor:[/bold] {' · '.join(parts)}")


def render_execute_result(console: Console, result: ExecuteResult) -> None:
    """Print the outcome summary of an executed plan.

    Five buckets: executed (green), warned (yellow soft-fails), printed
    (manual blocks the user must act on), skipped (cascade-skip + user
    declined), failed (red unrecovered errors). Skipped rows include the
    blocking dependency so users can trace the cascade back to its root
    cause without scrolling through subprocess output.
    """
    if result.executed:
        console.print_success(f"Executed: {len(result.executed)}")
        for o in result.executed:
            console.print(f"  [green]+[/green] {o.label}")
    if result.warned:
        console.print(f"[yellow]Warnings:[/yellow] {len(result.warned)}")
        for o in result.warned:
            console.print(f"  [yellow]![/yellow] {o.label} — {o.detail}")
    if result.printed:
        console.print(f"[blue]Manual blocks shown:[/blue] {len(result.printed)}")
        for o in result.printed:
            console.print(f"  [blue]i[/blue] {o.label}")
    if result.skipped:
        console.print(f"[dim]Skipped: {len(result.skipped)}[/dim]")
        for o in result.skipped:
            suffix = f" — {o.detail}" if o.detail else ""
            console.print(f"  [dim]⊘[/dim] {o.label}{suffix}")
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
