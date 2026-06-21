# Tests for SCCS Pi detector (skill/agent/command gap detection)

from pathlib import Path

from sccs.integrations.pi import PiDetector

SKILL_MD = """---
name: my-skill
description: A skill that does things.
---

# My Skill

Body.
"""

AGENT_MD = """---
name: my-agent
description: An agent.
model: sonnet
---
Agent body.
"""

COMMAND_MD = """---
description: A command.
---
Command body.
"""


def _make_dirs(tmp_path: Path):
    pi_base = tmp_path / ".pi" / "agent"
    cc_skills = tmp_path / ".claude" / "skills"
    cc_agents = tmp_path / ".claude" / "agents"
    cc_commands = tmp_path / ".claude" / "commands"
    return pi_base, cc_skills, cc_agents, cc_commands


def _make_skill(skills_dir: Path, name: str, content: str = SKILL_MD) -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def _detector(tmp_path: Path, *, install: bool = True) -> PiDetector:
    pi_base, cc_skills, cc_agents, cc_commands = _make_dirs(tmp_path)
    if install:
        pi_base.mkdir(parents=True)
    return PiDetector(
        base_dir=pi_base,
        cc_skills_dir=cc_skills,
        cc_agents_dir=cc_agents,
        cc_commands_dir=cc_commands,
    )


class TestInstallation:
    def test_not_installed(self, tmp_path: Path) -> None:
        detector = PiDetector(base_dir=tmp_path / "nope" / "agent")
        assert detector.is_installed() is False
        assert detector.get_info() is None
        assert detector.get_skill_gaps() == []
        assert detector.get_agent_gaps() == []
        assert detector.get_command_gaps() == []

    def test_installed_via_bare_pi_dir(self, tmp_path: Path) -> None:
        # ~/.pi exists but agent/ does not yet — still counts as installed.
        (tmp_path / ".pi").mkdir()
        detector = PiDetector(base_dir=tmp_path / ".pi" / "agent")
        assert detector.is_installed() is True
        info = detector.get_info()
        assert info is not None
        assert info.skills_dir_exists is False

    def test_get_info(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        info = detector.get_info()
        assert info is not None
        assert info.installed is True
        assert info.skills_dir.name == "skills"
        assert info.prompts_dir.name == "prompts"


class TestSkillGaps:
    def test_skill_gap_missing(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        _make_skill(detector._cc_skills_dir, "my-skill")
        gaps = detector.get_skill_gaps()
        assert len(gaps) == 1
        assert gaps[0].name == "my-skill"
        assert gaps[0].is_dir is True
        assert gaps[0].dst_exists is False

    def test_skill_without_marker_ignored(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        # Directory without SKILL.md is not a skill.
        (detector._cc_skills_dir / "notaskill").mkdir(parents=True)
        (detector._cc_skills_dir / "notaskill" / "README.md").write_text("x", encoding="utf-8")
        assert detector.get_skill_gaps() == []

    def test_skill_skips_private_dirs(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        _make_skill(detector._cc_skills_dir, "_archive")
        _make_skill(detector._cc_skills_dir, ".hidden")
        assert detector.get_skill_gaps() == []

    def test_skill_exclude_pattern(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        _make_skill(detector._cc_skills_dir, "gsd-thing")
        _make_skill(detector._cc_skills_dir, "astro")
        gaps = detector.get_skill_gaps(exclude_patterns=["gsd-*"])
        assert [g.name for g in gaps] == ["astro"]

    def test_skill_up_to_date_after_copy(self, tmp_path: Path) -> None:
        from sccs.integrations.pi import export_skills_to_pi

        detector = _detector(tmp_path)
        _make_skill(detector._cc_skills_dir, "my-skill")
        export_skills_to_pi(detector.get_skill_gaps())
        assert detector.get_skill_gaps() == []

    def test_skill_needs_update_when_changed(self, tmp_path: Path) -> None:
        from sccs.integrations.pi import export_skills_to_pi

        detector = _detector(tmp_path)
        skill_dir = _make_skill(detector._cc_skills_dir, "my-skill")
        export_skills_to_pi(detector.get_skill_gaps())
        (skill_dir / "SKILL.md").write_text(SKILL_MD.replace("does things", "does other things"), encoding="utf-8")
        gaps = detector.get_skill_gaps()
        assert len(gaps) == 1
        assert gaps[0].needs_update is True


class TestAgentGaps:
    def test_agent_gap_targets_skills_dir(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        detector._cc_agents_dir.mkdir(parents=True)
        (detector._cc_agents_dir / "my-agent.md").write_text(AGENT_MD, encoding="utf-8")
        gaps = detector.get_agent_gaps()
        assert len(gaps) == 1
        assert gaps[0].name == "my-agent"
        assert gaps[0].is_dir is False
        # Agents land as root .md skills under ~/.pi/agent/skills/
        assert gaps[0].dst_path == detector.skills_dir / "my-agent.md"

    def test_agent_skips_private_and_local(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        detector._cc_agents_dir.mkdir(parents=True)
        (detector._cc_agents_dir / "_private.md").write_text(AGENT_MD, encoding="utf-8")
        (detector._cc_agents_dir / "thing.local.md").write_text(AGENT_MD, encoding="utf-8")
        assert detector.get_agent_gaps() == []

    def test_agent_exclude_pattern(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        detector._cc_agents_dir.mkdir(parents=True)
        (detector._cc_agents_dir / "gsd-foo.md").write_text(AGENT_MD, encoding="utf-8")
        (detector._cc_agents_dir / "odoo-developer.md").write_text(AGENT_MD, encoding="utf-8")
        gaps = detector.get_agent_gaps(exclude_patterns=["gsd-*"])
        assert [g.name for g in gaps] == ["odoo-developer"]


class TestCommandGaps:
    def test_command_gap_targets_prompts_dir(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        detector._cc_commands_dir.mkdir(parents=True)
        (detector._cc_commands_dir / "do.md").write_text(COMMAND_MD, encoding="utf-8")
        gaps = detector.get_command_gaps()
        assert len(gaps) == 1
        assert gaps[0].name == "do"
        assert gaps[0].dst_path == detector.prompts_dir / "do.md"

    def test_command_exclude_pattern(self, tmp_path: Path) -> None:
        detector = _detector(tmp_path)
        detector._cc_commands_dir.mkdir(parents=True)
        (detector._cc_commands_dir / "gsd-bar.md").write_text(COMMAND_MD, encoding="utf-8")
        (detector._cc_commands_dir / "finalize.md").write_text(COMMAND_MD, encoding="utf-8")
        gaps = detector.get_command_gaps(exclude_patterns=["gsd-*"])
        assert [g.name for g in gaps] == ["finalize"]
