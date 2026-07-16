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
