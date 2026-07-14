# Tests for the `sccs capability-card` self-serve command.

from __future__ import annotations

from click.testing import CliRunner

import sccs.cli as cli_module
from sccs import __version__
from sccs.cli import cli


class TestCapabilityCard:
    def test_prints_card(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["capability-card"])
        assert result.exit_code == 0
        assert "Agent Capability Card" in result.output

    def test_version_is_injected_live(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["capability-card"])
        assert result.exit_code == 0
        assert f"**Version:** {__version__}" in result.output

    def test_contains_command_surface(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["capability-card"])
        assert result.exit_code == 0
        assert "sccs sync" in result.output
        assert "sccs doctor" in result.output
        # The card advertises itself.
        assert "sccs capability-card" in result.output

    def test_listed_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "capability-card" in result.output

    def test_missing_card_errors_cleanly(self, monkeypatch):
        monkeypatch.setattr(cli_module, "_find_capability_card", lambda: None)
        runner = CliRunner()
        result = runner.invoke(cli, ["capability-card"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestVersionInjection:
    def test_stale_version_is_replaced(self, monkeypatch, tmp_path):
        card = tmp_path / "AGENT.md"
        card.write_text(
            "# sccs — Agent Capability Card\n- **Version:** 0.1.0  ·  **Python:** ≥3.10\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(cli_module, "_find_capability_card", lambda: card)
        runner = CliRunner()
        result = runner.invoke(cli, ["capability-card"])
        assert result.exit_code == 0
        assert f"**Version:** {__version__}" in result.output
        assert "0.1.0" not in result.output
