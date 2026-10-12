"""Host-local repository path: local.yaml overrides the shared config.yaml.

The sync repo's location is a per-host decision, but config.yaml travels
between hosts through `sccs_config`. Adopting the shared config on a Windows
host whose clone lived in C:\\Projects pointed it at the Mac's path and every
`sccs sync` crashed (2.70.0).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from sccs.cli import cli
from sccs.config.loader import (
    get_local_config_path,
    load_config,
    read_local_repo_path,
    save_config,
    update_category_enabled,
    write_local_repo_path,
)
from sccs.doctor.shared_config import SharedConfigStatus, adopt_shared_config, detect_shared_config

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_SCCS_CATEGORY = {
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
    monkeypatch.delenv("SCCS_CONFIG", raising=False)
    return tmp_path


def _write_config(home: Path, repo: str = "~/gitbase/sccs-sync", categories: dict | None = None) -> Path:
    path = home / ".config" / "sccs" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"repository": {"path": repo}, "sync_categories": categories or {}}),
        encoding="utf-8",
    )
    return path


def _clone(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


class TestLoader:
    def test_without_local_yaml_the_shared_path_applies(self, home):
        config_path = _write_config(home)

        assert load_config(config_path).repository.path == str(home / "gitbase" / "sccs-sync")
        assert read_local_repo_path(config_path) is None

    def test_local_yaml_overrides_the_shared_path(self, home):
        config_path = _write_config(home)
        write_local_repo_path(str(home / "Projects" / "sccs-sync"), config_path)

        assert load_config(config_path).repository.path == str(home / "Projects" / "sccs-sync")

    def test_only_repository_path_is_read(self, home, caplog):
        # local.yaml must not grow into a second, unsynced config.
        config_path = _write_config(home)
        get_local_config_path(config_path).write_text(
            yaml.safe_dump({"repository": {"path": "/x", "auto_push": True}, "doctor": {"x": 1}}),
            encoding="utf-8",
        )

        config = load_config(config_path)

        assert config.repository.path == "/x"
        assert config.repository.auto_push is False
        assert "doctor" in caplog.text and "repository.auto_push" in caplog.text

    @pytest.mark.parametrize("content", ["repository: [broken\n", "- a list\n", "repository:\n  path: ''\n"])
    def test_unusable_local_yaml_falls_back_to_the_shared_path(self, home, content):
        config_path = _write_config(home)
        get_local_config_path(config_path).write_text(content, encoding="utf-8")

        assert load_config(config_path).repository.path == str(home / "gitbase" / "sccs-sync")

    def test_save_never_writes_the_host_path_into_the_shared_config(self, home):
        # categories enable/disable round-trips the loaded config through
        # save_config; the next sync would carry the host path to every host.
        config_path = _write_config(home, categories={"claude_skills": {"enabled": True}})
        write_local_repo_path("C:\\Projects\\sccs-sync", config_path)

        update_category_enabled("claude_skills", False, config_path)

        on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert on_disk["repository"]["path"] == "~/gitbase/sccs-sync"
        assert load_config(config_path).repository.path == "C:\\Projects\\sccs-sync"

    def test_save_without_local_yaml_writes_the_loaded_path(self, home):
        config_path = _write_config(home)
        config = load_config(config_path)
        config.repository.path = "~/elsewhere"

        save_config(config, config_path)

        assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["repository"]["path"] == "~/elsewhere"


class TestAdoptKeepsTheHostRepo:
    def _setup(self, home: Path, shared_repo: str) -> SharedConfigStatus:
        clone = _clone(home / "Projects" / "sccs-sync")
        local = _write_config(home, repo=str(clone))
        copy = clone / ".config" / "sccs" / "config.yaml"
        copy.parent.mkdir(parents=True)
        copy.write_text(
            yaml.safe_dump({"repository": {"path": shared_repo}, "sync_categories": {"sccs_config": _SCCS_CATEGORY}}),
            encoding="utf-8",
        )
        status = detect_shared_config(local)
        assert status is not None and status.state == "not_adopted"
        return status

    def test_a_differing_shared_path_is_pinned_in_local_yaml(self, home):
        status = self._setup(home, shared_repo="~/gitbase/sccs-sync")

        adopt_shared_config(status, pull_fn=lambda _p: True)

        assert read_local_repo_path(status.local_path) == str(home / "Projects" / "sccs-sync")
        assert load_config(status.local_path).repository.path == str(home / "Projects" / "sccs-sync")
        # The shared file itself stays untouched — it is what syncs.
        assert yaml.safe_load(status.local_path.read_text(encoding="utf-8"))["repository"]["path"] == (
            "~/gitbase/sccs-sync"
        )
        assert detect_shared_config(status.local_path).state == "adopted"

    def test_a_matching_shared_path_writes_no_local_yaml(self, home):
        status = self._setup(home, shared_repo="~/Projects/sccs-sync")

        adopt_shared_config(status, pull_fn=lambda _p: True)

        assert not get_local_config_path(status.local_path).exists()

    def test_an_existing_local_yaml_is_left_alone(self, home):
        status = self._setup(home, shared_repo="~/gitbase/sccs-sync")
        write_local_repo_path("~/Projects/sccs-sync", status.local_path)
        status = detect_shared_config(status.local_path)

        adopt_shared_config(status, pull_fn=lambda _p: True)

        assert read_local_repo_path(status.local_path) == "~/Projects/sccs-sync"

    def test_detect_follows_local_yaml_to_the_repo_copy(self, home):
        # Without this a host whose config.yaml names a missing path would
        # report "no shared config" although its real clone has one.
        status = self._setup(home, shared_repo="~/gitbase/sccs-sync")
        config_path = status.local_path
        config_path.write_text(yaml.safe_dump({"repository": {"path": "~/missing"}}), encoding="utf-8")
        write_local_repo_path(str(home / "Projects" / "sccs-sync"), config_path)

        assert detect_shared_config(config_path).state == "not_adopted"

    def test_a_rolled_back_adoption_leaves_no_local_yaml(self, home):
        from sccs.doctor.runner import DoctorError

        clone = _clone(home / "Projects" / "sccs-sync")
        local = _write_config(home, repo=str(clone))
        copy = clone / ".config" / "sccs" / "config.yaml"
        copy.parent.mkdir(parents=True)
        copy.write_text("repository: [not a mapping\n", encoding="utf-8")
        status = SharedConfigStatus(state="not_adopted", local_path=local, repo_path=clone, repo_copy=copy)

        with pytest.raises(DoctorError, match="restored"):
            adopt_shared_config(status, pull_fn=lambda _p: True)

        assert not get_local_config_path(local).exists()


class TestCli:
    def _run(self, *args: str):
        return CliRunner().invoke(cli, list(args))

    def test_repo_path_sets_local_yaml_and_leaves_config_alone(self, home):
        config_path = _write_config(home)
        before = config_path.read_text(encoding="utf-8")
        clone = _clone(home / "Projects" / "sccs-sync")

        result = self._run("config", "repo-path", str(clone))

        assert result.exit_code == 0, result.output
        assert read_local_repo_path(config_path) == str(clone.resolve())
        assert config_path.read_text(encoding="utf-8") == before

    def test_repo_path_refuses_a_directory_without_git(self, home):
        config_path = _write_config(home)
        (home / "empty").mkdir()

        result = self._run("config", "repo-path", str(home / "empty"))

        assert result.exit_code == 1
        assert "Not a git repository" in _ANSI.sub("", result.output)
        assert not get_local_config_path(config_path).exists()

    def test_repo_path_without_argument_names_the_source(self, home):
        config_path = _write_config(home)
        write_local_repo_path(str(_clone(home / "Projects" / "sccs-sync")), config_path)

        output = _ANSI.sub("", self._run("config", "repo-path").output)

        assert "host-local" in output and "~/gitbase/sccs-sync" in output

    def test_sync_stops_cleanly_when_the_repo_is_missing(self, home):
        # 2.70.0: NotADirectoryError traceback on Windows; the engine would
        # otherwise create the tree and copy every local item into it.
        _write_config(home, repo="~/does-not-exist")

        result = self._run("sync", "--dry-run")

        output = _ANSI.sub("", result.output)
        assert result.exit_code == 1
        assert "Sync repository not found" in output and "sccs config repo-path" in output
        assert not (home / "does-not-exist").exists()

    def test_sync_json_reports_the_missing_repo(self, home):
        _write_config(home, repo="~/does-not-exist")

        result = self._run("sync", "--dry-run", "--json")

        payload = json.loads(result.output.strip().splitlines()[-1])
        assert result.exit_code == 1
        assert payload["success"] is False and "not found" in payload["error"]

    def test_config_show_json_names_the_source(self, home):
        config_path = _write_config(home)
        write_local_repo_path("~/Projects/sccs-sync", config_path)

        payload = json.loads(self._run("config", "show", "--json").output.strip().splitlines()[-1])

        assert payload["repository_path_source"] == "local"
        assert payload["config"]["repository"]["path"] == str(home / "Projects" / "sccs-sync")


def test_git_reports_a_missing_repo_directory_instead_of_crashing(tmp_path):
    from sccs.git.operations import GitError, _run_git

    with pytest.raises(GitError, match="Repository directory not found"):
        _run_git("status", cwd=tmp_path / "missing")
