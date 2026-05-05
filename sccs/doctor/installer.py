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


def _plugin_update_actions(statuses: list[PluginStatus]) -> list[DoctorAction]:
    actions: list[DoctorAction] = []
    for st in statuses:
        if not st.installed:
            # Skip — install plan covers missing plugins.
            continue
        target = _effective_update_target(st)
        actions.append(
            DoctorAction(
                label=f"update plugin {target}",
                cmd=["claude", "plugin", "update", target],
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


def build_install_plan(
    config: DoctorConfig,  # noqa: ARG001 — kept for symmetry with build_update_plan
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    permissions: list[PermissionStatus] | None = None,
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
    return InstallPlan(actions=actions)


def build_update_plan(
    config: DoctorConfig,  # noqa: ARG001
    *,
    node: NodeStatus,
    claude_cli: ClaudeCliStatus,
    plugins: list[PluginStatus],
    npx_tools: list[NpxToolStatus],
    permissions: list[PermissionStatus] | None = None,
) -> InstallPlan:
    """Plan an update pass: refresh installed plugins + npx tools, plus install missing ones."""
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
            result.outcomes.append(ActionOutcome(label=action.label, status="failed", detail=err.stderr or str(err)))
            logger.warning("doctor action failed: %s — %s", action.label, err)
        except OSError as err:
            # Python-callable filesystem error (copytree etc.)
            result.outcomes.append(ActionOutcome(label=action.label, status="failed", detail=str(err)))
            logger.warning("doctor action failed: %s — %s", action.label, err)

    return result
