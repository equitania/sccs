"""Receipt persistence: round trip, re-install, removal."""

from __future__ import annotations

from pathlib import Path

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


# --- Final review, MINOR 4: the default receipt path must not freeze HOME ---


def test_default_receipt_path_follows_the_current_home(tmp_path, monkeypatch):
    """It used to be a module constant, evaluated once at import time."""
    from sccs.deploy.receipt import ReceiptManager, default_receipt_path

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_receipt_path() == tmp_path / ".config" / "sccs" / ".deploy_receipt.yaml"
    assert ReceiptManager().path == tmp_path / ".config" / "sccs" / ".deploy_receipt.yaml"

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(Path, "home", lambda: other)
    assert default_receipt_path() == other / ".config" / "sccs" / ".deploy_receipt.yaml"


def test_state_dir_flag_round_trips_through_the_receipt(tmp_path):
    from sccs.deploy.receipt import InstallRecord, ReceiptManager

    manager = ReceiptManager(tmp_path / ".deploy_receipt.yaml")
    manager.record_install(
        InstallRecord(
            profile="p",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            state_dir_pre_existing=True,
        )
    )
    assert manager.load().find("p").state_dir_pre_existing is True


def test_an_old_receipt_without_the_flag_still_loads(tmp_path):
    """Receipts written before this field existed must keep loading."""
    import yaml as _yaml

    from sccs.deploy.receipt import ReceiptManager

    path = tmp_path / ".deploy_receipt.yaml"
    path.write_text(
        _yaml.dump(
            {
                "version": 1,
                "installs": [{"profile": "p", "installed_at": "x", "sccs_version": "2.65.0", "entries": []}],
            }
        ),
        encoding="utf-8",
    )
    assert ReceiptManager(path).load().find("p").state_dir_pre_existing is False
