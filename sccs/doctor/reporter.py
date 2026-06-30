# SCCS Doctor Reporter
# Rich-based status table for `sccs doctor check` and the inline summary
# shown by `sccs status`.

from __future__ import annotations

from rich.table import Table

from sccs.doctor.detectors import (
    BrowserBundleStatus,
    BundledSkillStatus,
    ClaudeCliStatus,
    CliToolStatus,
    GsdOrphanStatus,
    MarketplaceStatus,
    NodeStatus,
    NpxToolStatus,
    PathPrefixStatus,
    PermissionStatus,
    PluginStatus,
    PowerShellStatus,
    StatusLineStatus,
)
from sccs.doctor.installer import ExecuteResult, _npm_global_fix_block
from sccs.output.console import Console

# Status icons reused across the reporter.
_OK = "[green]OK[/green]"
_MISSING = "[red]MISSING[/red]"
_OUTDATED = "[yellow]OUTDATED[/yellow]"
_MANUAL = "[blue]MANUAL[/blue]"
_STALE = "[yellow]STALE[/yellow]"
_INFO = "[blue]INFO[/blue]"
_UNKNOWN = "[dim]?[/dim]"


# Each row function returns (Component, Status, Version, Detail). The Version
# column is filled for components that carry a meaningful version (Node, the
# Claude plugins, the npx tools); everything else passes "" so the column
# stays aligned.


def _node_row(status: NodeStatus, min_major: int) -> tuple[str, str, str, str]:
    if not status.installed:
        return ("Node.js", _MISSING, "", f"need >= {min_major}.x")
    if not status.meets_minimum:
        return ("Node.js", _OUTDATED, f"v{status.version}", f"< {min_major}.x required")
    return ("Node.js", _OK, f"v{status.version}", "")


def _powershell_row(status: PowerShellStatus, min_major: int) -> tuple[str, str, str, str]:
    if not status.installed:
        return ("PowerShell 7+ (pwsh)", _MISSING, "", f"need >= {min_major}.x — install below")
    if not status.meets_minimum:
        return ("PowerShell 7+ (pwsh)", _OUTDATED, f"v{status.version}", f"< {min_major}.x — upgrade below")
    return ("PowerShell 7+ (pwsh)", _OK, f"v{status.version}", "")


def _claude_cli_row(status: ClaudeCliStatus) -> tuple[str, str, str, str]:
    if not status.installed:
        return ("Claude CLI", _MISSING, "", "binary 'claude' not on PATH")
    return ("Claude CLI", _OK, "", status.binary_path or "found")


def _plugin_row(status: PluginStatus) -> tuple[str, str, str, str]:
    label = status.spec.install_target
    version = f"v{status.version}" if status.version else ""
    # Source suffix: the marketplace is already in the Component label
    # (name@marketplace); marketplace_source adds the upstream repo when set.
    src = f" · {status.spec.marketplace_source}" if status.spec.marketplace_source else ""
    if not status.installed:
        return (f"plugin: {label}", _MISSING, "", "not in `claude plugin list`")
    if status.update_available:
        latest = f" → v{status.latest_version}" if status.latest_version else ""
        return (f"plugin: {label}", _OUTDATED, version, f"update available{latest}{src}")
    if status.detection_source == "alternative" and status.found_marketplace:
        # Installed under a different marketplace than configured. This is NOT
        # "outdated": `claude plugin` has no update-available signal, and the
        # status never converges (the plugin won't reappear under the configured
        # marketplace). Report as INFO, not a yellow OUTDATED that nags forever.
        return (
            f"plugin: {label}",
            _INFO,
            version,
            f"installed via {status.found_marketplace}",
        )
    if status.detection_source == "bare":
        return (f"plugin: {label}", _OK, version, f"installed (no marketplace shown){src}")
    return (f"plugin: {label}", _OK, version, f"installed{src}")


def _marketplace_row(status: MarketplaceStatus) -> tuple[str, str, str, str]:
    label = f"marketplace: {status.name}"
    if status.skipped_reason:
        return (label, _UNKNOWN, "", status.skipped_reason)
    if status.registered:
        return (label, _OK, "", "registered")
    if status.suggested_source:
        return (label, _MISSING, "", f"not registered — try `claude plugin marketplace add {status.suggested_source}`")
    return (label, _MISSING, "", "not registered — no marketplace_source configured")


def _path_prefix_row(status: PathPrefixStatus) -> tuple[str, str, str, str]:
    label = f"path: {status.spec.identifier}"
    if status.skipped_reason:
        return (label, _UNKNOWN, "", status.skipped_reason)
    if status.in_path:
        return (label, _OK, "", status.expected_path)
    return (label, _MISSING, "", f"{status.expected_path} not on $PATH")


def _status_line_row(status: StatusLineStatus) -> tuple[str, str, str, str]:
    label = f"statusline: {status.spec.identifier}"
    state = status.state
    if state == "ok":
        return (label, _OK, "", status.detail)
    if state == "missing":
        return (label, _MISSING, "", status.detail)
    if state == "missing_binary":
        return (label, _MISSING, "", status.detail)
    if state == "missing_script":
        return (label, _MISSING, "", status.detail)
    if state == "stale_cellar":
        return (label, _STALE, "", status.detail)
    if state == "opaque":
        return (label, _INFO, "", status.detail)
    if state == "no_settings_file":
        return (label, _UNKNOWN, "", status.detail)
    return (label, _UNKNOWN, "", status.detail)  # pragma: no cover


def _permission_row(status: PermissionStatus) -> tuple[str, str, str, str]:
    label = f"perm: {status.spec.path}"
    if status.skipped_reason:
        return (label, _UNKNOWN, "", status.skipped_reason)
    if not status.exists:
        return (label, _OK, "", "will be created on first use")
    if status.ok:
        return (label, _OK, "", "user-owned, writable")
    bits: list[str] = []
    if not status.is_writable:
        bits.append("not writable")
    if status.offending_paths:
        bits.append(f"{len(status.offending_paths)}+ foreign-owned")
    return (label, _MISSING, "", ", ".join(bits) or "permission issue")


def _npx_row(status: NpxToolStatus) -> tuple[str, str, str, str]:
    label = f"npx: {status.spec.name}"
    version = f"v{status.version}" if status.version else ""
    if not status.available:
        if status.spec.detect_via_state:
            return (label, _MISSING, "", "no successful run on record")
        return (label, _MISSING, "", "binary not on PATH")
    if status.update_available:
        latest = f"update available: v{status.latest_version}" if status.latest_version else "update available"
        return (label, _OUTDATED, version, latest)
    if status.detection_source == "state":
        return (label, _OK, version, "installed (last run cached)")
    return (label, _OK, version, status.binary_path or "found")


def _cli_tool_row(status: CliToolStatus) -> tuple[str, str, str, str]:
    """Optional CLI tools (zoxide, coreutils). Informational only — never red
    MISSING and never counted as a problem, so it can't flip the exit code."""
    label = f"tool: {status.spec.name}"
    version = f"v{status.version}" if status.version else ""
    if status.state == "on_path":
        return (label, _OK, version, status.binary_path or "on PATH")
    if status.state == "installed_not_on_path":
        return (label, _STALE, "", "installed via winget, not on PATH — see guidance below")
    return (label, _INFO, "", "not installed (optional) — run `sccs doctor install`")


def _bundled_skill_row(status: BundledSkillStatus) -> tuple[str, str, str, str]:
    label = f"skill: {status.spec.name}"
    if status.skill_md_present:
        return (label, _OK, "", f"{status.target_path}/SKILL.md")
    return (label, _MISSING, "", f"SKILL.md missing at {status.target_path}")


def _browser_bundle_row(status: BrowserBundleStatus) -> tuple[str, str, str, str]:
    label = f"browsers: {status.spec.name}"
    declared = list(status.present.keys())
    if status.all_present:
        return (label, _OK, "", ", ".join(declared))
    if not status.cache_dir_exists:
        return (label, _MISSING, "", f"cache dir not found: {status.cache_dir}")
    missing = [name for name, ok in status.present.items() if not ok]
    return (label, _MISSING, "", f"missing: {', '.join(missing)}")


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
    status_lines: list[StatusLineStatus] | None = None,
    gsd_orphans: list[GsdOrphanStatus] | None = None,
    cli_tools: list[CliToolStatus] | None = None,
    powershell: PowerShellStatus | None = None,
    min_pwsh_major: int = 7,
) -> None:
    """Print the full doctor status table."""
    table = Table(title="SCCS Doctor — System & Plugin Status", show_lines=False)
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Version", style="cyan")
    table.add_column("Detail", style="dim")

    table.add_row(*_node_row(node, min_node_major))
    # Windows-only: the converted PowerShell profile is consumed on Windows, so
    # the pwsh-7 check is noise on macOS/Linux and is hidden there.
    if powershell is not None and powershell.platform == "windows":
        table.add_row(*_powershell_row(powershell, min_pwsh_major))
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
    if status_lines:
        for sl_st in status_lines:
            table.add_row(*_status_line_row(sl_st))
    if cli_tools:
        for cli_st in cli_tools:
            table.add_row(*_cli_tool_row(cli_st))

    console.print(table)
    console.print(f"[dim]Platform: {node.platform}[/dim]")

    # Node.js install/upgrade block — surfaced below the table so `doctor check`
    # gives the exact, copy-pasteable command (e.g. the NodeSource two-liner on
    # Linux) instead of only flagging the version in the table. Mirrors the
    # permission/orphan remediation blocks; the same hint is otherwise only
    # printed by `doctor install`/`update`.
    if not (node.installed and node.meets_minimum) and node.install_hint is not None:
        hint = node.install_hint
        if not node.installed:
            headline = "Node.js missing — install:"
        else:
            headline = f"Node.js v{node.version} is older than the required v{min_node_major}.x — upgrade:"
        console.print()
        console.print(f"[yellow]{headline}[/yellow]")
        console.print(f"  [dim]{hint.label}[/dim]")
        if hint.runnable and hint.cmd:
            console.print(f"  [bold]{' '.join(hint.cmd)}[/bold]")
        elif hint.manual_block:
            # Render each line separately so a multi-step recipe (NodeSource:
            # curl … | sudo -E bash -  /  sudo apt-get install -y nodejs) never
            # collapses onto one line.
            for line in hint.manual_block.splitlines():
                console.print(f"  [bold]{line}[/bold]")
        console.print()

    # PowerShell 7+ install/upgrade suggestion (Windows only) — surfaced below
    # the table so `doctor check` hands over the exact winget command. A
    # suggestion only: SCCS never installs/upgrades PowerShell itself, and this
    # never flips the exit code (has_problems ignores it → CI-friendly).
    if (
        powershell is not None
        and powershell.platform == "windows"
        and not (powershell.installed and powershell.meets_minimum)
    ):
        console.print()
        if not powershell.installed:
            console.print("[yellow]PowerShell 7+ not found — install (Windows 11):[/yellow]")
            console.print(f"  [bold]{' '.join(powershell.install_cmd)}[/bold]")
        else:
            console.print(
                f"[yellow]PowerShell v{powershell.version} is older than the recommended "
                f"v{min_pwsh_major}.x — upgrade (Windows 11):[/yellow]"
            )
            console.print(f"  [bold]{' '.join(powershell.upgrade_cmd)}[/bold]")
        console.print("  [dim]winget ships with Windows 11; restart the shell afterwards.[/dim]")
        console.print()

    # Detailed remediation block for permission issues — shown below the table
    # so the user gets the exact `sudo chown` command (or the safe Option-A
    # alternative for system / multi-user prefixes) to copy.
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
                elif p.spec.path_kind in ("npm-root-global", "npm-bin-global"):
                    # `fix_command` is None → system prefix or multi-user dir.
                    # Reuse the installer's manual-fix block so the user never
                    # sees `sudo chown /usr/bin` from `doctor check`.
                    for line in _npm_global_fix_block(p):
                        console.print(f"  {line}")
                else:
                    console.print("  [dim]No safe single-line fix — see `sccs doctor install` for guidance.[/dim]")
                console.print()

    # Orphaned doctor-managed artefacts — surfaced below the table because the
    # cleanup is opt-in (run `sccs doctor update`). Only shown when the current
    # manifest already reveals orphans; pre-migration hosts show nothing here
    # (the redux manifest still owns everything) and get cleaned during update.
    if gsd_orphans:
        flagged = [g for g in gsd_orphans if g.has_orphans]
        if flagged:
            console.print()
            console.print(
                "[yellow]Orphaned doctor-managed artefacts "
                "(run `sccs doctor update` to move them to a backup):[/yellow]"
            )
            for g in flagged:
                console.print(f"  [dim]{g.tool_name} — {g.total} orphan(s) not in the install manifest:[/dim]")
                for orphan_path in g.orphan_paths[:20]:
                    console.print(f"    {orphan_path}")
                if g.total > 20:
                    console.print(f"    [dim]… and {g.total - 20} more[/dim]")
                if g.truncated:
                    console.print("    [dim](list capped — more orphans exist on disk)[/dim]")
            console.print()

    # CLI tools installed (winget) but not on PATH — show the PowerShell PATH
    # snippet below the table so the user can copy it. SCCS never edits the
    # environment itself (consistent with the npm PATH-prefix block).
    if cli_tools:
        from sccs.doctor.installer import _winget_links_path_block

        off_path = [c for c in cli_tools if c.state == "installed_not_on_path"]
        if off_path:
            console.print()
            console.print(
                "[yellow]CLI tools installed but not on PATH "
                "(SCCS never edits your environment — copy & run yourself):[/yellow]"
            )
            for c in off_path:
                console.print(f"  [dim]{c.spec.name}:[/dim]")
                for line in _winget_links_path_block(c.spec.name).splitlines():
                    console.print(f"  {line}")
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
    status_lines: list[StatusLineStatus] | None = None,
    gsd_orphans: list[GsdOrphanStatus] | None = None,
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
    if status_lines and any(not s.ok for s in status_lines):
        return True
    if gsd_orphans and any(g.has_orphans for g in gsd_orphans):
        return True
    return bool(browser_bundles and any(not b.all_present for b in browser_bundles))


def has_updates(
    *,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
) -> bool:
    """Return True if any plugin or npx tool has a newer version available.

    Deliberately separate from `has_problems`: an available update is a hint,
    not a failure, so `doctor check` shows it without flipping the exit code.
    """
    if any(p.update_available for p in plugins):
        return True
    return any(t.update_available for t in npx_tools)


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
    status_lines: list[StatusLineStatus] | None = None,
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
        # Informational, not a problem: installed, just under another marketplace.
        parts.append(f"[dim]alt marketplace: {len(alt_plugins)}[/dim]")

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

    if status_lines:
        bad_status = [s for s in status_lines if not s.ok]
        if bad_status:
            parts.append(f"[red]statusline issues: {len(bad_status)}[/red]")

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
