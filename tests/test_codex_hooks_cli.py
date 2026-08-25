# CLI tests for `sccs integrations codex export-hooks`.

from __future__ import annotations

import json
import re
from unittest.mock import patch

from click.testing import CliRunner

from sccs.cli import cli

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(output: str) -> str:
    """Strip ANSI color codes — CI forces color, local pipes do not."""
    return _ANSI_RE.sub("", output)


SETTINGS = {
    "hooks": {
        "PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "quality-gate.py"}]}],
        "PostToolUseFailure": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "nono-hook.sh"}]}],
    }
}


def _env(tmp_path):
    """Build a Codex home, a Claude settings.json and a state path."""
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".claude").mkdir()
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
    return settings, tmp_path / ".codex" / "hooks.json", tmp_path / "state.yaml"


class TestExportHooks:
    def test_help(self):
        result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks", "--help"])
        assert result.exit_code == 0

    def test_not_installed_exits_nonzero(self, tmp_path):
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(tmp_path / "s.json", tmp_path / "h.json")),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = False
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks"])
        assert result.exit_code == 1
        assert "not installed" in _plain(result.output)

    def test_dry_run_writes_nothing_and_reports(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks", "--dry-run"])
        assert result.exit_code == 0
        output = _plain(result.output)
        assert "Dry run" in output
        assert "PostToolUse / quality-gate.py" in output
        assert not hooks_path.exists()

    def test_export_writes_and_points_at_the_trust_review(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks"])
        assert result.exit_code == 0
        assert "/hooks" in _plain(result.output)
        written = json.loads(hooks_path.read_text())
        assert "PostToolUse" in written["hooks"]
        assert "PostToolUseFailure" not in written["hooks"]

    def test_dropped_event_is_warned_about(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks"])
        assert "PostToolUseFailure" in _plain(result.output)

    def test_second_run_reports_up_to_date(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            runner = CliRunner()
            runner.invoke(cli, ["integrations", "codex", "export-hooks"])
            result = runner.invoke(cli, ["integrations", "codex", "export-hooks"])
        assert "up to date" in _plain(result.output)

    def test_malformed_target_exits_nonzero_without_writing(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        hooks_path.write_text("[]", encoding="utf-8")
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks"])
        assert result.exit_code == 1
        assert hooks_path.read_text() == "[]"

    def test_export_all_does_not_touch_hooks(self, tmp_path):
        """Hooks execute code — they stay behind their own command."""
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = False
            CliRunner().invoke(cli, ["integrations", "codex", "export-all"])
        assert not hooks_path.exists()
