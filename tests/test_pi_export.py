# Tests for SCCS Pi export (skill/agent/command materialisation)

from pathlib import Path

from sccs.integrations.pi import (
    PiDetector,
    export_agents_to_pi,
    export_commands_to_pi,
    export_skills_to_pi,
)

SKILL_MD = """---
name: my-skill
description: A skill.
---
Body.
"""

AGENT_MD = """---
name: my-agent
description: An agent.
---
Agent body.
"""

COMMAND_MD = """---
description: A command.
---
Command body.
"""


def _detector(tmp_path: Path) -> PiDetector:
    pi_base = tmp_path / ".pi" / "agent"
    pi_base.mkdir(parents=True)
    return PiDetector(
        base_dir=pi_base,
        cc_skills_dir=tmp_path / ".claude" / "skills",
        cc_agents_dir=tmp_path / ".claude" / "agents",
        cc_commands_dir=tmp_path / ".claude" / "commands",
    )


def _make_skill(detector: PiDetector, name: str) -> Path:
    skill_dir = detector._cc_skills_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    return skill_dir


class TestSkillExport:
    def test_copies_whole_directory(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        skill_dir = _make_skill(detector, "my-skill")
        # nested reference file must come along
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "REF.md").write_text("ref", encoding="utf-8")

        result = export_skills_to_pi(detector.get_skill_gaps())
        assert result.created == ["my-skill"]

        dst = detector.skills_dir / "my-skill"
        assert (dst / "SKILL.md").is_file()
        assert (dst / "references" / "REF.md").read_text(encoding="utf-8") == "ref"

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        _make_skill(detector, "my-skill")
        result = export_skills_to_pi(detector.get_skill_gaps(), dry_run=True)
        assert result.created == ["my-skill"]
        assert not (detector.skills_dir / "my-skill").exists()

    def test_overwrite_updates(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        skill_dir = _make_skill(detector, "my-skill")
        export_skills_to_pi(detector.get_skill_gaps())
        (skill_dir / "SKILL.md").write_text(SKILL_MD.replace("A skill.", "Changed."), encoding="utf-8")
        result = export_skills_to_pi(detector.get_skill_gaps())
        assert result.updated == ["my-skill"]
        assert "Changed." in (detector.skills_dir / "my-skill" / "SKILL.md").read_text(encoding="utf-8")

    def test_no_overwrite_skips_existing(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        skill_dir = _make_skill(detector, "my-skill")
        export_skills_to_pi(detector.get_skill_gaps())
        (skill_dir / "SKILL.md").write_text(SKILL_MD.replace("A skill.", "Changed."), encoding="utf-8")
        result = export_skills_to_pi(detector.get_skill_gaps(), overwrite_existing=False)
        assert result.skipped == ["my-skill"]
        assert result.updated == []

    def test_selected_filter(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        _make_skill(detector, "skill-a")
        _make_skill(detector, "skill-b")
        result = export_skills_to_pi(detector.get_skill_gaps(), selected=["skill-a"])
        assert result.created == ["skill-a"]
        assert not (detector.skills_dir / "skill-b").exists()

    def test_target_dir_created_flag(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        _make_skill(detector, "my-skill")
        assert not detector.skills_dir.exists()
        result = export_skills_to_pi(detector.get_skill_gaps())
        assert result.target_dir_created is True
        assert detector.skills_dir.is_dir()


class TestAgentExport:
    def test_agent_lands_as_skill_md(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        detector._cc_agents_dir.mkdir(parents=True)
        (detector._cc_agents_dir / "my-agent.md").write_text(AGENT_MD, encoding="utf-8")
        result = export_agents_to_pi(detector.get_agent_gaps())
        assert result.created == ["my-agent"]
        dst = detector.skills_dir / "my-agent.md"
        assert dst.is_file()
        assert dst.read_text(encoding="utf-8") == AGENT_MD


class TestCommandExport:
    def test_command_lands_as_prompt(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        detector._cc_commands_dir.mkdir(parents=True)
        (detector._cc_commands_dir / "do.md").write_text(COMMAND_MD, encoding="utf-8")
        result = export_commands_to_pi(detector.get_command_gaps())
        assert result.created == ["do"]
        dst = detector.prompts_dir / "do.md"
        assert dst.is_file()
        assert dst.read_text(encoding="utf-8") == COMMAND_MD


class TestEmpty:
    def test_empty_gaps(self, tmp_path: Path) -> None:
        result = export_skills_to_pi([])
        assert result.created == []
        assert result.target_dir_created is False
