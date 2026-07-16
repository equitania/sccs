# Tests for the Codex export writers (materialisation).

from __future__ import annotations

from pathlib import Path

from sccs.integrations.codex import (
    CodexDetector,
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
