# Tests for SCCS OpenCode detector + artefact materialisation

from pathlib import Path

from sccs.integrations.opencode import (
    OpenCodeDetector,
    convert_agents_to_opencode,
    convert_commands_to_opencode,
)

AGENT_MD = """---
name: my-agent
description: An agent
model: sonnet
allowed-tools: Read Write
---
Agent body.
"""

COMMAND_MD = """---
description: A command
model: opus
tags: [x]
---
Command body.
"""


def _make_dirs(tmp_path: Path):
    config_dir = tmp_path / ".config" / "opencode"
    cc_agents = tmp_path / ".claude" / "agents"
    cc_commands = tmp_path / ".claude" / "commands"
    cc_skills = tmp_path / ".claude" / "skills"
    return config_dir, cc_agents, cc_commands, cc_skills


class TestOpenCodeDetector:
    def test_not_installed(self, tmp_path: Path) -> None:
        detector = OpenCodeDetector(config_dir=tmp_path / "nope")
        assert detector.is_installed() is False
        assert detector.get_info() is None
        assert detector.get_agent_gaps() == []
        assert detector.get_command_gaps() == []

    def test_get_info(self, tmp_path: Path) -> None:
        config_dir, *_ = _make_dirs(tmp_path)
        config_dir.mkdir(parents=True)
        (config_dir / "opencode.jsonc").write_text('{"$schema": "x"}', encoding="utf-8")
        detector = OpenCodeDetector(config_dir=config_dir)
        info = detector.get_info()
        assert info is not None
        assert info.installed is True
        assert info.config_file is not None
        assert info.config_file.name == "opencode.jsonc"
        assert info.reads_claude_skills is True

    def test_get_info_disable_skills_flag(self, tmp_path: Path) -> None:
        config_dir, *_ = _make_dirs(tmp_path)
        config_dir.mkdir(parents=True)
        detector = OpenCodeDetector(config_dir=config_dir, disable_claude_skills=True)
        info = detector.get_info()
        assert info is not None
        assert info.reads_claude_skills is False

    def test_agent_gap_missing(self, tmp_path: Path) -> None:
        config_dir, cc_agents, cc_commands, _ = _make_dirs(tmp_path)
        config_dir.mkdir(parents=True)
        cc_agents.mkdir(parents=True)
        (cc_agents / "my-agent.md").write_text(AGENT_MD, encoding="utf-8")
        detector = OpenCodeDetector(config_dir=config_dir, cc_agents_dir=cc_agents, cc_commands_dir=cc_commands)
        gaps = detector.get_agent_gaps()
        assert len(gaps) == 1
        assert gaps[0].name == "my-agent"
        assert gaps[0].oc_exists is False
        assert "anthropic/claude-sonnet-4-5" in gaps[0].converted_content

    def test_agent_gap_skips_private_and_local(self, tmp_path: Path) -> None:
        config_dir, cc_agents, cc_commands, _ = _make_dirs(tmp_path)
        config_dir.mkdir(parents=True)
        cc_agents.mkdir(parents=True)
        (cc_agents / "_private.md").write_text(AGENT_MD, encoding="utf-8")
        (cc_agents / "thing.local.md").write_text(AGENT_MD, encoding="utf-8")
        (cc_agents / ".hidden.md").write_text(AGENT_MD, encoding="utf-8")
        detector = OpenCodeDetector(config_dir=config_dir, cc_agents_dir=cc_agents, cc_commands_dir=cc_commands)
        assert detector.get_agent_gaps() == []

    def test_agent_gap_up_to_date(self, tmp_path: Path) -> None:
        config_dir, cc_agents, cc_commands, _ = _make_dirs(tmp_path)
        config_dir.mkdir(parents=True)
        cc_agents.mkdir(parents=True)
        (cc_agents / "my-agent.md").write_text(AGENT_MD, encoding="utf-8")
        detector = OpenCodeDetector(config_dir=config_dir, cc_agents_dir=cc_agents, cc_commands_dir=cc_commands)
        # Materialise it, then there should be no gap.
        result = convert_agents_to_opencode(detector.get_agent_gaps())
        assert result.created == ["my-agent"]
        assert detector.get_agent_gaps() == []

    def test_command_gap_missing(self, tmp_path: Path) -> None:
        config_dir, cc_agents, cc_commands, _ = _make_dirs(tmp_path)
        config_dir.mkdir(parents=True)
        cc_commands.mkdir(parents=True)
        (cc_commands / "do.md").write_text(COMMAND_MD, encoding="utf-8")
        detector = OpenCodeDetector(config_dir=config_dir, cc_agents_dir=cc_agents, cc_commands_dir=cc_commands)
        gaps = detector.get_command_gaps()
        assert len(gaps) == 1
        assert gaps[0].name == "do"


class TestMaterialize:
    def _detector(self, tmp_path: Path):
        config_dir, cc_agents, cc_commands, _ = _make_dirs(tmp_path)
        config_dir.mkdir(parents=True)
        cc_agents.mkdir(parents=True)
        (cc_agents / "a1.md").write_text(AGENT_MD, encoding="utf-8")
        return OpenCodeDetector(config_dir=config_dir, cc_agents_dir=cc_agents, cc_commands_dir=cc_commands), config_dir

    def test_create_writes_file(self, tmp_path: Path) -> None:
        detector, config_dir = self._detector(tmp_path)
        result = convert_agents_to_opencode(detector.get_agent_gaps())
        assert result.created == ["a1"]
        target = config_dir / "agent" / "a1.md"
        assert target.is_file()
        assert "mode: subagent" in target.read_text(encoding="utf-8")

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        detector, config_dir = self._detector(tmp_path)
        result = convert_agents_to_opencode(detector.get_agent_gaps(), dry_run=True)
        assert result.created == ["a1"]
        assert not (config_dir / "agent" / "a1.md").exists()

    def test_no_overwrite_skips_existing(self, tmp_path: Path) -> None:
        detector, config_dir = self._detector(tmp_path)
        convert_agents_to_opencode(detector.get_agent_gaps())
        # change source so a gap reappears
        (detector._cc_agents_dir / "a1.md").write_text(AGENT_MD.replace("An agent", "Changed"), encoding="utf-8")
        result = convert_agents_to_opencode(detector.get_agent_gaps(), overwrite_existing=False)
        assert result.skipped == ["a1"]
        assert result.updated == []

    def test_overwrite_updates(self, tmp_path: Path) -> None:
        detector, _ = self._detector(tmp_path)
        convert_agents_to_opencode(detector.get_agent_gaps())
        (detector._cc_agents_dir / "a1.md").write_text(AGENT_MD.replace("An agent", "Changed"), encoding="utf-8")
        result = convert_agents_to_opencode(detector.get_agent_gaps())
        assert result.updated == ["a1"]

    def test_selected_filter(self, tmp_path: Path) -> None:
        detector, _ = self._detector(tmp_path)
        (detector._cc_agents_dir / "a2.md").write_text(AGENT_MD, encoding="utf-8")
        result = convert_agents_to_opencode(detector.get_agent_gaps(), selected=["a1"])
        assert result.created == ["a1"]

    def test_warnings_collected(self, tmp_path: Path) -> None:
        detector, _ = self._detector(tmp_path)
        result = convert_agents_to_opencode(detector.get_agent_gaps())
        # allowed-tools allowlist warning is attached to the agent
        assert "a1" in result.warnings

    def test_empty_gaps(self, tmp_path: Path) -> None:
        result = convert_commands_to_opencode([])
        assert result.created == []
