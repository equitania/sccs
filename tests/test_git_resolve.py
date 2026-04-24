# Tests for sccs.git.resolve
# Interactive divergence resolution strategy + execution.

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sccs.git.resolve import (
    DivergenceStrategy,
    apply_divergence_strategy,
    prompt_divergence_strategy,
)


@pytest.fixture
def mock_console() -> MagicMock:
    """Minimal Console stub with the print_* API used by apply_divergence_strategy."""
    console = MagicMock()
    console.print_info = MagicMock()
    console.print_error = MagicMock()
    console.print_warning = MagicMock()
    console.print_success = MagicMock()
    return console


class TestPromptDivergenceStrategy:
    """prompt_divergence_strategy — interactive questionary.select behaviour."""

    def test_non_interactive_returns_abort(self):
        """CI/pipe context (no TTY) must auto-abort so prompts don't hang."""
        strategy = prompt_divergence_strategy(ahead=1, behind=1, remote="origin", interactive=False)
        assert strategy is DivergenceStrategy.ABORT

    @patch("sccs.git.resolve.questionary.select")
    def test_rebase_selected(self, mock_select):
        mock_select.return_value.ask.return_value = "rebase"
        strategy = prompt_divergence_strategy(ahead=2, behind=1, remote="origin", interactive=True)
        assert strategy is DivergenceStrategy.REBASE

    @patch("sccs.git.resolve.questionary.select")
    def test_merge_selected(self, mock_select):
        mock_select.return_value.ask.return_value = "merge"
        strategy = prompt_divergence_strategy(ahead=1, behind=3, remote="origin", interactive=True)
        assert strategy is DivergenceStrategy.MERGE

    @patch("sccs.git.resolve.questionary.select")
    def test_force_push_selected(self, mock_select):
        mock_select.return_value.ask.return_value = "force"
        strategy = prompt_divergence_strategy(ahead=1, behind=1, remote="origin", interactive=True)
        assert strategy is DivergenceStrategy.FORCE_PUSH

    @patch("sccs.git.resolve.questionary.select")
    def test_ctrl_c_returns_abort(self, mock_select):
        """questionary returns None on Ctrl-C / EOF — must be treated as ABORT."""
        mock_select.return_value.ask.return_value = None
        strategy = prompt_divergence_strategy(ahead=1, behind=1, remote="origin", interactive=True)
        assert strategy is DivergenceStrategy.ABORT


class TestApplyDivergenceStrategy:
    """apply_divergence_strategy — dispatches to pull/pull --rebase/force_push."""

    def test_abort_leaves_repo_unchanged(self, mock_console):
        result = apply_divergence_strategy(DivergenceStrategy.ABORT, Path("/repo"), mock_console, remote="origin")
        assert result is False
        mock_console.print_warning.assert_called_once()

    @patch("sccs.git.resolve.pull", return_value=True)
    def test_rebase_success(self, mock_pull, mock_console):
        result = apply_divergence_strategy(DivergenceStrategy.REBASE, Path("/repo"), mock_console, remote="origin")
        assert result is True
        mock_pull.assert_called_once_with(Path("/repo"), rebase=True)
        mock_console.print_success.assert_called_once()

    @patch("sccs.git.resolve.pull", return_value=False)
    def test_rebase_failure(self, mock_pull, mock_console):
        result = apply_divergence_strategy(DivergenceStrategy.REBASE, Path("/repo"), mock_console, remote="origin")
        assert result is False
        mock_console.print_error.assert_called_once()

    @patch("sccs.git.resolve.pull", return_value=True)
    def test_merge_success(self, mock_pull, mock_console):
        result = apply_divergence_strategy(DivergenceStrategy.MERGE, Path("/repo"), mock_console, remote="origin")
        assert result is True
        # merge is pull() without rebase
        mock_pull.assert_called_once_with(Path("/repo"))

    @patch("sccs.git.resolve.pull", return_value=False)
    def test_merge_failure(self, mock_pull, mock_console):
        result = apply_divergence_strategy(DivergenceStrategy.MERGE, Path("/repo"), mock_console, remote="origin")
        assert result is False
        mock_console.print_error.assert_called_once()

    @patch("sccs.git.resolve.force_push", return_value=True)
    def test_force_push_success(self, mock_force, mock_console):
        result = apply_divergence_strategy(
            DivergenceStrategy.FORCE_PUSH,
            Path("/repo"),
            mock_console,
            remote="upstream",
            branch="main",
        )
        assert result is True
        mock_force.assert_called_once_with(Path("/repo"), remote="upstream", branch="main")

    @patch("sccs.git.resolve.force_push", return_value=False)
    def test_force_push_rejected_by_lease(self, mock_force, mock_console):
        """--force-with-lease refuses when remote has advanced since fetch."""
        result = apply_divergence_strategy(DivergenceStrategy.FORCE_PUSH, Path("/repo"), mock_console, remote="origin")
        assert result is False
        mock_console.print_error.assert_called_once()
