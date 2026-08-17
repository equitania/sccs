# Tests for the machine-readable --json output layer across Core-First commands.
#
# The contract these tests protect: every --json path must emit clean,
# single-line JSON via click.echo (never the ANSI-forcing Rich Console). So the
# universal assertion is `json.loads(result.output)` succeeds AND the output
# carries no ESC byte.

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from sccs.cli import cli
from sccs.config.schema import SccsConfig
from sccs.sync.category import CategoryStatus
from sccs.sync.engine import SyncResult


def _parse_clean(output: str) -> dict:
    """Assert output is exactly one clean (ANSI-free) JSON object and return it."""
    assert "\x1b" not in output, f"ANSI escape leaked into JSON output: {output!r}"
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one JSON line, got {len(lines)}: {lines!r}"
    return json.loads(lines[0])


class TestStatusJson:
    """sccs status --json"""

    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_config")
    def test_status_json_serializes_real_dataclass(self, mock_load, mock_engine_cls):
        mock_load.return_value = MagicMock()
        status = CategoryStatus(name="skills", enabled=True, total_items=3, to_sync=1)
        mock_engine = MagicMock()
        mock_engine.get_status.return_value = {"skills": status}
        mock_engine_cls.return_value = mock_engine

        result = CliRunner().invoke(cli, ["status", "--json"])
        assert result.exit_code == 0
        data = _parse_clean(result.output)
        assert data["skills"]["total_items"] == 3
        assert data["skills"]["to_sync"] == 1
        assert data["skills"]["enabled"] is True
        # computed @property must NOT leak into the payload
        assert "has_changes" not in data["skills"]

    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_config")
    def test_status_json_no_categories_is_empty_object(self, mock_load, mock_engine_cls):
        mock_load.return_value = MagicMock()
        mock_engine = MagicMock()
        mock_engine.get_status.return_value = {}
        mock_engine_cls.return_value = mock_engine

        result = CliRunner().invoke(cli, ["status", "--json"])
        assert result.exit_code == 0
        assert _parse_clean(result.output) == {}

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config here"))
    def test_status_json_missing_config_error_envelope(self, mock_load):
        result = CliRunner().invoke(cli, ["status", "--json"])
        assert result.exit_code == 1
        data = _parse_clean(result.output)
        assert data["success"] is False
        assert "No config here" in data["error"]


class TestCategoriesJson:
    """sccs categories list --json"""

    @patch("sccs.cli.load_config")
    def test_categories_json_full_list(self, mock_load):
        cfg = MagicMock()
        cfg.sync_categories = {
            "claude_skills": MagicMock(enabled=True, description="Skills", platforms=None),
            "fish_config": MagicMock(enabled=False, description="Fish", platforms=["macos", "linux"]),
        }
        mock_load.return_value = cfg

        result = CliRunner().invoke(cli, ["categories", "list", "--json"])
        assert result.exit_code == 0
        data = _parse_clean(result.output)
        assert data["claude_skills"]["enabled"] is True
        assert data["fish_config"]["enabled"] is False
        assert data["fish_config"]["platforms"] == ["macos", "linux"]

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("nope"))
    def test_categories_json_missing_config(self, mock_load):
        result = CliRunner().invoke(cli, ["categories", "list", "--json"])
        assert result.exit_code == 1
        assert _parse_clean(result.output)["success"] is False


class TestConfigShowJson:
    """sccs config show --json"""

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_config_path")
    def test_config_show_json_full_model(self, mock_path, mock_load, sample_config):
        cfg_path = MagicMock()
        cfg_path.exists.return_value = True
        cfg_path.__str__ = lambda self: "/fake/config.yaml"
        mock_path.return_value = cfg_path
        mock_load.return_value = SccsConfig.model_validate(sample_config)

        result = CliRunner().invoke(cli, ["config", "show", "--json"])
        assert result.exit_code == 0
        data = _parse_clean(result.output)
        assert "config_path" in data
        assert "repository" in data["config"]
        assert "sync_categories" in data["config"]

    @patch("sccs.cli.get_config_path")
    def test_config_show_json_missing(self, mock_path):
        cfg_path = MagicMock()
        cfg_path.exists.return_value = False
        mock_path.return_value = cfg_path

        result = CliRunner().invoke(cli, ["config", "show", "--json"])
        assert result.exit_code == 0
        assert _parse_clean(result.output)["success"] is False


class TestConfigValidateJson:
    """sccs config validate --json"""

    @patch("sccs.cli.validate_config_file", return_value=(True, []))
    def test_validate_json_valid(self, mock_validate):
        result = CliRunner().invoke(cli, ["config", "validate", "--json"])
        assert result.exit_code == 0
        data = _parse_clean(result.output)
        assert data == {"valid": True, "errors": []}

    @patch("sccs.cli.validate_config_file", return_value=(False, ["bad thing"]))
    def test_validate_json_invalid_exits_1(self, mock_validate):
        result = CliRunner().invoke(cli, ["config", "validate", "--json"])
        assert result.exit_code == 1
        data = _parse_clean(result.output)
        assert data["valid"] is False
        assert data["errors"] == ["bad thing"]


class TestConfigInitJson:
    """sccs config init --repo-path --json (non-interactive)"""

    @patch("sccs.cli.generate_default_config", return_value="repository:\n  path: ~/gitbase/sccs-sync\n")
    @patch("sccs.cli.get_config_path")
    def test_config_init_repo_path_non_interactive(self, mock_path, mock_gen, tmp_path):
        target = tmp_path / "config.yaml"
        mock_path.return_value = target

        result = CliRunner().invoke(cli, ["config", "init", "--repo-path", "/custom/repo", "--json"])
        assert result.exit_code == 0
        data = _parse_clean(result.output)
        assert data["created"] is True
        assert data["repository_path"] == "/custom/repo"
        # The prompt must never have run: the repo path landed in the file.
        assert "/custom/repo" in target.read_text(encoding="utf-8")

    @patch("sccs.cli.get_config_path")
    def test_config_init_json_existing_without_force(self, mock_path, tmp_path):
        target = tmp_path / "config.yaml"
        target.write_text("existing", encoding="utf-8")
        mock_path.return_value = target

        result = CliRunner().invoke(cli, ["config", "init", "--repo-path", "/x", "--json"])
        assert result.exit_code == 0
        assert _parse_clean(result.output)["success"] is False


class TestSyncJson:
    """sccs sync --json"""

    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_config")
    def test_sync_dry_run_json_single_line(self, mock_load, mock_engine_cls):
        cfg = MagicMock()
        cfg.repository.path = "/tmp/repo"
        cfg.repository.auto_commit = False
        cfg.repository.auto_push = False
        mock_load.return_value = cfg

        result_obj = SyncResult(success=True, total_categories=2, synced_items=0)
        mock_engine = MagicMock()
        mock_engine.sync.return_value = result_obj
        mock_engine_cls.return_value = mock_engine

        result = CliRunner().invoke(cli, ["sync", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = _parse_clean(result.output)
        assert data["dry_run"] is True
        assert data["committed"] is False
        assert data["pushed"] is False
        assert data["result"]["success"] is True
        assert data["result"]["total_categories"] == 2


class TestDiffJson:
    """sccs diff --json"""

    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_config")
    def test_diff_json_no_categories(self, mock_load, mock_engine_cls):
        mock_load.return_value = MagicMock()
        mock_engine = MagicMock()
        mock_engine.get_enabled_categories.return_value = []
        mock_engine_cls.return_value = mock_engine

        result = CliRunner().invoke(cli, ["diff", "--json"])
        assert result.exit_code == 0
        assert _parse_clean(result.output) == {"diffs": []}

    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_config")
    def test_diff_json_unknown_category(self, mock_load, mock_engine_cls):
        mock_load.return_value = MagicMock()
        mock_engine = MagicMock()
        mock_engine.get_handler.return_value = None
        mock_engine_cls.return_value = mock_engine

        result = CliRunner().invoke(cli, ["diff", "-c", "nope", "--json"])
        assert result.exit_code == 1
        assert _parse_clean(result.output)["success"] is False


class TestDoctorJson:
    """sccs doctor check/install --json"""

    @patch("sccs.doctor.reporter.has_updates", return_value=False)
    @patch("sccs.doctor.reporter.has_problems", return_value=False)
    @patch("sccs.cli._collect_doctor_statuses")
    @patch("sccs.cli._load_doctor_config")
    def test_doctor_check_json_healthy(self, mock_cfg, mock_collect, mock_probs, mock_upd):
        mock_cfg.return_value = MagicMock(min_node_major=22)
        mock_collect.return_value = {
            "node": {"installed": True, "version": "22.1.0"},
            "claude_cli": {"installed": True},
            "plugins": [],
            "npx_tools": [],
        }

        result = CliRunner().invoke(cli, ["doctor", "check", "--json", "--no-update-check"])
        assert result.exit_code == 0
        data = _parse_clean(result.output)
        assert data["has_problems"] is False
        assert data["has_updates"] is False
        assert data["node"]["installed"] is True
        assert data["min_node_major"] == 22

    @patch("sccs.doctor.reporter.has_updates", return_value=False)
    @patch("sccs.doctor.reporter.has_problems", return_value=False)
    @patch("sccs.cli._collect_doctor_statuses")
    @patch("sccs.cli._load_doctor_config")
    def test_doctor_check_json_carries_statusline_presets(self, mock_cfg, mock_collect, mock_probs, mock_upd):
        """Regression (v2.58.2): the Rich table gained `statusline-preset:` rows
        in v2.58.1 but the JSON payload did not, so a GUI saw only the
        `status_lines` integrity check and could not tell which preset is
        chosen, installed or live."""
        from sccs.doctor.statusline import StatusLinePresetStatus

        mock_cfg.return_value = MagicMock(min_node_major=22)
        mock_collect.return_value = {
            "node": {},
            "claude_cli": {},
            "plugins": [],
            "npx_tools": [],
            "statusline_presets": [
                StatusLinePresetStatus(
                    name="claude-code-statusline",
                    description="",
                    command="~/.claude/statusline",
                    installed=True,
                    is_active=True,
                    is_configured=True,
                    installable=True,
                    version="statusline 1.0.0",
                )
            ],
        }

        result = CliRunner().invoke(cli, ["doctor", "check", "--json", "--no-update-check"])
        assert result.exit_code == 0
        presets = _parse_clean(result.output)["statusline_presets"]
        assert presets[0]["name"] == "claude-code-statusline"
        assert presets[0]["is_active"] is True
        assert presets[0]["version"] == "statusline 1.0.0"

    @patch("sccs.doctor.reporter.has_updates", return_value=False)
    @patch("sccs.doctor.reporter.has_problems", return_value=True)
    @patch("sccs.cli._collect_doctor_statuses")
    @patch("sccs.cli._load_doctor_config")
    def test_doctor_check_json_problems_exit_1(self, mock_cfg, mock_collect, mock_probs, mock_upd):
        mock_cfg.return_value = MagicMock(min_node_major=22)
        mock_collect.return_value = {"node": {}, "claude_cli": {}, "plugins": [], "npx_tools": []}

        result = CliRunner().invoke(cli, ["doctor", "check", "--json", "--no-update-check"])
        assert result.exit_code == 1
        assert _parse_clean(result.output)["has_problems"] is True

    @patch("sccs.doctor.installer.build_install_plan")
    @patch("sccs.doctor.state.DoctorStateManager")
    @patch("sccs.cli._collect_doctor_statuses")
    @patch("sccs.cli._load_doctor_config")
    def test_doctor_install_json_empty_plan(self, mock_cfg, mock_collect, mock_state, mock_plan):
        mock_cfg.return_value = MagicMock()
        mock_collect.return_value = {"node": {}, "claude_cli": {}, "plugins": [], "npx_tools": []}
        plan = MagicMock()
        plan.is_empty.return_value = True
        mock_plan.return_value = plan

        result = CliRunner().invoke(cli, ["doctor", "install", "--json"])
        assert result.exit_code == 0
        data = _parse_clean(result.output)
        assert data == {"planned_actions": 0, "assume_yes": False, "outcomes": []}
