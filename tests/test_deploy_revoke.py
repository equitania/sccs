"""Revocation: buckets, trace policy, verification sweep."""

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.deploy.receipt import InstallRecord, ReceiptEntry, ReceiptManager
from sccs.deploy.revoke import build_revoke_plan, execute_revoke, sweep
from sccs.utils.hashing import directory_hash


@pytest.fixture
def host(tmp_path):
    """A host with two profiles installed."""
    skills = tmp_path / ".claude" / "skills"
    for name in ("odoo-common", "odoo19", "customers-own"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")

    fish = tmp_path / ".config" / "fish"
    fish.mkdir(parents=True)
    (fish / "config.fish").write_text("# fish\n", encoding="utf-8")

    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / ".claude" / "projects" / "s.jsonl").write_text("{}\n", encoding="utf-8")
    return tmp_path


def _entry(host: Path, name: str, *, pre_existing=False, category="claude_skills"):
    target = host / ".claude" / "skills" / name
    return ReceiptEntry(
        category=category,
        name=name,
        target=str(target),
        item_type="directory",
        content_hash=directory_hash(target),
        pre_existing=pre_existing,
    )


@pytest.fixture
def manager(host):
    manager = ReceiptManager(host / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(
        InstallRecord(
            profile="odoo-server",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            retain=["fish_config"],
            sweep_globs={"claude_skills": ["odoo-common", "odoo19", "customers-own"]},
            entries=[
                _entry(host, "odoo-common"),
                _entry(host, "odoo19"),
                _entry(host, "customers-own", pre_existing=True),
                ReceiptEntry(
                    category="fish_config",
                    name="config.fish",
                    target=str(host / ".config" / "fish" / "config.fish"),
                    item_type="file",
                    content_hash="sha256:x",
                ),
                ReceiptEntry(
                    category="claude_skills",
                    name="already-gone",
                    target=str(host / ".claude" / "skills" / "already-gone"),
                    item_type="directory",
                ),
            ],
        )
    )
    return manager


def test_plan_sorts_into_four_buckets(manager, host):
    plan = build_revoke_plan(manager, home=host)
    assert {i.entry.name for i in plan.to_remove} == {"odoo-common", "odoo19"}
    assert {i.entry.name for i in plan.retained} == {"config.fish"}
    assert {i.entry.name for i in plan.untouched} == {"customers-own"}
    assert {i.entry.name for i in plan.already_gone} == {"already-gone"}


def test_modified_artefact_is_flagged_but_still_removed(manager, host):
    (host / ".claude" / "skills" / "odoo19" / "SKILL.md").write_text("edited\n", encoding="utf-8")
    plan = build_revoke_plan(manager, home=host)
    assert {i.entry.name for i in plan.modified} == {"odoo19"}
    assert "odoo19" in {i.entry.name for i in plan.to_remove}


def test_execute_removes_only_the_remove_bucket(manager, host):
    plan = build_revoke_plan(manager, home=host)
    result = execute_revoke(plan, manager)

    assert result.success
    assert result.removed == 2
    assert not (host / ".claude" / "skills" / "odoo-common").exists()
    assert not (host / ".claude" / "skills" / "odoo19").exists()
    assert (host / ".claude" / "skills" / "customers-own").exists()
    assert (host / ".config" / "fish" / "config.fish").exists()


def test_execute_purges_traces_and_drops_the_receipt(manager, host):
    plan = build_revoke_plan(manager, home=host)
    execute_revoke(plan, manager)
    assert not (host / ".claude" / "projects").exists()
    assert not manager.exists()


def test_keep_traces_leaves_transcripts(manager, host):
    plan = build_revoke_plan(manager, keep_traces=True, home=host)
    execute_revoke(plan, manager)
    assert (host / ".claude" / "projects").exists()


def test_dry_run_changes_nothing(manager, host):
    plan = build_revoke_plan(manager, home=host)
    result = execute_revoke(plan, manager, dry_run=True)
    assert result.success
    assert (host / ".claude" / "skills" / "odoo-common").exists()
    assert manager.exists()


def test_traces_survive_while_another_profile_remains(manager, host):
    manager.record_install(
        InstallRecord(
            profile="fastreport",
            installed_at="2026-09-01T11:00:00+00:00",
            sccs_version="2.65.0",
            retain=[],
            sweep_globs={},
            entries=[],
        )
    )
    plan = build_revoke_plan(manager, profile="odoo-server", home=host)
    assert plan.purge_traces is False
    execute_revoke(plan, manager)
    assert (host / ".claude" / "projects").exists()
    assert [r.profile for r in manager.load().installs] == ["fastreport"]


def test_sweep_is_clean_after_a_successful_revoke(manager, host):
    plan = build_revoke_plan(manager, home=host)
    execute_revoke(plan, manager)
    assert sweep(plan) == []


def test_sweep_reports_a_planted_leftover(manager, host):
    plan = build_revoke_plan(manager, home=host)
    execute_revoke(plan, manager)
    (host / ".claude" / "skills" / "odoo19").mkdir(parents=True)
    leftovers = sweep(plan)
    assert any("odoo19" in item for item in leftovers)


def test_execute_fails_when_the_sweep_finds_something(manager, host, monkeypatch):
    plan = build_revoke_plan(manager, home=host)

    def fake_sweep(_plan):
        return [str(host / ".claude" / "skills" / "odoo19")]

    monkeypatch.setattr("sccs.deploy.revoke.sweep", fake_sweep)
    result = execute_revoke(plan, manager)
    assert not result.success
    assert result.leftovers


def test_empty_receipt_yields_an_empty_plan(host):
    empty = ReceiptManager(host / "nothing.yaml")
    plan = build_revoke_plan(empty, home=host)
    assert plan.items == []
    assert plan.profiles == []
