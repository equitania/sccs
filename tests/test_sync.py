# SCCS Sync Tests
# Tests for synchronization engine and components

from pathlib import Path

from sccs.config.schema import ItemType, SccsConfig, SyncCategory
from sccs.sync.actions import ActionType, SyncAction, determine_action, execute_action
from sccs.sync.engine import SyncEngine
from sccs.sync.item import SyncItem, scan_items_for_category
from sccs.sync.state import StateManager, SyncState


class TestSyncItem:
    """Tests for SyncItem."""

    def test_item_creation(self):
        """Test basic item creation."""
        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
        )
        assert item.name == "test.md"
        assert item.category == "test"
        assert not item.exists_local
        assert not item.exists_repo

    def test_item_exists_local(self, temp_dir: Path):
        """Test exists_local property."""
        test_file = temp_dir / "test.md"
        test_file.write_text("test", encoding="utf-8")

        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=test_file,
        )
        assert item.exists_local is True

    def test_item_get_hash(self, temp_dir: Path):
        """Test content hash generation."""
        test_file = temp_dir / "test.md"
        test_file.write_text("test content", encoding="utf-8")

        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=test_file,
        )
        hash_value = item.get_hash("local")
        assert hash_value is not None
        assert len(hash_value) == 64  # SHA256 hex length


class TestScanItems:
    """Tests for item scanning."""

    def test_scan_file_items(self, mock_claude_dir: Path, mock_repo: Path):
        """Test scanning file items."""
        category = SyncCategory(
            local_path=str(mock_claude_dir / "commands"),
            repo_path=".claude/commands",
            item_type=ItemType.FILE,
            item_pattern="*.md",
            include=["*"],
            exclude=[],
        )

        items = scan_items_for_category(
            category_name="claude_commands",
            category=category,
            local_base=mock_claude_dir,
            repo_base=mock_repo,
        )

        assert len(items) > 0
        assert any(item.name == "test-command.md" for item in items)

    def test_scan_directory_items(self, mock_claude_dir: Path, mock_repo: Path):
        """Test scanning directory items with marker."""
        category = SyncCategory(
            local_path=str(mock_claude_dir / "skills"),
            repo_path=".claude/skills",
            item_type=ItemType.DIRECTORY,
            item_marker="SKILL.md",
            include=["*"],
            exclude=[],
        )

        items = scan_items_for_category(
            category_name="claude_skills",
            category=category,
            local_base=mock_claude_dir,
            repo_base=mock_repo,
        )

        assert len(items) > 0
        assert any(item.name == "test-skill" for item in items)


class TestActions:
    """Tests for sync actions."""

    def test_action_types(self):
        """Test action type values."""
        assert ActionType.UNCHANGED.value == "unchanged"
        assert ActionType.COPY_TO_REPO.value == "copy_to_repo"
        assert ActionType.CONFLICT.value == "conflict"

    def test_determine_action_unchanged(self, temp_dir: Path):
        """Test determining unchanged action."""
        # Create identical files
        local_file = temp_dir / "local" / "test.md"
        repo_file = temp_dir / "repo" / "test.md"

        local_file.parent.mkdir()
        repo_file.parent.mkdir()

        local_file.write_text("same content", encoding="utf-8")
        repo_file.write_text("same content", encoding="utf-8")

        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=local_file,
            repo_path=repo_file,
        )

        # Get hash for state
        content_hash = item.get_hash("local")

        action = determine_action(item, last_hash=content_hash, sync_mode="bidirectional")
        assert action.action_type == ActionType.UNCHANGED

    def test_determine_action_new_local(self, temp_dir: Path):
        """Test determining new local action."""
        local_file = temp_dir / "local" / "test.md"
        repo_file = temp_dir / "repo" / "test.md"

        local_file.parent.mkdir()
        repo_file.parent.mkdir(exist_ok=True)

        local_file.write_text("new content", encoding="utf-8")
        # repo_file doesn't exist

        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=local_file,
            repo_path=repo_file,
        )

        action = determine_action(item, last_hash=None, sync_mode="bidirectional")
        assert action.action_type == ActionType.NEW_LOCAL

    def test_execute_copy_action(self, temp_dir: Path):
        """Test executing a copy action."""
        source = temp_dir / "source.md"
        dest = temp_dir / "dest" / "file.md"

        source.write_text("copy this", encoding="utf-8")

        item = SyncItem(
            name="file.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=source,
            repo_path=dest,
        )

        action = SyncAction(
            item=item,
            action_type=ActionType.COPY_TO_REPO,
            source_path=source,
            dest_path=dest,
        )

        result = execute_action(action)
        assert result.success is True
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "copy this"


class TestSyncState:
    """Tests for sync state management."""

    def test_state_creation(self):
        """Test creating new state."""
        state = SyncState()
        assert state.version == "2.0"
        assert len(state.items) == 0

    def test_state_set_item(self):
        """Test setting item state."""
        state = SyncState()
        state.set_item(
            category="test",
            name="item.md",
            content_hash="abc123",
        )

        item = state.get_item("test", "item.md")
        assert item is not None
        assert item.content_hash == "abc123"

    def test_state_remove_item(self):
        """Test removing item from state."""
        state = SyncState()
        state.set_item(category="test", name="item.md")

        result = state.remove_item("test", "item.md")
        assert result is True

        item = state.get_item("test", "item.md")
        assert item is None

    def test_state_serialization(self):
        """Test state to/from dict."""
        state = SyncState()
        state.set_item(category="test", name="item.md", content_hash="abc123")

        data = state.to_dict()
        restored = SyncState.from_dict(data)

        assert restored.version == state.version
        item = restored.get_item("test", "item.md")
        assert item is not None
        assert item.content_hash == "abc123"


class TestStateManager:
    """Tests for StateManager."""

    def test_manager_load_empty(self, state_file: Path):
        """Test loading when no state file exists."""
        manager = StateManager(state_file)
        state = manager.state

        assert state is not None
        assert len(state.items) == 0

    def test_manager_save_load(self, state_file: Path):
        """Test saving and loading state."""
        manager = StateManager(state_file)
        manager.update_item(
            category="test",
            name="item.md",
            content_hash="abc123",
        )

        # Create new manager and load
        manager2 = StateManager(state_file)
        item = manager2.state.get_item("test", "item.md")

        assert item is not None
        assert item.content_hash == "abc123"


class TestSyncEngine:
    """Tests for SyncEngine."""

    def test_engine_creation(self, sample_config: dict):
        """Test engine creation."""
        config = SccsConfig.model_validate(sample_config)
        engine = SyncEngine(config)

        assert engine is not None
        assert engine.config == config

    def test_get_enabled_categories(self, sample_config: dict):
        """Test getting enabled categories."""
        config = SccsConfig.model_validate(sample_config)
        engine = SyncEngine(config)

        categories = engine.get_enabled_categories()
        assert "claude_framework" in categories
        assert "claude_skills" in categories

    def test_get_status(self, sample_config: dict, mock_claude_dir: Path, mock_repo: Path):
        """Test getting status."""
        config = SccsConfig.model_validate(sample_config)
        engine = SyncEngine(config)

        statuses = engine.get_status()
        assert len(statuses) > 0

    def test_sync_dry_run(self, sample_config: dict, mock_claude_dir: Path, mock_repo: Path):
        """Test sync with dry run."""
        config = SccsConfig.model_validate(sample_config)
        engine = SyncEngine(config)

        result = engine.sync(dry_run=True)

        assert result is not None
        assert result.success is True
