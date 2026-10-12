"""`sccs categories enable/disable` edits one key, never dumps the loaded model.

Dumping wrote all default categories with expanded absolute paths
(C:\\Users\\<user>\\.claude\\skills) into config.yaml, which `sccs_config`
carries to every other host (2.71.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sccs.config.loader import load_config, update_category_enabled

_ORIGINAL = {
    "repository": {"path": "~/gitbase/sccs-sync"},
    "sync_categories": {
        "claude_skills": {
            "enabled": True,
            "local_path": "~/.claude/skills",
            "repo_path": ".claude/skills",
            "item_type": "directory",
            "item_marker": "SKILL.md",
        }
    },
}


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".config" / "sccs" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(_ORIGINAL, sort_keys=False), encoding="utf-8")
    return path


def _on_disk(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_disabling_changes_only_the_enabled_key(config_path):
    update_category_enabled("claude_skills", False, config_path)

    expected = yaml.safe_load(yaml.safe_dump(_ORIGINAL))
    expected["sync_categories"]["claude_skills"]["enabled"] = False
    assert _on_disk(config_path) == expected


def test_enabling_a_default_category_adds_only_that_one_unexpanded(config_path):
    update_category_enabled("powershell_profile", True, config_path)

    data = _on_disk(config_path)
    assert set(data["sync_categories"]) == {"claude_skills", "powershell_profile"}
    entry = data["sync_categories"]["powershell_profile"]
    assert entry["enabled"] is True
    assert entry["local_path"] == "~/Documents/PowerShell"
    assert data["repository"]["path"] == "~/gitbase/sccs-sync"


def test_no_expanded_home_path_reaches_the_file(config_path, tmp_path):
    update_category_enabled("powershell_profile", True, config_path)
    update_category_enabled("claude_skills", False, config_path)

    assert str(tmp_path) not in config_path.read_text(encoding="utf-8")


def test_the_loaded_config_reflects_the_change(config_path):
    config = update_category_enabled("powershell_profile", True, config_path)

    assert config.sync_categories["powershell_profile"].enabled is True
    assert load_config(config_path).sync_categories["powershell_profile"].enabled is True


def test_unknown_category_raises_and_leaves_the_file_alone(config_path):
    before = config_path.read_text(encoding="utf-8")

    with pytest.raises(KeyError):
        update_category_enabled("no_such_category", True, config_path)

    assert config_path.read_text(encoding="utf-8") == before
