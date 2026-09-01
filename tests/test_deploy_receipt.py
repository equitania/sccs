"""Receipt persistence: round trip, re-install, removal."""

from __future__ import annotations

import pytest

from sccs.deploy.receipt import (
    DeployReceipt,
    InstallRecord,
    ReceiptEntry,
    ReceiptManager,
)


@pytest.fixture
def manager(tmp_path):
    return ReceiptManager(tmp_path / ".deploy_receipt.yaml")


def _record(profile="odoo-server", names=("odoo-common",)):
    return InstallRecord(
        profile=profile,
        installed_at="2026-09-01T10:00:00+00:00",
        sccs_version="2.65.0",
        retain=["fish_config"],
        sweep_globs={"claude_skills": list(names)},
        entries=[
            ReceiptEntry(
                category="claude_skills",
                name=name,
                target=f"/home/u/.claude/skills/{name}",
                item_type="directory",
                content_hash="sha256:abc",
                pre_existing=False,
            )
            for name in names
        ],
    )


def test_missing_receipt_loads_empty(manager):
    receipt = manager.load()
    assert isinstance(receipt, DeployReceipt)
    assert receipt.installs == []
    assert not manager.exists()


def test_round_trip(manager):
    manager.record_install(_record())
    loaded = manager.load()
    assert len(loaded.installs) == 1
    assert loaded.installs[0].profile == "odoo-server"
    assert loaded.installs[0].entries[0].name == "odoo-common"
    assert loaded.installs[0].entries[0].pre_existing is False
    assert loaded.installs[0].sweep_globs == {"claude_skills": ["odoo-common"]}


def test_reinstall_replaces_record_of_same_profile(manager):
    manager.record_install(_record(names=("odoo-common",)))
    manager.record_install(_record(names=("odoo-common", "odoo19")))
    loaded = manager.load()
    assert len(loaded.installs) == 1
    assert len(loaded.installs[0].entries) == 2


def test_two_profiles_coexist(manager):
    manager.record_install(_record(profile="odoo-server"))
    manager.record_install(_record(profile="fastreport", names=("fr-reports",)))
    assert {r.profile for r in manager.load().installs} == {"odoo-server", "fastreport"}


def test_remove_install_drops_only_that_profile(manager):
    manager.record_install(_record(profile="odoo-server"))
    manager.record_install(_record(profile="fastreport", names=("fr-reports",)))
    manager.remove_install("odoo-server")
    assert [r.profile for r in manager.load().installs] == ["fastreport"]


def test_receipt_file_is_owner_only(manager, tmp_path):
    manager.record_install(_record())
    mode = (tmp_path / ".deploy_receipt.yaml").stat().st_mode & 0o777
    assert mode == 0o600


def test_corrupt_receipt_raises_rather_than_silently_emptying(manager, tmp_path):
    (tmp_path / ".deploy_receipt.yaml").write_text("{[not: yaml", encoding="utf-8")
    with pytest.raises(ValueError, match="receipt"):
        manager.load()


def test_unknown_version_raises(manager, tmp_path):
    (tmp_path / ".deploy_receipt.yaml").write_text("version: 99\ninstalls: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        manager.load()
