# Tests for sccs.cli
# CLI commands using Click testing

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from sccs.cli import cli


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
