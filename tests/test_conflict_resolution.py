# Tests for conflict resolution improvements
# Covers: force newer, conflict counting, mtime-based resolution

import os
import time

from sccs.config.schema import ItemType, SyncCategory
from sccs.sync.actions import ActionType, SyncAction, determine_action, execute_action
from sccs.sync.category import CategoryHandler
from sccs.sync.item import SyncItem
from sccs.sync.state import StateManager


def _setup_conflict(tmp_path, local_content="local version", repo_content="repo version"):
    """Create a category handler with a conflict scenario.

    Files are placed so CategoryHandler finds them:
    - local: tmp_path/local/test.fish
    - repo:  tmp_path/repo_cat/test.fish  (repo_base=tmp_path, repo_path=repo_cat)
    """
    local_dir = tmp_path / "local"
    repo_cat_dir = tmp_path / "repo_cat"
    local_dir.mkdir(parents=True, exist_ok=True)
    repo_cat_dir.mkdir(parents=True, exist_ok=True)

    local_file = local_dir / "test.fish"
    repo_file = repo_cat_dir / "test.fish"
    local_file.write_text(local_content, encoding="utf-8")
    repo_file.write_text(repo_content, encoding="utf-8")

    category = SyncCategory(
        enabled=True,
        description="Test",
        local_path=str(local_dir),
        repo_path="repo_cat",
        sync_mode="bidirectional",
        item_type="file",
        include=["*.fish"],
    )

    state_mgr = StateManager(state_path=tmp_path / ".state" / ".sync_state.yaml")
    # Set a different hash so both sides appear "changed"
    state_mgr.update_item("test_cat", "test.fish", content_hash="old_hash_abc123")

    handler = CategoryHandler(
        name="test_cat",
        category=category,
        repo_base=tmp_path,
        state_manager=state_mgr,
    )

    return handler, local_file, repo_file


class TestConflictNotCountedAsError:
    """Verify that unresolved conflicts are counted separately from errors."""

    def test_unresolved_conflict_counted_as_conflict(self, tmp_path):
        """Unresolved conflicts should increment conflicts, not errors."""
        handler, _, _ = _setup_conflict(tmp_path)

        result = handler.sync()

        assert result.conflicts == 1
        assert result.errors == 0
        assert result.success is True

    def test_conflict_with_force_local(self, tmp_path):
        """--force local should resolve conflict and sync successfully."""
        handler, local_file, repo_file = _setup_conflict(tmp_path)

        result = handler.sync(force_direction="local")
        assert result.conflicts == 0
        assert result.errors == 0
        assert result.synced == 1
        assert repo_file.read_text(encoding="utf-8") == "local version"

    def test_conflict_with_force_repo(self, tmp_path):
        """--force repo should resolve conflict and sync successfully."""
        handler, local_file, repo_file = _setup_conflict(tmp_path)

        result = handler.sync(force_direction="repo")
        assert result.conflicts == 0
        assert result.errors == 0
        assert result.synced == 1
        assert local_file.read_text(encoding="utf-8") == "repo version"


class TestForceNewer:
    """Tests for --force newer mtime-based conflict resolution."""

    def test_force_newer_prefers_local_when_newer(self, tmp_path):
        """When local is newer, --force newer should copy local to repo."""
        handler, local_file, repo_file = _setup_conflict(
            tmp_path, "new local version", "old repo version"
        )

        # Make repo file older
        old_time = time.time() - 3600
        os.utime(repo_file, (old_time, old_time))

        result = handler.sync(force_direction="newer")
        assert result.conflicts == 0
        assert result.synced == 1
        assert repo_file.read_text(encoding="utf-8") == "new local version"

    def test_force_newer_prefers_repo_when_newer(self, tmp_path):
        """When repo is newer, --force newer should copy repo to local."""
        handler, local_file, repo_file = _setup_conflict(
            tmp_path, "old local version", "new repo version"
        )

        # Make local file older
        old_time = time.time() - 3600
        os.utime(local_file, (old_time, old_time))

        result = handler.sync(force_direction="newer")
        assert result.conflicts == 0
        assert result.synced == 1
        assert local_file.read_text(encoding="utf-8") == "new repo version"

    def test_force_newer_same_mtime_prefers_local(self, tmp_path):
        """When mtimes are equal, --force newer should prefer local (>=)."""
        handler, local_file, repo_file = _setup_conflict(
            tmp_path, "local content", "repo content"
        )

        # Set same mtime
        now = time.time()
        os.utime(local_file, (now, now))
        os.utime(repo_file, (now, now))

        result = handler.sync(force_direction="newer")
        assert result.synced == 1
        assert repo_file.read_text(encoding="utf-8") == "local content"


class TestDetermineActionConflict:
    """Tests for determine_action conflict detection."""

    def test_no_last_hash_both_exist_different(self, tmp_path):
        """When last_hash is None and both sides differ, should be CONFLICT."""
        local_file = tmp_path / "local" / "test.md"
        repo_file = tmp_path / "repo" / "test.md"
        local_file.parent.mkdir(parents=True)
        repo_file.parent.mkdir(parents=True)
        local_file.write_text("local", encoding="utf-8")
        repo_file.write_text("repo", encoding="utf-8")

        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=local_file,
            repo_path=repo_file,
        )

        action = determine_action(item, last_hash=None, sync_mode="bidirectional")
        assert action.action_type == ActionType.CONFLICT

    def test_no_last_hash_both_exist_same(self, tmp_path):
        """When last_hash is None but both sides are identical, should be UNCHANGED."""
        local_file = tmp_path / "local" / "test.md"
        repo_file = tmp_path / "repo" / "test.md"
        local_file.parent.mkdir(parents=True)
        repo_file.parent.mkdir(parents=True)
        local_file.write_text("same content", encoding="utf-8")
        repo_file.write_text("same content", encoding="utf-8")

        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=local_file,
            repo_path=repo_file,
        )

        action = determine_action(item, last_hash=None, sync_mode="bidirectional")
        assert action.action_type == ActionType.UNCHANGED

    def test_only_local_changed(self, tmp_path):
        """When only local changed, should be COPY_TO_REPO."""
        local_file = tmp_path / "local" / "test.md"
        repo_file = tmp_path / "repo" / "test.md"
        local_file.parent.mkdir(parents=True)
        repo_file.parent.mkdir(parents=True)
        local_file.write_text("changed local", encoding="utf-8")
        repo_file.write_text("original", encoding="utf-8")

        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=local_file,
            repo_path=repo_file,
        )

        from sccs.utils.hashing import content_hash

        repo_hash = content_hash("original")
        action = determine_action(item, last_hash=repo_hash, sync_mode="bidirectional")
        assert action.action_type == ActionType.COPY_TO_REPO

    def test_both_changed_local_to_repo_mode(self, tmp_path):
        """In local_to_repo mode, both changed → COPY_TO_REPO (no conflict)."""
        local_file = tmp_path / "local" / "test.md"
        repo_file = tmp_path / "repo" / "test.md"
        local_file.parent.mkdir(parents=True)
        repo_file.parent.mkdir(parents=True)
        local_file.write_text("local", encoding="utf-8")
        repo_file.write_text("repo", encoding="utf-8")

        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=local_file,
            repo_path=repo_file,
        )

        action = determine_action(item, last_hash=None, sync_mode="local_to_repo")
        assert action.action_type == ActionType.COPY_TO_REPO


class TestExecuteActionConflict:
    """Tests for execute_action with CONFLICT type."""

    def test_conflict_action_fails(self, tmp_path):
        """Executing a CONFLICT action should return failure."""
        item = SyncItem(
            name="test.md",
            category="test",
            item_type=ItemType.FILE,
            local_path=tmp_path / "local.md",
            repo_path=tmp_path / "repo.md",
        )
        action = SyncAction(
            item=item,
            action_type=ActionType.CONFLICT,
            reason="Both changed",
        )
        result = execute_action(action)
        assert result.success is False
        assert "Conflict" in (result.error or "")


class TestConsoleSyncResultConflicts:
    """Tests for console output with conflicts vs errors."""

    def test_conflicts_shown_differently_from_errors(self):
        """Conflicts should produce 'with conflicts', not 'with errors'."""
        from io import StringIO

        from rich.console import Console as RichConsole

        from sccs.output.console import Console
        from sccs.sync.engine import SyncResult

        console = Console(verbose=False, colored=False)
        console._console = RichConsole(file=StringIO(), no_color=True)

        result = SyncResult(
            success=True,
            total_categories=1,
            synced_categories=1,
            synced_items=5,
            conflicts=2,
            errors=0,
            category_results={},
        )
        console.print_sync_result(result)
        console._console.file.seek(0)
        output = console._console.file.read()
        assert "with conflicts" in output
        assert "with errors" not in output

    def test_errors_shown_as_errors(self):
        """Errors should produce 'with errors' output."""
        from io import StringIO

        from rich.console import Console as RichConsole

        from sccs.output.console import Console
        from sccs.sync.engine import SyncResult

        console = Console(verbose=False, colored=False)
        console._console = RichConsole(file=StringIO(), no_color=True)

        result = SyncResult(
            success=False,
            total_categories=1,
            synced_categories=0,
            synced_items=0,
            conflicts=0,
            errors=3,
            category_results={},
        )
        console.print_sync_result(result)
        console._console.file.seek(0)
        output = console._console.file.read()
        assert "with errors" in output

    def test_category_result_with_conflicts_shows_hints(self):
        """Category results with conflicts should show resolution hints."""
        from io import StringIO

        from rich.console import Console as RichConsole

        from sccs.output.console import Console
        from sccs.sync.category import CategorySyncResult

        console = Console(verbose=False, colored=False)
        console._console = RichConsole(file=StringIO(), no_color=True)

        cat_result = CategorySyncResult(
            name="fish_config",
            success=True,
            synced=5,
            conflicts=2,
            errors=0,
            results=[],
        )
        console._print_category_result("fish_config", cat_result)
        console._console.file.seek(0)
        output = console._console.file.read()
        assert "2 conflicts" in output
        assert "--force newer" in output
        assert "--force local" in output
