# Tests for sccs.cli
# CLI commands using Click testing

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import sccs.cli as cli_module
from sccs.cli import _print_platform_hint, cli
from sccs.config.schema import SccsConfig


class TestCliGroup:
    """Tests for main CLI group."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "SCCS" in result.output
        assert "Workflows" in result.output
        assert "Publisher" in result.output
        assert "Subscriber" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "sccs" in result.output


class TestSyncCommand:
    """Tests for sync command."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["sync", "--help"])
        assert result.exit_code == 0
        assert "Synchronize" in result.output
        assert "Publish local changes" in result.output
        assert "Receive repo changes" in result.output

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_missing_config(self, mock_load):
        runner = CliRunner()
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 1
        assert "No config" in result.output

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"up_to_date": True})
    @patch("sccs.cli.SyncEngine")
    def test_dry_run(self, mock_engine_cls, mock_remote, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 0
        mock_result.conflicts = 0
        mock_result.errors = 0
        mock_result.success = True
        mock_result.aborted = False
        mock_result.has_issues = False
        mock_result.total_categories = 1
        mock_result.synced_categories = 1
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["sync", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.output

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"up_to_date": True})
    @patch("sccs.cli.SyncEngine")
    def test_sync_with_conflicts(self, mock_engine_cls, mock_remote, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_config.repository.auto_commit = False
        mock_config.repository.auto_push = False
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 1
        mock_result.conflicts = 2
        mock_result.errors = 0
        mock_result.success = True
        mock_result.aborted = False
        mock_result.has_issues = True
        mock_result.total_categories = 1
        mock_result.synced_categories = 1
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        assert "conflicts" in result.output

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"behind": 2, "up_to_date": False})
    @patch("sccs.cli.SyncEngine")
    def test_sync_behind_no_pull(self, mock_engine_cls, mock_remote, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_config.repository.auto_pull = False
        mock_load.return_value = mock_config

        runner = CliRunner()
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 1

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"behind": 1, "up_to_date": False})
    @patch("sccs.cli.pull", return_value=True)
    @patch("sccs.cli.SyncEngine")
    def test_sync_behind_with_auto_pull(self, mock_engine_cls, mock_pull, mock_remote, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_config.repository.auto_pull = True
        mock_config.repository.auto_commit = False
        mock_config.repository.auto_push = False
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 0
        mock_result.conflicts = 0
        mock_result.errors = 0
        mock_result.success = True
        mock_result.aborted = False
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        mock_pull.assert_called_once()

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"error": "no remote"})
    @patch("sccs.cli.SyncEngine")
    def test_sync_remote_error_continues(self, mock_engine_cls, mock_remote, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_config.repository.auto_commit = False
        mock_config.repository.auto_push = False
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 0
        mock_result.conflicts = 0
        mock_result.errors = 0
        mock_result.success = True
        mock_result.aborted = False
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["sync"])
        # Should continue despite remote error
        assert result.exit_code == 0

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"up_to_date": True})
    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.has_uncommitted_changes", return_value=True)
    @patch("sccs.cli.stage_all")
    @patch("sccs.cli.commit")
    @patch("sccs.cli.push", return_value=True)
    def test_sync_with_commit_and_push(
        self, mock_push, mock_commit, mock_stage, mock_uncommitted, mock_engine_cls, mock_remote, mock_load
    ):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_config.repository.auto_commit = True
        mock_config.repository.auto_push = True
        mock_config.repository.remote = "origin"
        mock_config.repository.commit_prefix = "[SYNC]"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 3
        mock_result.conflicts = 0
        mock_result.errors = 0
        mock_result.success = True
        mock_result.aborted = False
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        mock_commit.assert_called_once()
        mock_push.assert_called_once()

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"up_to_date": True})
    @patch("sccs.cli.SyncEngine")
    def test_sync_aborted(self, mock_engine_cls, mock_remote, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 0
        mock_result.conflicts = 0
        mock_result.errors = 0
        mock_result.success = False
        mock_result.aborted = True
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 1
        assert "aborted" in result.output.lower()


class TestStatusCommand:
    """Tests for status command."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "synchronization status" in result.output
        assert "Examples" in result.output

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_missing_config(self, mock_load):
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.SyncEngine")
    def test_no_categories(self, mock_engine_cls, mock_load):
        mock_load.return_value = MagicMock()
        mock_engine = MagicMock()
        mock_engine.get_status.return_value = {}
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1

    @patch("sccs.cli._show_integrations_inline")
    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_config")
    def test_status_with_data(self, mock_load, mock_engine_cls, mock_integrations):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        # Use a spec-free mock with explicit attributes to avoid comparison errors
        mock_status = MagicMock()
        mock_status.new_items = 0
        mock_status.modified_items = 1
        mock_status.deleted_items = 0
        mock_status.conflicts = 0

        mock_engine = MagicMock()
        mock_engine.get_status.return_value = {"skills": mock_status}
        mock_engine_cls.return_value = mock_engine

        with patch("sccs.cli.Console.print_status"):
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        mock_engine.get_status.assert_called_once()

    @patch("sccs.cli._show_integrations_inline")
    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_config")
    def test_status_category_filter(self, mock_load, mock_engine_cls, mock_integrations):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        mock_status = MagicMock()
        mock_status.new_items = 0
        mock_status.modified_items = 0
        mock_status.deleted_items = 0
        mock_status.conflicts = 0

        mock_engine = MagicMock()
        mock_engine.get_status.return_value = {"skills": mock_status}
        mock_engine_cls.return_value = mock_engine

        with patch("sccs.cli.Console.print_status"):
            runner = CliRunner()
            result = runner.invoke(cli, ["status", "-c", "skills"])
        assert result.exit_code == 0
        mock_engine.get_status.assert_called_once_with(category_name="skills")

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.SyncEngine")
    def test_status_unknown_category(self, mock_engine_cls, mock_load):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.get_status.return_value = {}
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["status", "-c", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output or "not enabled" in result.output


class TestLogCommand:
    """Tests for log command."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["log", "--help"])
        assert result.exit_code == 0
        assert "sync history" in result.output
        assert "Examples" in result.output

    @patch("sccs.cli.StateManager")
    def test_empty_history(self, mock_manager_cls):
        mock_state = MagicMock()
        mock_state.items = {}
        mock_manager = MagicMock()
        mock_manager.state = mock_state
        mock_manager_cls.return_value = mock_manager

        runner = CliRunner()
        result = runner.invoke(cli, ["log"])
        assert result.exit_code == 0
        assert "No sync history" in result.output

    @patch("sccs.cli.StateManager")
    def test_log_with_history(self, mock_manager_cls):
        item1 = MagicMock()
        item1.last_synced = "2026-06-07T10:00:00"
        item1.last_action = "COPY_TO_REPO"
        item1.category = "skills"
        item1.name = "my-skill"

        mock_state = MagicMock()
        mock_state.last_sync = "2026-06-07T10:00:00"
        mock_state.items = {"skills:my-skill": item1}

        mock_manager = MagicMock()
        mock_manager.state = mock_state
        mock_manager_cls.return_value = mock_manager

        runner = CliRunner()
        result = runner.invoke(cli, ["log"])
        assert result.exit_code == 0
        assert "Last sync" in result.output
        assert "Total items" in result.output

    @patch("sccs.cli.StateManager")
    def test_log_last_option(self, mock_manager_cls):
        mock_state = MagicMock()
        mock_state.items = {}
        mock_manager = MagicMock()
        mock_manager.state = mock_state
        mock_manager_cls.return_value = mock_manager

        runner = CliRunner()
        result = runner.invoke(cli, ["log", "--last", "5"])
        assert result.exit_code == 0


class TestConfigCommands:
    """Tests for config subcommands."""

    def test_config_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "Configuration management" in result.output
        assert "repository.path" in result.output
        assert "auto_commit" in result.output

    def test_config_show_no_file(self):
        runner = CliRunner()
        with patch("sccs.cli.get_config_path") as mock_path:
            mock_path.return_value = MagicMock(exists=lambda: False)
            result = runner.invoke(cli, ["config", "show"])
            assert result.exit_code == 0
            assert "not found" in result.output

    def test_config_show_with_config(self):
        runner = CliRunner()
        mock_path = MagicMock()
        mock_path.exists.return_value = True

        mock_cfg = MagicMock()
        mock_cfg.repository.path = "/tmp/repo"
        mock_cfg.repository.auto_commit = False
        mock_cfg.repository.auto_push = False
        mock_cfg.get_enabled_categories.return_value = {"skills": MagicMock(description="Skills")}
        mock_cfg.sync_categories = {
            "skills": MagicMock(description="Skills", enabled=True),
        }

        with (
            patch("sccs.cli.get_config_path", return_value=mock_path),
            patch("sccs.cli.load_config", return_value=mock_cfg),
        ):
            result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0
        assert "Repository" in result.output

    def test_config_validate_valid(self):
        runner = CliRunner()
        with patch("sccs.cli.validate_config_file", return_value=(True, [])):
            result = runner.invoke(cli, ["config", "validate"])
            assert result.exit_code == 0
            assert "valid" in result.output

    def test_config_validate_invalid(self):
        runner = CliRunner()
        with patch("sccs.cli.validate_config_file", return_value=(False, ["bad key"])):
            result = runner.invoke(cli, ["config", "validate"])
            assert result.exit_code == 1
            assert "errors" in result.output

    def test_config_init_already_exists(self):
        runner = CliRunner()
        mock_path = MagicMock()
        mock_path.exists.return_value = True

        with patch("sccs.cli.get_config_path", return_value=mock_path):
            result = runner.invoke(cli, ["config", "init"])
        assert result.exit_code == 0
        assert "already exists" in result.output or "exists" in result.output

    def test_config_init_force(self, tmp_path):
        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.touch()

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.parent = tmp_path
        mock_path.write_text = MagicMock()

        with (
            patch("sccs.cli.get_config_path", return_value=mock_path),
            patch("sccs.cli.generate_default_config", return_value="repository:\n  path: ~/test\n"),
        ):
            result = runner.invoke(cli, ["config", "init", "--force"], input="~/myrepo\n")
        assert result.exit_code == 0

    def test_config_edit_no_file(self):
        runner = CliRunner()
        mock_path = MagicMock()
        mock_path.exists.return_value = False

        with (
            patch("sccs.cli.get_config_path", return_value=mock_path),
            patch("sccs.cli.ensure_config_exists"),
            patch("shutil.which", return_value=None),
        ):
            result = runner.invoke(cli, ["config", "edit"])
        assert result.exit_code == 0

    def test_config_upgrade_no_file(self):
        runner = CliRunner()
        mock_path = MagicMock()
        mock_path.exists.return_value = False

        with patch("sccs.cli.get_config_path", return_value=mock_path):
            result = runner.invoke(cli, ["config", "upgrade"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_config_upgrade_up_to_date(self):
        runner = CliRunner()
        mock_path = MagicMock()
        mock_path.exists.return_value = True

        with (
            patch("sccs.cli.get_config_path", return_value=mock_path),
            patch("sccs.cli.load_raw_user_data", return_value={}),
            patch("sccs.cli.MigrationStateManager"),
            patch("sccs.cli.detect_new_categories", return_value=[]),
        ):
            result = runner.invoke(cli, ["config", "upgrade"])
        assert result.exit_code == 0
        assert "up to date" in result.output


class TestCategoriesCommands:
    """Tests for categories subcommands."""

    def test_categories_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["categories", "--help"])
        assert result.exit_code == 0
        assert "Category management" in result.output
        assert "Examples" in result.output

    @patch("sccs.cli.update_category_enabled")
    def test_enable_category(self, mock_update):
        runner = CliRunner()
        result = runner.invoke(cli, ["categories", "enable", "fish"])
        assert result.exit_code == 0
        assert "Enabled" in result.output
        mock_update.assert_called_once_with("fish", True)

    @patch("sccs.cli.update_category_enabled")
    def test_disable_category(self, mock_update):
        runner = CliRunner()
        result = runner.invoke(cli, ["categories", "disable", "fish"])
        assert result.exit_code == 0
        assert "Disabled" in result.output
        mock_update.assert_called_once_with("fish", False)

    @patch("sccs.cli.update_category_enabled", side_effect=KeyError("not found"))
    def test_enable_unknown_category(self, mock_update):
        runner = CliRunner()
        result = runner.invoke(cli, ["categories", "enable", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("sccs.cli.update_category_enabled", side_effect=FileNotFoundError("No config"))
    def test_enable_no_config(self, mock_update):
        runner = CliRunner()
        result = runner.invoke(cli, ["categories", "enable", "skills"])
        assert result.exit_code == 1
        assert "No config" in result.output

    @patch("sccs.cli.load_config")
    def test_categories_list(self, mock_load):
        mock_config = MagicMock()
        mock_config.sync_categories = {
            "skills": MagicMock(enabled=True, description="Skills", platforms=None),
            "fish": MagicMock(enabled=False, description="Fish", platforms=["macos"]),
        }
        mock_load.return_value = mock_config

        runner = CliRunner()
        result = runner.invoke(cli, ["categories", "list", "--all"])
        assert result.exit_code == 0

    @patch("sccs.cli.load_config")
    def test_categories_list_enabled_only(self, mock_load):
        mock_config = MagicMock()
        mock_config.sync_categories = {
            "skills": MagicMock(enabled=True, description="Skills", platforms=None),
        }
        mock_load.return_value = mock_config

        runner = CliRunner()
        result = runner.invoke(cli, ["categories", "list"])
        assert result.exit_code == 0

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_categories_list_no_config(self, mock_load):
        runner = CliRunner()
        result = runner.invoke(cli, ["categories", "list"])
        assert result.exit_code == 1


class TestDiffCommand:
    """Tests for diff command."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["diff", "--help"])
        assert result.exit_code == 0
        assert "Show diff" in result.output

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_missing_config(self, mock_load):
        runner = CliRunner()
        result = runner.invoke(cli, ["diff"])
        assert result.exit_code == 1

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.SyncEngine")
    def test_diff_no_categories(self, mock_engine_cls, mock_load):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.get_enabled_categories.return_value = []
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["diff"])
        assert result.exit_code == 1
        assert "No categories" in result.output

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.SyncEngine")
    def test_diff_unknown_category(self, mock_engine_cls, mock_load):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.get_handler.return_value = None
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["diff", "-c", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.SyncEngine")
    def test_diff_no_differences(self, mock_engine_cls, mock_load):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        mock_item = MagicMock()
        mock_item.local_path = None
        mock_item.repo_path = None

        mock_handler = MagicMock()
        mock_handler.scan_items.return_value = [mock_item]

        mock_engine = MagicMock()
        mock_engine.get_handler.return_value = mock_handler
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["diff", "-c", "skills"])
        assert result.exit_code == 0
        assert "No differences" in result.output


class TestConvertCommand:
    """Tests for convert subcommand group."""

    def test_convert_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["convert", "--help"])
        assert result.exit_code == 0
        assert "Convert" in result.output

    def test_fish_to_pwsh_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["convert", "fish-to-pwsh", "--help"])
        assert result.exit_code == 0
        assert "PowerShell" in result.output

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_fish_to_pwsh_no_config(self, mock_load):
        runner = CliRunner()
        result = runner.invoke(cli, ["convert", "fish-to-pwsh"])
        assert result.exit_code == 1

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_current_platform", return_value="linux")
    def test_fish_to_pwsh_src_not_found(self, mock_platform, mock_load, tmp_path):
        mock_config = MagicMock()
        mock_config.repository.path = str(tmp_path)
        mock_load.return_value = mock_config

        nonexistent = tmp_path / "no_such_fish_dir"
        runner = CliRunner()
        result = runner.invoke(cli, ["convert", "fish-to-pwsh", "--src", str(nonexistent)])
        # Click returns exit_code 2 for path validation failures (exists=True)
        assert result.exit_code != 0

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_current_platform", return_value="linux")
    def test_fish_to_pwsh_dry_run(self, mock_platform, mock_load, tmp_path):
        mock_config = MagicMock()
        mock_config.repository.path = str(tmp_path)
        mock_load.return_value = mock_config

        fish_dir = tmp_path / ".config" / "fish"
        fish_dir.mkdir(parents=True)
        (fish_dir / "config.fish").write_text("alias ll='ls -la'\n")

        mock_report = MagicMock()
        mock_report.files_processed = 1
        mock_report.files_skipped = 0
        mock_report.aliases_converted = 1
        mock_report.functions_wrapped = 0
        mock_report.env_vars_converted = 0
        mock_report.path_lines_converted = 0
        mock_report.functions_stubbed = 0
        mock_report.fish_lines_passthrough = 0
        mock_report.warnings = []
        mock_report.written_files = []

        runner = CliRunner()
        with patch("sccs.convert.FishToPwshConverter") as mock_conv_cls:
            mock_conv = MagicMock()
            mock_conv.convert_directory.return_value = mock_report
            mock_conv_cls.return_value = mock_conv

            result = runner.invoke(
                cli,
                ["convert", "fish-to-pwsh", "--src", str(fish_dir), "--dry-run"],
            )
        assert result.exit_code == 0
        assert "Dry run" in result.output


class TestDocsCommand:
    """Tests for docs subcommand group."""

    def test_docs_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--help"])
        assert result.exit_code == 0
        assert "Documentation" in result.output or "hub README" in result.output

    def test_docs_generate_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "generate", "--help"])
        assert result.exit_code == 0
        assert "README" in result.output

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_docs_generate_no_config(self, mock_load):
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "generate"])
        assert result.exit_code == 1

    @patch("sccs.cli.load_config")
    def test_docs_generate_dry_run(self, mock_load):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        runner = CliRunner()
        with patch("sccs.docs.generator.DocsGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.render_readme.return_value = "# Hub README\n"
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(cli, ["docs", "generate", "--dry-run"])
        assert result.exit_code == 0

    @patch("sccs.cli.load_config")
    def test_docs_generate_success(self, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_config.repository.commit_prefix = "[SYNC]"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.readme_path = Path("/tmp/repo/README.md")
        mock_result.readmes_found = 3
        mock_result.categories_total = 5

        runner = CliRunner()
        with patch("sccs.docs.generator.DocsGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.generate.return_value = mock_result
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(cli, ["docs", "generate"])
        assert result.exit_code == 0

    @patch("sccs.cli.load_config")
    def test_docs_generate_failure(self, mock_load):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Template missing"

        runner = CliRunner()
        with patch("sccs.docs.generator.DocsGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.generate.return_value = mock_result
            mock_gen_cls.return_value = mock_gen

            result = runner.invoke(cli, ["docs", "generate"])
        assert result.exit_code == 1


class TestExportCommand:
    """Tests for export command."""

    def test_export_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert "Export" in result.output

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_export_no_config(self, mock_load):
        runner = CliRunner()
        result = runner.invoke(cli, ["export"])
        assert result.exit_code == 1

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.load_raw_user_data", return_value={})
    def test_export_no_items(self, mock_raw, mock_load, tmp_path):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        runner = CliRunner()
        with patch("sccs.transfer.exporter.Exporter") as mock_exp_cls:
            mock_exp = MagicMock()
            mock_exp.scan_available_items.return_value = {}
            mock_exp_cls.return_value = mock_exp

            result = runner.invoke(cli, ["export", "--all"])
        assert result.exit_code == 1
        assert "No local items" in result.output

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.load_raw_user_data", return_value={})
    def test_export_all_success(self, mock_raw, mock_load, tmp_path):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.total_items = 5
        mock_result.total_categories = 2
        mock_result.output_path = tmp_path / "export.zip"

        runner = CliRunner()
        with patch("sccs.transfer.exporter.Exporter") as mock_exp_cls:
            mock_exp = MagicMock()
            mock_exp.scan_available_items.return_value = {"skills": ["item1"]}
            mock_exp.build_selections_all.return_value = {"skills": ["item1"]}
            mock_exp.export_to_zip.return_value = mock_result
            mock_exp_cls.return_value = mock_exp

            with patch("sccs.transfer.exporter.generate_export_filename", return_value="export.zip"):
                result = runner.invoke(
                    cli,
                    ["export", "--all", "-o", str(tmp_path / "out.zip")],
                )
        assert result.exit_code == 0
        assert "Exported" in result.output


class TestImportCommand:
    """Tests for import command."""

    def test_import_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "--help"])
        assert result.exit_code == 0
        assert "Import" in result.output

    def test_import_missing_zip(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "/nonexistent/file.zip"])
        assert result.exit_code != 0

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_import_no_config(self, mock_load, tmp_path):
        zip_path = tmp_path / "export.zip"
        zip_path.write_bytes(b"PK")  # minimal placeholder

        runner = CliRunner()
        result = runner.invoke(cli, ["import", str(zip_path)])
        assert result.exit_code == 1
        assert "No config" in result.output

    @patch("sccs.cli.load_config")
    def test_import_invalid_zip(self, mock_load, tmp_path):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        zip_path = tmp_path / "bad.zip"
        zip_path.write_bytes(b"not a zip")

        runner = CliRunner()
        with patch("sccs.transfer.importer.Importer") as mock_imp_cls:
            mock_imp = MagicMock()
            mock_imp.load_manifest.side_effect = ValueError("Invalid ZIP")
            mock_imp_cls.return_value = mock_imp

            result = runner.invoke(cli, ["import", str(zip_path)])
        assert result.exit_code == 1

    @patch("sccs.cli.load_config")
    def test_import_all_success(self, mock_load, tmp_path):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        zip_path = tmp_path / "export.zip"
        zip_path.write_bytes(b"fake")

        mock_manifest = MagicMock()
        mock_manifest.created_at = "2026-06-07"
        mock_manifest.created_on = "macos"
        mock_manifest.sccs_version = "2.36.0"
        mock_manifest.total_categories = 1
        mock_manifest.total_items = 3

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.written = 3
        mock_result.skipped = 0
        mock_result.backed_up = 0
        mock_result.errors = []

        runner = CliRunner()
        with patch("sccs.transfer.importer.Importer") as mock_imp_cls:
            mock_imp = MagicMock()
            mock_imp.load_manifest.return_value = mock_manifest
            mock_imp.build_selections_all.return_value = {"skills": ["item1"]}
            mock_imp.apply.return_value = mock_result
            mock_imp_cls.return_value = mock_imp

            result = runner.invoke(cli, ["import", str(zip_path), "--all"])
        assert result.exit_code == 0
        assert "Written" in result.output or "3" in result.output


class TestIntegrationsCommand:
    """Tests for integrations subcommand group."""

    def test_integrations_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["integrations", "--help"])
        assert result.exit_code == 0
        assert "Integration" in result.output or "integration" in result.output

    def test_integrations_status_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["integrations", "status", "--help"])
        assert result.exit_code == 0

    def test_integrations_migrate_skills_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["integrations", "migrate-skills", "--help"])
        assert result.exit_code == 0
        assert "Migrate" in result.output or "skills" in result.output

    def test_integrations_trust_repo_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["integrations", "trust-repo", "--help"])
        assert result.exit_code == 0

    def test_integrations_status_no_integrations(self):
        runner = CliRunner()
        with (
            patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls,
            patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls,
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_oc_cls,
            patch("sccs.integrations.pi.PiDetector") as mock_pi_cls,
        ):
            mock_ag = MagicMock()
            mock_ag.get_info.return_value = None
            mock_ag.is_installed.return_value = False
            mock_ag_cls.return_value = mock_ag

            mock_cd = MagicMock()
            mock_cd.get_info.return_value = None
            mock_cd.is_installed.return_value = False
            mock_cd_cls.return_value = mock_cd

            mock_oc = MagicMock()
            mock_oc.get_info.return_value = None
            mock_oc.is_installed.return_value = False
            mock_oc_cls.return_value = mock_oc

            mock_pi = MagicMock()
            mock_pi.get_info.return_value = None
            mock_pi.is_installed.return_value = False
            mock_pi_cls.return_value = mock_pi

            result = runner.invoke(cli, ["integrations", "status"])
        assert result.exit_code == 0
        assert "No integrations" in result.output

    def test_integrations_migrate_skills_not_installed(self):
        runner = CliRunner()
        with patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls:
            mock_ag = MagicMock()
            mock_ag.is_installed.return_value = False
            mock_ag_cls.return_value = mock_ag

            result = runner.invoke(cli, ["integrations", "migrate-skills"])
        assert result.exit_code == 1
        assert "not installed" in result.output or "Antigravity" in result.output

    def test_integrations_migrate_skills_all_synced(self):
        runner = CliRunner()
        with patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls:
            mock_ag = MagicMock()
            mock_ag.is_installed.return_value = True
            mock_ag.get_skill_gaps.return_value = []
            mock_ag_cls.return_value = mock_ag

            result = runner.invoke(cli, ["integrations", "migrate-skills"])
        assert result.exit_code == 0
        assert "already available" in result.output

    def test_integrations_trust_repo_not_installed(self):
        runner = CliRunner()
        with patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls:
            mock_cd = MagicMock()
            mock_cd.is_installed.return_value = False
            mock_cd_cls.return_value = mock_cd

            result = runner.invoke(cli, ["integrations", "trust-repo"])
        assert result.exit_code == 1
        assert "not installed" in result.output or "Claude Desktop" in result.output

    @patch("sccs.cli.load_config", side_effect=FileNotFoundError("No config"))
    def test_integrations_trust_repo_no_config(self, mock_load):
        runner = CliRunner()
        with patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls:
            mock_cd = MagicMock()
            mock_cd.is_installed.return_value = True
            mock_cd_cls.return_value = mock_cd

            result = runner.invoke(cli, ["integrations", "trust-repo"])
        assert result.exit_code == 1

    @patch("sccs.cli.load_config")
    def test_integrations_trust_repo_already_trusted(self, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.already_trusted = True
        mock_result.repo_path = "/tmp/repo"

        runner = CliRunner()
        with patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls:
            mock_cd = MagicMock()
            mock_cd.is_installed.return_value = True
            mock_cd_cls.return_value = mock_cd

            with patch("sccs.integrations.claude_desktop.register_trusted_folder", return_value=mock_result):
                result = runner.invoke(cli, ["integrations", "trust-repo"])
        assert result.exit_code == 0
        assert "trusted" in result.output.lower()


class TestDoctorCommand:
    """Tests for doctor subcommand group."""

    def test_doctor_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "health" in result.output or "Health" in result.output

    def test_doctor_check_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "check", "--help"])
        assert result.exit_code == 0

    def test_doctor_install_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "install", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output

    def test_doctor_update_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "update", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output

    def test_doctor_optimize_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "optimize", "--help"])
        assert result.exit_code == 0
        assert "--strict" in result.output

    @patch("sccs.cli._load_doctor_config")
    @patch("sccs.cli._collect_doctor_statuses")
    def test_doctor_check_no_problems(self, mock_statuses, mock_cfg):
        mock_doctor_cfg = MagicMock()
        mock_doctor_cfg.min_node_major = 18
        mock_cfg.return_value = mock_doctor_cfg

        mock_statuses.return_value = {
            "node": MagicMock(),
            "claude_cli": MagicMock(),
            "plugins": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "bundled_skills": [],
            "browser_bundles": [],
            "status_lines": [],
            "settings_hook_violations": [],
            "settings_path": None,
        }

        runner = CliRunner()
        with (
            patch("sccs.doctor.reporter.render_doctor_report"),
            patch("sccs.doctor.reporter.has_problems", return_value=False),
        ):
            result = runner.invoke(cli, ["doctor", "check"])
        assert result.exit_code == 0

    @patch("sccs.cli._load_doctor_config")
    @patch("sccs.cli._collect_doctor_statuses")
    def test_doctor_check_with_problems(self, mock_statuses, mock_cfg):
        mock_doctor_cfg = MagicMock()
        mock_doctor_cfg.min_node_major = 18
        mock_cfg.return_value = mock_doctor_cfg

        mock_statuses.return_value = {
            "node": MagicMock(),
            "claude_cli": MagicMock(),
            "plugins": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "bundled_skills": [],
            "browser_bundles": [],
            "status_lines": [],
            "settings_hook_violations": [],
            "settings_path": None,
        }

        runner = CliRunner()
        with (
            patch("sccs.doctor.reporter.render_doctor_report"),
            patch("sccs.doctor.reporter.has_problems", return_value=True),
        ):
            result = runner.invoke(cli, ["doctor", "check"])
        assert result.exit_code == 1
        assert "install" in result.output.lower()

    @patch("sccs.cli._load_doctor_config")
    @patch("sccs.cli._collect_doctor_statuses")
    def test_doctor_install_nothing_to_do(self, mock_statuses, mock_cfg):
        mock_doctor_cfg = MagicMock()
        mock_cfg.return_value = mock_doctor_cfg

        mock_statuses.return_value = {
            "node": MagicMock(),
            "claude_cli": MagicMock(),
            "plugins": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "bundled_skills": [],
            "browser_bundles": [],
            "status_lines": [],
            "settings_hook_violations": [],
            "settings_path": None,
        }

        mock_plan = MagicMock()
        mock_plan.is_empty.return_value = True

        runner = CliRunner()
        with patch("sccs.doctor.installer.build_install_plan", return_value=mock_plan):
            result = runner.invoke(cli, ["doctor", "install"])
        assert result.exit_code == 0
        assert "Nothing to install" in result.output or "up to spec" in result.output

    @patch("sccs.cli._load_doctor_config")
    @patch("sccs.cli._collect_doctor_statuses")
    def test_doctor_update_nothing_to_do(self, mock_statuses, mock_cfg):
        mock_doctor_cfg = MagicMock()
        mock_cfg.return_value = mock_doctor_cfg

        mock_statuses.return_value = {
            "node": MagicMock(),
            "claude_cli": MagicMock(),
            "plugins": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "bundled_skills": [],
            "browser_bundles": [],
            "status_lines": [],
            "settings_hook_violations": [],
            "settings_path": None,
        }

        mock_plan = MagicMock()
        mock_plan.is_empty.return_value = True

        runner = CliRunner()
        with patch("sccs.doctor.installer.build_update_plan", return_value=mock_plan):
            result = runner.invoke(cli, ["doctor", "update"])
        assert result.exit_code == 0
        assert "Nothing to update" in result.output

    @patch("sccs.cli._load_doctor_config")
    @patch("sccs.cli._collect_doctor_statuses")
    def test_doctor_optimize_nothing_to_do(self, mock_statuses, mock_cfg):
        mock_doctor_cfg = MagicMock()
        mock_cfg.return_value = mock_doctor_cfg

        mock_statuses.return_value = {
            "node": MagicMock(),
            "claude_cli": MagicMock(),
            "plugins": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "bundled_skills": [],
            "browser_bundles": [],
            "status_lines": [],
            "settings_hook_violations": [],
            "settings_path": None,
            "foreign_plugins": [],
            "mcp_servers": [],
            "foreign_mcp_servers": [],
        }

        mock_plan = MagicMock()
        mock_plan.is_empty.return_value = True

        runner = CliRunner()
        with patch("sccs.doctor.installer.build_optimize_plan", return_value=mock_plan):
            result = runner.invoke(cli, ["doctor", "optimize"])
        assert result.exit_code == 0
        assert "optimal" in result.output or "Already" in result.output

    @patch("sccs.cli._load_doctor_config")
    @patch("sccs.cli._collect_doctor_statuses")
    def test_doctor_optimize_with_foreign(self, mock_statuses, mock_cfg):
        mock_doctor_cfg = MagicMock()
        mock_cfg.return_value = mock_doctor_cfg

        mock_statuses.return_value = {
            "node": MagicMock(),
            "claude_cli": MagicMock(),
            "plugins": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "bundled_skills": [],
            "browser_bundles": [],
            "status_lines": [],
            "settings_hook_violations": [],
            "settings_path": None,
            "foreign_plugins": [MagicMock(name="foreign-plugin")],
            "mcp_servers": [],
            "foreign_mcp_servers": [],
        }

        mock_plan = MagicMock()
        mock_plan.is_empty.return_value = True

        runner = CliRunner()
        with patch("sccs.doctor.installer.build_optimize_plan", return_value=mock_plan):
            result = runner.invoke(cli, ["doctor", "optimize"])
        assert result.exit_code == 0

    @patch("sccs.cli._load_doctor_config")
    @patch("sccs.cli._collect_doctor_statuses")
    def test_doctor_install_with_plan(self, mock_statuses, mock_cfg):
        mock_doctor_cfg = MagicMock()
        mock_cfg.return_value = mock_doctor_cfg

        mock_statuses.return_value = {
            "node": MagicMock(),
            "claude_cli": MagicMock(),
            "plugins": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "bundled_skills": [],
            "browser_bundles": [],
            "status_lines": [],
            "settings_hook_violations": [],
            "settings_path": None,
        }

        mock_plan = MagicMock()
        mock_plan.is_empty.return_value = False
        mock_plan.actions = [MagicMock()]

        mock_exec_result = MagicMock()
        mock_exec_result.failed = False

        runner = CliRunner()
        with (
            patch("sccs.doctor.installer.build_install_plan", return_value=mock_plan),
            patch("sccs.doctor.installer.execute_plan", return_value=mock_exec_result),
            patch("sccs.doctor.reporter.render_execute_result"),
        ):
            result = runner.invoke(cli, ["doctor", "install", "--yes"])
        assert result.exit_code == 0

    @patch("sccs.cli._load_doctor_config")
    @patch("sccs.cli._collect_doctor_statuses")
    def test_doctor_update_with_plan(self, mock_statuses, mock_cfg):
        mock_doctor_cfg = MagicMock()
        mock_cfg.return_value = mock_doctor_cfg

        mock_statuses.return_value = {
            "node": MagicMock(),
            "claude_cli": MagicMock(),
            "plugins": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "bundled_skills": [],
            "browser_bundles": [],
            "status_lines": [],
            "settings_hook_violations": [],
            "settings_path": None,
        }

        mock_plan = MagicMock()
        mock_plan.is_empty.return_value = False
        mock_plan.actions = [MagicMock()]

        mock_exec_result = MagicMock()
        mock_exec_result.failed = False

        runner = CliRunner()
        with (
            patch("sccs.doctor.installer.build_update_plan", return_value=mock_plan),
            patch("sccs.doctor.installer.execute_plan", return_value=mock_exec_result),
            patch("sccs.doctor.reporter.render_execute_result"),
        ):
            result = runner.invoke(cli, ["doctor", "update", "--yes"])
        assert result.exit_code == 0


class TestMigrationCheck:
    """Tests for migration-related CLI paths."""

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"up_to_date": True})
    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_raw_user_data", return_value={})
    @patch("sccs.cli.get_categories_to_offer", return_value=[])
    @patch("sccs.cli.MigrationStateManager")
    def test_sync_migration_check_skipped_with_flag(
        self, mock_mgr, mock_offer, mock_raw, mock_engine_cls, mock_remote, mock_load
    ):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 0
        mock_result.conflicts = 0
        mock_result.errors = 0
        mock_result.success = True
        mock_result.aborted = False
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["sync", "--no-migrate", "--dry-run"])
        assert result.exit_code == 0
        # Migration check should have been skipped
        mock_offer.assert_not_called()

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"up_to_date": True})
    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_raw_user_data", return_value={})
    @patch("sccs.cli.detect_new_categories", return_value=["new_cat"])
    @patch("sccs.cli.get_categories_to_offer", return_value=[])
    @patch("sccs.cli.MigrationStateManager")
    def test_sync_migration_notice_in_ci(
        self, mock_mgr, mock_offer, mock_detect, mock_raw, mock_engine_cls, mock_remote, mock_load
    ):
        """In non-TTY mode, new categories emit a notice without interaction."""
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 0
        mock_result.conflicts = 0
        mock_result.errors = 0
        mock_result.success = True
        mock_result.aborted = False
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        # CliRunner is non-TTY by default → CI branch. The check is opt-in now,
        # so the notice only appears with --migrate.
        result = runner.invoke(cli, ["sync", "--migrate", "--dry-run"])
        assert result.exit_code == 0
        assert "Notice" in result.output or "new" in result.output.lower()

    @patch("sccs.cli.load_config")
    @patch("sccs.cli.get_remote_status", return_value={"up_to_date": True})
    @patch("sccs.cli.SyncEngine")
    @patch("sccs.cli.load_raw_user_data", return_value={})
    @patch("sccs.cli.detect_new_categories", return_value=["new_cat"])
    @patch("sccs.cli.get_categories_to_offer", return_value=["new_cat"])
    @patch("sccs.cli.MigrationStateManager")
    def test_sync_default_is_silent_about_new_categories(
        self, mock_mgr, mock_offer, mock_detect, mock_raw, mock_engine_cls, mock_remote, mock_load
    ):
        """Without --migrate, sync never touches the migration check (opt-in)."""
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.synced_items = 0
        mock_result.conflicts = 0
        mock_result.errors = 0
        mock_result.success = True
        mock_result.aborted = False
        mock_result.category_results = {}

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        result = runner.invoke(cli, ["sync", "--dry-run"])
        assert result.exit_code == 0
        mock_offer.assert_not_called()
        mock_detect.assert_not_called()
        assert "Notice" not in result.output
        assert "new categories available" not in result.output.lower()


class TestIntegrationsStatusWithData:
    """Tests for integrations status with actual data."""

    def test_integrations_status_antigravity_detected(self):
        runner = CliRunner()

        mock_ag_info = MagicMock()
        mock_gap = MagicMock()
        mock_gap.name = "my-skill"
        mock_gap.needs_update = False

        with (
            patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls,
            patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls,
            patch("sccs.cli.load_config", side_effect=FileNotFoundError("no config")),
        ):
            mock_ag = MagicMock()
            mock_ag.get_info.return_value = mock_ag_info
            mock_ag.is_installed.return_value = True
            mock_ag.get_skill_gaps.return_value = [mock_gap]
            mock_ag_cls.return_value = mock_ag

            mock_cd = MagicMock()
            mock_cd.get_info.return_value = None
            mock_cd.is_installed.return_value = False
            mock_cd_cls.return_value = mock_cd

            result = runner.invoke(cli, ["integrations", "status"])

        assert result.exit_code == 0

    def test_integrations_status_claude_desktop_detected(self):
        runner = CliRunner()

        mock_cd_info = MagicMock()

        with (
            patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls,
            patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls,
            patch("sccs.cli.load_config") as mock_load,
        ):
            mock_ag = MagicMock()
            mock_ag.get_info.return_value = None
            mock_ag.is_installed.return_value = False
            mock_ag.get_skill_gaps.return_value = []
            mock_ag_cls.return_value = mock_ag

            mock_cd = MagicMock()
            mock_cd.get_info.return_value = mock_cd_info
            mock_cd.is_installed.return_value = True
            mock_cd.is_repo_trusted.return_value = True
            mock_cd_cls.return_value = mock_cd

            mock_config = MagicMock()
            mock_config.repository.path = "/tmp/repo"
            mock_load.return_value = mock_config
            result = runner.invoke(cli, ["integrations", "status"])

        assert result.exit_code == 0


class TestIntegrationsMigrateSkillsWithData:
    """Tests for integrations migrate-skills with actual skill gaps."""

    def test_migrate_skills_dry_run(self):
        runner = CliRunner()

        mock_gap = MagicMock()
        mock_gap.name = "my-skill"
        mock_gap.needs_update = False

        mock_result = MagicMock()
        mock_result.prompts_dir_created = False
        mock_result.created = ["my-skill"]
        mock_result.updated = []
        mock_result.skipped = []
        mock_result.errors = {}

        with patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls:
            mock_ag = MagicMock()
            mock_ag.is_installed.return_value = True
            mock_ag.get_skill_gaps.return_value = [mock_gap]
            mock_ag_cls.return_value = mock_ag

            with patch("sccs.integrations.antigravity.migrate_skills_to_prompts", return_value=mock_result):
                result = runner.invoke(cli, ["integrations", "migrate-skills", "--dry-run"])

        assert result.exit_code == 0
        assert "Would create" in result.output or "Dry run" in result.output

    def test_migrate_skills_verbose_output(self):
        runner = CliRunner()

        mock_gap = MagicMock()
        mock_gap.name = "my-skill"
        mock_gap.needs_update = True

        mock_result = MagicMock()
        mock_result.prompts_dir_created = True
        mock_result.created = ["new-skill"]
        mock_result.updated = ["my-skill"]
        mock_result.skipped = []
        mock_result.errors = {}

        with patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls:
            mock_ag = MagicMock()
            mock_ag.is_installed.return_value = True
            mock_ag.get_skill_gaps.return_value = [mock_gap]
            mock_ag_cls.return_value = mock_ag

            with patch("sccs.integrations.antigravity.migrate_skills_to_prompts", return_value=mock_result):
                # -v is a global flag, must come before subcommands
                result = runner.invoke(cli, ["-v", "integrations", "migrate-skills"])

        assert result.exit_code == 0
        assert "Updated" in result.output or "Created" in result.output

    def test_migrate_skills_with_errors(self):
        runner = CliRunner()

        mock_gap = MagicMock()
        mock_gap.name = "bad-skill"
        mock_gap.needs_update = False

        mock_result = MagicMock()
        mock_result.prompts_dir_created = False
        mock_result.created = []
        mock_result.updated = []
        mock_result.skipped = []
        mock_result.errors = {"bad-skill": "permission denied"}

        with patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls:
            mock_ag = MagicMock()
            mock_ag.is_installed.return_value = True
            mock_ag.get_skill_gaps.return_value = [mock_gap]
            mock_ag_cls.return_value = mock_ag

            with patch("sccs.integrations.antigravity.migrate_skills_to_prompts", return_value=mock_result):
                result = runner.invoke(cli, ["integrations", "migrate-skills"])

        assert result.exit_code == 1
        assert "Errors" in result.output or "error" in result.output.lower()

    @patch("sccs.cli.load_config")
    def test_integrations_trust_repo_success(self, mock_load):
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"
        mock_load.return_value = mock_config

        mock_result = MagicMock()
        mock_result.already_trusted = False
        mock_result.success = True
        mock_result.repo_path = "/tmp/repo"
        mock_result.error = None

        runner = CliRunner()
        with patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls:
            mock_cd = MagicMock()
            mock_cd.is_installed.return_value = True
            mock_cd_cls.return_value = mock_cd

            with patch("sccs.integrations.claude_desktop.register_trusted_folder", return_value=mock_result):
                result = runner.invoke(cli, ["integrations", "trust-repo"])

        assert result.exit_code == 0
        assert "Registered" in result.output


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_load_doctor_config_no_file(self):
        """_load_doctor_config returns default DoctorConfig when config missing."""
        from sccs.cli import _load_doctor_config

        with patch("sccs.cli.load_config", side_effect=FileNotFoundError("no config")):
            cfg = _load_doctor_config()
        # Should return a DoctorConfig instance
        assert cfg is not None

    def test_load_doctor_config_with_file(self):
        """_load_doctor_config returns config.doctor when config exists."""
        from sccs.cli import _load_doctor_config

        mock_config = MagicMock()
        mock_config.doctor = MagicMock()

        with patch("sccs.cli.load_config", return_value=mock_config):
            cfg = _load_doctor_config()
        assert cfg is mock_config.doctor

    def test_is_statusline_sync_enabled_no_config(self):
        """Returns False when config is missing."""
        from sccs.cli import _is_statusline_sync_enabled

        with patch("sccs.cli.load_config", side_effect=FileNotFoundError("no config")):
            result = _is_statusline_sync_enabled()
        assert result is False

    def test_is_statusline_sync_enabled_with_enabled_category(self):
        """Returns True when claude_statusline is enabled."""
        from sccs.cli import _is_statusline_sync_enabled

        mock_cat = MagicMock()
        mock_cat.enabled = True
        mock_config = MagicMock()
        mock_config.sync_categories = {"claude_statusline": mock_cat}

        with patch("sccs.cli.load_config", return_value=mock_config):
            result = _is_statusline_sync_enabled()
        assert result is True

    def test_is_statusline_sync_enabled_with_disabled_category(self):
        """Returns False when claude_statusline is disabled."""
        from sccs.cli import _is_statusline_sync_enabled

        mock_cat = MagicMock()
        mock_cat.enabled = False
        mock_config = MagicMock()
        mock_config.sync_categories = {"claude_statusline": mock_cat}

        with patch("sccs.cli.load_config", return_value=mock_config):
            result = _is_statusline_sync_enabled()
        assert result is False

    def test_show_integrations_inline_no_integrations(self):
        """_show_integrations_inline runs without error when no integrations."""
        from sccs.cli import _show_integrations_inline

        mock_console = MagicMock()
        mock_config = MagicMock()

        with (
            patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls,
            patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls,
        ):
            mock_ag = MagicMock()
            mock_ag.get_info.return_value = None
            mock_ag.get_skill_gaps.return_value = []
            mock_ag_cls.return_value = mock_ag

            mock_cd = MagicMock()
            mock_cd.get_info.return_value = None
            mock_cd.is_repo_trusted.return_value = False
            mock_cd_cls.return_value = mock_cd

            # Should not raise
            _show_integrations_inline(mock_console, mock_config)

        mock_console.print_integrations_status.assert_called_once()

    def test_show_integrations_inline_with_claude_desktop(self):
        """_show_integrations_inline checks repo trust when Claude Desktop detected."""
        from sccs.cli import _show_integrations_inline

        mock_console = MagicMock()
        mock_config = MagicMock()
        mock_config.repository.path = "/tmp/repo"

        with (
            patch("sccs.integrations.detectors.AntigravityDetector") as mock_ag_cls,
            patch("sccs.integrations.detectors.ClaudeDesktopDetector") as mock_cd_cls,
        ):
            mock_ag = MagicMock()
            mock_ag.get_info.return_value = None
            mock_ag.get_skill_gaps.return_value = []
            mock_ag_cls.return_value = mock_ag

            mock_cd = MagicMock()
            mock_cd_info = MagicMock()
            mock_cd.get_info.return_value = mock_cd_info
            mock_cd.is_repo_trusted.return_value = True
            mock_cd_cls.return_value = mock_cd

            _show_integrations_inline(mock_console, mock_config)

        mock_cd.is_repo_trusted.assert_called_once()
        mock_console.print_integrations_status.assert_called_once()

    def test_run_migration_check_off_by_default(self):
        """_run_migration_check returns immediately when migrate=False (opt-in)."""
        from sccs.cli import _run_migration_check

        mock_console = MagicMock()
        with patch("sccs.cli.load_raw_user_data") as mock_raw:
            _run_migration_check(mock_console, migrate=False)
            mock_raw.assert_not_called()

    def test_run_migration_check_ci_no_new_categories(self):
        """With migrate=True in CI (non-TTY), no output when nothing is new."""
        from sccs.cli import _run_migration_check

        mock_console = MagicMock()
        with (
            patch("sccs.cli.load_raw_user_data", return_value={}),
            patch("sccs.cli.MigrationStateManager"),
            patch("sccs.cli.detect_new_categories", return_value=[]),
        ):
            _run_migration_check(mock_console, migrate=True)
        mock_console.print_info.assert_not_called()


class _CapturingConsole:
    """Minimal stand-in for sccs.output.Console that records printed text."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args, **kwargs) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def reset_platform_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the once-per-process hint guard so each test sees a fresh state."""
    monkeypatch.setattr(cli_module, "_PLATFORM_HINT_PRINTED", False)


def _build_fish_macos_config(temp_home, mock_repo) -> SccsConfig:
    """Config with two macos-only fish categories that should be skipped on linux."""
    raw = {
        "repository": {"path": str(mock_repo)},
        "sync_categories": {
            "fish_config_macos": {
                "enabled": True,
                "description": "Fish macOS",
                "local_path": str(temp_home / ".config" / "fish" / "conf.d"),
                "repo_path": ".config/fish/conf.d",
                "sync_mode": "bidirectional",
                "item_type": "file",
                "platforms": ["macos"],
            },
            "fish_functions_macos": {
                "enabled": True,
                "description": "Fish functions macOS",
                "local_path": str(temp_home / ".config" / "fish" / "functions" / "macos"),
                "repo_path": ".config/fish/functions/macos",
                "sync_mode": "bidirectional",
                "item_type": "file",
                "platforms": ["macos"],
            },
        },
    }
    return SccsConfig.model_validate(raw)


class TestPlatformHint:
    """Regression tests for the platform-skipped-categories hint wording."""

    def test_linux_with_fish_uses_platform_specific_wording(
        self, monkeypatch, reset_platform_hint, temp_home, mock_repo
    ):
        """Fish installed on Linux + macos-only fish categories → 'plattformspezifisch', not 'nicht verfügbar'."""
        monkeypatch.setattr("sccs.cli.get_current_platform", lambda: "linux")
        monkeypatch.setattr("sccs.utils.platform.get_current_platform", lambda: "linux")
        monkeypatch.setattr("sccs.cli.is_shell_available", lambda shell: shell == "fish")

        cfg = _build_fish_macos_config(temp_home, mock_repo)
        console = _CapturingConsole()

        _print_platform_hint(console, cfg)

        assert "plattformspezifisch übersprungen" in console.text
        assert "Fish nicht verfügbar" not in console.text
        assert "fish_config_macos" in console.text
        assert "fish_functions_macos" in console.text

    def test_linux_without_fish_uses_unavailable_wording(self, monkeypatch, reset_platform_hint, temp_home, mock_repo):
        """Fish missing on Linux → keep 'Fish nicht verfügbar' wording."""
        monkeypatch.setattr("sccs.cli.get_current_platform", lambda: "linux")
        monkeypatch.setattr("sccs.utils.platform.get_current_platform", lambda: "linux")
        monkeypatch.setattr("sccs.cli.is_shell_available", lambda shell: False)

        cfg = _build_fish_macos_config(temp_home, mock_repo)
        console = _CapturingConsole()

        _print_platform_hint(console, cfg)

        assert "Fish nicht verfügbar" in console.text
        assert "plattformspezifisch" not in console.text

    def test_no_skipped_categories_emits_nothing(self, monkeypatch, reset_platform_hint, temp_home, mock_repo):
        """When no enabled category is filtered out, the hint stays silent."""
        # macos current platform → macos-only categories match → nothing skipped
        monkeypatch.setattr("sccs.cli.get_current_platform", lambda: "macos")
        monkeypatch.setattr("sccs.utils.platform.get_current_platform", lambda: "macos")
        monkeypatch.setattr("sccs.cli.is_shell_available", lambda shell: True)

        cfg = _build_fish_macos_config(temp_home, mock_repo)
        console = _CapturingConsole()

        _print_platform_hint(console, cfg)

        assert console.text == ""


class TestOpenCodeCli:
    """Tests for the `sccs integrations opencode` sub-group."""

    def test_group_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["integrations", "opencode", "--help"])
        assert result.exit_code == 0
        assert "OpenCode" in result.output

    def test_status_not_installed(self):
        runner = CliRunner()
        with patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls:
            mock_cls.return_value.get_info.return_value = None
            result = runner.invoke(cli, ["integrations", "opencode", "status"])
        assert result.exit_code == 0
        assert "not installed" in result.output

    def test_status_installed(self):
        runner = CliRunner()
        info = MagicMock(config_dir="/x/opencode")
        with patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls:
            inst = mock_cls.return_value
            inst.get_info.return_value = info
            inst.get_agent_gaps.return_value = []
            inst.get_command_gaps.return_value = []
            inst.get_mcp_status.return_value = {"missing": []}
            result = runner.invoke(cli, ["integrations", "opencode", "status"])
        assert result.exit_code == 0
        assert "OpenCode" in result.output

    def test_export_agents_not_installed(self):
        runner = CliRunner()
        with patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls:
            mock_cls.return_value.is_installed.return_value = False
            result = runner.invoke(cli, ["integrations", "opencode", "export-agents"])
        assert result.exit_code == 1
        assert "not installed" in result.output

    def test_export_agents_up_to_date(self):
        runner = CliRunner()
        with patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls:
            inst = mock_cls.return_value
            inst.is_installed.return_value = True
            inst.get_agent_gaps.return_value = []
            result = runner.invoke(cli, ["integrations", "opencode", "export-agents"])
        assert result.exit_code == 0
        assert "up to date" in result.output

    def test_export_agents_dry_run(self):
        runner = CliRunner()
        gap = MagicMock(name="a1")
        result_obj = MagicMock(created=["a1"], updated=[], skipped=[], errors={}, warnings={}, target_dir_created=False)
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.integrations.opencode.convert_agents_to_opencode", return_value=result_obj),
        ):
            inst = mock_cls.return_value
            inst.is_installed.return_value = True
            inst.get_agent_gaps.return_value = [gap]
            result = runner.invoke(cli, ["integrations", "opencode", "export-agents", "--dry-run"])
        assert result.exit_code == 0
        assert "Would create" in result.output

    def test_export_commands_dry_run(self):
        runner = CliRunner()
        gap = MagicMock()
        result_obj = MagicMock(created=["c1"], updated=[], skipped=[], errors={}, warnings={}, target_dir_created=False)
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.integrations.opencode.convert_commands_to_opencode", return_value=result_obj),
        ):
            inst = mock_cls.return_value
            inst.is_installed.return_value = True
            inst.get_command_gaps.return_value = [gap]
            result = runner.invoke(cli, ["integrations", "opencode", "export-commands", "--dry-run"])
        assert result.exit_code == 0
        assert "Would create" in result.output

    def test_resolve_excludes_no_config_uses_doctor_defaults(self):
        from sccs import cli as cli_mod

        with patch("sccs.cli.load_config", side_effect=FileNotFoundError):
            patterns = cli_mod._resolve_opencode_excludes()
        # Bundled doctor defaults manage the gsd-* artefacts out of the box.
        assert "gsd-*" in patterns

    def test_resolve_excludes_appends_user_exclude(self):
        from sccs import cli as cli_mod

        fake_config = MagicMock()
        fake_config.doctor = MagicMock()
        fake_config.opencode.exclude = ["mine-*"]
        with (
            patch("sccs.cli.load_config", return_value=fake_config),
            patch("sccs.doctor.managed.get_doctor_managed_excludes", return_value=["gsd-*"]),
        ):
            patterns = cli_mod._resolve_opencode_excludes()
        assert patterns == ["gsd-*", "mine-*"]

    def test_export_agents_applies_default_excludes(self):
        runner = CliRunner()
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.cli._resolve_opencode_excludes", return_value=["gsd-*"]),
            patch("sccs.cli._resolve_opencode_model_map", return_value={}),
        ):
            inst = mock_cls.return_value
            inst.is_installed.return_value = True
            inst.get_agent_gaps.return_value = []
            runner.invoke(cli, ["integrations", "opencode", "export-agents"])
        # Default run passes the resolved excludes to gap detection.
        assert inst.get_agent_gaps.call_args.kwargs["exclude_patterns"] == ["gsd-*"]

    def test_export_agents_explicit_selection_overrides_excludes(self):
        runner = CliRunner()
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.cli._resolve_opencode_excludes", return_value=["gsd-*"]),
            patch("sccs.cli._resolve_opencode_model_map", return_value={}),
        ):
            inst = mock_cls.return_value
            inst.is_installed.return_value = True
            inst.get_agent_gaps.return_value = []
            runner.invoke(cli, ["integrations", "opencode", "export-agents", "-a", "gsd-debugger"])
        # Explicit -a bypasses the default exclude so the named agent exports.
        assert inst.get_agent_gaps.call_args.kwargs["exclude_patterns"] is None

    def test_merge_mcp_success(self):
        runner = CliRunner()
        result_obj = MagicMock(
            success=True, added=["context7"], updated=[], already_present=[], warnings={}, error=None
        )
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.integrations.opencode.merge_mcp_to_opencode", return_value=result_obj),
        ):
            mock_cls.return_value.is_installed.return_value = True
            result = runner.invoke(cli, ["integrations", "opencode", "merge-mcp"])
        assert result.exit_code == 0
        assert "context7" in result.output

    def test_merge_mcp_failure(self):
        runner = CliRunner()
        result_obj = MagicMock(success=False, error="boom")
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.integrations.opencode.merge_mcp_to_opencode", return_value=result_obj),
        ):
            mock_cls.return_value.is_installed.return_value = True
            result = runner.invoke(cli, ["integrations", "opencode", "merge-mcp"])
        assert result.exit_code == 1
        assert "boom" in result.output

    def test_map_models_not_installed(self):
        runner = CliRunner()
        with patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls:
            mock_cls.return_value.is_installed.return_value = False
            result = runner.invoke(cli, ["integrations", "opencode", "map-models"])
        assert result.exit_code == 1
        assert "not installed" in result.output

    def test_map_models_no_tokens(self):
        runner = CliRunner()
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.cli._collect_cc_model_tokens", return_value=[]),
        ):
            mock_cls.return_value.is_installed.return_value = True
            result = runner.invoke(cli, ["integrations", "opencode", "map-models"])
        assert result.exit_code == 0
        assert "nothing to map" in result.output

    def test_map_models_no_opencode_models(self):
        runner = CliRunner()
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.cli._collect_cc_model_tokens", return_value=["sonnet"]),
            patch("sccs.integrations.opencode.list_opencode_models", return_value=[]),
        ):
            mock_cls.return_value.is_installed.return_value = True
            result = runner.invoke(cli, ["integrations", "opencode", "map-models"])
        assert result.exit_code == 1
        assert "authenticate a provider" in result.output

    def test_map_models_dry_run(self):
        runner = CliRunner()
        select_mock = MagicMock()
        select_mock.ask.return_value = "anthropic/claude-sonnet-4-5"
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.cli._collect_cc_model_tokens", return_value=["sonnet"]),
            patch("sccs.integrations.opencode.list_opencode_models", return_value=["anthropic/claude-sonnet-4-5"]),
            patch("sccs.cli.load_config", side_effect=FileNotFoundError),
            patch("questionary.select", return_value=select_mock),
            patch("sccs.config.loader.save_opencode_model_map") as mock_save,
        ):
            mock_cls.return_value.is_installed.return_value = True
            result = runner.invoke(cli, ["integrations", "opencode", "map-models", "--dry-run"])
        assert result.exit_code == 0
        assert "sonnet" in result.output
        mock_save.assert_not_called()

    def test_map_models_persists(self):
        runner = CliRunner()
        select_mock = MagicMock()
        select_mock.ask.return_value = "anthropic/claude-sonnet-4-5"
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.cli._collect_cc_model_tokens", return_value=["sonnet"]),
            patch("sccs.integrations.opencode.list_opencode_models", return_value=["anthropic/claude-sonnet-4-5"]),
            patch("sccs.cli.load_config", side_effect=FileNotFoundError),
            patch("questionary.select", return_value=select_mock),
            patch("sccs.config.loader.save_opencode_model_map") as mock_save,
        ):
            mock_cls.return_value.is_installed.return_value = True
            result = runner.invoke(cli, ["integrations", "opencode", "map-models"])
        assert result.exit_code == 0
        mock_save.assert_called_once_with({"sonnet": "anthropic/claude-sonnet-4-5"})

    def test_map_models_cancelled(self):
        runner = CliRunner()
        select_mock = MagicMock()
        select_mock.ask.return_value = None  # user hit Ctrl-C
        with (
            patch("sccs.integrations.opencode.OpenCodeDetector") as mock_cls,
            patch("sccs.cli._collect_cc_model_tokens", return_value=["sonnet"]),
            patch("sccs.integrations.opencode.list_opencode_models", return_value=["anthropic/claude-sonnet-4-5"]),
            patch("sccs.cli.load_config", side_effect=FileNotFoundError),
            patch("questionary.select", return_value=select_mock),
            patch("sccs.config.loader.save_opencode_model_map") as mock_save,
        ):
            mock_cls.return_value.is_installed.return_value = True
            result = runner.invoke(cli, ["integrations", "opencode", "map-models"])
        assert result.exit_code == 0
        assert "Cancelled" in result.output
        mock_save.assert_not_called()
