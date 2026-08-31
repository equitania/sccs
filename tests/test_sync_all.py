"""Tests for the cross-assistant collection pass (sccs/integrations/sync_all.py).

The orchestration is tested against fake targets rather than real detectors:
what matters here is that one broken assistant cannot hide or sink the others,
and that nothing is written for a target with no pending work. The individual
export paths have their own suites.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sccs.integrations.sync_all import (
    TargetOutcome,
    TargetPlan,
    apply_plans,
    collect_plans,
    has_errors,
    outcomes_to_dict,
    plans_to_dict,
)


@dataclass
class FakeTarget:
    key: str
    label: str
    plan_result: TargetPlan | None = None
    plan_raises: Exception | None = None
    apply_raises: Exception | None = None
    applied: list[dict] = field(default_factory=list)

    def plan(self) -> TargetPlan:
        if self.plan_raises:
            raise self.plan_raises
        assert self.plan_result is not None
        return self.plan_result

    def apply(self, *, dry_run: bool, replace_foreign: bool) -> TargetOutcome:
        if self.apply_raises:
            raise self.apply_raises
        self.applied.append({"dry_run": dry_run, "replace_foreign": replace_foreign})
        return TargetOutcome(key=self.key, label=self.label, created=1)


def _plan(key: str, *, installed: bool = True, pending: int = 0, error: str | None = None) -> TargetPlan:
    return TargetPlan(
        key=key,
        label=key.title(),
        installed=installed,
        counts={"skills": pending} if pending else {},
        error=error,
    )


class TestTargetPlan:
    def test_pending_sums_every_kind(self):
        plan = TargetPlan(key="pi", label="Pi", installed=True, counts={"skills": 12, "agents": 2})
        assert plan.pending == 14

    def test_summary_reads_as_a_sentence(self):
        plan = TargetPlan(key="pi", label="Pi", installed=True, counts={"skills": 12, "agents": 2})
        assert plan.summary() == "12 skills, 2 agents"

    def test_summary_of_an_idle_target(self):
        assert TargetPlan(key="pi", label="Pi", installed=True).summary() == "up to date"

    def test_zero_counts_do_not_reach_the_summary(self):
        plan = TargetPlan(key="pi", label="Pi", installed=True, counts={"skills": 3, "agents": 0})
        assert plan.summary() == "3 skills"


class TestCollectPlans:
    def test_one_broken_target_does_not_hide_the_others(self):
        good = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=3))
        broken = FakeTarget("codex", "Codex", plan_raises=RuntimeError("boom"))

        plans = collect_plans([good, broken])
        assert [p.key for p in plans] == ["pi", "codex"]
        assert plans[0].pending == 3
        assert plans[1].error is not None and "boom" in plans[1].error

    def test_a_broken_target_is_never_reported_as_absent(self):
        """`installed=False` means 'not on this machine'; an inspection failure
        is a different thing and must not be presented as the same."""
        plans = collect_plans([FakeTarget("codex", "Codex", plan_raises=OSError("denied"))])
        assert plans[0].installed is True
        assert plans[0].error


class TestApplyPlans:
    def test_only_targets_with_work_are_applied(self):
        busy = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=2))
        idle = FakeTarget("codex", "Codex", plan_result=_plan("codex"))
        absent = FakeTarget("opencode", "Opencode", plan_result=_plan("opencode", installed=False))

        targets = [busy, idle, absent]
        outcomes = apply_plans(targets, collect_plans(targets), dry_run=False, replace_foreign=False)

        assert [o.key for o in outcomes] == ["pi"]
        assert busy.applied and not idle.applied and not absent.applied

    def test_a_target_that_failed_to_plan_is_not_applied(self):
        broken = FakeTarget("codex", "Codex", plan_raises=RuntimeError("boom"))
        outcomes = apply_plans([broken], collect_plans([broken]), dry_run=False, replace_foreign=False)
        assert outcomes == []

    def test_flags_reach_the_target(self):
        busy = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=1))
        apply_plans([busy], collect_plans([busy]), dry_run=True, replace_foreign=True)
        assert busy.applied == [{"dry_run": True, "replace_foreign": True}]

    def test_an_export_failure_is_reported_and_the_pass_continues(self):
        failing = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=1), apply_raises=OSError("disk full"))
        later = FakeTarget("codex", "Codex", plan_result=_plan("codex", pending=1))

        targets = [failing, later]
        outcomes = apply_plans(targets, collect_plans(targets), dry_run=False, replace_foreign=False)

        assert has_errors(outcomes)
        assert "disk full" in outcomes[0].errors["pi"]
        # The second assistant still ran.
        assert later.applied

    def test_no_errors_when_everything_worked(self):
        busy = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=1))
        assert not has_errors(apply_plans([busy], collect_plans([busy]), dry_run=False, replace_foreign=False))


class TestJsonShape:
    def test_plan_payload_carries_the_decision_fields(self):
        plan = TargetPlan(
            key="codex",
            label="Codex",
            installed=True,
            location="/home/u/.agents/skills",
            counts={"skills": 2},
            foreign=["afterwork"],
            notes=["hooks excluded"],
        )
        payload = plans_to_dict([plan])[0]
        assert payload["target"] == "codex"
        assert payload["pending"] == 2
        assert payload["foreign"] == ["afterwork"]
        assert payload["notes"] == ["hooks excluded"]

    def test_outcome_payload(self):
        payload = outcomes_to_dict([TargetOutcome(key="pi", label="Pi", created=3, updated=1)])[0]
        assert payload == {
            "target": "pi",
            "label": "Pi",
            "created": 3,
            "updated": 1,
            "skipped": 0,
            "errors": {},
            "warnings": {},
        }


# --------------------------------------------------------------------------- #
# Adapter wiring — against real detectors.
#
# The fake-target tests above cover orchestration only. These cover the half
# that orchestration cannot: that each adapter calls its integration's real
# detector and writer with the right arguments. A typo in a method name or a
# keyword survives every test above.
# --------------------------------------------------------------------------- #

from pathlib import Path  # noqa: E402

from sccs.integrations.codex import CodexDetector, CodexExportState  # noqa: E402
from sccs.integrations.pi import PiDetector  # noqa: E402
from sccs.integrations.sync_all import CodexTarget, PiTarget  # noqa: E402

SKILL_MD = "---\nname: my-skill\ndescription: A skill.\n---\nBody.\n"


def _pi_detector(tmp_path: Path) -> PiDetector:
    base = tmp_path / ".pi" / "agent"
    base.mkdir(parents=True)
    for sub in ("skills", "agents", "commands"):
        (tmp_path / ".claude" / sub).mkdir(parents=True)
    return PiDetector(
        base_dir=base,
        cc_skills_dir=tmp_path / ".claude" / "skills",
        cc_agents_dir=tmp_path / ".claude" / "agents",
        cc_commands_dir=tmp_path / ".claude" / "commands",
    )


def _codex_detector(tmp_path: Path) -> CodexDetector:
    codex = tmp_path / ".codex"
    skills = tmp_path / ".agents" / "skills"
    for path in (codex, skills):
        path.mkdir(parents=True)
    for sub in ("skills", "agents", "commands"):
        (tmp_path / ".claude" / sub).mkdir(parents=True)
    return CodexDetector(
        codex_dir=codex,
        skills_dir=skills,
        cc_skills_dir=tmp_path / ".claude" / "skills",
        cc_agents_dir=tmp_path / ".claude" / "agents",
        cc_commands_dir=tmp_path / ".claude" / "commands",
    )


def _write_skill(cc_skills_dir: Path, name: str, body: str = SKILL_MD) -> Path:
    d = cc_skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return d


class _FakeCodexState:
    """Minimal stand-in for CodexExportStateManager."""

    def __init__(self):
        self.state = CodexExportState()
        self.saved = 0

    def load(self):
        return self.state

    def save(self, state):
        self.saved += 1


class TestPiTargetWiring:
    def test_plan_counts_pending_skills(self, tmp_path):
        detector = _pi_detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "one")

        plan = PiTarget(detector=detector).plan()
        assert plan.installed and plan.counts == {"skills": 1}

    def test_apply_actually_writes(self, tmp_path):
        detector = _pi_detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "one")

        outcome = PiTarget(detector=detector).apply(dry_run=False, replace_foreign=False)
        assert outcome.created == 1
        assert (detector.skills_dir / "one" / "SKILL.md").is_file()

    def test_dry_run_writes_nothing(self, tmp_path):
        detector = _pi_detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "one")

        PiTarget(detector=detector).apply(dry_run=True, replace_foreign=False)
        assert not (detector.skills_dir / "one").exists()

    def test_over_long_description_is_named_in_the_plan(self, tmp_path):
        detector = _pi_detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "fat", f"---\nname: fat\ndescription: {'d' * 2000}\n---\nBody.\n")

        plan = PiTarget(detector=detector).plan()
        assert any("will not load" in note for note in plan.notes)

    def test_not_installed_when_pi_is_absent(self, tmp_path):
        # PiDetector treats either ~/.pi or ~/.pi/agent as an install marker,
        # so the absent base_dir needs an absent parent too.
        detector = PiDetector(
            base_dir=tmp_path / "nowhere" / "agent",
            cc_skills_dir=tmp_path / ".claude" / "skills",
            cc_agents_dir=tmp_path / ".claude" / "agents",
            cc_commands_dir=tmp_path / ".claude" / "commands",
        )
        assert PiTarget(detector=detector).plan().installed is False


class TestCodexTargetWiring:
    def _target(self, detector, state) -> CodexTarget:
        return CodexTarget(detector=detector, model_map={}, reasoning_map={}, state_manager=state)

    def test_apply_writes_and_persists_ownership(self, tmp_path):
        detector = _codex_detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "one")
        state = _FakeCodexState()

        outcome = self._target(detector, state).apply(dry_run=False, replace_foreign=False)
        assert outcome.created == 1
        assert (detector.skills_dir / "one" / "SKILL.md").is_file()
        # Without this the next run would see its own target as foreign.
        assert state.saved == 1

    def test_dry_run_neither_writes_nor_persists(self, tmp_path):
        detector = _codex_detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "one")
        state = _FakeCodexState()

        self._target(detector, state).apply(dry_run=True, replace_foreign=False)
        assert not (detector.skills_dir / "one").exists()
        assert state.saved == 0

    def test_foreign_target_is_named_in_the_plan_and_kept(self, tmp_path):
        detector = _codex_detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "one")
        foreign = detector.skills_dir / "one"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("hand written", encoding="utf-8")
        state = _FakeCodexState()

        plan = self._target(detector, state).plan()
        assert plan.foreign == ["one"]

        self._target(detector, state).apply(dry_run=False, replace_foreign=False)
        assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "hand written"

    def test_replace_foreign_reaches_the_writer(self, tmp_path):
        detector = _codex_detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "one")
        foreign = detector.skills_dir / "one"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("hand written", encoding="utf-8")
        state = _FakeCodexState()

        self._target(detector, state).apply(dry_run=False, replace_foreign=True)
        assert (foreign / "SKILL.md").read_text(encoding="utf-8") != "hand written"

    def test_plan_warns_that_hooks_are_excluded(self, tmp_path):
        detector = _codex_detector(tmp_path)
        state = _FakeCodexState()
        assert any("hooks excluded" in note for note in self._target(detector, state).plan().notes)


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #

import json as _json  # noqa: E402

from click.testing import CliRunner  # noqa: E402

from sccs.cli import cli  # noqa: E402


def _install_fake_targets(monkeypatch, targets):
    """Replace the real assistant detection for one CLI invocation."""
    monkeypatch.setattr("sccs.cli._build_sync_all_targets", lambda: targets)


class TestSyncAllCli:
    def test_unknown_target_fails_loudly(self, monkeypatch):
        _install_fake_targets(monkeypatch, [FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=1))])
        result = CliRunner().invoke(cli, ["integrations", "sync-all", "-t", "nope"], obj={})
        assert result.exit_code == 1
        assert "No such target" in result.output

    def test_dry_run_never_applies(self, monkeypatch):
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=3))
        _install_fake_targets(monkeypatch, [target])

        result = CliRunner().invoke(cli, ["integrations", "sync-all", "--dry-run"], obj={})
        assert result.exit_code == 0
        assert not target.applied

    def test_declining_the_confirmation_writes_nothing(self, monkeypatch):
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=3))
        _install_fake_targets(monkeypatch, [target])

        result = CliRunner().invoke(cli, ["integrations", "sync-all"], input="n\n", obj={})
        assert result.exit_code == 0
        assert not target.applied

    def test_yes_skips_the_confirmation_and_applies(self, monkeypatch):
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=3))
        _install_fake_targets(monkeypatch, [target])

        result = CliRunner().invoke(cli, ["integrations", "sync-all", "--yes"], obj={})
        assert result.exit_code == 0
        assert target.applied == [{"dry_run": False, "replace_foreign": False}]

    def test_replace_foreign_is_off_unless_asked(self, monkeypatch):
        """The convenience command must not discard hand edits by default."""
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=1))
        _install_fake_targets(monkeypatch, [target])

        CliRunner().invoke(cli, ["integrations", "sync-all", "--yes"], obj={})
        assert target.applied[0]["replace_foreign"] is False

    def test_replace_foreign_reaches_the_target(self, monkeypatch):
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=1))
        _install_fake_targets(monkeypatch, [target])

        CliRunner().invoke(cli, ["integrations", "sync-all", "--yes", "--replace-foreign"], obj={})
        assert target.applied[0]["replace_foreign"] is True

    def test_nothing_to_do_exits_clean_without_asking(self, monkeypatch):
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi"))
        _install_fake_targets(monkeypatch, [target])

        result = CliRunner().invoke(cli, ["integrations", "sync-all"], obj={})
        assert result.exit_code == 0
        assert not target.applied

    def test_json_output_is_a_single_parsable_line(self, monkeypatch):
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=2))
        _install_fake_targets(monkeypatch, [target])

        result = CliRunner().invoke(cli, ["integrations", "sync-all", "--json"], obj={})
        assert result.exit_code == 0
        payload = _json.loads(result.output.strip())
        assert payload["success"] is True
        assert payload["plan"][0]["pending"] == 2
        assert payload["applied"][0]["created"] == 1

    def test_json_never_prompts(self, monkeypatch):
        """A machine consumer must not be blocked on a confirmation."""
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=2))
        _install_fake_targets(monkeypatch, [target])

        result = CliRunner().invoke(cli, ["integrations", "sync-all", "--json"], obj={})
        assert target.applied and result.exit_code == 0

    def test_export_failure_exits_non_zero(self, monkeypatch):
        target = FakeTarget("pi", "Pi", plan_result=_plan("pi", pending=1), apply_raises=OSError("disk full"))
        _install_fake_targets(monkeypatch, [target])

        result = CliRunner().invoke(cli, ["integrations", "sync-all", "--yes"], obj={})
        assert result.exit_code == 1
