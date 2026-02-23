# Tests for SCCS Memory Module
# Tests for MemoryItem, MemoryFilter, MemoryManager

from __future__ import annotations

import tempfile
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sccs.memory.filter import MemoryFilter
from sccs.memory.item import MemoryCategory, MemoryItem
from sccs.memory.manager import MemoryManager, _slugify

# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────


@pytest.fixture
def temp_memory_dir() -> Generator[Path, None, None]:
    """Temporary directory for memory items."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def manager(temp_memory_dir: Path) -> MemoryManager:
    return MemoryManager(memory_dir=temp_memory_dir)


# ─────────────────────────────────────────────
# MemoryItem Tests
# ─────────────────────────────────────────────


class TestMemoryItem:
    def test_basic_creation(self):
        item = MemoryItem(id="test-id", title="Test Title")
        assert item.id == "test-id"
        assert item.title == "Test Title"
        assert item.priority == 2
        assert item.category == MemoryCategory.CONTEXT

    def test_markdown_roundtrip(self):
        item = MemoryItem(
            id="my-decision",
            title="My Decision",
            body="We chose PostgreSQL over MySQL.",
            category=MemoryCategory.DECISION,
            project="v18",
            tags=["database", "architecture"],
            priority=4,
        )
        md = item.to_markdown()

        restored = MemoryItem.from_markdown(md)
        assert restored.id == "my-decision"
        assert restored.title == "My Decision"
        assert restored.body == "We chose PostgreSQL over MySQL."
        assert restored.category == MemoryCategory.DECISION
        assert restored.project == "v18"
        assert restored.tags == ["database", "architecture"]
        assert restored.priority == 4

    def test_frontmatter_contains_required_fields(self):
        item = MemoryItem(id="abc", title="Test")
        md = item.to_markdown()
        assert "id: abc" in md
        assert "title: Test" in md
        assert "priority:" in md
        assert "created:" in md
        assert "updated:" in md

    def test_expires_field(self):
        future = datetime.now() + timedelta(days=30)
        item = MemoryItem(id="x", title="X", expires=future)
        assert not item.is_expired

        past = datetime.now() - timedelta(days=1)
        item2 = MemoryItem(id="y", title="Y", expires=past)
        assert item2.is_expired

    def test_expires_none(self):
        item = MemoryItem(id="z", title="Z")
        assert item.expires is None
        assert not item.is_expired

    def test_save_and_load(self, temp_memory_dir: Path):
        item = MemoryItem(id="save-test", title="Save Test", body="Hello")
        path = item.save_to_dir(temp_memory_dir)

        assert path.exists()
        loaded = MemoryItem.from_file(path)
        assert loaded.id == "save-test"
        assert loaded.title == "Save Test"
        assert loaded.body == "Hello"

    def test_from_markdown_missing_frontmatter(self):
        with pytest.raises(ValueError, match="frontmatter"):
            MemoryItem.from_markdown("# No frontmatter\n\nJust body.")

    def test_all_categories(self):
        for cat in MemoryCategory:
            item = MemoryItem(id=cat.value, title="T", category=cat)
            md = item.to_markdown()
            restored = MemoryItem.from_markdown(md)
            assert restored.category == cat


# ─────────────────────────────────────────────
# MemoryFilter Tests
# ─────────────────────────────────────────────


class TestMemoryFilter:
    def _items(self) -> list[MemoryItem]:
        return [
            MemoryItem(id="a", title="A", project="v18", tags=["odoo"], priority=5),
            MemoryItem(id="b", title="B", project="flowise", tags=["ai"], priority=2),
            MemoryItem(id="c", title="C", project="v18", tags=["odoo", "db"], priority=3),
            MemoryItem(id="d", title="D", priority=1),
        ]

    def test_no_filter(self):
        f = MemoryFilter()
        result = f.apply(self._items())
        assert len(result) == 4

    def test_project_filter(self):
        f = MemoryFilter(project="v18")
        result = f.apply(self._items())
        assert all(i.project == "v18" for i in result)
        assert len(result) == 2

    def test_min_priority_filter(self):
        f = MemoryFilter(min_priority=3)
        result = f.apply(self._items())
        assert all(i.priority >= 3 for i in result)
        assert len(result) == 2

    def test_tag_filter(self):
        f = MemoryFilter(tags=["odoo"])
        result = f.apply(self._items())
        assert len(result) == 2
        assert all("odoo" in i.tags for i in result)

    def test_expired_excluded_by_default(self):
        past = datetime.now() - timedelta(days=1)
        items = [
            MemoryItem(id="live", title="Live"),
            MemoryItem(id="expired", title="Expired", expires=past),
        ]
        f = MemoryFilter()
        result = f.apply(items)
        assert len(result) == 1
        assert result[0].id == "live"

    def test_expired_included_when_flag_set(self):
        past = datetime.now() - timedelta(days=1)
        items = [
            MemoryItem(id="live", title="Live"),
            MemoryItem(id="expired", title="Expired", expires=past),
        ]
        f = MemoryFilter(include_expired=True)
        result = f.apply(items)
        assert len(result) == 2

    def test_category_filter(self):
        items = [
            MemoryItem(id="d", title="D", category=MemoryCategory.DECISION),
            MemoryItem(id="l", title="L", category=MemoryCategory.LEARNING),
        ]
        f = MemoryFilter(category="decision")
        result = f.apply(items)
        assert len(result) == 1
        assert result[0].category == MemoryCategory.DECISION

    def test_sorting_by_priority(self):
        items = [
            MemoryItem(id="low", title="Low", priority=1),
            MemoryItem(id="high", title="High", priority=5),
            MemoryItem(id="mid", title="Mid", priority=3),
        ]
        f = MemoryFilter()
        result = f.apply(items)
        priorities = [i.priority for i in result]
        assert priorities == sorted(priorities, reverse=True)


# ─────────────────────────────────────────────
# MemoryManager Tests
# ─────────────────────────────────────────────


class TestMemoryManager:
    def test_add_and_load(self, manager: MemoryManager):
        item = manager.add("Test Item", body="Some content", priority=3)
        assert item.id
        assert item.title == "Test Item"
        assert item.body == "Some content"

        loaded = manager.load(item.id)
        assert loaded.id == item.id
        assert loaded.title == "Test Item"

    def test_list_slugs_empty(self, manager: MemoryManager):
        assert manager.list_slugs() == []

    def test_list_slugs_after_add(self, manager: MemoryManager):
        manager.add("Item One")
        manager.add("Item Two")
        slugs = manager.list_slugs()
        assert len(slugs) == 2

    def test_load_nonexistent_raises(self, manager: MemoryManager):
        with pytest.raises(FileNotFoundError):
            manager.load("does-not-exist")

    def test_update_body(self, manager: MemoryManager):
        item = manager.add("Update Test", body="Original")
        manager.update(item.id, body="New body")
        loaded = manager.load(item.id)
        assert loaded.body == "New body"

    def test_update_extend_body(self, manager: MemoryManager):
        item = manager.add("Extend Test", body="Part 1")
        manager.update(item.id, extend_body="Part 2")
        loaded = manager.load(item.id)
        assert "Part 1" in loaded.body
        assert "Part 2" in loaded.body

    def test_update_bump_version(self, manager: MemoryManager):
        item = manager.add("Version Test")
        assert item.version == 1
        updated = manager.update(item.id, bump_version=True)
        assert updated.version == 2

    def test_delete_archives_item(self, manager: MemoryManager):
        item = manager.add("Delete Test")
        assert manager.exists(item.id)

        result = manager.delete(item.id)
        assert result is True
        assert not manager.exists(item.id)

        # Archived item should exist in _archive
        archive_path = manager.memory_dir / "_archive" / item.id / "MEMORY.md"
        assert archive_path.exists()

    def test_delete_nonexistent(self, manager: MemoryManager):
        assert manager.delete("nonexistent") is False

    def test_search(self, manager: MemoryManager):
        manager.add("Odoo Architecture", body="We use PostgreSQL for data storage")
        manager.add("Flowise Setup", body="AI workflow automation")

        results = manager.search("PostgreSQL")
        assert len(results) == 1
        assert "Odoo Architecture" in results[0].title

    def test_search_by_project(self, manager: MemoryManager):
        manager.add("Item A", project="v18")
        manager.add("Item B", project="flowise")

        results = manager.search("Item", project="v18")
        assert len(results) == 1

    def test_expire_items(self, manager: MemoryManager):
        past = datetime.now() - timedelta(days=1)
        future = datetime.now() + timedelta(days=30)

        manager.add("Live Item", expires=future)
        manager.add("Expired Item", expires=past)

        expired = manager.expire_items()
        assert len(expired) == 1
        assert expired[0].title == "Expired Item"
        assert manager.exists("live-item")

    def test_stats_empty(self, manager: MemoryManager):
        stats = manager.stats()
        assert stats["total"] == 0
        assert stats["expired"] == 0

    def test_stats_with_items(self, manager: MemoryManager):
        manager.add("D", category=MemoryCategory.DECISION, project="v18")
        manager.add("L", category=MemoryCategory.LEARNING, project="v18")
        manager.add("C", category=MemoryCategory.CONTEXT)

        stats = manager.stats()
        assert stats["total"] == 3
        assert stats["by_category"]["decision"] == 1
        assert stats["by_category"]["learning"] == 1
        assert stats["by_project"]["v18"] == 2

    def test_unique_slug_on_collision(self, manager: MemoryManager):
        item1 = manager.add("Same Title")
        item2 = manager.add("Same Title")
        assert item1.id != item2.id
        assert item2.id.startswith("same-title-")

    def test_load_all(self, manager: MemoryManager):
        manager.add("One")
        manager.add("Two")
        manager.add("Three")
        items = manager.load_all()
        assert len(items) == 3


# ─────────────────────────────────────────────
# Slugify Tests
# ─────────────────────────────────────────────


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        result = _slugify("Odoo 18: Architecture & Decisions!")
        assert " " not in result
        assert ":" not in result
        assert "&" not in result
        assert "!" not in result

    def test_max_length(self):
        long_title = "A" * 100
        result = _slugify(long_title)
        assert len(result) <= 60

    def test_empty(self):
        assert _slugify("") == ""


# ─────────────────────────────────────────────
# Bridge Tests
# ─────────────────────────────────────────────


class TestClaudeAiBridge:
    def test_export_context_block_empty(self):
        from sccs.memory.bridge import ClaudeAiBridge

        result = ClaudeAiBridge.export_to_context_block([])
        assert result == ""

    def test_export_context_block_format(self):
        from sccs.memory.bridge import ClaudeAiBridge

        items = [
            MemoryItem(
                id="test", title="My Decision", body="Body text", category=MemoryCategory.DECISION, project="v18"
            ),
        ]
        result = ClaudeAiBridge.export_to_context_block(items)
        assert "<memory>" in result
        assert "</memory>" in result
        assert "My Decision" in result
        assert "decision" in result

    def test_export_json(self):

        from sccs.memory.bridge import ClaudeAiBridge

        items = [MemoryItem(id="j", title="JSON Test", body="body")]
        result = ClaudeAiBridge.export_to_json(items)
        assert result["count"] == 1
        assert result["items"][0]["id"] == "j"
        assert "exported_at" in result

    def test_export_context_block_respects_max_chars(self):
        from sccs.memory.bridge import ClaudeAiBridge

        # Create item with very long body
        items = [
            MemoryItem(id=f"item-{i}", title=f"Item {i}", body="X" * 5000, priority=3)
            for i in range(5)
        ]
        result = ClaudeAiBridge.export_to_context_block(items, max_chars=1000)
        # Should truncate
        assert "truncated" in result.lower() or len(result) < 50000


# ─────────────────────────────────────────────
# Config Integration Tests
# ─────────────────────────────────────────────


class TestMemoryConfigIntegration:
    def test_memory_config_in_sccs_config(self):
        from sccs.config.defaults import DEFAULT_CONFIG
        from sccs.config.schema import SccsConfig

        cfg = SccsConfig.model_validate(DEFAULT_CONFIG)
        assert hasattr(cfg, "memory_config")
        assert cfg.memory_config.max_context_chars == 8000
        assert cfg.memory_config.auto_expire is False
        assert cfg.memory_config.min_priority == 1

    def test_claude_memory_category_in_defaults(self):
        from sccs.config.defaults import DEFAULT_CONFIG
        from sccs.config.schema import SccsConfig

        cfg = SccsConfig.model_validate(DEFAULT_CONFIG)
        assert "claude_memory" in cfg.sync_categories
        cat = cfg.sync_categories["claude_memory"]
        assert cat.enabled is False
        assert cat.item_marker == "MEMORY.md"
        assert "bidirectional" in cat.sync_mode.value

    def test_memory_category_not_in_enabled(self):
        from sccs.config.defaults import DEFAULT_CONFIG
        from sccs.config.schema import SccsConfig

        cfg = SccsConfig.model_validate(DEFAULT_CONFIG)
        enabled = cfg.get_enabled_categories()
        assert "claude_memory" not in enabled
