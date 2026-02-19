# Tests for sccs.git.operations
# Git command execution and repository management

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sccs.git.operations import (
    GitError,
    _run_git,
    clone_repo,
    commit,
    fetch,
    get_changed_files,
    get_current_branch,
    get_remote_status,
    get_repo_root,
    has_uncommitted_changes,
    init_repo,
    is_git_repo,
    pull,
    push,
    stage_all,
    stage_files,
)


class TestGitError:
    """Tests for GitError exception."""

    def test_basic_error(self):
        err = GitError("test message")
        assert err.message == "test message"
        assert err.returncode == 1
        assert err.stderr == ""
        assert str(err) == "test message"

    def test_error_with_details(self):
        err = GitError("failed", returncode=128, stderr="fatal: not a repo")
        assert err.returncode == 128
        assert err.stderr == "fatal: not a repo"


class TestRunGit:
    """Tests for _run_git helper."""

    @patch("sccs.git.operations.subprocess.run")
    def test_successful_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "status"], returncode=0, stdout="clean", stderr=""
        )
        result = _run_git("status")
        assert result.returncode == 0
        assert result.stdout == "clean"

    @patch("sccs.git.operations.subprocess.run")
    def test_failed_command_raises(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "bad"], returncode=1, stdout="", stderr="error"
        )
        with pytest.raises(GitError) as exc_info:
            _run_git("bad")
        assert exc_info.value.returncode == 1

    @patch("sccs.git.operations.subprocess.run")
    def test_failed_command_no_check(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "bad"], returncode=1, stdout="", stderr="error"
        )
        result = _run_git("bad", check=False)
        assert result.returncode == 1

    @patch("sccs.git.operations.subprocess.run", side_effect=FileNotFoundError)
    def test_git_not_found(self, mock_run):
        with pytest.raises(GitError, match="git command not found"):
            _run_git("status")

    @patch("sccs.git.operations.subprocess.run")
    def test_cwd_passed(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=["git", "status"], returncode=0, stdout="", stderr="")
        _run_git("status", cwd=Path("/tmp"))
        mock_run.assert_called_once_with(
            ["git", "status"], cwd=Path("/tmp"), check=False, capture_output=True, text=True
        )


class TestGetRepoRoot:
    """Tests for get_repo_root."""

    @patch("sccs.git.operations._run_git")
    def test_returns_path(self, mock_git):
        mock_git.return_value = MagicMock(stdout="/home/user/repo\n")
        result = get_repo_root()
        assert result == Path("/home/user/repo")

    @patch("sccs.git.operations._run_git", side_effect=GitError("not a repo"))
    def test_returns_none_outside_repo(self, mock_git):
        assert get_repo_root() is None


class TestIsGitRepo:
    """Tests for is_git_repo."""

    @patch("sccs.git.operations.get_repo_root", return_value=Path("/repo"))
    def test_true_in_repo(self, mock_root):
        assert is_git_repo() is True

    @patch("sccs.git.operations.get_repo_root", return_value=None)
    def test_false_outside_repo(self, mock_root):
        assert is_git_repo() is False


class TestGitStatus:
    """Tests for git_status and has_uncommitted_changes."""

    @patch("sccs.git.operations._run_git")
    def test_has_uncommitted_changes_true(self, mock_git):
        mock_git.return_value = MagicMock(stdout="M  file.py\n")
        assert has_uncommitted_changes() is True

    @patch("sccs.git.operations._run_git")
    def test_has_uncommitted_changes_false(self, mock_git):
        mock_git.return_value = MagicMock(stdout="")
        assert has_uncommitted_changes() is False


class TestGetCurrentBranch:
    """Tests for get_current_branch."""

    @patch("sccs.git.operations._run_git")
    def test_returns_branch(self, mock_git):
        mock_git.return_value = MagicMock(stdout="main\n")
        assert get_current_branch() == "main"

    @patch("sccs.git.operations._run_git")
    def test_detached_head(self, mock_git):
        mock_git.return_value = MagicMock(stdout="HEAD\n")
        assert get_current_branch() is None

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_error_returns_none(self, mock_git):
        assert get_current_branch() is None


class TestStageFiles:
    """Tests for stage_files."""

    @patch("sccs.git.operations._run_git")
    def test_stage_files(self, mock_git):
        assert stage_files([Path("a.py"), Path("b.py")]) is True

    def test_stage_empty_list(self):
        assert stage_files([]) is True

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_stage_failure(self, mock_git):
        assert stage_files([Path("a.py")]) is False


class TestStageAll:
    """Tests for stage_all."""

    @patch("sccs.git.operations._run_git")
    def test_success(self, mock_git):
        assert stage_all() is True

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_failure(self, mock_git):
        assert stage_all() is False


class TestCommit:
    """Tests for commit."""

    @patch("sccs.git.operations._run_git")
    def test_success(self, mock_git):
        mock_git.return_value = MagicMock(stdout="abc123\n")
        result = commit("test message")
        assert result == "abc123"

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_failure(self, mock_git):
        assert commit("test") is None

    def test_invalid_author(self):
        with pytest.raises(GitError, match="Invalid author format"):
            commit("msg", author="invalid")

    @patch("sccs.git.operations._run_git")
    def test_valid_author(self, mock_git):
        mock_git.return_value = MagicMock(stdout="abc123\n")
        commit("msg", author="Name <email@test.com>")
        # Verify --author was passed
        first_call_args = mock_git.call_args_list[0][0]
        assert "--author" in first_call_args


class TestPush:
    """Tests for push."""

    @patch("sccs.git.operations._run_git")
    def test_success(self, mock_git):
        assert push() is True

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_failure(self, mock_git):
        assert push() is False

    @patch("sccs.git.operations._run_git")
    def test_with_branch_and_upstream(self, mock_git):
        push(remote="upstream", branch="main", set_upstream=True)
        args = mock_git.call_args[0]
        assert "-u" in args
        assert "upstream" in args
        assert "main" in args


class TestPull:
    """Tests for pull."""

    @patch("sccs.git.operations._run_git")
    def test_success(self, mock_git):
        assert pull() is True

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_failure(self, mock_git):
        assert pull() is False

    @patch("sccs.git.operations._run_git")
    def test_with_rebase(self, mock_git):
        pull(rebase=True)
        args = mock_git.call_args[0]
        assert "--rebase" in args


class TestFetch:
    """Tests for fetch."""

    @patch("sccs.git.operations._run_git")
    def test_success(self, mock_git):
        assert fetch() is True

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_failure(self, mock_git):
        assert fetch() is False


class TestGetRemoteStatus:
    """Tests for get_remote_status."""

    @patch("sccs.git.operations._run_git")
    @patch("sccs.git.operations.fetch", return_value=True)
    @patch("sccs.git.operations.get_current_branch", return_value="main")
    def test_up_to_date(self, mock_branch, mock_fetch, mock_git):
        mock_git.return_value = MagicMock(stdout="0\t0\n")
        result = get_remote_status()
        assert result["up_to_date"] is True
        assert result["ahead"] == 0
        assert result["behind"] == 0

    @patch("sccs.git.operations._run_git")
    @patch("sccs.git.operations.fetch", return_value=True)
    @patch("sccs.git.operations.get_current_branch", return_value="main")
    def test_behind(self, mock_branch, mock_fetch, mock_git):
        mock_git.return_value = MagicMock(stdout="0\t3\n")
        result = get_remote_status()
        assert result["behind"] == 3
        assert result["diverged"] is False

    @patch("sccs.git.operations._run_git")
    @patch("sccs.git.operations.fetch", return_value=True)
    @patch("sccs.git.operations.get_current_branch", return_value="main")
    def test_diverged(self, mock_branch, mock_fetch, mock_git):
        mock_git.return_value = MagicMock(stdout="2\t3\n")
        result = get_remote_status()
        assert result["diverged"] is True

    @patch("sccs.git.operations.fetch", return_value=True)
    @patch("sccs.git.operations.get_current_branch", return_value=None)
    def test_no_branch(self, mock_branch, mock_fetch):
        result = get_remote_status()
        assert "error" in result

    @patch("sccs.git.operations.fetch", side_effect=GitError("network error"))
    def test_fetch_error(self, mock_fetch):
        result = get_remote_status()
        assert "error" in result


class TestGetChangedFiles:
    """Tests for get_changed_files."""

    @patch("sccs.git.operations.get_repo_root", return_value=Path("/repo"))
    @patch("sccs.git.operations._run_git")
    def test_staged_files(self, mock_git, mock_root):
        mock_git.return_value = MagicMock(stdout="M  file.py\nA  new.py\n")
        files = get_changed_files(staged=True)
        assert Path("/repo/file.py") in files
        assert Path("/repo/new.py") in files

    @patch("sccs.git.operations.get_repo_root", return_value=Path("/repo"))
    @patch("sccs.git.operations._run_git")
    def test_untracked_files(self, mock_git, mock_root):
        mock_git.return_value = MagicMock(stdout="?? untracked.py\n")
        files = get_changed_files(untracked=True)
        assert Path("/repo/untracked.py") in files

    @patch("sccs.git.operations.get_repo_root", return_value=Path("/repo"))
    @patch("sccs.git.operations._run_git")
    def test_renamed_files(self, mock_git, mock_root):
        mock_git.return_value = MagicMock(stdout="R  old.py -> new.py\n")
        files = get_changed_files(staged=True)
        assert Path("/repo/new.py") in files

    @patch("sccs.git.operations.get_repo_root", return_value=Path("/repo"))
    @patch("sccs.git.operations._run_git")
    def test_empty_status(self, mock_git, mock_root):
        mock_git.return_value = MagicMock(stdout="")
        files = get_changed_files(staged=True, unstaged=True, untracked=True)
        assert files == []


class TestInitRepo:
    """Tests for init_repo."""

    @patch("sccs.git.operations._run_git")
    def test_success(self, mock_git, temp_dir):
        target = temp_dir / "new_repo"
        assert init_repo(target) is True
        assert target.exists()

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_failure(self, mock_git, temp_dir):
        target = temp_dir / "fail_repo"
        assert init_repo(target) is False


class TestCloneRepo:
    """Tests for clone_repo."""

    @patch("sccs.git.operations._run_git")
    def test_basic_clone(self, mock_git):
        assert clone_repo("https://example.com/repo.git", Path("/tmp/dest")) is True

    @patch("sccs.git.operations._run_git")
    def test_clone_with_options(self, mock_git):
        clone_repo("https://example.com/repo.git", Path("/tmp/dest"), branch="main", depth=1)
        args = mock_git.call_args[0]
        assert "-b" in args
        assert "main" in args
        assert "--depth" in args
        assert "1" in args

    @patch("sccs.git.operations._run_git", side_effect=GitError("error"))
    def test_failure(self, mock_git):
        assert clone_repo("https://example.com/repo.git", Path("/tmp/dest")) is False
