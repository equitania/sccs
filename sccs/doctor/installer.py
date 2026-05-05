# SCCS Doctor Installer
#
# HARD RULES (mirrored from runner.py):
#   1. Confirm-prompt before EVERY runnable action; default = No.
#   2. requires_sudo / runnable=False actions are PRINTED ONLY, never executed.
#   3. argv lists are pre-validated when constructed; runner._run validates again.

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import questionary

from sccs.doctor.detectors import (
    BrowserBundleStatus,
    BundledSkillStatus,
    ClaudeCliStatus,
    NodeStatus,
    NpxToolStatus,
    PermissionStatus,
    PluginStatus,
)
from sccs.doctor.runner import DoctorError, _run
from sccs.doctor.schema import BundledSkillSpec, DoctorConfig, NpxToolSpec
from sccs.doctor.state import DoctorStateManager
from sccs.utils.logging import get_logger

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
    status: str  # "executed" | "skipped" | "printed" | "failed"
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


def _npm_root_global_fix_block(st: PermissionStatus) -> list[str]:
    """Two-option remediation for an unwritable `npm root -g` directory.

    Real Debian incident: system npm installs land in /usr/lib/node_modules/
    (root-owned), so `npm install -g @playwright/cli@latest` dies with EACCES.
    Doctor surfaces this *before* the npm action runs and offers both:

      * Preferred: user-local npm prefix (`~/.npm-global`) — no sudo required,
        survives `apt install nodejs` cleanly.
      * Alternative: `sudo chown -R` of the existing global root — quicker
        but reverts on every system-wide nodejs upgrade.
    """
    lines: list[str] = []
    lines.append(f"# Detected: {st.resolved_path} is not writable by uid {st.expected_uid}.")
    lines.append("# Two fixes — pick ONE:")
    lines.append("")
    lines.append("# Option A (recommended): user-local npm prefix, no sudo")
    # Pre-create lib/ and bin/ — without them, the next `npx -y <tool>` will
    # die with ENOENT on `<prefix>/lib` because npx lstat's the dir before the
    # first npm install -g would have created it. Real Debian incident.
    lines.append("mkdir -p ~/.npm-global/lib ~/.npm-global/bin")
    lines.append("npm config set prefix ~/.npm-global")
    lines.append("# Add to your shell rc (bash/zsh):")
    lines.append('export PATH="$HOME/.npm-global/bin:$PATH"')
    lines.append("# Or fish:")
    lines.append("set -gx PATH $HOME/.npm-global/bin $PATH")
    lines.append("")
    lines.append("# Option B: take ownership of the system npm root")
    lines.append(st.fix_command or f"sudo chown -R {st.expected_uid}:{st.expected_gid} {st.resolved_path}")
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
        if st.spec.path_kind == "npm-root-global":
            block_lines.extend(_npm_root_global_fix_block(st))
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


def _claude_cli_action(status: ClaudeCliStatus) -> DoctorAction | None:
    if status.installed:
        return None
    return DoctorAction(
        label="install Claude Code CLI (npm i -g @anthropic-ai/claude-code)",
        cmd=["npm", "install", "-g", "@anthropic-ai/claude-code"],
        runnable=True,
        component="claude-cli",
    )


def _plugin_install_actions(statuses: list[PluginStatus]) -> list[DoctorAction]:
    actions: list[DoctorAction] = []
    for st in statuses:
        if st.installed:
            continue
        spec = st.spec
        if spec.marketplace_source:
            actions.append(
                DoctorAction(
                    label=f"register marketplace {spec.marketplace_source}",
                    cmd=["claude", "plugin", "marketplace", "add", spec.marketplace_source],
                    runnable=True,
                    component=f"plugin:{spec.name}",
                )
            )
        actions.append(
            DoctorAction(
                label=f"install plugin {spec.install_target}",
                cmd=["claude", "plugin", "install", spec.install_target],
                runnable=True,
                component=f"plugin:{spec.name}",
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
            )
        )
    return actions


def _post_install_actions(spec: NpxToolSpec) -> list[DoctorAction]:
    """Action list for `spec.post_install` (e.g. `playwright-cli install-browser …`).

    These run after the main invocation succeeds. They are intentionally
    treated as regular runnable actions so the user sees the confirm prompt
    and the result lands in `ExecuteResult` like every other step.
    """
    return [
        DoctorAction(
            label=f"{spec.name}: {' '.join(cmd)}",
            cmd=list(cmd),
            runnable=True,
            component=f"npx:{spec.name}:post",
        )
        for cmd in spec.post_install
    ]


def _bundled_skill_action(spec: NpxToolSpec) -> DoctorAction | None:
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
        python_callable=_run_skill_sync,
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


def _npx_install_actions(statuses: list[NpxToolStatus]) -> list[DoctorAction]:
    actions: list[DoctorAction] = []
    for st in statuses:
        if st.available:
            continue
        spec = st.spec
        actions.append(
            DoctorAction(
                label=f"install npx tool {spec.name}",
                cmd=list(spec.invocation),
                runnable=True,
                component=f"npx:{spec.name}",
                npx_tool_name=spec.name if spec.detect_via_state else None,
                npx_invocation=list(spec.invocation) if spec.detect_via_state else None,
            )
        )
        actions.extend(_post_install_actions(spec))
        skill_action = _bundled_skill_action(spec)
        if skill_action:
            actions.append(skill_action)
    return actions


def _npx_update_actions(statuses: list[NpxToolStatus]) -> list[DoctorAction]:
    """Re-run the `npx ...` invocation; npx will fetch the latest version.

    Always re-runs `post_install` and `bundled_skill` so an npm update that
    bumps the bundled browser drivers or skill content propagates to the
    user's machine without manual intervention.
    """
    actions: list[DoctorAction] = []
    for st in statuses:
        spec = st.spec
        actions.append(
            DoctorAction(
                label=f"refresh npx tool {spec.name}",
                cmd=list(spec.invocation),
                runnable=True,
                component=f"npx:{spec.name}",
                npx_tool_name=spec.name if spec.detect_via_state else None,
                npx_invocation=list(spec.invocation) if spec.detect_via_state else None,
            )
        )
        actions.extend(_post_install_actions(spec))
        skill_action = _bundled_skill_action(spec)
        if skill_action:
            actions.append(skill_action)
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
                )
            )
    return actions


def build_install_plan(
    config: DoctorConfig,  # noqa: ARG001 — kept for symmetry with build_update_plan
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    permissions: list[PermissionStatus] | None = None,
    bundled_skills: list[BundledSkillStatus] | None = None,
    browser_bundles: list[BrowserBundleStatus] | None = None,
) -> InstallPlan:
    """Plan the actions needed to bring a missing/outdated host up to spec."""
    actions: list[DoctorAction] = []
    # Permission issues come FIRST so the user sees the chown command before
    # any downstream subprocess fails with EACCES.
    if permissions:
        actions.extend(_permission_actions(permissions))
    node_action = _node_action(node)
    if node_action:
        actions.append(node_action)
    cli_action = _claude_cli_action(claude_cli)
    if cli_action:
        actions.append(cli_action)
    actions.extend(_plugin_install_actions(plugins))
    actions.extend(_npx_install_actions(npx_tools))
    if bundled_skills:
        actions.extend(_bundled_skill_repair_actions(bundled_skills, npx_tools))
    if browser_bundles:
        actions.extend(_browser_bundle_repair_actions(browser_bundles, npx_tools))
    return InstallPlan(actions=actions)


def build_update_plan(
    config: DoctorConfig,  # noqa: ARG001
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    permissions: list[PermissionStatus] | None = None,
    bundled_skills: list[BundledSkillStatus] | None = None,  # noqa: ARG001 — symmetry
    browser_bundles: list[BrowserBundleStatus] | None = None,  # noqa: ARG001 — symmetry
) -> InstallPlan:
    """Plan an update pass: refresh installed plugins + npx tools, plus install missing ones.

    bundled_skills / browser_bundles are accepted but unused: `_npx_update_actions`
    already queues the bundled-skill copy and every `post_install` browser-fetch
    on each tool's update, so adding them here would duplicate the work.
    """
    actions: list[DoctorAction] = []
    if permissions:
        actions.extend(_permission_actions(permissions))
    node_action = _node_action(node)
    if node_action:
        actions.append(node_action)
    cli_action = _claude_cli_action(claude_cli)
    if cli_action:
        actions.append(cli_action)
    # First install anything missing, then update everything that's there.
    actions.extend(_plugin_install_actions(plugins))
    actions.extend(_plugin_update_actions(plugins))
    actions.extend(_npx_update_actions(npx_tools))
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
    """
    out_print = print_fn or print
    result = ExecuteResult()

    for action in plan.actions:
        if action.is_print_only():
            block = action.manual_block or "(no command)"
            out_print(f"\n[manual] {action.label}\n{block}")
            result.outcomes.append(ActionOutcome(label=action.label, status="printed", detail=block))
            continue

        if not _confirm(action.label, assume_yes=assume_yes):
            result.outcomes.append(ActionOutcome(label=action.label, status="skipped"))
            continue

        try:
            if action.python_callable is not None:
                # In-process action (e.g. bundled-skill copy). Errors are
                # surfaced as DoctorError just like subprocess failures.
                action.python_callable()
                result.outcomes.append(ActionOutcome(label=action.label, status="executed"))
                logger.info("doctor action ok: %s", action.label)
                continue

            assert action.cmd is not None  # narrowed by is_print_only above
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
            # Soft-fail when a plugin update reports "not installed at scope X" —
            # detection said the plugin was there, so this is a list/update
            # mismatch in the Claude CLI rather than a genuine install problem.
            # Without this guard the user sees a red FAILED row for a plugin
            # that is in fact installed and working — just under a scope the
            # detector either didn't read or that update doesn't accept.
            err_text = (err.stderr or str(err)).lower()
            if "not installed at scope" in err_text and action.component.startswith("plugin:"):
                result.outcomes.append(
                    ActionOutcome(
                        label=action.label,
                        status="skipped",
                        detail=f"scope mismatch — plugin already installed elsewhere: {err.stderr or err}",
                    )
                )
                logger.warning("doctor plugin update skipped (scope mismatch): %s — %s", action.label, err)
            else:
                result.outcomes.append(
                    ActionOutcome(label=action.label, status="failed", detail=err.stderr or str(err))
                )
                logger.warning("doctor action failed: %s — %s", action.label, err)
        except OSError as err:
            # Python-callable filesystem error (copytree etc.)
            result.outcomes.append(ActionOutcome(label=action.label, status="failed", detail=str(err)))
            logger.warning("doctor action failed: %s — %s", action.label, err)

    return result
