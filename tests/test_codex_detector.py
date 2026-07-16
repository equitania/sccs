# Tests for the Codex detector (installation + gap detection).

from __future__ import annotations

from pathlib import Path

from sccs.integrations.codex import CodexDetector

AGENT_MD = """---
name: reviewer
description: Reviews Python code.
model: sonnet
tools: Read, Grep, Glob
---
# Role

You review diffs.
"""

COMMAND_MD = """---
description: Quality gate before commit.
---
Run format, tests, build.
"""


def _make_dirs(tmp_path: Path) -> dict[str, Path]:
    dirs = {
        "codex": tmp_path / ".codex",
        "skills": tmp_path / ".agents" / "skills",
        "cc_skills": tmp_path / ".claude" / "skills",
        "cc_agents": tmp_path / ".claude" / "agents",
        "cc_commands": tmp_path / ".claude" / "commands",
    }
    for path in dirs.values():
        path.mkdir(parents=True)
    return dirs


def _detector(tmp_path: Path, *, install: bool = True) -> CodexDetector:
    dirs = _make_dirs(tmp_path)
    if not install:
        dirs["codex"].rmdir()
    return CodexDetector(
        codex_dir=dirs["codex"],
        skills_dir=dirs["skills"],
        cc_skills_dir=dirs["cc_skills"],
        cc_agents_dir=dirs["cc_agents"],
        cc_commands_dir=dirs["cc_commands"],
    )


def _write_skill(cc_skills: Path, name: str, content: str = "---\nname: s\ndescription: d\n---\nBody\n") -> Path:
    skill_dir = cc_skills / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


class TestInstallation:
    def test_not_installed(self, tmp_path):
        detector = _detector(tmp_path, install=False)
        assert not detector.is_installed()
        assert detector.get_info() is None
        assert detector.get_skill_gaps() == []
        assert detector.get_agent_gaps() == []
        assert detector.get_command_gaps() == []

    def test_installed(self, tmp_path):
        detector = _detector(tmp_path)
        assert detector.is_installed()
        info = detector.get_info()
        assert info is not None
        assert info.installed
        assert info.skills_dir.name == "skills"
        assert info.agents_dir == info.codex_dir / "agents"
        assert not info.agents_dir_exists

    def test_skills_dir_alone_is_not_an_install_marker(self, tmp_path):
        # ~/.agents/skills may exist because of an unrelated agentskills tool.
        detector = _detector(tmp_path, install=False)
        assert not detector.is_installed()


class TestSkillGaps:
    def test_missing_skill_is_a_gap(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "my-skill")

        gaps = detector.get_skill_gaps()
        assert [g.name for g in gaps] == ["my-skill"]
        assert gaps[0].is_dir
        assert not gaps[0].dst_exists
        assert gaps[0].converted_content is None

    def test_private_and_markerless_skipped(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "_private")
        (detector._cc_skills_dir / "no-marker").mkdir()

        assert detector.get_skill_gaps() == []

    def test_exclude_pattern(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "gsd-thing")
        _write_skill(detector._cc_skills_dir, "mine")

        gaps = detector.get_skill_gaps(exclude_patterns=["gsd-*"])
        assert [g.name for g in gaps] == ["mine"]

    def test_up_to_date_skill_is_no_gap(self, tmp_path):
        from sccs.integrations.codex import export_skills_to_codex

        detector = _detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "my-skill")
        export_skills_to_codex(detector.get_skill_gaps())

        assert detector.get_skill_gaps() == []

    def test_changed_skill_needs_update(self, tmp_path):
        from sccs.integrations.codex import export_skills_to_codex

        detector = _detector(tmp_path)
        skill_dir = _write_skill(detector._cc_skills_dir, "my-skill")
        export_skills_to_codex(detector.get_skill_gaps())

        (skill_dir / "SKILL.md").write_text("---\nname: s\ndescription: new\n---\nChanged\n", encoding="utf-8")
        gaps = detector.get_skill_gaps()
        assert len(gaps) == 1
        assert gaps[0].needs_update


class TestAgentGaps:
    def test_missing_agent_renders_toml(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "reviewer.md").write_text(AGENT_MD, encoding="utf-8")

        gaps = detector.get_agent_gaps()
        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.dst_path.name == "reviewer.toml"
        assert not gap.is_dir
        assert 'name = "reviewer"' in gap.converted_content
        assert 'sandbox_mode = "read-only"' in gap.converted_content
        assert "You review diffs." in gap.converted_content

    def test_model_map_injection_changes_content(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "reviewer.md").write_text(AGENT_MD, encoding="utf-8")

        gaps = detector.get_agent_gaps({"sonnet": "my-model"}, {"sonnet": "low"})
        assert 'model = "my-model"' in gaps[0].converted_content
        assert 'model_reasoning_effort = "low"' in gaps[0].converted_content

    def test_private_local_and_excluded_skipped(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "_private.md").write_text(AGENT_MD, encoding="utf-8")
        (detector._cc_agents_dir / "mine.local.md").write_text(AGENT_MD, encoding="utf-8")
        (detector._cc_agents_dir / "gsd-thing.md").write_text(AGENT_MD, encoding="utf-8")

        assert detector.get_agent_gaps(exclude_patterns=["gsd-*"]) == []

    def test_up_to_date_agent_is_no_gap(self, tmp_path):
        from sccs.integrations.codex import convert_agents_to_codex

        detector = _detector(tmp_path)
        (detector._cc_agents_dir / "reviewer.md").write_text(AGENT_MD, encoding="utf-8")
        convert_agents_to_codex(detector.get_agent_gaps())

        assert detector.get_agent_gaps() == []


class TestCommandGaps:
    def test_missing_command_wraps_as_skill(self, tmp_path):
        detector = _detector(tmp_path)
        (detector._cc_commands_dir / "finalize.md").write_text(COMMAND_MD, encoding="utf-8")

        gaps = detector.get_command_gaps()
        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.dst_path == detector.skills_dir / "finalize" / "SKILL.md"
        assert not gap.collision
        assert "name: finalize" in gap.converted_content
        assert "Run format, tests, build." in gap.converted_content

    def test_collision_with_claude_skill(self, tmp_path):
        detector = _detector(tmp_path)
        _write_skill(detector._cc_skills_dir, "finalize")
        (detector._cc_commands_dir / "finalize.md").write_text(COMMAND_MD, encoding="utf-8")

        gaps = detector.get_command_gaps()
        assert len(gaps) == 1
        assert gaps[0].collision
        assert any("skill wins" in w for w in gaps[0].warnings)

    def test_collision_with_real_on_disk_skill(self, tmp_path):
        detector = _detector(tmp_path)
        target = detector.skills_dir / "finalize"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("real skill", encoding="utf-8")
        (target / "scripts").mkdir()
        (detector._cc_commands_dir / "finalize.md").write_text(COMMAND_MD, encoding="utf-8")

        gaps = detector.get_command_gaps()
        assert gaps[0].collision

    def test_reexport_of_wrapped_command_is_not_a_collision(self, tmp_path):
        from sccs.integrations.codex import convert_commands_to_codex

        detector = _detector(tmp_path)
        cmd = detector._cc_commands_dir / "finalize.md"
        cmd.write_text(COMMAND_MD, encoding="utf-8")
        convert_commands_to_codex(detector.get_command_gaps())

        # Unchanged: no gap at all.
        assert detector.get_command_gaps() == []

        # Changed source: an update gap, not a collision.
        cmd.write_text("---\ndescription: New gate.\n---\nNew body.\n", encoding="utf-8")
        gaps = detector.get_command_gaps()
        assert len(gaps) == 1
        assert not gaps[0].collision
        assert gaps[0].needs_update
