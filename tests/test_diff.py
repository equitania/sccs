# Tests for sccs.output.diff
# Diff generation and display

from rich.console import Console as RichConsole

from sccs.config.schema import ItemType
from sccs.output.diff import (
    DiffResult,
    format_diff_summary,
    generate_diff,
    read_content,
    show_diff,
)
from sccs.sync.item import SyncItem


class TestReadContent:
    """Tests for read_content function."""

    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read_content(f) == "hello world"

    def test_read_nonexistent_file(self, tmp_path):
        f = tmp_path / "missing.txt"
        assert read_content(f) is None

    def test_read_directory_with_marker(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text("# My Skill", encoding="utf-8")
        assert read_content(d) == "# My Skill"

    def test_read_directory_without_marker(self, tmp_path):
        d = tmp_path / "plain"
        d.mkdir()
        result = read_content(d)
        assert "[Directory:" in result

    def test_read_binary_file(self, tmp_path):
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe")
        result = read_content(f)
        assert "[Binary file]" in result

    def test_read_directory_readme_fallback(self, tmp_path):
        d = tmp_path / "project"
        d.mkdir()
        (d / "README.md").write_text("# README", encoding="utf-8")
        assert read_content(d) == "# README"


class TestGenerateDiff:
    """Tests for generate_diff function."""

    def test_identical_content(self):
        result = generate_diff("hello", "hello")
        assert result == []

    def test_different_content(self):
        result = generate_diff("new content", "old content")
        assert len(result) > 0
        assert any("+" in line for line in result)
        assert any("-" in line for line in result)

    def test_none_local(self):
        result = generate_diff(None, "repo content")
        assert len(result) > 0

    def test_none_repo(self):
        result = generate_diff("local content", None)
        assert len(result) > 0

    def test_both_none(self):
        result = generate_diff(None, None)
        assert result == []

    def test_multiline_diff(self):
        local = "line1\nline2\nline3 changed\n"
        repo = "line1\nline2\nline3\n"
        result = generate_diff(local, repo)
        assert len(result) > 0

    def test_context_lines(self):
        local = "a\nb\nc\nd\ne\nf changed\n"
        repo = "a\nb\nc\nd\ne\nf\n"
        result_1 = generate_diff(local, repo, context_lines=1)
        result_5 = generate_diff(local, repo, context_lines=5)
        # More context = more lines
        assert len(result_5) >= len(result_1)


class TestShowDiff:
    """Tests for show_diff function."""

    def _make_item(self, tmp_path, local_content=None, repo_content=None):
        local_path = tmp_path / "local" / "test.md"
        repo_path = tmp_path / "repo" / "test.md"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        repo_path.parent.mkdir(parents=True, exist_ok=True)

        if local_content is not None:
            local_path.write_text(local_content, encoding="utf-8")
        if repo_content is not None:
            repo_path.write_text(repo_content, encoding="utf-8")

        return SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=local_path,
            repo_path=repo_path,
        )

    def test_diff_with_changes(self, tmp_path):
        item = self._make_item(tmp_path, "local version", "repo version")
        console = RichConsole(file=open("/dev/null", "w"), no_color=True)
        result = show_diff(item, console=console)
        assert result.has_diff is True
        assert result.local_exists is True
        assert result.repo_exists is True

    def test_diff_no_changes(self, tmp_path):
        item = self._make_item(tmp_path, "same", "same")
        console = RichConsole(file=open("/dev/null", "w"), no_color=True)
        result = show_diff(item, console=console)
        assert result.has_diff is False

    def test_diff_only_local(self, tmp_path):
        item = self._make_item(tmp_path, "local only", None)
        console = RichConsole(file=open("/dev/null", "w"), no_color=True)
        result = show_diff(item, console=console)
        assert result.has_diff is True
        assert result.repo_exists is False

    def test_diff_only_repo(self, tmp_path):
        item = self._make_item(tmp_path, None, "repo only")
        console = RichConsole(file=open("/dev/null", "w"), no_color=True)
        result = show_diff(item, console=console)
        assert result.has_diff is True
        assert result.local_exists is False

    def test_diff_neither_exists(self, tmp_path):
        item = self._make_item(tmp_path, None, None)
        console = RichConsole(file=open("/dev/null", "w"), no_color=True)
        result = show_diff(item, console=console)
        assert result.has_diff is False
        assert result.error is not None


class TestDiffResult:
    """Tests for DiffResult dataclass."""

    def test_default_diff_lines(self):
        result = DiffResult(item_name="test", has_diff=False, local_exists=True, repo_exists=True)
        assert result.diff_lines == []

    def test_with_diff_lines(self):
        result = DiffResult(
            item_name="test",
            has_diff=True,
            local_exists=True,
            repo_exists=True,
            diff_lines=["+added", "-removed"],
        )
        assert len(result.diff_lines) == 2


class TestFormatDiffSummary:
    """Tests for format_diff_summary function."""

    def test_error_result(self):
        result = DiffResult(item_name="x", has_diff=False, local_exists=False, repo_exists=False, error="fail")
        assert "Error" in format_diff_summary(result)

    def test_no_diff(self):
        result = DiffResult(item_name="x", has_diff=False, local_exists=True, repo_exists=True)
        assert "No differences" in format_diff_summary(result)

    def test_only_in_repo(self):
        result = DiffResult(item_name="x", has_diff=True, local_exists=False, repo_exists=True)
        assert "Only in repo" in format_diff_summary(result)

    def test_only_in_local(self):
        result = DiffResult(item_name="x", has_diff=True, local_exists=True, repo_exists=False)
        assert "Only in local" in format_diff_summary(result)

    def test_additions_and_deletions(self):
        result = DiffResult(
            item_name="x",
            has_diff=True,
            local_exists=True,
            repo_exists=True,
            diff_lines=["--- a", "+++ b", "+added1", "+added2", "-removed1"],
        )
        summary = format_diff_summary(result)
        assert "+2" in summary
        assert "-1" in summary

    def test_no_diff_lines_changed(self):
        result = DiffResult(
            item_name="x",
            has_diff=True,
            local_exists=True,
            repo_exists=True,
            diff_lines=["--- a", "+++ b"],
        )
        assert "Changed" in format_diff_summary(result)
