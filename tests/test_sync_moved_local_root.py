"""A category whose local directory moved must never delete repo items.

The sync state records per-item hashes, not where they were synced. When
2.71.1 followed OneDrive's Documents redirection, powershell_profile pointed
at a new directory, all 57 tracked files were missing there, and the next
sync would have read that as "deleted locally" and removed them from the
repo (2.71.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.config.schema import SyncCategory
from sccs.sync.category import CategoryHandler
from sccs.sync.state import StateManager, SyncState

_FILES = {"a.ps1": "one", "b.ps1": "two", "c.ps1": "three"}


def _category(local: Path) -> SyncCategory:
    return SyncCategory(local_path=str(local), repo_path="profile", item_type="file", include=["*.ps1"])


def _handler(local: Path, repo: Path, state: StateManager) -> CategoryHandler:
    return CategoryHandler(name="pwsh", category=_category(local), repo_base=repo, state_manager=state)


@pytest.fixture
def setup(tmp_path: Path):
    old_local = tmp_path / "Documents" / "PowerShell"
    new_local = tmp_path / "OneDrive" / "Dokumente" / "PowerShell"
    repo = tmp_path / "repo"
    # Only the local side starts filled: the first sync copies every file into
    # the repo and so records a hash for each, as on the real host.
    old_local.mkdir(parents=True)
    for name, content in _FILES.items():
        (old_local / name).write_text(content, encoding="utf-8")
    (repo / "profile").mkdir(parents=True)
    new_local.mkdir(parents=True)
    state = StateManager(tmp_path / "state.yaml")
    result = _handler(old_local, repo, state).sync()
    assert result.success
    return old_local, new_local, repo, state


def _repo_files(repo: Path) -> set[str]:
    return {p.name for p in (repo / "profile").iterdir()}


class TestRecordedRoot:
    def test_a_sync_records_the_local_directory(self, setup):
        old_local, _new, _repo, state = setup

        assert state.get_category_root("pwsh") is not None
        assert Path(state.get_category_root("pwsh")).name == old_local.name

    def test_a_moved_directory_is_filled_from_the_repo_not_emptied_in_it(self, setup):
        _old, new_local, repo, state = setup
        (new_local / "Microsoft.PowerShell_profile.ps1").write_text("mine", encoding="utf-8")

        result = _handler(new_local, repo, state).sync()

        assert result.state_reset and "local path changed" in result.state_reset
        assert _repo_files(repo) >= set(_FILES)
        assert {p.name for p in new_local.iterdir()} >= set(_FILES)
        # The file only the new directory had is offered to the repo, not lost.
        assert "Microsoft.PowerShell_profile.ps1" in _repo_files(repo)

    def test_the_dry_run_after_a_move_proposes_no_deletion(self, setup):
        _old, new_local, repo, state = setup

        handler = _handler(new_local, repo, state)
        result = handler.sync(dry_run=True)

        assert result.state_reset
        assert all(a.action_type.value != "deleted_local" for a in handler.detect_changes())
        assert _repo_files(repo) == set(_FILES)
        # A dry run must not move the recorded directory.
        assert Path(state.get_category_root("pwsh")).parent.name == "Documents"

    def test_after_the_move_the_new_directory_is_remembered(self, setup):
        _old, new_local, repo, state = setup
        _handler(new_local, repo, state).sync()

        handler = _handler(new_local, repo, state)
        assert handler.sync(dry_run=True).state_reset is None

    def test_deleting_one_file_in_the_same_directory_still_deletes_it_in_the_repo(self, setup):
        old_local, _new, repo, state = setup
        (old_local / "b.ps1").unlink()

        result = _handler(old_local, repo, state).sync()

        assert result.state_reset is None
        assert "b.ps1" not in _repo_files(repo)


class TestStateWithoutRecordedRoot:
    """State written before 2.71.2 has no directory — the Windows host's case."""

    def _forget_root(self, state: StateManager) -> None:
        state.state.category_roots.clear()
        state.save()

    def test_every_tracked_item_missing_restores_instead_of_deleting(self, setup):
        _old, new_local, repo, state = setup
        self._forget_root(state)

        result = _handler(new_local, repo, state).sync()

        assert result.state_reset and "restoring" in result.state_reset
        assert _repo_files(repo) == set(_FILES)
        assert {p.name for p in new_local.iterdir()} == set(_FILES)

    def test_a_partial_deletion_is_still_a_deletion(self, setup):
        old_local, _new, repo, state = setup
        self._forget_root(state)
        (old_local / "a.ps1").unlink()

        result = _handler(old_local, repo, state).sync()

        assert result.state_reset is None
        assert "a.ps1" not in _repo_files(repo)


def test_state_roundtrip_keeps_category_roots(tmp_path):
    state = StateManager(tmp_path / "s.yaml")
    state.set_category_root("pwsh", "/x/y")

    assert StateManager(tmp_path / "s.yaml").get_category_root("pwsh") == "/x/y"
    assert SyncState.from_dict({"items": {}}).category_roots == {}
