"""Work traces: enumeration, ~/.claude.json surgery, removal."""

from __future__ import annotations

import json

import pytest

from sccs.deploy.traces import (
    TraceTarget,
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


def test_claude_json_symlink_within_home_strips_the_target(home):
    real = home / "real-claude.json"
    real.write_text(
        json.dumps({"userID": "abc", "history": [{"display": "secret"}]}),
        encoding="utf-8",
    )
    link = home / ".claude.json"
    link.unlink()
    link.symlink_to(real)

    changed = strip_claude_json_history(link)
    assert changed

    doc = json.loads(real.read_text(encoding="utf-8"))
    assert "history" not in doc
    assert doc["userID"] == "abc"
    assert link.is_symlink()


def test_claude_json_symlink_outside_home_is_left_alone(home):
    outside = home.parent / "outside-claude.json"
    outside.write_text(json.dumps({"history": [{"display": "secret"}]}), encoding="utf-8")
    link = home / ".claude.json"
    link.unlink()
    link.symlink_to(outside)

    result = strip_claude_json_history(link)
    assert result is False

    doc = json.loads(outside.read_text(encoding="utf-8"))
    assert doc["history"] == [{"display": "secret"}]


def test_remove_traces_rejects_unknown_kind(tmp_path):
    mystery = tmp_path / "mystery.txt"
    mystery.write_text("data", encoding="utf-8")
    target = TraceTarget(path=mystery, label="mystery", kind="bogus", exists=True, size_bytes=4)

    errors = remove_traces([target])

    assert mystery.exists()
    assert len(errors) == 1
    assert "bogus" in errors[0]


def test_enumerate_lists_sccs_state_dir_contents_and_excludes_receipt(home):
    state_dir = home / ".config" / "sccs"
    (state_dir / "sync.log").write_text("log\n", encoding="utf-8")
    (state_dir / ".sync_state.yaml").write_text("state:\n", encoding="utf-8")
    (state_dir / "profiles").mkdir()
    (state_dir / "profiles" / "p1.yaml").write_text("x\n", encoding="utf-8")
    (state_dir / ".deploy_receipt.yaml").write_text("receipt\n", encoding="utf-8")

    targets = enumerate_traces(home)
    all_paths = {t.path for t in targets}
    state_paths = {t.path for t in targets if t.path.parent == state_dir}

    assert state_paths == {
        state_dir / "config.yaml",
        state_dir / "sync.log",
        state_dir / ".sync_state.yaml",
        state_dir / "profiles",
    }
    assert state_dir / ".deploy_receipt.yaml" not in all_paths


def test_remove_traces_clears_sccs_state_but_keeps_receipt(home):
    state_dir = home / ".config" / "sccs"
    (state_dir / "sync.log").write_text("log\n", encoding="utf-8")
    (state_dir / "profiles").mkdir()
    (state_dir / "profiles" / "p1.yaml").write_text("x\n", encoding="utf-8")
    (state_dir / ".deploy_receipt.yaml").write_text("receipt\n", encoding="utf-8")

    targets = [t for t in enumerate_traces(home) if t.exists]
    errors = remove_traces(targets)

    assert errors == []
    assert not (state_dir / "config.yaml").exists()
    assert not (state_dir / "sync.log").exists()
    assert not (state_dir / "profiles").exists()
    assert (state_dir / ".deploy_receipt.yaml").exists()


def test_enumerate_contributes_no_sccs_state_targets_when_dir_absent(tmp_path):
    targets = enumerate_traces(tmp_path)
    assert not any(t.label.startswith("SCCS state") for t in targets)
