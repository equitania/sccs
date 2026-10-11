"""Shared config adoption: a host that never received the synced config.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sccs.doctor.installer import InstallPlan, execute_plan
from sccs.doctor.shared_config import (
    SharedConfigStatus,
    adopt_shared_config,
    detect_shared_config,
    shared_config_actions,
)

_CATEGORY = {
    "enabled": True,
    "local_path": "~/.config/sccs",
    "repo_path": ".config/sccs",
    "item_type": "file",
    "include": ["config.yaml"],
}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _config(categories: dict, *, marker: str = "local") -> str:
    return yaml.safe_dump(
        {
            "repository": {"path": "~/sync"},
            "sync_categories": categories,
            "global_exclude": [marker],
        }
    )


def _local(home: Path, content: str) -> Path:
    path = home / ".config" / "sccs" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _repo_copy(home: Path, content: str) -> Path:
    path = home / "sync" / ".config" / "sccs" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestDetect:
    def test_not_adopted_when_local_lacks_the_category_and_repo_has_a_copy(self, home):
        local = _local(home, _config({}))
        _repo_copy(home, _config({"sccs_config": _CATEGORY}, marker="shared"))

        status = detect_shared_config(local)

        assert status is not None and status.state == "not_adopted"

    def test_adopted_when_a_category_syncs_the_config_dir(self, home):
        # Matched by local_path, not by name — a user may call it anything.
        local = _local(home, _config({"my_sccs": _CATEGORY}))
        _repo_copy(home, _config({"sccs_config": _CATEGORY}))

        assert detect_shared_config(local).state == "adopted"

    def test_no_repo_copy_means_nothing_to_adopt(self, home):
        local = _local(home, _config({}))

        assert detect_shared_config(local).state == "no_repo_copy"

    def test_no_local_config_yields_no_status(self, home):
        assert detect_shared_config(home / ".config" / "sccs" / "config.yaml") is None

    def test_only_not_adopted_produces_an_action(self, home):
        local = _local(home, _config({}))
        assert shared_config_actions(detect_shared_config(local)) == []
        _repo_copy(home, _config({"sccs_config": _CATEGORY}))
        assert len(shared_config_actions(detect_shared_config(local))) == 1
        assert shared_config_actions(None) == []


class TestAdopt:
    def _status(self, home: Path) -> SharedConfigStatus:
        local = _local(home, _config({}))
        _repo_copy(home, _config({"sccs_config": _CATEGORY}, marker="shared"))
        return detect_shared_config(local)

    def test_replaces_local_and_keeps_a_backup(self, home):
        status = self._status(home)
        before = status.local_path.read_text(encoding="utf-8")

        adopt_shared_config(status, pull_fn=lambda _path: True)

        assert "shared" in status.local_path.read_text(encoding="utf-8")
        backups = list((home / ".config" / "sccs" / "backups").glob("config.yaml.*"))
        assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == before
        assert detect_shared_config(status.local_path).state == "adopted"

    def test_failed_pull_changes_nothing(self, home):
        from sccs.doctor.runner import DoctorError

        status = self._status(home)
        before = status.local_path.read_text(encoding="utf-8")

        with pytest.raises(DoctorError, match="pull"):
            adopt_shared_config(status, pull_fn=lambda _path: False)

        assert status.local_path.read_text(encoding="utf-8") == before

    def test_invalid_shared_config_is_rolled_back(self, home):
        from sccs.doctor.runner import DoctorError

        local = _local(home, _config({}))
        _repo_copy(home, "repository: [this is not a mapping\n")
        status = SharedConfigStatus(
            state="not_adopted",
            local_path=local,
            repo_path=home / "sync",
            repo_copy=home / "sync" / ".config" / "sccs" / "config.yaml",
        )
        before = local.read_text(encoding="utf-8")

        with pytest.raises(DoctorError, match="restored"):
            adopt_shared_config(status, pull_fn=lambda _path: True)

        assert local.read_text(encoding="utf-8") == before


class TestExecutePlan:
    @pytest.fixture(autouse=True)
    def _terminal(self, monkeypatch):
        monkeypatch.setattr("sccs.doctor.installer._interactive", lambda: True)

    def test_without_a_terminal_the_action_is_skipped_not_assumed(self, home, monkeypatch):
        monkeypatch.setattr("sccs.doctor.installer._interactive", lambda: False)
        status = TestAdopt()._status(home)
        before = status.local_path.read_text(encoding="utf-8")

        result = execute_plan(InstallPlan(actions=shared_config_actions(status)), assume_yes=True)

        assert result.outcomes[0].status == "skipped"
        assert "interactive terminal" in result.outcomes[0].detail
        assert status.local_path.read_text(encoding="utf-8") == before

    def test_yes_does_not_skip_the_prompt(self, home, monkeypatch):
        # Replacing the whole config is never an unattended step.
        status = TestAdopt()._status(home)
        before = status.local_path.read_text(encoding="utf-8")
        asked: list[str] = []

        class _Answer:
            def ask(self):
                return False

        def fake_confirm(message, default=False):
            asked.append(message)
            return _Answer()

        monkeypatch.setattr("sccs.doctor.installer.questionary.confirm", fake_confirm)
        result = execute_plan(InstallPlan(actions=shared_config_actions(status)), assume_yes=True)

        assert len(asked) == 1
        assert result.outcomes[0].status == "skipped"
        assert status.local_path.read_text(encoding="utf-8") == before

    def test_confirmed_action_adopts_the_shared_config(self, home, monkeypatch):
        status = TestAdopt()._status(home)
        monkeypatch.setattr("sccs.doctor.shared_config._git_pull", lambda _path: True)

        class _Answer:
            def ask(self):
                return True

        monkeypatch.setattr("sccs.doctor.installer.questionary.confirm", lambda *_a, **_k: _Answer())
        result = execute_plan(InstallPlan(actions=shared_config_actions(status)), print_fn=lambda _m: None)

        assert result.outcomes[0].status == "executed"
        assert "shared" in status.local_path.read_text(encoding="utf-8")


def test_sccs_config_is_a_bundled_default_category():
    from sccs.config.defaults import DEFAULT_CONFIG

    cat = DEFAULT_CONFIG["sync_categories"]["sccs_config"]
    assert cat["local_path"] == "~/.config/sccs"
    assert cat["include"] == ["config.yaml"]
    # State, logs and backups must never travel.
    for never in (".sync_state.yaml", ".doctor_state.yaml", "backups/*", "sync.log"):
        assert never in cat["exclude"]


def test_deploy_never_treats_the_sccs_state_dir_as_a_managed_root():
    # A bundle that could write ~/.config/sccs could forge the deploy receipt.
    from sccs.deploy.install import _lexical, _managed_roots

    state_dir = _lexical(Path("~/.config/sccs"))
    assert state_dir not in _managed_roots()
    assert not any((state_dir / ".deploy_receipt.yaml").is_relative_to(r) for r in _managed_roots())
