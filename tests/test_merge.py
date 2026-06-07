# SCCS Merge Tests
# Tests for interactive merge functionality

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console as RichConsole

from sccs.config.schema import ItemType
from sccs.output.merge import (
    DiffHunk,
    MergeResult,
    _detect_syntax,
    _show_file_metadata,
    edit_in_editor,
    interactive_merge,
    prompt_hunk_resolution,
    show_hunk,
    split_into_hunks,
)
from sccs.sync.actions import ActionType, SyncAction
from sccs.sync.item import SyncItem

# Resolve real binaries instead of assuming /bin paths — `true` lives in
# /usr/bin on macOS, /bin on many Linuxes. shutil.which() finds whichever.
_TRUE = shutil.which("true")
_FALSE = shutil.which("false")
_CAT = shutil.which("cat")


def _scripted_console(inputs: Iterable[str]) -> RichConsole:
    """A recording Rich console whose .input() replays a scripted sequence."""
    console = RichConsole(record=True, width=120)
    it = iter(inputs)
    console.input = lambda *a, **k: next(it)  # type: ignore[method-assign]
    return console


def _conflict_action(local: Path, repo: Path) -> SyncAction:
    item = SyncItem(
        name=local.name,
        category="test",
        item_type=ItemType.FILE,
        local_path=local,
        repo_path=repo,
    )
    return SyncAction(item=item, action_type=ActionType.CONFLICT)


class TestSplitIntoHunks:
    """Tests for split_into_hunks()."""

    def test_no_diff(self):
        """Identical content should produce only equal hunks."""
        content = "line 1\nline 2\nline 3\n"
        hunks = split_into_hunks(content, content)
        change_hunks = [h for h in hunks if h.is_change]
        assert len(change_hunks) == 0

    def test_single_change(self):
        """One changed line should produce one change hunk."""
        local = "line 1\nline 2 modified\nline 3\n"
        repo = "line 1\nline 2\nline 3\n"
        hunks = split_into_hunks(local, repo)
        change_hunks = [h for h in hunks if h.is_change]
        assert len(change_hunks) == 1

    def test_multiple_changes(self):
        """Multiple separated changes should produce multiple hunks."""
        local = "AAA\nline 2\nline 3\nline 4\nBBB\n"
        repo = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        hunks = split_into_hunks(local, repo)
        change_hunks = [h for h in hunks if h.is_change]
        assert len(change_hunks) >= 2

    def test_addition_only(self):
        """Added lines should create an insertion hunk."""
        local = "line 1\nnew line\nline 2\n"
        repo = "line 1\nline 2\n"
        hunks = split_into_hunks(local, repo)
        change_hunks = [h for h in hunks if h.is_change]
        assert len(change_hunks) >= 1

    def test_deletion_only(self):
        """Removed lines should create a deletion hunk."""
        local = "line 1\nline 3\n"
        repo = "line 1\nline 2\nline 3\n"
        hunks = split_into_hunks(local, repo)
        change_hunks = [h for h in hunks if h.is_change]
        assert len(change_hunks) >= 1

    def test_empty_local(self):
        """Empty local content should be all deletions from repo perspective."""
        hunks = split_into_hunks("", "line 1\nline 2\n")
        change_hunks = [h for h in hunks if h.is_change]
        assert len(change_hunks) >= 1

    def test_empty_repo(self):
        """Empty repo content should be all additions from local perspective."""
        hunks = split_into_hunks("line 1\nline 2\n", "")
        change_hunks = [h for h in hunks if h.is_change]
        assert len(change_hunks) >= 1


class TestDiffHunkProperties:
    """Tests for DiffHunk dataclass properties."""

    def test_is_addition(self):
        hunk = DiffHunk(
            tag="insert",
            local_lines=["new\n"],
            repo_lines=[],
            local_start=0,
            local_end=1,
            repo_start=0,
            repo_end=0,
        )
        assert hunk.is_addition is True
        assert hunk.is_deletion is False
        assert hunk.is_modification is False
        assert hunk.is_change is True

    def test_is_deletion(self):
        hunk = DiffHunk(
            tag="delete",
            local_lines=[],
            repo_lines=["old\n"],
            local_start=0,
            local_end=0,
            repo_start=0,
            repo_end=1,
        )
        assert hunk.is_deletion is True
        assert hunk.is_addition is False
        assert hunk.is_change is True

    def test_is_modification(self):
        hunk = DiffHunk(
            tag="replace",
            local_lines=["new\n"],
            repo_lines=["old\n"],
            local_start=0,
            local_end=1,
            repo_start=0,
            repo_end=1,
        )
        assert hunk.is_modification is True
        assert hunk.is_change is True

    def test_is_equal(self):
        hunk = DiffHunk(
            tag="equal",
            local_lines=["same\n"],
            repo_lines=["same\n"],
            local_start=0,
            local_end=1,
            repo_start=0,
            repo_end=1,
        )
        assert hunk.is_equal is True
        assert hunk.is_change is False


class TestMergeResult:
    """Tests for MergeResult dataclass."""

    def test_all_local(self):
        """All local choices should be trackable."""
        result = MergeResult(
            merged_content="local content",
            hunks_total=3,
            hunks_local=3,
        )
        assert result.hunks_local == 3
        assert result.is_complete is True

    def test_all_repo(self):
        """All repo choices should be trackable."""
        result = MergeResult(
            merged_content="repo content",
            hunks_total=3,
            hunks_repo=3,
        )
        assert result.hunks_repo == 3
        assert result.is_complete is True

    def test_both(self):
        """Both hunks should be trackable."""
        result = MergeResult(
            merged_content="combined",
            hunks_total=2,
            hunks_both=2,
        )
        assert result.hunks_both == 2
        assert result.is_complete is True

    def test_aborted(self):
        """Aborted merge should be flagged."""
        result = MergeResult(aborted=True)
        assert result.aborted is True
        assert result.is_complete is False

    def test_empty_not_complete(self):
        """Empty merged content should not be complete."""
        result = MergeResult()
        assert result.is_complete is False


class TestDetectSyntax:
    """Tests for _detect_syntax()."""

    def test_fish(self):
        assert _detect_syntax("config.fish") == "bash"

    def test_markdown(self):
        assert _detect_syntax("README.md") == "markdown"

    def test_yaml(self):
        assert _detect_syntax("config.yaml") == "yaml"

    def test_yml(self):
        assert _detect_syntax("config.yml") == "yaml"

    def test_python(self):
        assert _detect_syntax("script.py") == "python"

    def test_unknown(self):
        assert _detect_syntax("file.xyz") == "text"

    def test_no_extension(self):
        assert _detect_syntax("Makefile") == "text"


class TestEditInEditor:
    """Tests for edit_in_editor()."""

    @patch.dict("os.environ", {"EDITOR": "", "VISUAL": ""}, clear=False)
    @patch("sccs.output.merge.subprocess.run", side_effect=FileNotFoundError)
    def test_no_editor_returns_none(self, mock_run):
        """No editor available should return None."""
        result = edit_in_editor("test content")
        assert result is None

    @pytest.mark.skipif(not _TRUE, reason="no `true` binary available")
    def test_editor_success_unchanged(self, monkeypatch):
        """A no-op editor (exit 0, no write) returns the original content."""
        monkeypatch.setenv("EDITOR", _TRUE)
        assert edit_in_editor("original content") == "original content"

    @pytest.mark.skipif(not _FALSE, reason="no `false` binary available")
    def test_editor_nonzero_returncode_returns_none(self, monkeypatch):
        """A non-zero editor exit code yields None (edit discarded)."""
        monkeypatch.setenv("EDITOR", _FALSE)
        assert edit_in_editor("content") is None

    @pytest.mark.skipif(not _CAT, reason="no resolvable editor binary available")
    def test_editor_writes_modified_content(self, monkeypatch):
        """When the editor mutates the temp file, the new content is returned."""

        def fake_run(cmd, *a, **k):
            # cmd == [editor, temp_path]; rewrite the buffer as a real editor would.
            Path(cmd[1]).write_text("EDITED", encoding="utf-8")

            class _R:
                returncode = 0

            return _R()

        monkeypatch.setenv("EDITOR", _CAT)  # any which-resolvable binary; run is mocked
        monkeypatch.setattr("sccs.output.merge.subprocess.run", fake_run)
        assert edit_in_editor("before") == "EDITED"

    @pytest.mark.skipif(not _CAT or sys.platform == "win32", reason="POSIX perms only")
    def test_editor_buffer_is_private(self, monkeypatch):
        """The merge buffer (may hold tokens) must be chmod'd 0600 before editing."""
        seen = {}

        def fake_run(cmd, *a, **k):
            import os
            import stat

            seen["mode"] = stat.S_IMODE(os.stat(cmd[1]).st_mode)

            class _R:
                returncode = 0

            return _R()

        monkeypatch.setenv("EDITOR", _CAT)
        monkeypatch.setattr("sccs.output.merge.subprocess.run", fake_run)
        edit_in_editor("secret")
        assert seen["mode"] == 0o600


class TestShowHunk:
    """Tests for show_hunk() rendering."""

    def test_renders_modification(self):
        console = RichConsole(record=True, width=120)
        hunk = DiffHunk(
            tag="replace",
            local_lines=["new\n"],
            repo_lines=["old\n"],
            local_start=0,
            local_end=1,
            repo_start=0,
            repo_end=1,
        )
        show_hunk(hunk, 1, 3, console, syntax="text")
        out = console.export_text()
        assert "Hunk 1/3" in out
        assert "modified" in out

    def test_renders_addition_and_deletion_titles(self):
        console = RichConsole(record=True, width=120)
        add = DiffHunk("insert", ["a\n"], [], 0, 1, 0, 0)
        rem = DiffHunk("delete", [], ["b\n"], 0, 0, 0, 1)
        show_hunk(add, 1, 2, console)
        show_hunk(rem, 2, 2, console)
        out = console.export_text()
        assert "added in local" in out
        assert "removed in local" in out


class TestPromptHunkResolution:
    """Tests for prompt_hunk_resolution()."""

    @pytest.mark.parametrize(
        "typed,expected",
        [
            ("l", "local"),
            ("local", "local"),
            ("r", "repo"),
            ("b", "both"),
            ("e", "edit"),
            ("s", "skip"),
        ],
    )
    def test_valid_choices(self, typed, expected):
        console = _scripted_console([typed])
        assert prompt_hunk_resolution(console) == expected

    def test_invalid_then_valid(self):
        console = _scripted_console(["x", "?", "r"])
        assert prompt_hunk_resolution(console) == "repo"
        assert "Invalid choice" in console.export_text()


class TestShowFileMetadata:
    """Tests for _show_file_metadata()."""

    def test_renders_sizes_and_newer_indicator(self, tmp_path):
        local = tmp_path / "f.txt"
        repo = tmp_path / "repo_f.txt"
        repo.write_text("short", encoding="utf-8")
        local.write_text("a much longer local body", encoding="utf-8")
        # Make local strictly newer than repo.
        import os

        os.utime(repo, (1_000_000, 1_000_000))
        os.utime(local, (2_000_000, 2_000_000))

        console = RichConsole(record=True, width=120)
        _show_file_metadata(_conflict_action(local, repo), console)
        out = console.export_text()
        assert "File Comparison" in out
        assert "bytes" in out
        assert "LOCAL" in out  # newer indicator points at local


class TestInteractiveMerge:
    """End-to-end tests for interactive_merge() with scripted input."""

    def _make_files(self, tmp_path: Path) -> tuple[Path, Path]:
        local = tmp_path / "item.txt"
        repo = tmp_path / "repo" / "item.txt"
        repo.parent.mkdir(parents=True, exist_ok=True)
        local.write_text("line 1\nLOCAL\nline 3\n", encoding="utf-8")
        repo.write_text("line 1\nREPO\nline 3\n", encoding="utf-8")
        return local, repo

    def test_no_differences_short_circuits(self, tmp_path):
        local = tmp_path / "a.txt"
        repo = tmp_path / "b.txt"
        local.write_text("same\n", encoding="utf-8")
        repo.write_text("same\n", encoding="utf-8")
        console = RichConsole(record=True, width=120)
        result = interactive_merge(_conflict_action(local, repo), console)
        assert result.is_complete
        assert result.merged_content == "same\n"
        assert "No differences" in console.export_text()

    def test_choose_local_and_accept_writes_both(self, tmp_path):
        local, repo = self._make_files(tmp_path)
        console = _scripted_console(["l", "y"])  # one hunk -> local, then accept
        result = interactive_merge(_conflict_action(local, repo), console)
        assert result.is_complete
        assert result.hunks_local == 1
        assert "LOCAL" in local.read_text(encoding="utf-8")
        assert "LOCAL" in repo.read_text(encoding="utf-8")

    def test_choose_repo(self, tmp_path):
        local, repo = self._make_files(tmp_path)
        console = _scripted_console(["r", "y"])
        result = interactive_merge(_conflict_action(local, repo), console)
        assert result.hunks_repo == 1
        assert "REPO" in local.read_text(encoding="utf-8")

    def test_choose_both(self, tmp_path):
        local, repo = self._make_files(tmp_path)
        console = _scripted_console(["b", "y"])
        result = interactive_merge(_conflict_action(local, repo), console)
        assert result.hunks_both == 1
        body = local.read_text(encoding="utf-8")
        assert "REPO" in body and "LOCAL" in body

    def test_abort_on_reject_does_not_write(self, tmp_path):
        local, repo = self._make_files(tmp_path)
        original = repo.read_text(encoding="utf-8")
        console = _scripted_console(["l", "n"])  # choose local, then reject
        result = interactive_merge(_conflict_action(local, repo), console)
        assert result.aborted
        assert not result.is_complete
        assert repo.read_text(encoding="utf-8") == original  # untouched

    def test_edit_choice_uses_editor_output(self, tmp_path, monkeypatch):
        local, repo = self._make_files(tmp_path)
        monkeypatch.setattr("sccs.output.merge.edit_in_editor", lambda content, suffix=".txt": "MERGED\n")
        console = _scripted_console(["e", "y"])
        result = interactive_merge(_conflict_action(local, repo), console)
        assert result.hunks_edited == 1
        assert "MERGED" in local.read_text(encoding="utf-8")

    def test_edit_failure_falls_back_to_local(self, tmp_path, monkeypatch):
        local, repo = self._make_files(tmp_path)
        monkeypatch.setattr("sccs.output.merge.edit_in_editor", lambda content, suffix=".txt": None)
        console = _scripted_console(["e", "y"])
        result = interactive_merge(_conflict_action(local, repo), console)
        assert result.hunks_local == 1
        assert "Editor failed" in console.export_text()
