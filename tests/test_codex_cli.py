# CLI tests for the `sccs integrations codex` sub-group.

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from sccs.cli import cli

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(output: str) -> str:
    """Strip ANSI color codes — CI forces color, local pipes do not."""
    return _ANSI_RE.sub("", output)


class TestCodexGroup:
    def test_group_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["integrations", "codex", "--help"])
        assert result.exit_code == 0
        assert "Codex" in result.output

    def test_subcommand_help(self):
        runner = CliRunner()
        for command in ("status", "export-skills", "export-agents", "export-commands", "export-all"):
            result = runner.invoke(cli, ["integrations", "codex", command, "--help"])
            assert result.exit_code == 0, command

    def test_status_not_installed(self):
        runner = CliRunner()
        with patch("sccs.integrations.codex.CodexDetector") as mock_cls:
            mock = MagicMock()
            mock.get_info.return_value = None
            mock.is_installed.return_value = False
            mock_cls.return_value = mock
            result = runner.invoke(cli, ["integrations", "codex", "status"])
        assert result.exit_code == 0
        assert "not installed" in _plain(result.output)

    def test_export_not_installed_exits_nonzero(self):
        runner = CliRunner()
        for command in ("export-skills", "export-agents", "export-commands"):
            with patch("sccs.integrations.codex.CodexDetector") as mock_cls:
                mock = MagicMock()
                mock.is_installed.return_value = False
                mock_cls.return_value = mock
                result = runner.invoke(cli, ["integrations", "codex", command])
            assert result.exit_code == 1, command
            assert "not installed" in _plain(result.output)

    def test_export_skills_dry_run_happy_path(self, tmp_path):
        from sccs.integrations.codex import CodexDetector

        dirs = {
            "codex": tmp_path / ".codex",
            "skills": tmp_path / ".agents" / "skills",
            "cc_skills": tmp_path / ".claude" / "skills",
        }
        for path in dirs.values():
            path.mkdir(parents=True)
        skill = dirs["cc_skills"] / "my-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: my-skill\ndescription: d\n---\nBody\n", encoding="utf-8")

        detector = CodexDetector(
            codex_dir=dirs["codex"],
            skills_dir=dirs["skills"],
            cc_skills_dir=dirs["cc_skills"],
            cc_agents_dir=tmp_path / "none-agents",
            cc_commands_dir=tmp_path / "none-commands",
        )

        runner = CliRunner()
        with patch("sccs.cli._make_codex_detector", return_value=detector):
            result = runner.invoke(cli, ["integrations", "codex", "export-skills", "--dry-run"])

        assert result.exit_code == 0
        output = _plain(result.output)
        assert "Dry run" in output
        assert "Would create" in output
        assert not (dirs["skills"] / "my-skill").exists()


class TestSelectionByName:
    """A typo in -s/-a/-c must fail loudly, not report silent success."""

    def _detector(self, tmp_path):
        from sccs.integrations.codex import CodexDetector

        for rel in (".codex", ".agents/skills", ".claude/skills", ".claude/agents", ".claude/commands"):
            (tmp_path / rel).mkdir(parents=True)
        skill = tmp_path / ".claude" / "skills" / "my-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: my-skill\ndescription: d\n---\nBody\n", encoding="utf-8")
        (tmp_path / ".claude" / "agents" / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Reviews code.\nmodel: sonnet\n---\nBody\n", encoding="utf-8"
        )
        return CodexDetector(
            codex_dir=tmp_path / ".codex",
            skills_dir=tmp_path / ".agents" / "skills",
            cc_skills_dir=tmp_path / ".claude" / "skills",
            cc_agents_dir=tmp_path / ".claude" / "agents",
            cc_commands_dir=tmp_path / ".claude" / "commands",
        )

    def test_unknown_agent_name_exits_nonzero(self, tmp_path):
        runner = CliRunner()
        with patch("sccs.cli._make_codex_detector", return_value=self._detector(tmp_path)):
            result = runner.invoke(cli, ["integrations", "codex", "export-agents", "-a", "nope", "--dry-run"])
        assert result.exit_code == 1
        assert "No such agent" in _plain(result.output)
        assert "nope" in _plain(result.output)

    def test_unknown_skill_name_exits_nonzero(self, tmp_path):
        runner = CliRunner()
        with patch("sccs.cli._make_codex_detector", return_value=self._detector(tmp_path)):
            result = runner.invoke(cli, ["integrations", "codex", "export-skills", "-s", "typo", "--dry-run"])
        assert result.exit_code == 1
        assert "No such skill" in _plain(result.output)

    def test_known_name_still_exports(self, tmp_path):
        runner = CliRunner()
        with patch("sccs.cli._make_codex_detector", return_value=self._detector(tmp_path)):
            result = runner.invoke(cli, ["integrations", "codex", "export-skills", "-s", "my-skill", "--dry-run"])
        assert result.exit_code == 0
        assert "Would create" in _plain(result.output)


class TestIntegrationsStatusModelMap:
    """`integrations status` must judge agent gaps with the CONFIGURED map.

    Regression for v2.58.3: it called get_agent_gaps() without the maps, so it
    rendered agent TOML against the bundled defaults and disagreed with
    `sccs integrations codex status` for anyone overriding codex.model_map.
    """

    def test_status_injects_the_resolved_model_maps(self):
        runner = CliRunner()
        detector = MagicMock()
        detector.get_info.return_value = MagicMock(codex_dir="/x/.codex")
        detector.get_skill_gaps.return_value = []
        detector.get_agent_gaps.return_value = []
        detector.get_command_gaps.return_value = []

        model_map = {"sonnet": "custom-model"}
        reasoning_map = {"sonnet": "high"}

        with (
            patch("sccs.cli._make_codex_detector", return_value=detector),
            patch("sccs.cli._resolve_codex_model_maps", return_value=(model_map, reasoning_map)),
            patch("sccs.cli._resolve_codex_excludes", return_value=[]),
        ):
            result = runner.invoke(cli, ["integrations", "status"])

        assert result.exit_code == 0
        detector.get_agent_gaps.assert_called_once()
        args, kwargs = detector.get_agent_gaps.call_args
        assert args[0] is model_map
        assert args[1] is reasoning_map
