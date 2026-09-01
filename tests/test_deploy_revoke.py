"""Revocation: buckets, trace policy, verification sweep."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from sccs.deploy.receipt import InstallRecord, ReceiptEntry, ReceiptManager
from sccs.deploy.revoke import (
    SWEEP_CONTENT_MATCH,
    SWEEP_PLANNED_SURVIVOR,
    SWEEP_UNRECORDED,
    SweepFinding,
    build_revoke_plan,
    execute_revoke,
    sweep,
    sweep_findings,
)
from sccs.utils.hashing import directory_hash


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A host with two profiles installed.

    Path.home() is patched to this fixture's tmp_path so the containment
    guard in execute_revoke (`is_home_path`) treats it as HOME — the same
    pattern test_deploy_install.py uses for its `source_home` fixture.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
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


def _entry(host: Path, name: str, *, pre_existing=False, category="claude_skills", shipped_hash=None):
    """A receipt entry as `deploy install` writes it.

    `written_by_sccs` mirrors the install: False exactly for a target we
    skipped because it was already there. `shipped_hash` is what the bundle
    would have written to such a target — None here means the customer's
    artefact is not our artefact.
    """
    target = host / ".claude" / "skills" / name
    return ReceiptEntry(
        category=category,
        name=name,
        target=str(target),
        item_type="directory",
        content_hash=directory_hash(target),
        pre_existing=pre_existing,
        written_by_sccs=not pre_existing,
        shipped_hash=shipped_hash,
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

    assert result.removed == 2
    assert not (host / ".claude" / "skills" / "odoo-common").exists()
    assert not (host / ".claude" / "skills" / "odoo19").exists()
    assert (host / ".claude" / "skills" / "customers-own").exists()
    assert (host / ".config" / "fish" / "config.fish").exists()

    # `customers-own` is in the profile's sweep_globs and still on disk, so
    # the sweep reports it — but the receipt POSITIVELY records that SCCS
    # never wrote there and its content is not ours, so it is case 3:
    # surfaced, labelled, and not a failure. Failing here would fail on
    # every host that has its own copy of a shipped name.
    assert result.benign_leftovers == [str(host / ".claude" / "skills" / "customers-own")]
    assert result.leftovers == []
    assert result.success


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
    """A successful revoke leaves nothing of ours — with the host untouched.

    The customer's own `customers-own` stays exactly where it is. It is
    still reported (it is a name the profile ships), but as case 3, so no
    finding fails and the revoke genuinely succeeds.
    """
    plan = build_revoke_plan(manager, home=host)
    result = execute_revoke(plan, manager)

    assert result.success
    assert [f for f in sweep_findings(plan) if f.failure] == []
    assert (host / ".claude" / "skills" / "customers-own").exists()
    # And with theirs gone too, the sweep reports nothing at all.
    shutil.rmtree(host / ".claude" / "skills" / "customers-own")
    assert sweep(plan) == []


def test_sweep_catches_a_leftover_the_bookkeeping_calls_accounted_for(manager, host):
    """The sweep re-scans sweep_globs, so it sees what the buckets cannot.

    `customers-own` is bucketed `untouched` — the per-entry bookkeeping says
    it needs no removal and reports nothing about it. It is nevertheless a
    name this profile shipped that is still on the host, and that is the
    fact the operator has to be handed. This is the pass that would have
    caught a receipt where `pre_existing` was wrongly recomputed as True.
    """
    plan = build_revoke_plan(manager, home=host)
    assert {i.entry.name for i in plan.untouched} == {"customers-own"}
    assert not any(i.entry.name == "customers-own" for i in plan.to_remove)

    execute_revoke(plan, manager)

    assert str(host / ".claude" / "skills" / "customers-own") in sweep(plan)


def test_sweep_ignores_retained_categories(manager, host):
    """`retain` means "stays by design", so it is never a leftover."""
    record = manager.load().find("odoo-server")
    record.sweep_globs["fish_config"] = ["config.fish"]
    manager.record_install(record)

    plan = build_revoke_plan(manager, home=host)
    execute_revoke(plan, manager)

    assert (host / ".config" / "fish" / "config.fish").exists()
    assert not any("config.fish" in item for item in sweep(plan))


def test_sweep_reports_a_planted_leftover(manager, host):
    plan = build_revoke_plan(manager, home=host)
    execute_revoke(plan, manager)
    (host / ".claude" / "skills" / "odoo19").mkdir(parents=True)
    leftovers = sweep(plan)
    assert any("odoo19" in item for item in leftovers)


def test_execute_fails_when_the_sweep_finds_something(manager, host, monkeypatch):
    plan = build_revoke_plan(manager, home=host)

    def fake_sweep(_plan):
        return [
            SweepFinding(
                path=str(host / ".claude" / "skills" / "odoo19"),
                category="claude_skills",
                name="odoo19",
                reason=SWEEP_PLANNED_SURVIVOR,
                profile="odoo-server",
            )
        ]

    monkeypatch.setattr("sccs.deploy.revoke.sweep_findings", fake_sweep)
    result = execute_revoke(plan, manager)
    assert not result.success
    assert result.leftovers


def test_empty_receipt_yields_an_empty_plan(host):
    empty = ReceiptManager(host / "nothing.yaml")
    plan = build_revoke_plan(empty, home=host)
    assert plan.items == []
    assert plan.profiles == []


# --- Finding 1: a failed removal must not drop the profile's receipt record ---


def test_removal_failure_keeps_the_profile_record(manager, host):
    if os.geteuid() == 0:
        pytest.skip("chmod-based permission guard has no effect as root")

    plan = build_revoke_plan(manager, home=host)
    odoo19 = host / ".claude" / "skills" / "odoo19"
    skills_dir = odoo19.parent
    original_mode = skills_dir.stat().st_mode
    skills_dir.chmod(0o500)  # r-x: entries inside can no longer be unlinked
    try:
        result = execute_revoke(plan, manager)
    finally:
        skills_dir.chmod(original_mode)

    assert not result.success
    assert result.errors
    assert odoo19.exists()
    # odoo-server's record survives so a retry can find the artefacts again.
    assert [r.profile for r in manager.load().installs] == ["odoo-server"]


# --- Finding 2: a corrupted receipt must not walk rmtree outside HOME ---


def test_containment_guard_blocks_a_target_outside_home(host):
    manager = ReceiptManager(host / ".config" / "sccs" / ".deploy_receipt.yaml")
    outside = host.parent / "outside-home" / "evil"
    outside.mkdir(parents=True)
    manager.record_install(
        InstallRecord(
            profile="malicious",
            installed_at="2026-09-01T12:00:00+00:00",
            sccs_version="2.65.0",
            retain=[],
            sweep_globs={},
            entries=[
                ReceiptEntry(
                    category="claude_skills",
                    name="evil",
                    target=str(outside),
                    item_type="directory",
                    content_hash=directory_hash(outside),
                )
            ],
        )
    )
    plan = build_revoke_plan(manager, home=host)
    result = execute_revoke(plan, manager)

    assert not result.success
    assert outside.exists()
    assert any(str(outside) in e for e in result.errors)
    # The offending entry's profile keeps its record, same as any other
    # removal failure.
    assert [r.profile for r in manager.load().installs] == ["malicious"]


# --- Finding 3: an artefact shared by two profiles survives revoking one ---


def _shared_install(host: Path) -> InstallRecord:
    return InstallRecord(
        profile="fastreport",
        installed_at="2026-09-01T11:00:00+00:00",
        sccs_version="2.65.0",
        retain=[],
        sweep_globs={"claude_skills": ["odoo-common"]},
        entries=[_entry(host, "odoo-common")],
    )


def test_shared_skill_is_bucketed_shared_and_survives(manager, host):
    manager.record_install(_shared_install(host))

    plan = build_revoke_plan(manager, profile="odoo-server", home=host)
    assert {i.entry.name for i in plan.shared} == {"odoo-common"}
    assert "odoo-common" not in {i.entry.name for i in plan.to_remove}

    result = execute_revoke(plan, manager)
    assert result.success
    assert (host / ".claude" / "skills" / "odoo-common").exists()
    assert not (host / ".claude" / "skills" / "odoo19").exists()
    assert [r.profile for r in manager.load().installs] == ["fastreport"]
    # A shared artefact is excluded from the sweep — another profile still
    # claims it, so "still present" is the intended outcome, not a leak.
    assert not any("odoo-common" in item for item in result.leftovers)
    assert not any("odoo-common" in item for item in result.benign_leftovers)


def test_shared_skill_removed_once_the_last_profile_goes(manager, host):
    manager.record_install(_shared_install(host))

    # First revoke leaves the shared skill behind.
    plan1 = build_revoke_plan(manager, profile="odoo-server", home=host)
    execute_revoke(plan1, manager)
    assert (host / ".claude" / "skills" / "odoo-common").exists()

    # Revoking the remaining (last) profile removes it normally.
    plan2 = build_revoke_plan(manager, home=host)
    assert {i.entry.name for i in plan2.to_remove} == {"odoo-common"}
    execute_revoke(plan2, manager)
    assert not (host / ".claude" / "skills" / "odoo-common").exists()


# --- Second-pass sweep findings keep the receipt record (three-way rule) ---


def test_a_wrongly_skipped_artefact_of_ours_keeps_the_record(manager, host):
    """The headline failure mode, one command later.

    An entry is marked `pre_existing` on an artefact SCCS did write — the
    exact shape of a receipt from a build whose ownership logic was wrong.
    Revoke reports it and exits non-zero, correct. If the record went with
    it, the operator's re-run would find no receipt, print "Nothing to
    revoke on this host", exit 0, and leave the artefact standing. So the
    provenance record, not the inference, decides: written_by_sccs=True
    keeps the finding a failure and the record in place.
    """
    record = manager.load().find("odoo-server")
    for entry in record.entries:
        if entry.name == "odoo19":
            entry.pre_existing = True  # the wrong inference ...
            entry.written_by_sccs = True  # ... over the right record
    manager.record_install(record)

    plan = build_revoke_plan(manager, home=host)
    # Bucketed untouched, so no planned removal will ever look at it.
    assert "odoo19" in {i.entry.name for i in plan.untouched}

    result = execute_revoke(plan, manager)

    assert not result.success
    assert str(host / ".claude" / "skills" / "odoo19") in result.leftovers
    # The record survives, so the re-run still knows where to look.
    assert [r.profile for r in manager.load().installs] == ["odoo-server"]
    again = build_revoke_plan(manager, home=host)
    assert again.records
    assert str(host / ".claude" / "skills" / "odoo19") in sweep(again)


def test_a_shipped_name_with_no_entry_at_all_fails_and_keeps_the_record(manager, host):
    """Case 2: files written without being recorded.

    A name in `sweep_globs` with no receipt entry is the signature of an
    install that wrote and did not record. Losing the record here is the
    worst case of all: there is no entry left to re-derive the directory
    from, so the sweep could never find that artefact again.
    """
    record = manager.load().find("odoo-server")
    record.sweep_globs["claude_skills"].append("ghost")
    manager.record_install(record)
    ghost = host / ".claude" / "skills" / "ghost"
    ghost.mkdir(parents=True)
    (ghost / "SKILL.md").write_text("# ghost\n", encoding="utf-8")

    plan = build_revoke_plan(manager, home=host)
    assert "ghost" not in {i.entry.name for i in plan.items}

    result = execute_revoke(plan, manager)

    assert not result.success
    assert str(ghost) in result.leftovers
    assert [f.reason for f in result.findings if f.name == "ghost"] == [SWEEP_UNRECORDED]
    assert [r.profile for r in manager.load().installs] == ["odoo-server"]


def test_a_foreign_target_holding_our_content_is_a_failure(manager, host):
    """Condition (b): "already here" and "is our content" can coincide.

    Ownership says the customer put it there and nothing of ours was
    written. The bytes say otherwise — the artefact on that host IS the one
    the bundle ships, so our knowledge is on it and the revoke has not
    delivered its promise.
    """
    theirs = host / ".claude" / "skills" / "customers-own"
    record = manager.load().find("odoo-server")
    record.entries = [
        _entry(host, "customers-own", pre_existing=True, shipped_hash=directory_hash(theirs))
        if e.name == "customers-own"
        else e
        for e in record.entries
    ]
    manager.record_install(record)

    plan = build_revoke_plan(manager, home=host)
    result = execute_revoke(plan, manager)

    assert not result.success
    assert str(theirs) in result.leftovers
    assert [f.reason for f in result.findings if f.name == "customers-own"] == [SWEEP_CONTENT_MATCH]
    # Their file is still theirs — reported, never deleted.
    assert theirs.exists()
    assert [r.profile for r in manager.load().installs] == ["odoo-server"]


def test_a_case_3_finding_alone_lets_the_receipt_record_go(manager, host):
    """The other side of the rule: an alarm that always fires is no alarm.

    `customers-own` is recorded as never written by SCCS and holds
    different content. It is reported, but the revoke succeeds and the
    record goes — otherwise every host carrying its own copy of a shipped
    name would be permanently un-revokable.
    """
    plan = build_revoke_plan(manager, home=host)
    result = execute_revoke(plan, manager)

    assert result.success
    assert result.benign_leftovers == [str(host / ".claude" / "skills" / "customers-own")]
    assert not manager.exists()
