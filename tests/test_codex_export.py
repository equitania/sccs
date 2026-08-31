# Tests for the Codex export writers (materialisation).

from __future__ import annotations

from pathlib import Path

from sccs.integrations.codex import (
    CodexDetector,
    CodexExportState,
    convert_agents_to_codex,
    convert_commands_to_codex,
    export_skills_to_codex,
)

AGENT_MD = """---
description: Reviews Python code.
model: haiku
---
Review the diff.
"""

COMMAND_MD = """---
description: Quality gate.
---
Run the gate.
"""


def _detector(tmp_path: Path) -> CodexDetector:
    dirs = {
        "codex": tmp_path / ".codex",
        "skills": tmp_path / ".agents" / "skills",
        "cc_skills": tmp_path / ".claude" / "skills",
        "cc_agents": tmp_path / ".claude" / "agents",
        "cc_commands": tmp_path / ".claude" / "commands",
    }
    for path in dirs.values():
        path.mkdir(parents=True)
    return CodexDetector(
        codex_dir=dirs["codex"],
        skills_dir=dirs["skills"],
        cc_skills_dir=dirs["cc_skills"],
        cc_agents_dir=dirs["cc_agents"],
        cc_commands_dir=dirs["cc_commands"],
    )


def _write_skill(detector: CodexDetector, name: str) -> Path:
    skill_dir = detector._cc_skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\nBody\n", encoding="utf-8")
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "extra.md").write_text("ref", encoding="utf-8")
    return skill_dir


class TestSkillExport:
    def test_copies_whole_directory(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")

        result = export_skills_to_codex(detector.get_skill_gaps())
        assert result.created == ["my-skill"]
        assert (detector.skills_dir / "my-skill" / "SKILL.md").is_file()
        assert (detector.skills_dir / "my-skill" / "references" / "extra.md").is_file()

    def test_dry_run_writes_nothing(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")

        result = export_skills_to_codex(detector.get_skill_gaps(), dry_run=True)
        assert result.created == ["my-skill"]
        assert not (detector.skills_dir / "my-skill").exists()

    def test_no_overwrite_skips_existing(self, tmp_path):
        detector = _detector(tmp_path)
        skill_dir = _write_skill(detector, "my-skill")
        export_skills_to_codex(detector.get_skill_gaps())

        (skill_dir / "SKILL.md").write_text("changed", encoding="utf-8")
        result = export_skills_to_codex(detector.get_skill_gaps(), overwrite_existing=False)
        assert result.skipped == ["my-skill"]

    def test_overwrite_updates(self, tmp_path):
        detector = _detector(tmp_path)
        skill_dir = _write_skill(detector, "my-skill")
        export_skills_to_codex(detector.get_skill_gaps())

        (skill_dir / "SKILL.md").write_text("changed", encoding="utf-8")
        result = export_skills_to_codex(detector.get_skill_gaps())
        assert result.updated == ["my-skill"]
        assert (detector.skills_dir / "my-skill" / "SKILL.md").read_text(encoding="utf-8") == "changed"

    def test_selected_filter(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "one")
        _write_skill(detector, "two")

        result = export_skills_to_codex(detector.get_skill_gaps(), selected=["two"])
        assert result.created == ["two"]
        assert not (detector.skills_dir / "one").exists()

    def test_foreign_target_is_flagged_not_automatically_updated(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")
        target = detector.skills_dir / "my-skill"
        target.mkdir()
        (target / "SKILL.md").write_text("foreign", encoding="utf-8")

        gaps = detector.get_skill_gaps(state=CodexExportState())
        assert gaps[0].foreign_target
        # Not a collision: that guard is absolute, this one is releasable.
        assert not gaps[0].collision
        assert "was not written by SCCS" in gaps[0].warnings[0]

    def test_foreign_target_survives_plain_overwrite(self, tmp_path):
        """--overwrite governs targets SCCS wrote; it must not touch foreign ones."""
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")
        target = detector.skills_dir / "my-skill"
        target.mkdir()
        (target / "SKILL.md").write_text("foreign", encoding="utf-8")

        result = export_skills_to_codex(detector.get_skill_gaps(state=CodexExportState()), overwrite_existing=True)
        assert result.skipped == ["my-skill"]
        assert (target / "SKILL.md").read_text(encoding="utf-8") == "foreign"
        assert "--replace-foreign" in " ".join(result.warnings["my-skill"])

    def test_replace_foreign_refreshes_the_target(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")
        target = detector.skills_dir / "my-skill"
        target.mkdir()
        (target / "SKILL.md").write_text("foreign", encoding="utf-8")

        state = CodexExportState()
        result = export_skills_to_codex(detector.get_skill_gaps(state=state), replace_foreign=True, state=state)
        assert result.updated == ["my-skill"]
        assert (target / "SKILL.md").read_text(encoding="utf-8") != "foreign"
        # Ownership is recorded, so the next run is a plain update.
        assert state.owns("skills", "my-skill", target)

    def test_replace_foreign_is_inert_without_a_foreign_target(self, tmp_path):
        """The escape hatch must not become a second --overwrite."""
        detector = _detector(tmp_path)
        source = _write_skill(detector, "my-skill")
        state = CodexExportState()
        export_skills_to_codex(detector.get_skill_gaps(state=state), state=state)

        (source / "SKILL.md").write_text("changed", encoding="utf-8")
        result = export_skills_to_codex(
            detector.get_skill_gaps(state=state), overwrite_existing=False, replace_foreign=True, state=state
        )
        assert result.skipped == ["my-skill"]

    def test_replace_foreign_never_releases_a_command_collision(self, tmp_path):
        """A real skill claiming the slot is an absolute guard, not a releasable one."""
        detector = _detector(tmp_path)
        _write_skill(detector, "shared-name")
        command = detector._cc_commands_dir
        command.mkdir(parents=True, exist_ok=True)
        (command / "shared-name.md").write_text("---\ndescription: c\n---\nbody\n", encoding="utf-8")

        gaps = [g for g in detector.get_command_gaps() if g.name == "shared-name"]
        assert gaps and gaps[0].collision
        result = convert_commands_to_codex(gaps, replace_foreign=True, overwrite_existing=True)
        assert result.skipped == ["shared-name"]

    def test_owned_target_can_be_updated(self, tmp_path):
        detector = _detector(tmp_path)
        source = _write_skill(detector, "my-skill")
        state = CodexExportState()
        export_skills_to_codex(detector.get_skill_gaps(state=state), state=state)

        (source / "SKILL.md").write_text("changed", encoding="utf-8")
        gaps = detector.get_skill_gaps(state=state)
        assert len(gaps) == 1
        assert not gaps[0].collision

    def test_symlink_inside_source_skill_is_blocked(self, tmp_path):
        detector = _detector(tmp_path)
        skill = detector._cc_skills_dir / "linked"
        skill.mkdir()
        (skill / "SKILL.md").symlink_to(tmp_path / "outside.md")

        gaps = detector.get_skill_gaps()
        assert gaps[0].blocked
        assert "symlink" in gaps[0].warnings[0]


class TestAgentExport:
    def test_agent_lands_as_toml(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "reviewer.md").write_text(AGENT_MD, encoding="utf-8")

        result = convert_agents_to_codex(detector.get_agent_gaps())
        assert result.created == ["reviewer"]
        assert result.target_dir_created  # ~/.codex/agents did not exist yet

        written = (detector.agents_dir / "reviewer.toml").read_text(encoding="utf-8")
        assert 'name = "reviewer"' in written
        assert "Review the diff." in written

    def test_dry_run_writes_nothing(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "reviewer.md").write_text(AGENT_MD, encoding="utf-8")

        result = convert_agents_to_codex(detector.get_agent_gaps(), dry_run=True)
        assert result.created == ["reviewer"]
        assert not detector.agents_dir.exists()

    def test_warnings_surface_in_result(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "bare.md").write_text("No frontmatter at all.\n", encoding="utf-8")

        result = convert_agents_to_codex(detector.get_agent_gaps())
        assert "bare" in result.warnings
        assert any("description" in w for w in result.warnings["bare"])

    def test_non_utf8_agent_is_reported_not_raised(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "broken.md").write_bytes(b"\xff")

        gaps = detector.get_agent_gaps()
        assert gaps[0].blocked
        result = convert_agents_to_codex(gaps)
        assert result.skipped == ["broken"]


class TestCommandExport:
    def test_command_lands_as_skill_md(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_commands_dir / "finalize.md").write_text(COMMAND_MD, encoding="utf-8")

        result = convert_commands_to_codex(detector.get_command_gaps())
        assert result.created == ["finalize"]

        written = (detector.skills_dir / "finalize" / "SKILL.md").read_text(encoding="utf-8")
        assert written.startswith("---\n")
        assert "name: finalize" in written
        assert "Run the gate." in written

    def test_collision_skipped_and_never_written(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "finalize")
        (detector._cc_commands_dir / "finalize.md").write_text(COMMAND_MD, encoding="utf-8")

        result = convert_commands_to_codex(detector.get_command_gaps())
        assert result.skipped == ["finalize"]
        assert "finalize" in result.warnings
        assert not (detector.skills_dir / "finalize").exists()

    def test_collision_skipped_even_with_overwrite(self, tmp_path):
        detector = _detector(tmp_path)
        target = detector.skills_dir / "finalize"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("real skill", encoding="utf-8")
        (target / "scripts").mkdir()
        (detector._cc_commands_dir / "finalize.md").write_text(COMMAND_MD, encoding="utf-8")

        result = convert_commands_to_codex(detector.get_command_gaps(), overwrite_existing=True)
        assert result.skipped == ["finalize"]
        assert (target / "SKILL.md").read_text(encoding="utf-8") == "real skill"


class TestEmpty:
    def test_empty_gaps_are_a_noop(self, tmp_path):
        result = export_skills_to_codex([])
        assert result.created == []
        assert result.updated == []
        assert result.skipped == []
        assert not result.target_dir_created


class TestAdoptInSync:
    """Ownership for targets that already match the source.

    The gap this closes: ownership used to be recorded only when a target was
    WRITTEN, so a target that never needed writing could never earn it. On a
    real host that was most of them (90 targets, 18 records) — and the moment
    such a source changed, SCCS refused to update a target it had created.
    """

    def test_identical_target_is_adopted(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")
        # Write it, then start from an empty register as if the export
        # predated ownership tracking.
        export_skills_to_codex(detector.get_skill_gaps())
        state = CodexExportState()

        assert detector.adopt_in_sync(state) == ["skills:my-skill"]
        assert state.owns("skills", "my-skill", detector.skills_dir / "my-skill")

    def test_adoption_makes_the_next_update_ordinary(self, tmp_path):
        """The whole point: after adoption a changed source updates its target
        without --replace-foreign."""
        detector = _detector(tmp_path)
        source = _write_skill(detector, "my-skill")
        export_skills_to_codex(detector.get_skill_gaps())

        state = CodexExportState()
        detector.adopt_in_sync(state)
        (source / "SKILL.md").write_text("changed", encoding="utf-8")

        gaps = detector.get_skill_gaps(state=state)
        assert not gaps[0].foreign_target
        result = export_skills_to_codex(gaps, state=state)
        assert result.updated == ["my-skill"]

    def test_a_differing_target_is_never_adopted(self, tmp_path):
        """The guard must survive: divergence is exactly what it protects."""
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")
        target = detector.skills_dir / "my-skill"
        target.mkdir()
        (target / "SKILL.md").write_text("hand written", encoding="utf-8")

        state = CodexExportState()
        assert detector.adopt_in_sync(state) == []
        assert detector.get_skill_gaps(state=state)[0].foreign_target
        assert (target / "SKILL.md").read_text(encoding="utf-8") == "hand written"

    def test_missing_target_is_not_adopted(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")
        assert detector.adopt_in_sync(CodexExportState()) == []

    def test_excluded_artefacts_are_not_adopted(self, tmp_path):
        """source_names ignores excludes, so an excluded artefact also has no
        gap — it must not be mistaken for an in-sync one."""
        detector = _detector(tmp_path)
        _write_skill(detector, "gsd-thing")
        export_skills_to_codex(detector.get_skill_gaps())

        state = CodexExportState()
        assert detector.adopt_in_sync(state, exclude_patterns=["gsd-*"]) == []

    def test_adoption_is_idempotent(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector, "my-skill")
        export_skills_to_codex(detector.get_skill_gaps())

        state = CodexExportState()
        assert detector.adopt_in_sync(state) == ["skills:my-skill"]
        assert detector.adopt_in_sync(state) == []

    def test_agents_and_commands_are_adopted_too(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "reviewer.md").write_text(AGENT_MD, encoding="utf-8")
        (detector._cc_commands_dir / "finalize.md").write_text(COMMAND_MD, encoding="utf-8")
        convert_agents_to_codex(detector.get_agent_gaps())
        convert_commands_to_codex(detector.get_command_gaps())

        state = CodexExportState()
        assert sorted(detector.adopt_in_sync(state)) == ["agents:reviewer", "commands:finalize"]

    def test_a_command_blocked_by_a_skill_collision_is_not_adopted(self, tmp_path):
        """A collision produces a gap, so silence never covers it."""
        detector = _detector(tmp_path)
        _write_skill(detector, "shared-name")
        export_skills_to_codex(detector.get_skill_gaps())
        (detector._cc_commands_dir / "shared-name.md").write_text(COMMAND_MD, encoding="utf-8")

        state = CodexExportState()
        # The skill is adopted; the command that lost the slot is not.
        assert detector.adopt_in_sync(state) == ["skills:shared-name"]
