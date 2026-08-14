# SCCS Doctor Installer
#
# HARD RULES (mirrored from runner.py):
#   1. Confirm-prompt before EVERY runnable action; default = No.
#   2. requires_sudo / runnable=False actions are PRINTED ONLY, never executed.
#   3. argv lists are pre-validated when constructed; runner._run validates again.

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import questionary

from sccs.doctor import scope_patch
from sccs.doctor.detectors import (
    BrowserBundleStatus,
    BundledSkillStatus,
    ClaudeCliStatus,
    CliToolStatus,
    ForeignMCPServerStatus,
    ForeignPluginStatus,
    GsdOrphanDetector,
    GsdOrphanStatus,
    MarketplaceStatus,
    MCPServerStatus,
    NodeStatus,
    NpxToolStatus,
    PathPrefixStatus,
    PermissionStatus,
    PluginStatus,
    SettingsHookViolation,
    StatusLineStatus,
)
from sccs.doctor.runner import DoctorError, _run
from sccs.doctor.schema import BundledSkillSpec, DoctorConfig, NpxToolSpec
from sccs.doctor.state import DoctorStateManager
from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write, expand_path
from sccs.utils.platform import get_current_platform

logger = get_logger("doctor.installer")


@dataclass
class DoctorAction:
    """A single planned install/update step."""

    label: str
    cmd: list[str] | None = None
    manual_block: str | None = None
    runnable: bool = True
    component: str = ""
    # When the action targets an npx tool that needs state-file tracking
    # (detect_via_state=True), the runner records the successful invocation
    # so future `sccs doctor check` calls can still report it as installed.
    npx_tool_name: str | None = None
    npx_invocation: list[str] | None = None
    # In-process callable used instead of subprocess. Needed for actions
    # that involve filesystem operations (e.g. copying a skill out of the
    # npm global root): keeps everything Python-side so we don't have to
    # whitelist `cp` in the runner or shell out for path resolution.
    python_callable: Callable[[], None] | None = None
    # --- Cascade-Resilience (v2.28.0) ---
    # Manual-block actions that fence off downstream work. Real-world
    # failure mode: doctor printed a "fix npm root permissions" block, then
    # `--yes` ran the npm install anyway, the install died with EACCES, and
    # the user was buried under cascade noise. Setting this True on the
    # manual block lets execute_plan() add `component` to a `blocked_components`
    # set so any later action that lists this component in
    # `depends_on_components` is reported as `skipped` rather than executed.
    blocks_downstream: bool = False
    # Components that must have run successfully (or at least not have failed
    # / been blocked) for this action to make sense. Used to model:
    #   - npx post_install / bundled-skill steps depend on npx install
    #   - npx install depends on permission:npm-root-global
    #   - npx post_install depends on path:npm-prefix-bin (binary on PATH)
    depends_on_components: tuple[str, ...] = ()
    # Best-effort actions: a failure marks the action `warned` instead of
    # `failed` and leaves no entry in `failed_components`. Used for
    # `claude plugin marketplace update <name>` which is a stale-cache
    # refresh — if it fails, the install still has a chance and we don't
    # want a red FAILED row for an opportunistic step.
    soft_fail: bool = False
    # Safe, idempotent maintenance (plugin install/update, npx refresh,
    # marketplace add/update, post-install + bundled-skill follow-ups) runs
    # without a confirm prompt so `sccs doctor update` / `optimize` keep the
    # host current unattended. Destructive actions (foreign plugin/MCP
    # uninstall, settings.json hook removal, settings.json statusline rewrite)
    # keep auto_confirm=False — the global delete-safety rule still applies and
    # the user is asked every time. `--yes` remains the blanket override.
    auto_confirm: bool = False

    def is_print_only(self) -> bool:
        return not self.runnable or (self.cmd is None and self.python_callable is None)


@dataclass
class InstallPlan:
    """Ordered list of actions to bring the host up to spec."""

    actions: list[DoctorAction] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.actions


@dataclass
class ActionOutcome:
    """Result of a single executed (or printed) DoctorAction."""

    label: str
    status: str  # "executed" | "skipped" | "printed" | "failed" | "warned"
    detail: str = ""


@dataclass
class ExecuteResult:
    """Aggregate result of running an InstallPlan."""

    outcomes: list[ActionOutcome] = field(default_factory=list)

    @property
    def executed(self) -> list[ActionOutcome]:
        return [o for o in self.outcomes if o.status == "executed"]

    @property
    def failed(self) -> list[ActionOutcome]:
        return [o for o in self.outcomes if o.status == "failed"]

    @property
    def skipped(self) -> list[ActionOutcome]:
        return [o for o in self.outcomes if o.status == "skipped"]

    @property
    def printed(self) -> list[ActionOutcome]:
        return [o for o in self.outcomes if o.status == "printed"]

    @property
    def warned(self) -> list[ActionOutcome]:
        return [o for o in self.outcomes if o.status == "warned"]


# Component identifier conventions used across the doctor plan. Keeping the
# strings stable matters — execute_plan() compares them against
# `depends_on_components` to decide whether to run, skip, or block.
PERM_NPM_ROOT_GLOBAL = "perm:npm root -g"  # mirrors PermissionCheckSpec.path
PATH_NPM_PREFIX_BIN = "path:npm-prefix-bin"


def _diagnose_hint(text: str) -> str | None:
    """Map common subprocess failure signatures to a one-line user hint.

    Real-session failure modes (Debian 13, eq_devops, 2026-05-06) used as
    pattern source. Returning None means "no opinion" — the bare stderr is
    still surfaced.
    """
    low = text.lower()
    if "plugin not found in marketplace" in low:
        return (
            "Marketplace cache may be stale — `claude plugin marketplace update <name>` "
            "is queued automatically in v2.28.0. If it still fails, check the marketplace "
            "source URL and your network."
        )
    if "eacces" in low and "node_modules" in low:
        return (
            "EACCES on npm global root — see the manual block above. Pick Option A "
            "(user-local prefix `~/.npm-global`) or Option B (`sudo chown`), then "
            "re-run `sccs doctor install`."
        )
    if "command not found" in low or ("enoent" in low and "spawn" in low):
        return (
            "Binary not on PATH — confirm `$(npm config get prefix)/bin` is in $PATH "
            "and reload your shell before re-running `sccs doctor install`."
        )
    return None


from sccs.doctor._paths import is_home_path as _is_home_path  # noqa: E402


def _write_settings_backup(p: Path, text: str) -> Path:
    """Write a timestamped settings.json backup with private (0600) perms.

    The primary file is written via atomic_write(mode=0o600) because it may
    hold MCP tokens — the backup carries the exact same content, so it gets
    the exact same hardening. A plain write_text() would inherit the process
    umask (often 0644) and leave the secrets world-readable indefinitely on
    multi-user hosts.
    """
    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = p.with_name(f"{p.name}.bak-{timestamp}")
    atomic_write(backup, text, mode=0o600)
    return backup


def _user_local_prefix_lines(header: str) -> list[str]:
    """Option-A remediation snippet: relocate npm's global prefix under $HOME.

    A single user-local prefix fixes BOTH the global root (lib/node_modules)
    AND the bin dir in one move — which is exactly why it's the only correct
    fix for a system prefix. Pre-creates lib/ and bin/ to dodge the
    ENOENT-on-first-npx quirk (npx lstat's `<prefix>/lib` before the first
    `npm install -g` would have created it — real Debian incident).
    """
    return [
        header,
        "mkdir -p ~/.npm-global/lib ~/.npm-global/bin",
        "npm config set prefix ~/.npm-global",
        "# Add to your shell rc PERMANENTLY (survives new shells):",
        "# fish (3.2+, idempotent):",
        "fish_add_path $HOME/.npm-global/bin",
        "# bash — append to ~/.bashrc:",
        "echo 'export PATH=\"$HOME/.npm-global/bin:$PATH\"' >> ~/.bashrc",
        "# zsh — append to ~/.zshrc:",
        "echo 'export PATH=\"$HOME/.npm-global/bin:$PATH\"' >> ~/.zshrc",
        "# Or temporarily (current session only):",
        'export PATH="$HOME/.npm-global/bin:$PATH"   # bash/zsh',
        "set -gx PATH $HOME/.npm-global/bin $PATH     # fish",
    ]


_RELOAD_HINT_LINES = [
    "",
    "# After applying the fix, restart your shell (or `exec $SHELL`) so the new",
    "# $PATH / npm prefix is visible to the next `sccs doctor check`.",
]


def _npm_global_fix_block(st: PermissionStatus) -> list[str]:
    """Remediation for an unwritable npm global dir (root `lib` OR `bin`).

    Real Debian incident: system npm installs land in /usr/lib/node_modules/
    (root-owned), so `npm install -g @playwright/cli@latest` dies with EACCES.
    Doctor surfaces this *before* the npm action runs.

    Option B (`sudo chown`) is offered ONLY when it is both safe and complete,
    i.e. when the directory lives under the user's home (a user-controlled
    `~/.npm-global` chowned to root by a stray `sudo npm`). It is suppressed:

      * on multi-user systems (v2.28.1): ≥2 distinct non-root owners → chown
        would destroy the other users' installs.
      * on system prefixes (v2.32.1): `/usr/lib/node_modules` and `/usr/bin`
        have different parents. Chowning only the lib dir is the trap that
        bit the original report — the bin-dir symlink still fails with EACCES;
        and chowning `/usr/bin` is dangerous. The user-local prefix (Option A)
        relocates BOTH dirs under home in one step.

    All branches end with a `restart your shell` hint (v2.33.2): the running
    doctor process only sees the *current* shell's $PATH / npm prefix, so the
    next `sccs doctor check` after an Option-A fix would otherwise still
    report the old MISSING status.
    """
    lines: list[str] = []
    lines.append(f"# Detected: {st.resolved_path} is not writable by uid {st.expected_uid}.")

    if st.is_multi_user:
        # Foreign uids → list them so the user can verify the heuristic.
        foreign = sorted(uid for uid in st.foreign_uids if uid not in (0, st.expected_uid))
        uid_list = ", ".join(str(u) for u in foreign)
        lines.append(f"# WARNING: directory owned by multiple non-root users (uids: {uid_list}).")
        lines.append("# This is a multi-user / terminal-server setup. `sudo chown -R` would")
        lines.append("# DESTROY the other users' installs — DO NOT chown here.")
        lines.append("# Use Option A (user-local prefix) only.")
        lines.append("")
        lines.extend(
            _user_local_prefix_lines("# Option A (REQUIRED on multi-user systems): user-local npm prefix, no sudo")
        )
        lines.extend(_RELOAD_HINT_LINES)
        return lines

    if not _is_home_path(st.resolved_path):
        # System prefix (e.g. /usr): chowning the lib dir alone is incomplete
        # (the bin dir stays root-owned) and chowning /usr/bin is unsafe.
        lines.append(f"# WARNING: {st.resolved_path} is a system directory (npm prefix outside your home).")
        lines.append("# `sudo chown` here is unsafe AND incomplete: npm uses BOTH")
        lines.append("# <prefix>/lib/node_modules AND <prefix>/bin (e.g. /usr/bin). Chowning one")
        lines.append("# is not enough, and chowning /usr/bin breaks your system.")
        lines.append("# Use Option A (user-local prefix) only — it relocates BOTH dirs under $HOME.")
        lines.append("")
        lines.extend(
            _user_local_prefix_lines("# Option A (REQUIRED for system npm prefixes): user-local npm prefix, no sudo")
        )
        lines.extend(_RELOAD_HINT_LINES)
        return lines

    lines.append("# Two fixes — pick ONE:")
    lines.append("")
    lines.extend(_user_local_prefix_lines("# Option A (recommended): user-local npm prefix, no sudo"))
    lines.append("")
    lines.append("# Option B: take ownership of the npm dir (safe here — it's under your home)")
    # st.fix_command is None for system / multi-user paths but reachable here
    # only for the in-$HOME branch where chown is safe; fall back to the
    # explicit string if a future caller bypasses the property.
    chown_fallback = f"sudo chown -R {st.expected_uid}:{st.expected_gid} {st.resolved_path}"
    lines.append(st.fix_command or chown_fallback)
    lines.extend(_RELOAD_HINT_LINES)
    return lines


def _permission_actions(statuses: list[PermissionStatus]) -> list[DoctorAction]:
    """Surface filesystem permission issues as runnable=False manual blocks.

    These are intentionally print-only — `sudo chown` is out of scope for SCCS
    (HARD RULE: never call sudo). Putting them at the front of the plan ensures
    the user sees the chown command before we run any subsequent npm/npx/claude
    plugin actions that would otherwise fail with EACCES.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        if st.ok:
            continue
        block_lines: list[str] = []
        block_lines.append(f"# {st.spec.label}: {st.spec.purpose}")
        if st.offending_paths:
            block_lines.append(f"# Examples of foreign-owned entries under {st.resolved_path}:")
            for p in st.offending_paths[:3]:
                block_lines.append(f"#   {p}")
        if st.spec.path_kind in ("npm-root-global", "npm-bin-global"):
            block_lines.extend(_npm_global_fix_block(st))
        else:
            if not st.is_writable:
                block_lines.append(f"# Path is not writable by uid {st.expected_uid}.")
            block_lines.append("# Fix:")
            block_lines.append(st.fix_command or "")
        actions.append(
            DoctorAction(
                label=f"fix permissions: {st.spec.path}",
                cmd=None,
                manual_block="\n".join(block_lines),
                runnable=False,
                component=f"perm:{st.spec.path}",
                # Manual block fences off any downstream work that would
                # otherwise hit the same EACCES — see execute_plan() for the
                # blocked_components handling.
                blocks_downstream=True,
            )
        )
    return actions


def _marketplace_missing_actions(statuses: list[MarketplaceStatus]) -> list[DoctorAction]:
    """Surface configured-but-not-registered plugin marketplaces as manual blocks.

    Real failure mode (Debian-13 multi-user terminal server): the
    `claude-plugins-official` marketplace was never registered locally, so
    every `claude plugin install <name>@claude-plugins-official` died with
    "Plugin not found in marketplace …" — and `claude plugin marketplace
    update` (the v2.28.0 auto-step) cannot help because you cannot UPDATE
    a marketplace that does not exist; you must ADD it. This action prints
    a copy-paste `claude plugin marketplace add …` snippet and fences off
    every install for the same marketplace via `blocks_downstream=True`.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        if st.ok:
            continue
        block_lines: list[str] = []
        block_lines.append(f"# Marketplace '{st.name}' is not registered locally.")
        block_lines.append(
            "# `claude plugin install <name>@" + st.name + "` cannot succeed until the marketplace is added."
        )
        if st.suggested_source:
            block_lines.append("# Run:")
            block_lines.append(f"claude plugin marketplace add {st.suggested_source}")
        else:
            block_lines.append("# No `marketplace_source` is configured for this marketplace in your sccs config.")
            block_lines.append("# Find the source (e.g. `owner/repo` or full URL) and run:")
            block_lines.append(f"claude plugin marketplace add <owner/repo>   # for marketplace '{st.name}'")
            block_lines.append("# Then add `marketplace_source: '<owner/repo>'` to the matching plugin entry")
            block_lines.append("# under `doctor.plugins:` in `~/.config/sccs/config.yaml`.")
        actions.append(
            DoctorAction(
                label=f"register marketplace: {st.name}",
                cmd=None,
                manual_block="\n".join(block_lines),
                runnable=False,
                component=f"plugin-marketplace:{st.name}:exists",
                blocks_downstream=True,
            )
        )
    return actions


def _powershell_path_block(label: str, purpose: str, expected_path: str) -> str:
    """PowerShell PATH-fix instructions for Windows.

    The bash/zsh/fish snippets are useless in PowerShell, so on Windows we emit
    a persistent User-PATH edit via `[Environment]::SetEnvironmentVariable`
    (idempotent) plus the temporary `$env:Path` form. Print-only — SCCS never
    edits the environment itself.
    """
    return "\n".join(
        [
            f"# {label}: {purpose}",
            f"# Detected: {expected_path} is not on your PATH.",
            "",
            "# Add it PERMANENTLY (User PATH, survives new shells):",
            f"$dir = '{expected_path}'",
            "$userPath = [Environment]::GetEnvironmentVariable('Path','User')",
            "if (($userPath -split ';') -notcontains $dir) {",
            "    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $dir), 'User')",
            "}",
            "",
            "# Or TEMPORARILY (current session only):",
            "$env:Path += ';' + $dir",
            "",
            "# Then START A NEW PowerShell and re-run:",
            "sccs doctor install",
        ]
    )


def _path_prefix_actions(
    statuses: list[PathPrefixStatus],
    *,
    platform_name: str | None = None,
) -> list[DoctorAction]:
    """Surface PATH-mismatch issues (e.g. user changed npm prefix but PATH
    in the current shell still points to the system prefix).

    The block is print-only: SCCS cannot mutate the user's shell rc files.
    `blocks_downstream=True` so any action that *uses* the npm-installed
    binary (post_install steps, browser-bundle fetches) is reported as
    `skipped` rather than failing with `command not found`. On Windows the
    snippet is PowerShell; elsewhere bash/zsh/fish.
    """
    platform = platform_name or get_current_platform()
    actions: list[DoctorAction] = []
    for st in statuses:
        if st.ok:
            continue
        if st.skipped_reason:
            continue
        if platform == "windows":
            manual_block = _powershell_path_block(st.spec.label, st.spec.purpose, st.expected_path)
        else:
            block_lines: list[str] = []
            block_lines.append(f"# {st.spec.label}: {st.spec.purpose}")
            block_lines.append(f"# Detected: {st.expected_path} is not on $PATH for this shell session.")
            block_lines.append("")
            block_lines.append("# Add it PERMANENTLY (survives new shells):")
            block_lines.append("# fish (3.2+, idempotent):")
            block_lines.append(f"fish_add_path {st.expected_path}")
            block_lines.append("# bash — append to ~/.bashrc:")
            block_lines.append(f"echo 'export PATH=\"{st.expected_path}:$PATH\"' >> ~/.bashrc")
            block_lines.append("# zsh — append to ~/.zshrc:")
            block_lines.append(f"echo 'export PATH=\"{st.expected_path}:$PATH\"' >> ~/.zshrc")
            block_lines.append("")
            block_lines.append("# Or TEMPORARILY (current session only):")
            block_lines.append("# bash/zsh:")
            block_lines.append(f'export PATH="{st.expected_path}:$PATH"')
            block_lines.append("# fish:")
            block_lines.append(f"set -gx PATH {st.expected_path} $PATH")
            block_lines.append("")
            block_lines.append("# After updating, START A NEW SHELL and re-run:")
            block_lines.append("sccs doctor install")
            manual_block = "\n".join(block_lines)
        actions.append(
            DoctorAction(
                label=f"add to PATH: {st.spec.label}",
                cmd=None,
                manual_block=manual_block,
                runnable=False,
                component=f"path:{st.spec.identifier}",
                blocks_downstream=True,
            )
        )
    return actions


# Apple-Silicon Homebrew Cellar pattern. Same regex as the detector but
# kept private here so the rewrite logic is self-contained.
_STATUS_LINE_CELLAR_RE = re.compile(r"/opt/homebrew/Cellar/([^/]+)/([^/]+)/(?:.*/)?bin/([^/\s\"']+)")


def _rewrite_stale_cellar_command(cmd: str) -> str | None:
    """Rewrite `/opt/homebrew/Cellar/<pkg>/<ver>/bin/X` segments to `/opt/homebrew/bin/X`.

    Returns the new command string, or None if no rewrite applied. Idempotent:
    a string with no Cellar segments returns None and the caller skips the
    write. Operates on the raw string to preserve user quoting/escaping.
    """
    new_cmd, count = _STATUS_LINE_CELLAR_RE.subn(r"/opt/homebrew/bin/\3", cmd)
    return new_cmd if count > 0 else None


# GSD renamed its statusline hook `hooks/statusline.js` -> `hooks/gsd-statusline.js`
# during the get-shit-done-redux move. A command still pointing at the old name
# leaves the statusline dead. Match only the `hooks/`-prefixed name (mirrors the
# upstream redux #330 guard) so we never touch a third-party `statusline.js`.
_STATUS_LINE_GSD_SCRIPT_RE = re.compile(r"hooks([/\\])statusline\.js")


def _rewrite_stale_gsd_script_command(cmd: str) -> str | None:
    """Rewrite `hooks/statusline.js` -> `hooks/gsd-statusline.js` (separator-preserving).

    Returns the new string, or None if no rewrite applied. Operates on the raw
    string to preserve user quoting/escaping. Idempotent: a string already
    pointing at gsd-statusline.js has no `hooks/statusline.js` match and returns
    None, so the caller skips the write.
    """
    new_cmd, count = _STATUS_LINE_GSD_SCRIPT_RE.subn(r"hooks\1gsd-statusline.js", cmd)
    return new_cmd if count > 0 else None


def _status_line_actions(statuses: list[StatusLineStatus]) -> list[DoctorAction]:
    """Surface statusline issues (stale Cellar path, missing binary, etc.).

    Two states produce a mechanical, safe auto-fix action (backed up before
    write, idempotent):
      - `stale_cellar`: rewrite a Cellar path to the stable Homebrew bin-symlink.
      - `missing_script`: rewrite the GSD rename hooks/statusline.js →
        hooks/gsd-statusline.js, but only when the new script exists on disk.
    Everything else — `missing_binary`, `missing`, generic `missing_script`
    (non-GSD or new script absent) — gets a manual block because the right fix
    depends on the user's intent (reinstall? change tool? remove statusline?).

    `blocks_downstream=False` for all — statusline failure does not cascade
    into other doctor components per CONTEXT.md D4.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        if st.ok:
            continue
        component = f"statusline:{st.spec.identifier}"
        if st.state == "stale_cellar" and st.spec.auto_fix_stale_cellar and st.raw_command is not None:
            settings_path = Path(st.settings_path)
            raw_cmd = st.raw_command
            new_cmd_opt = _rewrite_stale_cellar_command(raw_cmd)
            if new_cmd_opt is None:
                # Defensive: detector said stale_cellar but the rewrite regex
                # didn't match (e.g. binary not under bin/). Fall through to
                # the manual-block branch below.
                pass
            else:
                new_cmd: str = new_cmd_opt

                def _fix(p: Path = settings_path, new: str = new_cmd) -> None:
                    """Mutate settings.json in-place after writing a backup."""
                    text = p.read_text(encoding="utf-8")
                    data = json.loads(text)
                    sl = data.get("statusLine")
                    if not isinstance(sl, dict):
                        raise DoctorError("statusLine key missing or non-dict")
                    _write_settings_backup(p, text)
                    sl["command"] = new
                    # Atomic write (temp + os.replace) so a crash mid-write cannot
                    # leave settings.json truncated; mode=0o600 forces private
                    # perms on a file that may hold MCP tokens (os.replace would
                    # otherwise inherit the prior, possibly world-readable, mode).
                    atomic_write(p, json.dumps(data, indent=2) + "\n", mode=0o600)

                actions.append(
                    DoctorAction(
                        label=f"fix stale Cellar path in {settings_path.name} ({st.cellar_pkg}/{st.cellar_version})",
                        cmd=None,
                        python_callable=_fix,
                        component=component,
                        blocks_downstream=False,
                    )
                )
                continue
        if (
            st.state == "missing_script"
            and st.spec.auto_fix_stale_script
            and st.raw_command is not None
            and st.script is not None
        ):
            # Known, safe GSD rename: hooks/statusline.js -> hooks/gsd-statusline.js,
            # and only when the new script actually exists on disk. Any other
            # missing-script case falls through to the manual block — no guessing.
            new_cmd_opt = _rewrite_stale_gsd_script_command(st.raw_command)
            new_script_opt = _rewrite_stale_gsd_script_command(st.script)
            if new_cmd_opt is not None and new_script_opt is not None and Path(new_script_opt).expanduser().is_file():
                settings_path = Path(st.settings_path)
                new_cmd = new_cmd_opt

                def _fix_script(p: Path = settings_path, new: str = new_cmd) -> None:
                    """Mutate settings.json in-place after writing a backup."""
                    text = p.read_text(encoding="utf-8")
                    data = json.loads(text)
                    sl = data.get("statusLine")
                    if not isinstance(sl, dict):
                        raise DoctorError("statusLine key missing or non-dict")
                    _write_settings_backup(p, text)
                    sl["command"] = new
                    atomic_write(p, json.dumps(data, indent=2) + "\n", mode=0o600)

                actions.append(
                    DoctorAction(
                        label=f"fix stale GSD statusline path in {settings_path.name} (→ gsd-statusline.js)",
                        cmd=None,
                        python_callable=_fix_script,
                        component=component,
                        blocks_downstream=False,
                    )
                )
                continue
            # else: new script missing or no match → fall through to manual block
        # Manual block for unfixable states (missing / missing_binary / missing_script
        # / stale_cellar without auto_fix enabled).
        block_lines: list[str] = [f"# Statusline issue: {st.detail}"]
        if st.raw_command:
            block_lines.append(f"# Current command: {st.raw_command}")
        block_lines.append(f"# Settings file: {st.settings_path}")
        block_lines.append("")
        if st.state == "missing":
            block_lines.append("# Statusline is expected (claude_statusline sync category is enabled")
            block_lines.append("# and a statusline script exists), but no statusLine key was found.")
            block_lines.append("# Run `sccs sync --category claude_statusline` to apply the configured")
            block_lines.append("# settings_ensure block, or edit settings.json manually.")
        elif st.state == "missing_binary":
            block_lines.append("# The binary referenced by statusLine.command was not found.")
            block_lines.append("# Either reinstall it, or edit ~/.claude/settings.json to point at a")
            block_lines.append("# binary that exists on this system.")
        elif st.state == "missing_script":
            block_lines.append("# The script referenced by statusLine.command was not found.")
            block_lines.append("# Either restore the script (e.g. via the source plugin) or edit")
            block_lines.append("# ~/.claude/settings.json to remove/update the statusLine.")
        elif st.state == "stale_cellar":
            block_lines.append("# Auto-fix is disabled for this check. Manually edit settings.json")
            block_lines.append("# and replace the Cellar path with the stable /opt/homebrew/bin symlink.")
        actions.append(
            DoctorAction(
                label=f"statusline: {st.spec.identifier} ({st.state})",
                cmd=None,
                manual_block="\n".join(block_lines),
                runnable=False,
                component=component,
                blocks_downstream=False,
            )
        )
    return actions


def _node_action(status: NodeStatus) -> DoctorAction | None:
    if status.installed and status.meets_minimum:
        return None
    spec = status.install_hint
    return DoctorAction(
        label=spec.label,
        cmd=spec.cmd if spec.runnable else None,
        manual_block=spec.manual_block,
        runnable=spec.runnable and spec.cmd is not None,
        component="node",
    )


def _winget_links_path_block(name: str) -> str:
    """PowerShell snippet to put a winget-installed tool's binary on the
    persistent User PATH — for the WinGet-Links-not-on-PATH trap.

    Print-only: SCCS never mutates the user's environment. Mirrors the
    approach the captain validated for the zoxide fix.
    """
    return "\n".join(
        [
            f"# {name} is installed (winget) but its binary folder is not on your PATH.",
            "# Add it PERMANENTLY (PowerShell — find the package dir, then persist it):",
            '$exe = Get-ChildItem "$env:LOCALAPPDATA\\Microsoft\\WinGet\\Packages" -Recurse `',
            f"        -Include {name}.exe,coreutils.exe,zoxide.exe -ErrorAction SilentlyContinue | "
            "Select-Object -First 1",
            "$dir = $exe.DirectoryName",
            "$userPath = [Environment]::GetEnvironmentVariable('Path','User')",
            "if ($dir -and (($userPath -split ';') -notcontains $dir)) {",
            "    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $dir), 'User')",
            "}",
            "# Then START A NEW PowerShell and re-run: sccs doctor check",
        ]
    )


def _cli_tool_install_actions(
    statuses: list[CliToolStatus] | None,
    *,
    platform_name: str | None = None,
) -> list[DoctorAction]:
    """Install / PATH-fix actions for the opt-in CLI tools (zoxide, coreutils).

    - `missing` → run the platform install recipe (winget/brew) behind a
      confirm prompt, or print the manual block (e.g. linux zoxide installer).
    - `installed_not_on_path` → print-only PowerShell PATH guidance (the
      WinGet-Links trap); SCCS never edits the environment itself.
    On-path tools produce no action.
    """
    if not statuses:
        return []
    platform = platform_name or get_current_platform()
    actions: list[DoctorAction] = []
    for st in statuses:
        spec = st.spec
        if st.state == "installed_not_on_path":
            actions.append(
                DoctorAction(
                    label=f"add {spec.name} to PATH (installed via winget, not on PATH)",
                    cmd=None,
                    manual_block=_winget_links_path_block(spec.name),
                    runnable=False,
                    component=f"cli-tool:{spec.name}",
                )
            )
            continue
        if st.state != "missing":
            continue
        recipe = spec.install.get(platform)
        if recipe is None:
            actions.append(
                DoctorAction(
                    label=f"install {spec.name} (no recipe for {platform})",
                    cmd=None,
                    manual_block=f"# No install recipe for {spec.name} on {platform}.",
                    runnable=False,
                    component=f"cli-tool:{spec.name}",
                )
            )
            continue
        actions.append(
            DoctorAction(
                label=recipe.label,
                cmd=recipe.cmd if recipe.runnable else None,
                manual_block=recipe.manual_block,
                runnable=recipe.runnable and recipe.cmd is not None,
                component=f"cli-tool:{spec.name}",
            )
        )
    return actions


def _claude_cli_action(status: ClaudeCliStatus) -> DoctorAction | None:
    if status.installed:
        return None
    return DoctorAction(
        label="install Claude Code CLI (npm i -g @anthropic-ai/claude-code)",
        cmd=["npm", "install", "-g", "@anthropic-ai/claude-code"],
        runnable=True,
        component="claude-cli",
    )


def _plugin_install_actions(
    statuses: list[PluginStatus],
    *,
    marketplaces: list[MarketplaceStatus] | None = None,
) -> list[DoctorAction]:
    """Plan claude-plugin install steps.

    For plugins shipped via a registered marketplace but without an explicit
    `marketplace_source`, prepend a single `claude plugin marketplace update
    <name>` step per marketplace. Real failure mode (Debian 13, 2026-05-06):
    `claude plugin install skill-creator@claude-plugins-official` died with
    "Plugin not found in marketplace" because the local marketplace cache
    was stale; the CLI's own remediation hint is "try `claude plugin
    marketplace update claude-plugins-official`". v2.28.0 queues that step
    automatically. Marked `soft_fail=True`: if the refresh itself fails
    (network blip, marketplace gone), we still try the install.

    v2.28.1: when `marketplaces` is supplied, plugins whose marketplace is
    NOT registered list `plugin-marketplace:<name>:exists` as a dependency
    so the cascade engine reports them as `⊘ skipped` rather than queuing
    a guaranteed-failed `claude plugin install`. The companion
    `_marketplace_missing_actions` provides the manual block that fences
    those installs off.
    """
    # Map marketplace name → registered? Only used to inject the dependency
    # for plugins whose source we cannot install on the current host.
    market_registered: dict[str, bool] = {}
    if marketplaces:
        for m in marketplaces:
            market_registered[m.name] = m.ok

    actions: list[DoctorAction] = []
    seen_marketplace_updates: set[str] = set()
    for st in statuses:
        if st.installed:
            continue
        spec = st.spec

        # Build per-plugin extra dependencies. Only relevant when the
        # plugin uses a marketplace that doctor knows is missing.
        extra_deps: tuple[str, ...] = ()
        if spec.marketplace and spec.marketplace in market_registered and not market_registered[spec.marketplace]:
            extra_deps = (f"plugin-marketplace:{spec.marketplace}:exists",)

        # Auto-refresh stale marketplace metadata before the install attempt.
        # Skipped when the marketplace is known to be missing (the manual
        # block from `_marketplace_missing_actions` is the only correct fix
        # there — `update` cannot succeed for a non-existent marketplace).
        if (
            spec.marketplace
            and not spec.marketplace_source
            and spec.marketplace not in seen_marketplace_updates
            and market_registered.get(spec.marketplace, True)
        ):
            seen_marketplace_updates.add(spec.marketplace)
            actions.append(
                DoctorAction(
                    label=f"sync plugin marketplace: {spec.marketplace}",
                    cmd=["claude", "plugin", "marketplace", "update", spec.marketplace],
                    runnable=True,
                    component=f"plugin-marketplace:{spec.marketplace}:update",
                    soft_fail=True,
                    auto_confirm=True,  # prerequisite for unattended install
                )
            )
        if spec.marketplace_source:
            actions.append(
                DoctorAction(
                    label=f"register marketplace {spec.marketplace_source}",
                    cmd=["claude", "plugin", "marketplace", "add", spec.marketplace_source],
                    runnable=True,
                    component=f"plugin:{spec.name}",
                    auto_confirm=True,  # prerequisite for unattended install
                )
            )
        actions.append(
            DoctorAction(
                label=f"install plugin {spec.install_target}",
                cmd=["claude", "plugin", "install", spec.install_target],
                runnable=True,
                component=f"plugin:{spec.name}",
                depends_on_components=extra_deps,
                auto_confirm=True,  # safe maintenance — runs unattended
            )
        )
    return actions


def _effective_update_target(status: PluginStatus) -> str:
    """Return the `name@marketplace` argv that actually exists for `claude plugin update`.

    `claude plugin update` always requires the EXACT installed identifier — bare
    names fail with "Plugin not found", and so does the default marketplace when
    the plugin was installed under a different one. Therefore we always prefer
    `found_marketplace` (what `claude plugin list` actually reports) over the
    user-configured `marketplace` (what the user wishes were installed).
    """
    if status.found_marketplace:
        return f"{status.spec.name}@{status.found_marketplace}"
    # Fallback: no marketplace anywhere — pass the bare name and let the CLI
    # surface its own error rather than silently dropping the action.
    return status.spec.install_target


# Scope values accepted by `claude plugin update --scope <value>` — anything
# else gets dropped silently rather than passed through, so a future Claude
# CLI release that introduces an additional scope cannot break our argv.
_VALID_PLUGIN_SCOPES = frozenset({"user", "project", "local", "managed"})


def _plugin_update_actions(statuses: list[PluginStatus]) -> list[DoctorAction]:
    actions: list[DoctorAction] = []
    for st in statuses:
        if not st.installed:
            # Skip — install plan covers missing plugins.
            continue
        target = _effective_update_target(st)
        cmd = ["claude", "plugin", "update", target]
        # Forward the scope detected in `claude plugin list` so update doesn't
        # default to scope=user and fail with "Plugin … is not installed at
        # scope user" for plugins installed under project/local/managed (real
        # incident on Debian 13 with `superpowers@claude-plugins-official`).
        scope_label = ""
        if st.scope and st.scope.lower() in _VALID_PLUGIN_SCOPES:
            cmd.extend(["--scope", st.scope.lower()])
            scope_label = f" (scope: {st.scope.lower()})"
        actions.append(
            DoctorAction(
                label=f"update plugin {target}{scope_label}",
                cmd=cmd,
                runnable=True,
                component=f"plugin:{st.spec.name}",
                auto_confirm=True,  # safe maintenance — runs unattended
            )
        )
    return actions


def _post_install_actions(
    spec: NpxToolSpec,
    *,
    extra_deps: tuple[str, ...] = (),
) -> list[DoctorAction]:
    """Action list for `spec.post_install` (e.g. `playwright-cli install-browser …`).

    These run after the main invocation succeeds. They are intentionally
    treated as regular runnable actions so the user sees the confirm prompt
    and the result lands in `ExecuteResult` like every other step.

    `extra_deps` carries cross-cutting prerequisites (e.g. the install
    component itself, plus `path:npm-prefix-bin` so a "wrong PATH" detector
    block fences these off rather than letting them die with "command not
    found" on the freshly-installed binary).
    """
    return [
        DoctorAction(
            label=f"{spec.name}: {' '.join(cmd)}",
            cmd=list(cmd),
            runnable=True,
            component=f"npx:{spec.name}:post:{i}",
            depends_on_components=extra_deps,
            auto_confirm=True,  # follow-up of an auto-confirmed npx maintenance step
        )
        for i, cmd in enumerate(spec.post_install)
    ]


def _bundled_skill_action(
    spec: NpxToolSpec,
    *,
    extra_deps: tuple[str, ...] = (),
) -> DoctorAction | None:
    """Action that copies the npm-bundled skill into `~/.claude/skills/`."""
    if spec.bundled_skill is None:
        return None
    bs = spec.bundled_skill

    def _run_skill_sync() -> None:
        _sync_bundled_skill(bs)

    return DoctorAction(
        label=f"sync bundled skill {spec.name} → {bs.target}",
        runnable=True,
        component=f"npx:{spec.name}:skill",
        depends_on_components=extra_deps,
        python_callable=_run_skill_sync,
        auto_confirm=True,  # follow-up of an auto-confirmed npx maintenance step
    )


def _sync_bundled_skill(bs: BundledSkillSpec) -> None:
    """Copy `<npm root -g>/<package_subpath>` to `<target>` (overwriting).

    Resolved at execute-time because the npm global root differs across
    Homebrew, NodeSource, nvm and Windows installations. Whole-directory
    overwrite is intentional: the target is also added to the doctor-
    managed exclude registry so `sccs sync` ignores it; the npm package is
    therefore the single source of truth.
    """
    proc = _run(["npm", "root", "-g"], check=True, capture=True, timeout=30)
    raw = (proc.stdout or "").strip()
    if not raw:
        raise DoctorError("Could not resolve `npm root -g` (empty output)")
    npm_root = Path(raw.splitlines()[0].strip())
    source = npm_root / bs.package_subpath
    if not source.is_dir():
        raise DoctorError(f"bundled skill source not found: {source}")
    target = Path(bs.target).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    logger.info("doctor copied bundled skill: %s → %s", source, target)


def _gsd_patch_action(
    spec: NpxToolSpec,
    *,
    extra_deps: tuple[str, ...] = (),
) -> DoctorAction | None:
    """Action that prepends a SCOPE BOUNDARY directive to the tool's prompt files.

    Only emitted when `spec.patch_scope_boundary` is set (GSD). Runs after the
    npx (re)install so it re-applies on every install/update — the vendor
    overwrites the files each run, so the patch must be idempotent (it is; see
    scope_patch.patch_file). Mirrors `_bundled_skill_action`: a python_callable
    follow-up, auto-confirmed, cascade-skipped if the install itself failed.
    """
    if not spec.patch_scope_boundary:
        return None

    scan_dirs = list(spec.managed_scan_dirs)

    def _run_scope_patch() -> None:
        scope_patch.patch_gsd_scope(scan_dirs, print_fn=logger.info)

    return DoctorAction(
        label=f"pin scope boundary in {spec.name} prompts",
        runnable=True,
        component=f"npx:{spec.name}:scope",
        depends_on_components=extra_deps,
        python_callable=_run_scope_patch,
        auto_confirm=True,  # follow-up of an auto-confirmed npx maintenance step
    )


def _npx_install_actions(
    statuses: list[NpxToolStatus],
    *,
    install_deps: tuple[str, ...] = (),
    use_deps: tuple[str, ...] = (),
) -> list[DoctorAction]:
    """Plan install + post_install + bundled-skill steps for missing npx tools.

    `install_deps` are components the install itself depends on — typically
    `perm:npm root -g` so a permission manual block fences off the install.
    `use_deps` extend that with components only needed to *use* the binary
    (e.g. `path:npm-prefix-bin` for the post_install browser fetches).
    The bundled-skill copy uses `install_deps` because it works off
    `npm root -g` directly, not the binary on PATH.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        if st.available:
            continue
        spec = st.spec
        install_component = f"npx:{spec.name}"
        actions.append(
            DoctorAction(
                label=f"install npx tool {spec.name}",
                cmd=list(spec.invocation),
                runnable=True,
                component=install_component,
                depends_on_components=install_deps,
                npx_tool_name=spec.name if spec.detect_via_state else None,
                npx_invocation=list(spec.invocation) if spec.detect_via_state else None,
                auto_confirm=True,  # safe maintenance — runs unattended
            )
        )
        post_deps = (install_component, *use_deps)
        actions.extend(_post_install_actions(spec, extra_deps=post_deps))
        skill_action = _bundled_skill_action(spec, extra_deps=(install_component, *install_deps))
        if skill_action:
            actions.append(skill_action)
        scope_action = _gsd_patch_action(spec, extra_deps=(install_component, *install_deps))
        if scope_action:
            actions.append(scope_action)
    return actions


def _npx_update_actions(
    statuses: list[NpxToolStatus],
    *,
    install_deps: tuple[str, ...] = (),
    use_deps: tuple[str, ...] = (),
) -> list[DoctorAction]:
    """Re-run the `npx ...` invocation; npx will fetch the latest version.

    Always re-runs `post_install` and `bundled_skill` so an npm update that
    bumps the bundled browser drivers or skill content propagates to the
    user's machine without manual intervention.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        spec = st.spec
        install_component = f"npx:{spec.name}"
        actions.append(
            DoctorAction(
                label=f"refresh npx tool {spec.name}",
                cmd=list(spec.invocation),
                runnable=True,
                component=install_component,
                depends_on_components=install_deps,
                npx_tool_name=spec.name if spec.detect_via_state else None,
                npx_invocation=list(spec.invocation) if spec.detect_via_state else None,
                auto_confirm=True,  # safe maintenance — runs unattended (GSD refresh)
            )
        )
        post_deps = (install_component, *use_deps)
        actions.extend(_post_install_actions(spec, extra_deps=post_deps))
        skill_action = _bundled_skill_action(spec, extra_deps=(install_component, *install_deps))
        if skill_action:
            actions.append(skill_action)
        scope_action = _gsd_patch_action(spec, extra_deps=(install_component, *install_deps))
        if scope_action:
            actions.append(scope_action)
    return actions


def _bundled_skill_repair_actions(
    statuses: list[BundledSkillStatus],
    npx_tools: list[NpxToolStatus],
) -> list[DoctorAction]:
    """Re-sync skills whose target dir lost its SKILL.md but whose npm tool
    is still on PATH. (When the npm tool itself is missing, _npx_install_actions
    already queues the full install + skill-sync chain.)
    """
    actions: list[DoctorAction] = []
    npx_available_by_name = {st.spec.name: st.available for st in npx_tools}
    for st in statuses:
        if st.skill_md_present:
            continue
        # Tool itself missing → main install path will handle the skill sync.
        if not npx_available_by_name.get(st.spec.name, False):
            continue
        action = _bundled_skill_action(st.spec)
        if action:
            actions.append(action)
    return actions


def _browser_bundle_repair_actions(
    statuses: list[BrowserBundleStatus],
    npx_tools: list[NpxToolStatus],
    *,
    use_deps: tuple[str, ...] = (),
) -> list[DoctorAction]:
    """Re-fetch missing browser bundles when the tool itself is on PATH.

    Each missing bundle becomes a single `<binary> install-browser <name>`
    action, mirroring the post_install entries in defaults.py. The command
    is idempotent on Playwright's side, so re-running it for an already-
    present bundle is safe — we still skip it here to keep the plan tight.
    """
    actions: list[DoctorAction] = []
    npx_available_by_name = {st.spec.name: st.available for st in npx_tools}
    for st in statuses:
        if st.all_present:
            continue
        if not npx_available_by_name.get(st.spec.name, False):
            continue
        for bundle, present in st.present.items():
            if present:
                continue
            cmd = [st.spec.name, "install-browser", bundle]
            actions.append(
                DoctorAction(
                    label=f"{st.spec.name}: install-browser {bundle}",
                    cmd=cmd,
                    runnable=True,
                    component=f"npx:{st.spec.name}:browser:{bundle}",
                    depends_on_components=use_deps,
                    auto_confirm=True,  # follow-up of an auto-confirmed npx maintenance step
                )
            )
    return actions


def _foreign_plugin_remove_actions(
    statuses: list[ForeignPluginStatus],
) -> list[DoctorAction]:
    """Plan `claude plugin uninstall` steps for plugins outside the spec.

    Only emitted by `build_optimize_plan` when `--strict` is set. Without
    strict mode, foreign plugins are surfaced as a warning block in the
    reporter — keeping the default behaviour conservative so a single user
    declaring `doctor.plugins:` does not nuke peer-installed tooling.

    Scope is forwarded as `--scope <value>` when the detector parsed it
    out of `claude plugin list`; otherwise `claude plugin uninstall`
    defaults to scope=user. This mirrors `_plugin_update_actions` so
    project/local/managed installs are uninstalled cleanly.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        target = f"{st.name}@{st.marketplace}" if st.marketplace else st.name
        cmd = ["claude", "plugin", "uninstall", target]
        scope_label = ""
        if st.scope and st.scope.lower() in _VALID_PLUGIN_SCOPES:
            cmd.extend(["--scope", st.scope.lower()])
            scope_label = f" (scope: {st.scope.lower()})"
        actions.append(
            DoctorAction(
                label=f"REMOVE foreign plugin {target}{scope_label}",
                cmd=cmd,
                runnable=True,
                # foreign:<name> component so a future plugin-install action
                # for the same name can depend on it if needed.
                component=f"foreign-plugin:{st.name}",
            )
        )
    return actions


def _foreign_mcp_remove_actions(
    statuses: list[ForeignMCPServerStatus],
) -> list[DoctorAction]:
    """Plan `claude mcp remove` steps for MCP servers outside the spec.

    Only emitted by `build_optimize_plan` when `--strict` is set. Default
    scope is `user` — matches `claude mcp remove`'s own default, and we
    don't have a reliable per-server scope from `claude mcp list` output.

    Server names with embedded spaces or colons (e.g. `claude.ai Gmail`,
    `plugin:context-mode:context-mode`) are quoted by the runner's argv
    handling — no shell expansion happens because `_run(shell=False)`.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        cmd = ["claude", "mcp", "remove", st.name, "-s", "user"]
        actions.append(
            DoctorAction(
                label=f"REMOVE foreign MCP server {st.name}",
                cmd=cmd,
                runnable=True,
                component=f"foreign-mcp:{st.name}",
            )
        )
    return actions


def _settings_hook_cleanup_actions(
    violations: list[SettingsHookViolation],
    *,
    settings_path: Path,
) -> list[DoctorAction]:
    """Queue a single sanitiser action that removes disallowed hooks from
    settings.json (after writing a timestamped backup).

    Strategy: collect ALL violations into one action rather than emitting
    one action per violation. Reason: the python_callable rewrites the
    whole file atomically, and per-violation confirms would force the
    user to say yes N times to a single semantic operation. The single
    action's manual_block lists every violation it intends to remove so
    the confirm prompt is still informed.

    Removal rules:
      * `hooks[event][i].hooks[j]` entries whose `command` substring-matches
        any disallowed pattern are deleted.
      * If an event's outer entry (`hooks[event][i]`) ends up with an
        empty inner `hooks` list after removal, the outer entry is
        dropped too — otherwise settings.json accumulates dead `{matcher:
        …, hooks: []}` blocks across runs.
      * If an event itself ends up empty, the event key is removed.

    Idempotent: a second run after sanitisation finds no violations and
    returns []. No action queued.
    """
    if not violations:
        return []

    # Group violations by command for the manual_block so the user sees
    # "PreToolUse: Write|Edit → gsd-read-guard.js" rather than a wall of
    # paths. Pattern-list per command gives stable output across runs.
    block_lines = ["# Will sanitise settings.json — remove these hook entries:"]
    for v in violations:
        matcher_label = f" [{v.matcher}]" if v.matcher else ""
        block_lines.append(f"#   - {v.event}{matcher_label} → matched {v.matched_pattern!r}")
    block_lines.append(f"# Backup will be written next to {settings_path.name}.")

    # Snapshot the violation set into the closure so the action remains
    # valid if settings.json is mutated between plan-build and execute
    # (worst case: we re-read fresh and find the same violations again).
    patterns_to_remove = sorted({v.matched_pattern for v in violations})

    def _sanitise(p: Path = settings_path, pats: list[str] = patterns_to_remove) -> None:
        """Rewrite settings.json without entries matching disallowed patterns."""
        if not p.is_file():
            return  # nothing to do — settings.json vanished between detect and run
        text = p.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DoctorError(f"settings.json is not valid JSON: {exc}") from exc

        hooks_root = data.get("hooks")
        if not isinstance(hooks_root, dict):
            return  # no hooks block — nothing to sanitise

        _write_settings_backup(p, text)

        new_hooks: dict[str, list[dict]] = {}
        for event, entries in hooks_root.items():
            if not isinstance(entries, list):
                new_hooks[event] = entries
                continue
            kept_entries: list[dict] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    kept_entries.append(entry)
                    continue
                inner = entry.get("hooks")
                if not isinstance(inner, list):
                    kept_entries.append(entry)
                    continue
                kept_inner = [
                    ih
                    for ih in inner
                    if not (
                        isinstance(ih, dict)
                        and isinstance(ih.get("command"), str)
                        and any(pat in ih["command"] for pat in pats)
                    )
                ]
                if kept_inner:
                    new_entry = dict(entry)
                    new_entry["hooks"] = kept_inner
                    kept_entries.append(new_entry)
                # else: drop the outer entry — its hooks list is empty.
            if kept_entries:
                new_hooks[event] = kept_entries
            # else: drop the event key — no entries left.

        data["hooks"] = new_hooks
        # Atomic write (temp + os.replace) — see _status_line_actions for rationale.
        atomic_write(p, json.dumps(data, indent=2) + "\n", mode=0o600)

    return [
        DoctorAction(
            label=f"sanitise settings.json: remove {len(violations)} disallowed hook(s)",
            cmd=[],
            runnable=True,
            python_callable=_sanitise,
            manual_block="\n".join(block_lines),
            component="settings-hooks:sanitise",
        )
    ]


def _statusline_preset_install_actions(statusline_presets: list | None) -> list[DoctorAction]:
    """Offer to install the CONFIGURED statusline when it is missing.

    Only the preset named by `statusline.active` qualifies: installing a
    statusline the user has not chosen would be surprising, and merely
    having a preset defined says nothing about wanting it.

    Third-party code, so the action carries an explicit warning in its
    manual block and — like every runnable action — a confirm prompt that
    defaults to No. The install itself never pipes curl into a shell; see
    statusline.install_preset().
    """
    from sccs.doctor.statusline import (
        StatusLineError,
        install_command_hint,
        install_preset,
        resolve_statusline_presets,
    )

    actions: list[DoctorAction] = []
    presets = resolve_statusline_presets(None)

    for st in statusline_presets or []:
        if not st.is_configured or st.installed or not st.installable:
            continue
        preset = presets.get(st.name)
        if preset is None or not preset.install_url:
            continue

        posix_hint = install_command_hint(preset)
        block = "\n".join(
            [
                f"# Installs the '{st.name}' statusline by running a third-party script:",
                f"#   {preset.install_url}",
                "# SCCS downloads it to a temp file and runs it with bash —",
                "# it is never piped from curl into a shell.",
                f"# By hand: {posix_hint}",
            ]
        )

        def _install(p=preset) -> None:
            try:
                install_preset(p)
            except StatusLineError as exc:
                raise DoctorError(str(exc)) from exc

        actions.append(
            DoctorAction(
                label=f"install statusline '{st.name}' (runs a third-party installer)",
                cmd=[],
                runnable=True,
                python_callable=_install,
                manual_block=block,
                component=f"statusline-preset:{st.name}",
            )
        )
    return actions


def _orphan_backup_root() -> Path:
    """Base dir under which orphan backups are created. Mirrors the doctor
    state location (~/.config/sccs); monkeypatch Path.home in tests."""
    return Path.home() / ".config" / "sccs"


def _managed_orphan_cleanup_actions(
    npx_tools: list[NpxToolStatus],
    gsd_orphans: list[GsdOrphanStatus] | None = None,
) -> list[DoctorAction]:
    """Queue a move-to-backup cleanup for orphaned doctor-managed artefacts.

    Real driver: gsd-core's own legacy cleanup only prunes stale hooks/ and
    commands/, so skills/ and agents/ from a superseded package (e.g.
    @opengsd/get-shit-done-redux) pile up. After the npx (re)install rewrites
    the tool's manifest, any on-disk gsd-* artefact the manifest does not
    reference is stale. We MOVE (never hard-delete) each orphan into a
    timestamped backup dir so the operation is reversible.

    `gsd_orphans` carries the CURRENT detector results (pre-install), computed
    once by the caller — the plan builder itself does no filesystem I/O, so it
    stays test-isolated (pass None → nothing queued). An action is queued only
    when the matching status shows a real reason at plan-build:
      * current orphans already exist (vs the current manifest), or
      * a legacy-layout dir is physically present (migration pending — the
        old manifest still owns everything, so `has_orphans` is False yet the
        cleanup is genuinely due).
    On a clean, already-migrated host nothing is queued, so `doctor update`
    does not nag. The closure RE-DETECTS against the fresh (post-install)
    manifest via the tool's spec, so it reflects the new package's file set and
    is a no-op when nothing is orphaned.

    auto_confirm stays False: this is a delete-class operation, so the user is
    asked every time (`--yes` is the blanket override), per the global
    delete-safety rule. Runs after the npx action (which rewrites the
    manifest) and is fenced off via depends_on_components if that install
    failed.
    """
    by_name = {g.tool_name: g for g in (gsd_orphans or [])}
    actions: list[DoctorAction] = []
    for tool_status in npx_tools:
        spec = tool_status.spec
        if not spec.managed_file_manifest:
            continue

        current = by_name.get(spec.name)
        if current is None:
            continue
        if not (current.has_orphans or current.legacy_present):
            continue

        block_lines = ["# Will move orphaned doctor-managed artefacts to a backup dir:"]
        if current.has_orphans:
            for p in current.orphan_paths:
                block_lines.append(f"#   - {p}")
        else:
            block_lines.append("#   (set computed after the (re)install rewrites the manifest)")
        block_lines.append(f"# Backup root: {_orphan_backup_root()}/gsd-orphans-backup-<timestamp>/")

        def _cleanup(spec: NpxToolSpec = spec) -> None:
            """Re-detect against the fresh manifest and move orphans to backup."""
            fresh = GsdOrphanDetector().get_statuses([spec])
            st = fresh[0] if fresh else None
            if st is None or not st.has_orphans:
                return  # nothing orphaned against the post-install manifest
            if spec.managed_file_manifest is None:
                raise DoctorError(f"Cannot clean up orphans for {spec.name!r}: managed_file_manifest is missing")
            config_root = expand_path(spec.managed_file_manifest).parent
            timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_root = _orphan_backup_root() / f"gsd-orphans-backup-{timestamp}"
            for orphan in st.orphan_paths:
                try:
                    rel = orphan.relative_to(config_root)
                except ValueError:
                    rel = Path(orphan.name)
                dest = backup_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(orphan), str(dest))

        actions.append(
            DoctorAction(
                label=f"clean up orphaned {spec.name} artefacts (move to backup)",
                cmd=[],
                runnable=True,
                python_callable=_cleanup,
                manual_block="\n".join(block_lines),
                component=f"orphan-cleanup:{spec.name}",
                depends_on_components=(f"npx:{spec.name}",),
            )
        )
    return actions


def _mcp_server_install_warnings(
    statuses: list[MCPServerStatus],
) -> list[DoctorAction]:
    """Warn (no runnable action) when a spec'd MCP server is missing.

    `claude mcp add` needs the server's command/URL — information we
    don't carry in `MCPServerSpec` (only name + scope). Surfacing this
    as a manual_block tells the user what to do without inventing
    fragile auto-install logic.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        if st.installed:
            continue
        block = (
            f"# MCP server '{st.spec.name}' is declared in doctor.mcp_servers "
            f"but not registered locally.\n"
            f"# Add it manually with the correct command/URL, e.g.:\n"
            f"#   claude mcp add {st.spec.name} <command-or-url> -s {st.spec.scope}"
        )
        actions.append(
            DoctorAction(
                label=f"missing MCP server {st.spec.name} — manual setup required",
                cmd=[],
                runnable=False,
                manual_block=block,
                component=f"mcp:{st.spec.name}",
            )
        )
    return actions


def _blocking_components(
    permissions: list[PermissionStatus] | None,
    path_prefixes: list[PathPrefixStatus] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Compute (install_deps, use_deps) component tuples for npx steps.

    install_deps: must be writable to even attempt `npm install -g`
        (currently only `perm:npm root -g`).
    use_deps: install_deps PLUS PATH-correctness — a freshly-installed
        binary lives under `<npm prefix>/bin`, but a stale shell PATH
        keeps `shutil.which()` returning None and post_install fails with
        "command not found". Modelling these as dependencies turns the
        cascade noise into clean `skipped` rows.
    """
    install: list[str] = []
    use: list[str] = []
    if permissions:
        for perm_st in permissions:
            # Both the global root (lib/node_modules) and the global bin dir
            # must be writable for `npm install -g` to succeed: it writes the
            # package under root and symlinks the binary under bin. Gating on
            # both closes the Linux system-npm gap where chowning only the root
            # passed the check but the bin-dir symlink still failed with EACCES.
            if not perm_st.ok and perm_st.spec.path_kind in ("npm-root-global", "npm-bin-global"):
                comp = f"perm:{perm_st.spec.path}"
                install.append(comp)
                use.append(comp)
    if path_prefixes:
        for path_st in path_prefixes:
            if not path_st.ok:
                use.append(f"path:{path_st.spec.identifier}")
    return tuple(install), tuple(use)


def build_install_plan(
    config: DoctorConfig,  # noqa: ARG001 — kept for symmetry with build_update_plan
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
    settings_hook_violations: list[SettingsHookViolation] | None = None,
    settings_path: Path | None = None,
    gsd_orphans: list[GsdOrphanStatus] | None = None,
    cli_tools: list[CliToolStatus] | None = None,
    statusline_presets: list | None = None,
) -> InstallPlan:
    """Plan the actions needed to bring a missing/outdated host up to spec."""
    actions: list[DoctorAction] = []
    # Permission and PATH issues come FIRST so the user sees the manual
    # remediation block before any downstream subprocess fails with EACCES
    # or "command not found". Their `blocks_downstream=True` fences off the
    # subsequent install / post_install / skill-sync actions in execute_plan.
    if permissions:
        actions.extend(_permission_actions(permissions))
    if path_prefixes:
        actions.extend(_path_prefix_actions(path_prefixes))
    if marketplaces:
        actions.extend(_marketplace_missing_actions(marketplaces))
    install_deps, use_deps = _blocking_components(permissions, path_prefixes)
    node_action = _node_action(node)
    if node_action:
        actions.append(node_action)
    cli_action = _claude_cli_action(claude_cli)
    if cli_action:
        actions.append(cli_action)
    actions.extend(_plugin_install_actions(plugins, marketplaces=marketplaces))
    actions.extend(_npx_install_actions(npx_tools, install_deps=install_deps, use_deps=use_deps))
    # Orphan cleanup runs after the npx install rewrites the tool manifest.
    actions.extend(_managed_orphan_cleanup_actions(npx_tools, gsd_orphans))
    if bundled_skills:
        actions.extend(_bundled_skill_repair_actions(bundled_skills, npx_tools))
    if browser_bundles:
        actions.extend(_browser_bundle_repair_actions(browser_bundles, npx_tools, use_deps=use_deps))
    if status_lines:
        actions.extend(_status_line_actions(status_lines))
    actions.extend(_cli_tool_install_actions(cli_tools))
    actions.extend(_statusline_preset_install_actions(statusline_presets))
    # Settings.json sanitisation runs LAST so that third-party tools
    # (@opengsd/gsd-core, etc.) which overwrite settings.json during their
    # install step are followed by our cleanup pass.
    if settings_hook_violations and settings_path is not None:
        actions.extend(_settings_hook_cleanup_actions(settings_hook_violations, settings_path=settings_path))
    return InstallPlan(actions=actions)


def build_update_plan(
    config: DoctorConfig,  # noqa: ARG001
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    permissions: list[PermissionStatus] | None = None,
    path_prefixes: list[PathPrefixStatus] | None = None,
    marketplaces: list[MarketplaceStatus] | None = None,
    bundled_skills: list[BundledSkillStatus] | None = None,  # noqa: ARG001 — symmetry
    browser_bundles: list[BrowserBundleStatus] | None = None,  # noqa: ARG001 — symmetry
    status_lines: list[StatusLineStatus] | None = None,
    settings_hook_violations: list[SettingsHookViolation] | None = None,
    settings_path: Path | None = None,
    gsd_orphans: list[GsdOrphanStatus] | None = None,
    cli_tools: list[CliToolStatus] | None = None,
) -> InstallPlan:
    """Plan an update pass: refresh installed plugins + npx tools, plus install missing ones.

    bundled_skills / browser_bundles are accepted but unused: `_npx_update_actions`
    already queues the bundled-skill copy and every `post_install` browser-fetch
    on each tool's update, so adding them here would duplicate the work.
    """
    actions: list[DoctorAction] = []
    if permissions:
        actions.extend(_permission_actions(permissions))
    if path_prefixes:
        actions.extend(_path_prefix_actions(path_prefixes))
    if marketplaces:
        actions.extend(_marketplace_missing_actions(marketplaces))
    install_deps, use_deps = _blocking_components(permissions, path_prefixes)
    node_action = _node_action(node)
    if node_action:
        actions.append(node_action)
    cli_action = _claude_cli_action(claude_cli)
    if cli_action:
        actions.append(cli_action)
    # First install anything missing, then update everything that's there.
    actions.extend(_plugin_install_actions(plugins, marketplaces=marketplaces))
    actions.extend(_plugin_update_actions(plugins))
    actions.extend(_npx_update_actions(npx_tools, install_deps=install_deps, use_deps=use_deps))
    # Orphan cleanup runs after the npx refresh rewrites the tool manifest.
    actions.extend(_managed_orphan_cleanup_actions(npx_tools, gsd_orphans))
    if status_lines:
        actions.extend(_status_line_actions(status_lines))
    actions.extend(_cli_tool_install_actions(cli_tools))
    if settings_hook_violations and settings_path is not None:
        actions.extend(_settings_hook_cleanup_actions(settings_hook_violations, settings_path=settings_path))
    return InstallPlan(actions=actions)


def build_optimize_plan(
    config: DoctorConfig,  # noqa: ARG001 — symmetry with build_install_plan / build_update_plan
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    foreign_plugins: list[ForeignPluginStatus],
    mcp_servers: list[MCPServerStatus],
    foreign_mcp_servers: list[ForeignMCPServerStatus],
    npx_tools: list[NpxToolStatus],
    permissions: list[PermissionStatus] | None = None,
    path_prefixes: list[PathPrefixStatus] | None = None,
    marketplaces: list[MarketplaceStatus] | None = None,
    status_lines: list[StatusLineStatus] | None = None,
    settings_hook_violations: list[SettingsHookViolation] | None = None,
    settings_path: Path | None = None,
    gsd_orphans: list[GsdOrphanStatus] | None = None,
    cli_tools: list[CliToolStatus] | None = None,
    strict: bool = False,
) -> InstallPlan:
    """Plan a one-shot optimize pass.

    Combines `build_update_plan`'s install+update behaviour with two new
    concerns:

      * `foreign_plugins` — installed but not in the spec. With
        `strict=True`, queue `claude plugin uninstall` actions; without
        strict, surface them as a manual_block warning so the user can
        review before the next strict run.
      * `foreign_mcp_servers` — registered with Claude but not in
        `doctor.mcp_servers` and not matching `ignored_mcp_patterns`.
        Same strict/non-strict split as foreign plugins.
      * `mcp_servers` — spec'd servers that are missing get a manual_block
        only (since `claude mcp add` needs command/URL info we don't
        carry in the spec).

    Strict-mode uninstall actions run BEFORE plugin install/update so a
    foreign claude-mem cannot get refreshed in the same pass that's
    removing it.
    """
    actions: list[DoctorAction] = []
    if permissions:
        actions.extend(_permission_actions(permissions))
    if path_prefixes:
        actions.extend(_path_prefix_actions(path_prefixes))
    if marketplaces:
        actions.extend(_marketplace_missing_actions(marketplaces))
    install_deps, use_deps = _blocking_components(permissions, path_prefixes)
    node_action = _node_action(node)
    if node_action:
        actions.append(node_action)
    cli_action = _claude_cli_action(claude_cli)
    if cli_action:
        actions.append(cli_action)

    # Strict cleanup happens first so subsequent install/update steps don't
    # race against foreign entries we're about to remove.
    if strict:
        actions.extend(_foreign_plugin_remove_actions(foreign_plugins))
        actions.extend(_foreign_mcp_remove_actions(foreign_mcp_servers))
    else:
        # Non-strict: surface the foreign set as a single warning block per
        # category. This avoids spamming the action list with manual_blocks
        # that the user has to scroll past on every `optimize` run, while
        # still making the drift visible.
        if foreign_plugins:
            lines = ["# Foreign Claude plugins (not in doctor.plugins):"]
            for fp in foreign_plugins:
                target = f"{fp.name}@{fp.marketplace}" if fp.marketplace else fp.name
                lines.append(f"#   - {target}" + (f"  [scope: {fp.scope}]" if fp.scope else ""))
            lines.append("# Re-run with `--strict` to queue uninstall actions.")
            actions.append(
                DoctorAction(
                    label=f"{len(foreign_plugins)} foreign plugin(s) detected — review needed",
                    cmd=[],
                    runnable=False,
                    manual_block="\n".join(lines),
                    component="foreign-plugins:summary",
                )
            )
        if foreign_mcp_servers:
            lines = ["# Foreign MCP servers (not in doctor.mcp_servers, not ignored):"]
            for fm in foreign_mcp_servers:
                lines.append(f"#   - {fm.name}")
            lines.append("# Re-run with `--strict` to queue `claude mcp remove` actions.")
            actions.append(
                DoctorAction(
                    label=f"{len(foreign_mcp_servers)} foreign MCP server(s) detected — review needed",
                    cmd=[],
                    runnable=False,
                    manual_block="\n".join(lines),
                    component="foreign-mcp:summary",
                )
            )

    # Same install+update sequence as build_update_plan so optimize is a
    # superset of update: anything update would do, optimize also does.
    actions.extend(_plugin_install_actions(plugins, marketplaces=marketplaces))
    actions.extend(_plugin_update_actions(plugins))
    actions.extend(_npx_update_actions(npx_tools, install_deps=install_deps, use_deps=use_deps))
    # Orphan cleanup runs after the npx refresh rewrites the tool manifest.
    actions.extend(_managed_orphan_cleanup_actions(npx_tools, gsd_orphans))

    # Spec'd-but-missing MCP servers get a manual_block (no auto-add).
    actions.extend(_mcp_server_install_warnings(mcp_servers))

    actions.extend(_cli_tool_install_actions(cli_tools))

    if status_lines:
        actions.extend(_status_line_actions(status_lines))
    # Settings.json sanitisation always runs LAST so any settings.json
    # rewrites performed by upstream actions (npx tools, plugin installs,
    # statusline auto-fix) happen before our cleanup pass.
    if settings_hook_violations and settings_path is not None:
        actions.extend(_settings_hook_cleanup_actions(settings_hook_violations, settings_path=settings_path))
    return InstallPlan(actions=actions)


def _confirm(label: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        answer = questionary.confirm(f"Run: {label}?", default=False).ask()
    except (KeyboardInterrupt, EOFError):
        return False
    return bool(answer)


def execute_plan(
    plan: InstallPlan,
    *,
    assume_yes: bool = False,
    print_fn=None,
    state_manager: DoctorStateManager | None = None,
) -> ExecuteResult:
    """Execute the plan, prompting before each runnable action.

    print_fn(text: str) is used for both manual blocks and human status
    updates. Defaults to builtin print. Pass console.print_info or similar
    when wiring into the CLI.

    state_manager records successful runs of npx tools whose action carries
    an `npx_tool_name` — needed for tools that don't drop a binary on PATH
    so future `sccs doctor check` calls can still report them as installed.

    Cascade-Resilience (v2.28.0): we maintain two component-sets across the
    iteration. `failed_components` collects components whose runnable action
    raised. `blocked_components` collects components whose `manual_block`
    action was printed and was marked `blocks_downstream=True`. Any later
    action that lists a member of either set in `depends_on_components` is
    reported as `skipped` *without* spawning a subprocess — turning the
    multi-error cascade users used to see (EACCES → command-not-found →
    bundled-skill-not-found) into one decisive `printed` row plus a few
    quiet `⊘ skipped` lines.
    """
    out_print = print_fn or print
    result = ExecuteResult()
    failed_components: set[str] = set()
    blocked_components: set[str] = set()

    for action in plan.actions:
        # Cascade-skip: any blocked or failed dependency turns this into a
        # no-op. Evaluated BEFORE the manual-block / confirm path so a
        # blocked downstream action never even prints a prompt.
        blocking = sorted(
            {c for c in action.depends_on_components if c in failed_components or c in blocked_components}
        )
        if blocking:
            joined = ", ".join(blocking)
            result.outcomes.append(
                ActionOutcome(
                    label=action.label,
                    status="skipped",
                    detail=f"depends on {joined}",
                )
            )
            logger.info("doctor action skipped: %s — depends on %s", action.label, joined)
            continue

        if action.is_print_only():
            block = action.manual_block or "(no command)"
            out_print(f"\n[manual] {action.label}\n{block}")
            result.outcomes.append(ActionOutcome(label=action.label, status="printed", detail=block))
            if action.blocks_downstream and action.component:
                blocked_components.add(action.component)
            continue

        if not _confirm(action.label, assume_yes=assume_yes or action.auto_confirm):
            result.outcomes.append(ActionOutcome(label=action.label, status="skipped", detail="user declined"))
            continue

        try:
            if action.python_callable is not None:
                # In-process action (e.g. bundled-skill copy). Errors are
                # surfaced as DoctorError just like subprocess failures.
                action.python_callable()
                result.outcomes.append(ActionOutcome(label=action.label, status="executed"))
                logger.info("doctor action ok: %s", action.label)
                continue

            if action.cmd is None:
                raise DoctorError(f"Action {action.label!r} is not print-only but has no command")
            proc = _run(action.cmd, check=True, capture=True, timeout=300)
            detail = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
            result.outcomes.append(ActionOutcome(label=action.label, status="executed", detail=detail))
            logger.info("doctor action ok: %s", action.label)
            # Persist marker for state-tracked npx tools.
            if state_manager is not None and action.npx_tool_name is not None and action.npx_invocation is not None:
                try:
                    state_manager.mark_npx_tool(action.npx_tool_name, action.npx_invocation)
                except OSError as state_err:
                    logger.warning(
                        "could not write doctor state for %s: %s",
                        action.npx_tool_name,
                        state_err,
                    )
        except DoctorError as err:
            err_text = (err.stderr or str(err)).lower()
            # Soft-fail when a plugin update reports "not installed at scope X" —
            # detection said the plugin was there, so this is a list/update
            # mismatch in the Claude CLI rather than a genuine install problem.
            if "not installed at scope" in err_text and action.component.startswith("plugin:"):
                result.outcomes.append(
                    ActionOutcome(
                        label=action.label,
                        status="skipped",
                        detail=f"scope mismatch — plugin already installed elsewhere: {err.stderr or err}",
                    )
                )
                logger.warning("doctor plugin update skipped (scope mismatch): %s — %s", action.label, err)
            elif action.soft_fail:
                # Best-effort step (e.g. marketplace update). Surface the
                # error as a yellow `warned` row instead of red FAILED so
                # the user knows it's nice-to-have, not blocking.
                result.outcomes.append(
                    ActionOutcome(label=action.label, status="warned", detail=err.stderr or str(err))
                )
                logger.info("doctor soft-fail: %s — %s", action.label, err)
            else:
                detail = err.stderr or str(err)
                hint = _diagnose_hint(detail)
                if hint:
                    detail = f"{detail.strip()}\n  → {hint}"
                if action.component:
                    failed_components.add(action.component)
                result.outcomes.append(ActionOutcome(label=action.label, status="failed", detail=detail))
                logger.warning("doctor action failed: %s — %s", action.label, err)
        except OSError as err:
            # Python-callable filesystem error (copytree etc.)
            if action.component:
                failed_components.add(action.component)
            result.outcomes.append(ActionOutcome(label=action.label, status="failed", detail=str(err)))
            logger.warning("doctor action failed: %s — %s", action.label, err)

    return result
