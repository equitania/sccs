# Tests for SCCS Memory CLI Commands

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from sccs.cli import cli
from sccs.memory.item import MemoryCategory
from sccs.memory.manager import MemoryManager


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_memory_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def ctx_obj(temp_memory_dir: Path) -> dict:
    """Click context object with memory_dir override."""
    from sccs.output.console import Console as SccsConsole

    return {
        "console": SccsConsole(),
        "verbose": False,
        "memory_dir": str(temp_memory_dir),
    }


class TestMemoryAdd:
    def test_add_basic(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "add", "My Test Item", "--content", "Test body"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0, result.output
        assert "my-test-item" in result.output or "Created" in result.output

        # Verify file was created
        item_dir = temp_memory_dir / "my-test-item"
        assert item_dir.exists()
        assert (item_dir / "MEMORY.md").exists()

    def test_add_with_tags_and_priority(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "add", "Tagged Item", "-t", "tag1", "-t", "tag2", "--priority", "4"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0, result.output

        manager = MemoryManager(temp_memory_dir)
        items = manager.load_all()
        assert len(items) == 1
        assert items[0].tags == ["tag1", "tag2"]
        assert items[0].priority == 4

    def test_add_with_from_file(self, runner: CliRunner, temp_memory_dir: Path):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Content from file\n\nThis is the body.")
            file_path = f.name

        result = runner.invoke(
            cli,
            ["memory", "add", "From File", "--from-file", file_path],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0, result.output

        manager = MemoryManager(temp_memory_dir)
        item = manager.load("from-file")
        assert "Content from file" in item.body


class TestMemoryList:
    def test_list_empty(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "list"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "No memory items" in result.output

    def test_list_with_items(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("Item Alpha", priority=3)
        manager.add("Item Beta", priority=1)

        result = runner.invoke(
            cli,
            ["memory", "list"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "item-alpha" in result.output
        assert "item-beta" in result.output

    def test_list_filter_by_project(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("V18 Item", project="v18")
        manager.add("Flowise Item", project="flowise")

        result = runner.invoke(
            cli,
            ["memory", "list", "--project", "v18"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "v18-item" in result.output
        assert "flowise-item" not in result.output

    def test_list_filter_by_min_priority(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("High", priority=4)
        manager.add("Low", priority=1)

        result = runner.invoke(
            cli,
            ["memory", "list", "--min-priority", "3"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "high" in result.output
        assert "low" not in result.output


class TestMemoryShow:
    def test_show_item(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("Show Test", body="The content here")

        result = runner.invoke(
            cli,
            ["memory", "show", "show-test"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "Show Test" in result.output or "show-test" in result.output

    def test_show_raw(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("Raw Test", body="Raw content")

        result = runner.invoke(
            cli,
            ["memory", "show", "raw-test", "--raw"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "---" in result.output  # frontmatter delimiters

    def test_show_not_found(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "show", "does-not-exist"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 1


class TestMemoryDelete:
    def test_delete_with_force(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("Delete Me")

        result = runner.invoke(
            cli,
            ["memory", "delete", "delete-me", "--force"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert not manager.exists("delete-me")

    def test_delete_not_found(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "delete", "ghost", "--force"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 1


class TestMemorySearch:
    def test_search_finds_results(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("Architecture Doc", body="PostgreSQL database decision")
        manager.add("Unrelated Item", body="Something else entirely")

        result = runner.invoke(
            cli,
            ["memory", "search", "PostgreSQL"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "architecture-doc" in result.output

    def test_search_no_results(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "search", "xyzzy-not-found"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "No results" in result.output


class TestMemoryExport:
    def test_export_claude_block(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("Decision", body="We chose X", category=MemoryCategory.DECISION)

        result = runner.invoke(
            cli,
            ["memory", "export"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "<memory>" in result.output
        assert "</memory>" in result.output

    def test_export_json_format(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("JSON Item", body="JSON body")

        result = runner.invoke(
            cli,
            ["memory", "export", "--format", "json"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 1

    def test_export_empty(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "export"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "No memory items" in result.output

    def test_export_to_file(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("Export Item", body="body")

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            out_path = f.name

        result = runner.invoke(
            cli,
            ["memory", "export", "--out", out_path],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert Path(out_path).read_text()


class TestMemoryExpire:
    def test_expire_no_expired(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        from datetime import timedelta

        future = __import__("datetime").datetime.now() + timedelta(days=30)
        manager.add("Not expired", expires=future)

        result = runner.invoke(
            cli,
            ["memory", "expire"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "No expired" in result.output

    def test_expire_archives_items(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        from datetime import timedelta

        past = __import__("datetime").datetime.now() - timedelta(days=1)
        manager.add("Old item", expires=past)

        result = runner.invoke(
            cli,
            ["memory", "expire"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "1" in result.output


class TestMemoryStats:
    def test_stats_empty(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "stats"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "0" in result.output

    def test_stats_with_items(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("D", category=MemoryCategory.DECISION)
        manager.add("L", category=MemoryCategory.LEARNING)

        result = runner.invoke(
            cli,
            ["memory", "stats"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0
        assert "2" in result.output


class TestMemoryUpdate:
    def test_update_extend(self, runner: CliRunner, temp_memory_dir: Path):
        manager = MemoryManager(temp_memory_dir)
        manager.add("Update Me", body="Original")

        result = runner.invoke(
            cli,
            ["memory", "update", "update-me", "--extend", "Appended"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 0

        item = manager.load("update-me")
        assert "Original" in item.body
        assert "Appended" in item.body

    def test_update_not_found(self, runner: CliRunner, temp_memory_dir: Path):
        result = runner.invoke(
            cli,
            ["memory", "update", "ghost", "--extend", "text"],
            obj={"console": None, "verbose": False, "memory_dir": str(temp_memory_dir)},
        )
        assert result.exit_code == 1
