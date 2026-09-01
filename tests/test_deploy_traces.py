"""Work traces: enumeration, ~/.claude.json surgery, removal."""

from __future__ import annotations

import json

import pytest

from sccs.deploy.traces import (
    enumerate_traces,
    remove_traces,
    strip_claude_json_history,
)


@pytest.fixture
def home(tmp_path):
    claude = tmp_path / ".claude"
    (claude / "projects" / "-Users-x-repo").mkdir(parents=True)
    (claude / "projects" / "-Users-x-repo" / "session.jsonl").write_text('{"role":"user"}\n', encoding="utf-8")
    (claude / "plans").mkdir()
    (claude / "plans" / "p.md").write_text("plan\n", encoding="utf-8")
    (claude / "todos").mkdir()
    (claude / "shell-snapshots").mkdir()
    (tmp_path / ".config" / "sccs").mkdir(parents=True)
    (tmp_path / ".config" / "sccs" / "config.yaml").write_text("repository:\n", encoding="utf-8")
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "userID": "abc",
                "hasCompletedOnboarding": True,
                "history": [{"display": "secret prompt"}],
                "projects": {"/x": {"allowedTools": ["Bash"], "history": [{"display": "another"}]}},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_enumerate_finds_the_documented_locations(home):
    targets = enumerate_traces(home)
    labels = {t.label for t in targets if t.exists}
    assert "session transcripts and project memory" in labels
    assert {t.path for t in targets if t.exists} >= {
        home / ".claude" / "projects",
        home / ".claude" / "plans",
        home / ".claude" / "todos",
        home / ".claude" / "shell-snapshots",
        home / ".config" / "sccs" / "config.yaml",
        home / ".claude.json",
    }


def test_enumerate_marks_absent_paths(tmp_path):
    targets = enumerate_traces(tmp_path)
    assert all(not t.exists for t in targets)


def test_claude_json_keeps_everything_but_history(home):
    changed = strip_claude_json_history(home / ".claude.json")
    assert changed

    doc = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert "history" not in doc
    assert "history" not in doc["projects"]["/x"]
    assert doc["userID"] == "abc"
    assert doc["hasCompletedOnboarding"] is True
    assert doc["projects"]["/x"]["allowedTools"] == ["Bash"]


def test_claude_json_is_not_deleted(home):
    strip_claude_json_history(home / ".claude.json")
    assert (home / ".claude.json").exists()


def test_claude_json_dry_run_changes_nothing(home):
    before = (home / ".claude.json").read_text(encoding="utf-8")
    changed = strip_claude_json_history(home / ".claude.json", dry_run=True)
    assert changed
    assert (home / ".claude.json").read_text(encoding="utf-8") == before


def test_claude_json_without_history_reports_no_change(home):
    (home / ".claude.json").write_text(json.dumps({"userID": "abc"}), encoding="utf-8")
    assert strip_claude_json_history(home / ".claude.json") is False


def test_malformed_claude_json_is_left_alone(home):
    (home / ".claude.json").write_text("{not json", encoding="utf-8")
    assert strip_claude_json_history(home / ".claude.json") is False
    assert (home / ".claude.json").read_text(encoding="utf-8") == "{not json"


def test_claude_json_stays_owner_only(home):
    strip_claude_json_history(home / ".claude.json")
    assert (home / ".claude.json").stat().st_mode & 0o777 == 0o600


def test_remove_traces_clears_trees_and_files(home):
    targets = [t for t in enumerate_traces(home) if t.exists]
    errors = remove_traces(targets)
    assert errors == []
    assert not (home / ".claude" / "projects").exists()
    assert not (home / ".config" / "sccs" / "config.yaml").exists()
    assert (home / ".claude.json").exists()


def test_remove_traces_dry_run_removes_nothing(home):
    targets = [t for t in enumerate_traces(home) if t.exists]
    assert remove_traces(targets, dry_run=True) == []
    assert (home / ".claude" / "projects").exists()
