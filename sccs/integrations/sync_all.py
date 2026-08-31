# SCCS — one pass across every installed agent CLI
#
# Without this, keeping four assistants current means running four to twelve
# separate export commands and remembering which ones exist on this machine.
# `sccs integrations sync-all` detects what is installed, shows one combined
# plan, asks once, and applies it.
#
# The adapters below are deliberately thin: each one wraps the SAME detector
# and writer the individual export command uses, so there is one export path
# per target, not two that can drift apart. What this module adds is detection,
# aggregation and a single confirmation.
#
# Two rules shape it:
#   - `--overwrite` is the DEFAULT here, unlike the individual commands. A
#     collection command that only ever creates new artefacts would never keep
#     anything current, which is the entire reason it exists.
#   - `--replace-foreign` is NOT the default. A target SCCS did not write may
#     hold somebody's hand edits, and a convenience command is the worst place
#     to discard those silently. Such targets are counted and named instead.
#
# Codex hooks are deliberately absent, for the same reason `codex export-all`
# omits them: a hook runs code on every matching tool call and deserves its own
# deliberate command.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class TargetPlan:
    """What one assistant needs, before anything is written."""

    key: str
    label: str
    installed: bool
    location: str | None = None
    # Artefact kind -> number of pending items ("skills" -> 12).
    counts: dict[str, int] = field(default_factory=dict)
    # Targets that exist but were not written by SCCS: reported, never touched
    # unless the user passes --replace-foreign.
    foreign: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def pending(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> str:
        """Human-readable count line, e.g. '12 skills, 2 agents'."""
        if not self.counts:
            return "up to date"
        return ", ".join(f"{count} {kind}" for kind, count in self.counts.items() if count)


@dataclass
class TargetOutcome:
    """What one assistant actually received."""

    key: str
    label: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)

    @property
    def changed(self) -> int:
        return self.created + self.updated


class Target(Protocol):
    """One assistant SCCS can export to."""

    key: str
    label: str

    def plan(self) -> TargetPlan: ...

    def apply(self, *, dry_run: bool, replace_foreign: bool) -> TargetOutcome: ...


def collect_plans(targets: list[Target]) -> list[TargetPlan]:
    """Plan every target, letting no single failure hide the others.

    A broken installation of one assistant must not stop the run: the plan
    records the error against that target and the remaining ones still report.
    """
    plans: list[TargetPlan] = []
    for target in targets:
        try:
            plans.append(target.plan())
        except Exception as exc:  # noqa: BLE001 - one bad target must not sink the pass
            plans.append(
                TargetPlan(key=target.key, label=target.label, installed=True, error=f"could not inspect: {exc}")
            )
    return plans


def apply_plans(
    targets: list[Target],
    plans: list[TargetPlan],
    *,
    dry_run: bool,
    replace_foreign: bool,
) -> list[TargetOutcome]:
    """Apply only the targets that are installed and actually have work."""
    by_key = {plan.key: plan for plan in plans}
    outcomes: list[TargetOutcome] = []
    for target in targets:
        plan = by_key.get(target.key)
        if plan is None or not plan.installed or plan.error or not plan.pending:
            continue
        try:
            outcomes.append(target.apply(dry_run=dry_run, replace_foreign=replace_foreign))
        except Exception as exc:  # noqa: BLE001 - report and continue to the next assistant
            outcomes.append(
                TargetOutcome(key=target.key, label=target.label, errors={target.key: f"export failed: {exc}"})
            )
    return outcomes


def plans_to_dict(plans: list[TargetPlan]) -> list[dict]:
    """JSON shape for `--json`, mirroring the Core-First commands."""
    return [
        {
            "target": plan.key,
            "label": plan.label,
            "installed": plan.installed,
            "location": plan.location,
            "pending": plan.pending,
            "counts": plan.counts,
            "foreign": plan.foreign,
            "notes": plan.notes,
            "error": plan.error,
        }
        for plan in plans
    ]


def outcomes_to_dict(outcomes: list[TargetOutcome]) -> list[dict]:
    return [
        {
            "target": outcome.key,
            "label": outcome.label,
            "created": outcome.created,
            "updated": outcome.updated,
            "skipped": outcome.skipped,
            "errors": outcome.errors,
            "warnings": outcome.warnings,
        }
        for outcome in outcomes
    ]


def has_errors(outcomes: list[TargetOutcome]) -> bool:
    return any(outcome.errors for outcome in outcomes)


# --------------------------------------------------------------------------- #
# Adapters — one per assistant
#
# Each holds its already-configured detector plus whatever that integration
# needs (excludes, model maps, ownership state). Dependencies are injected
# rather than resolved here, so a test can drive a target against tmp_path and
# the CLI stays the single place that reads the user's config.
# --------------------------------------------------------------------------- #


def _skill_limit_notes(cc_skills_dir, exclude_patterns: list[str] | None, target_label: str) -> list[str]:
    """Name skills the target will refuse to load, as plan notes."""
    from sccs.integrations.skill_limits import scan_claude_skills

    violations = scan_claude_skills(cc_skills_dir, exclude_patterns=exclude_patterns)
    if not violations:
        return []
    names = sorted(violations)
    shown = ", ".join(names[:3])
    if len(names) > 3:
        shown += f", +{len(names) - 3} more"
    return [f"{len(names)} skill(s) {target_label} will not load: {shown}"]


@dataclass
class AntigravityTarget:
    detector: Any
    key: str = "antigravity"
    label: str = "Antigravity"

    def plan(self) -> TargetPlan:
        info = self.detector.get_info()
        if info is None:
            return TargetPlan(key=self.key, label=self.label, installed=False)
        gaps = self.detector.get_skill_gaps()
        return TargetPlan(
            key=self.key,
            label=self.label,
            installed=True,
            location=str(info.prompts_dir),
            counts={"prompts": len(gaps)} if gaps else {},
        )

    def apply(self, *, dry_run: bool, replace_foreign: bool) -> TargetOutcome:
        from sccs.integrations.antigravity import migrate_skills_to_prompts

        result = migrate_skills_to_prompts(
            self.detector.get_skill_gaps(),
            dry_run=dry_run,
            overwrite_existing=True,
        )
        return TargetOutcome(
            key=self.key,
            label=self.label,
            created=len(result.created),
            updated=len(result.updated),
            skipped=len(result.skipped),
            errors=dict(result.errors),
        )


@dataclass
class OpenCodeTarget:
    detector: Any
    model_map: dict
    exclude: list[str] | None = None
    key: str = "opencode"
    label: str = "OpenCode"

    def plan(self) -> TargetPlan:
        info = self.detector.get_info()
        if info is None:
            return TargetPlan(key=self.key, label=self.label, installed=False)
        agents = self.detector.get_agent_gaps(self.model_map, exclude_patterns=self.exclude)
        commands = self.detector.get_command_gaps(self.model_map, exclude_patterns=self.exclude)
        mcp = self.detector.get_mcp_status()
        counts = {"agents": len(agents), "commands": len(commands), "MCP servers": len(mcp["missing"])}
        return TargetPlan(
            key=self.key,
            label=self.label,
            installed=True,
            location=str(info.config_dir),
            counts={k: v for k, v in counts.items() if v},
            # Skills need no export at all: OpenCode reads ~/.claude/skills natively.
            notes=["skills: read natively from ~/.claude/skills, no export needed"],
        )

    def apply(self, *, dry_run: bool, replace_foreign: bool) -> TargetOutcome:
        from sccs.integrations.opencode import (
            convert_agents_to_opencode,
            convert_commands_to_opencode,
            merge_mcp_to_opencode,
        )

        outcome = TargetOutcome(key=self.key, label=self.label)
        for gaps, writer in (
            (self.detector.get_agent_gaps(self.model_map, exclude_patterns=self.exclude), convert_agents_to_opencode),
            (
                self.detector.get_command_gaps(self.model_map, exclude_patterns=self.exclude),
                convert_commands_to_opencode,
            ),
        ):
            if not gaps:
                continue
            result = writer(gaps, dry_run=dry_run, overwrite_existing=True)
            outcome.created += len(result.created)
            outcome.updated += len(result.updated)
            outcome.skipped += len(result.skipped)
            outcome.errors.update(result.errors)
            outcome.warnings.update(getattr(result, "warnings", {}) or {})

        if self.detector.get_mcp_status()["missing"]:
            info = self.detector.get_info()
            # overwrite_existing stays False: opencode.json belongs to the user,
            # and an entry already there is not ours to replace.
            mcp_result = merge_mcp_to_opencode(
                config_dir=info.config_dir if info else None, dry_run=dry_run, overwrite_existing=False
            )
            outcome.created += len(getattr(mcp_result, "added", []) or [])
            outcome.skipped += len(getattr(mcp_result, "skipped", []) or [])
            mcp_error = getattr(mcp_result, "error", None)
            if mcp_error:
                outcome.errors["mcp"] = mcp_error
        return outcome


@dataclass
class PiTarget:
    detector: Any
    exclude: list[str] | None = None
    key: str = "pi"
    label: str = "Pi"

    def plan(self) -> TargetPlan:
        info = self.detector.get_info()
        if info is None:
            return TargetPlan(key=self.key, label=self.label, installed=False)
        counts = {
            "skills": len(self.detector.get_skill_gaps(exclude_patterns=self.exclude)),
            "agents": len(self.detector.get_agent_gaps(exclude_patterns=self.exclude)),
            "commands": len(self.detector.get_command_gaps(exclude_patterns=self.exclude)),
        }
        return TargetPlan(
            key=self.key,
            label=self.label,
            installed=True,
            location=str(info.base_dir),
            counts={k: v for k, v in counts.items() if v},
            notes=_skill_limit_notes(self.detector._cc_skills_dir, self.exclude, self.label),
        )

    def apply(self, *, dry_run: bool, replace_foreign: bool) -> TargetOutcome:
        from sccs.integrations.pi import export_agents_to_pi, export_commands_to_pi, export_skills_to_pi

        outcome = TargetOutcome(key=self.key, label=self.label)
        for getter, writer in (
            (self.detector.get_skill_gaps, export_skills_to_pi),
            (self.detector.get_agent_gaps, export_agents_to_pi),
            (self.detector.get_command_gaps, export_commands_to_pi),
        ):
            gaps = getter(exclude_patterns=self.exclude)
            if not gaps:
                continue
            result = writer(gaps, dry_run=dry_run, overwrite_existing=True)
            outcome.created += len(result.created)
            outcome.updated += len(result.updated)
            outcome.skipped += len(result.skipped)
            outcome.errors.update(result.errors)
            outcome.warnings.update(result.warnings)
        return outcome


@dataclass
class CodexTarget:
    detector: Any
    model_map: dict
    reasoning_map: dict
    state_manager: Any
    exclude: list[str] | None = None
    key: str = "codex"
    label: str = "Codex"

    def plan(self) -> TargetPlan:
        info = self.detector.get_info()
        if info is None:
            return TargetPlan(key=self.key, label=self.label, installed=False)
        state = self.state_manager.load()
        skills = self.detector.get_skill_gaps(exclude_patterns=self.exclude, state=state)
        agents = self.detector.get_agent_gaps(
            self.model_map, self.reasoning_map, exclude_patterns=self.exclude, state=state
        )
        commands = self.detector.get_command_gaps(exclude_patterns=self.exclude, state=state)
        counts = {"skills": len(skills), "agents": len(agents), "commands": len(commands)}
        foreign = sorted(gap.name for gap in (*skills, *agents, *commands) if getattr(gap, "foreign_target", False))
        notes = _skill_limit_notes(self.detector._cc_skills_dir, self.exclude, self.label)
        notes.append("hooks excluded — run `codex export-hooks` deliberately")
        return TargetPlan(
            key=self.key,
            label=self.label,
            installed=True,
            location=str(info.skills_dir),
            counts={k: v for k, v in counts.items() if v},
            foreign=foreign,
            notes=notes,
        )

    def apply(self, *, dry_run: bool, replace_foreign: bool) -> TargetOutcome:
        from sccs.integrations.codex import (
            convert_agents_to_codex,
            convert_commands_to_codex,
            export_skills_to_codex,
        )

        outcome = TargetOutcome(key=self.key, label=self.label)
        state = self.state_manager.load()
        adopted = self.detector.adopt_in_sync(
            state,
            model_map=self.model_map,
            reasoning_map=self.reasoning_map,
            exclude_patterns=self.exclude,
        )
        jobs = (
            (
                "skills",
                self.detector.get_skill_gaps(exclude_patterns=self.exclude, state=state),
                export_skills_to_codex,
            ),
            (
                "agents",
                self.detector.get_agent_gaps(
                    self.model_map, self.reasoning_map, exclude_patterns=self.exclude, state=state
                ),
                convert_agents_to_codex,
            ),
            (
                "commands",
                self.detector.get_command_gaps(exclude_patterns=self.exclude, state=state),
                convert_commands_to_codex,
            ),
        )
        wrote = False
        for _kind, gaps, writer in jobs:
            if not gaps:
                continue
            result = writer(
                gaps,
                dry_run=dry_run,
                overwrite_existing=True,
                replace_foreign=replace_foreign,
                state=state,
            )
            outcome.created += len(result.created)
            outcome.updated += len(result.updated)
            outcome.skipped += len(result.skipped)
            outcome.errors.update(result.errors)
            outcome.warnings.update(result.warnings)
            wrote = wrote or bool(result.created or result.updated)

        if (wrote or adopted) and not dry_run:
            try:
                self.state_manager.save(state)
            except OSError as exc:
                outcome.errors["state"] = f"exported, but could not persist ownership state: {exc}"
        return outcome
