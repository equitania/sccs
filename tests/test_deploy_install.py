"""Installation: pre-existing detection, home guard, receipt writing."""

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.config.schema import SccsConfig
from sccs.deploy.bundle import build_bundle
from sccs.deploy.install import install_bundle
from sccs.deploy.receipt import ReceiptManager
from sccs.deploy.resolve import resolve_profile
from sccs.deploy.schema import DeploymentProfile


@pytest.fixture
def source_home(tmp_path, monkeypatch):
    """The exporting machine."""
    home = tmp_path / "source"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    skills = home / ".claude" / "skills"
    for name in ("odoo-common", "odoo19"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: t\n---\n\nBody of {name}.\n", encoding="utf-8"
        )
    return home


@pytest.fixture
def source_config(source_home):
    return SccsConfig.model_validate(
        {
            "repository": {"path": str(source_home / "repo")},
            "sync_categories": {
                "claude_skills": {
                    "enabled": True,
                    "local_path": "~/.claude/skills",
                    "repo_path": ".claude/skills",
                    "item_type": "directory",
                    "item_marker": "SKILL.md",
                    "include": ["*"],
                }
            },
        }
    )


@pytest.fixture
def bundle(source_config, tmp_path):
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"claude_skills": ["odoo-common", "odoo19"]},
    )
    resolved = resolve_profile(source_config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    assert build_bundle(source_config, resolved, out, {}).success
    return out


def _switch_home(monkeypatch, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)


def test_install_writes_items_and_receipt(bundle, tmp_path, monkeypatch):
    target = tmp_path / "target"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(bundle, config=None, receipt_manager=manager)

    assert outcome.success
    assert outcome.installed == 2
    assert (target / ".claude" / "skills" / "odoo-common" / "SKILL.md").exists()

    record = manager.load().find("t")
    assert record is not None
    assert {e.name for e in record.entries} == {"odoo-common", "odoo19"}
    assert all(e.content_hash for e in record.entries)


def test_pre_existing_item_is_marked(bundle, tmp_path, monkeypatch):
    target = tmp_path / "target"
    _switch_home(monkeypatch, target)
    existing = target / ".claude" / "skills" / "odoo-common"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("customer's own\n", encoding="utf-8")

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    install_bundle(bundle, config=None, receipt_manager=manager)

    record = manager.load().find("t")
    marks = {e.name: e.pre_existing for e in record.entries}
    assert marks["odoo-common"] is True
    assert marks["odoo19"] is False


def test_dry_run_writes_nothing(bundle, tmp_path, monkeypatch):
    target = tmp_path / "target"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(bundle, config=None, receipt_manager=manager, dry_run=True)

    assert outcome.success
    assert not (target / ".claude" / "skills" / "odoo-common").exists()
    assert not manager.exists()


def test_bundle_without_deployment_section_is_refused(source_config, tmp_path, monkeypatch):
    """`sccs deploy install` takes deployment bundles, not plain exports."""
    from sccs.transfer.exporter import Exporter

    exporter = Exporter(source_config)
    scanned = exporter.scan_available_items()
    plain = tmp_path / "plain.zip"
    exporter.export_to_zip(exporter.build_selections_all(scanned), plain, {})

    target = tmp_path / "target2"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(plain, config=None, receipt_manager=manager)
    assert not outcome.success
    assert any("deployment" in e.lower() for e in outcome.errors)


def test_target_outside_home_is_refused(bundle, tmp_path, monkeypatch):
    """A manifest local_path outside HOME is rejected even in legacy mode."""
    import zipfile

    import yaml

    from sccs.transfer.manifest import MANIFEST_FILENAME

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(bundle) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == MANIFEST_FILENAME:
                doc = yaml.safe_load(data.decode("utf-8"))
                doc["categories"]["claude_skills"]["local_path"] = "/etc/sccs-evil"
                data = yaml.dump(doc).encode("utf-8")
            dst.writestr(info, data)

    target = tmp_path / "target3"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(tampered, config=None, receipt_manager=manager)
    assert not outcome.success
    assert any("home" in e.lower() for e in outcome.errors)
    assert not Path("/etc/sccs-evil").exists()


def test_reinstall_updates_the_record(bundle, tmp_path, monkeypatch):
    target = tmp_path / "target4"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    install_bundle(bundle, config=None, receipt_manager=manager)
    install_bundle(bundle, config=None, receipt_manager=manager)

    receipt = manager.load()
    assert len(receipt.installs) == 1
    assert len(receipt.installs[0].entries) == 2
