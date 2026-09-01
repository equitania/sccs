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


def _bundle_at(source_home: Path, tmp_path: Path, local_path: str, out_name: str) -> Path:
    """A second bundle shipping the same skill under a different local_path."""
    src = source_home / local_path.removeprefix("~/")
    src.mkdir(parents=True, exist_ok=True)
    for name in ("odoo-common",):
        (src / name).mkdir(parents=True, exist_ok=True)
        (src / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: t\n---\n\nBody of {name}.\n", encoding="utf-8"
        )
    config = SccsConfig.model_validate(
        {
            "repository": {"path": str(source_home / "repo")},
            "sync_categories": {
                "claude_skills": {
                    "enabled": True,
                    "local_path": local_path,
                    "repo_path": ".claude/skills",
                    "item_type": "directory",
                    "item_marker": "SKILL.md",
                    "include": ["*"],
                }
            },
        }
    )
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"claude_skills": ["odoo-common"]},
    )
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / out_name
    assert build_bundle(config, resolved, out, {}).success
    return out


def test_a_relocated_category_still_checks_the_new_path(bundle, source_home, tmp_path, monkeypatch):
    """Ownership is a fact about a PATH, not about a (category, name) pair.

    The first bundle maps `claude_skills` to `~/.claude/skills` and the
    receipt records `odoo-common` there as ours. A later bundle — a changed
    maintainer config, or an export from a second machine — maps the same
    category to `~/.claude/skills-alt`, where the customer has their own
    `odoo-common`. Keyed on `(category, name)` the stored claim answers
    "ours" for a directory no install has ever touched, no `exists()` check
    runs, and the import writes over the customer's work.
    """
    second = _bundle_at(source_home, tmp_path, "~/.claude/skills-alt", "alt.zip")

    target = tmp_path / "target-alt"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    assert install_bundle(bundle, config=None, receipt_manager=manager).success

    theirs = target / ".claude" / "skills-alt" / "odoo-common"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("# the customer's own\n", encoding="utf-8")

    outcome = install_bundle(second, config=None, receipt_manager=manager)

    assert outcome.skipped_foreign == ["claude_skills/odoo-common"]
    assert (theirs / "SKILL.md").read_text(encoding="utf-8") == "# the customer's own\n"
    record = manager.load().find("t")
    assert {(e.target, e.pre_existing) for e in record.entries} == {(str(theirs), True)}


# --- Final review, CRITICAL 1: pre_existing is sticky, foreign targets are skipped ---


def test_reinstall_keeps_pre_existing_false_for_our_own_artefacts(bundle, tmp_path, monkeypatch):
    """A second install must not relabel our own artefacts as "not ours".

    `pre_existing` used to be recomputed from `target.exists()` on every
    install. The second run therefore saw the files the FIRST run wrote and
    marked everything True — after which revoke buckets the whole payload
    `untouched` and reports a clean host with the skills still on it.
    """
    target = tmp_path / "sticky"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    install_bundle(bundle, config=None, receipt_manager=manager)
    outcome = install_bundle(bundle, config=None, receipt_manager=manager)

    record = manager.load().find("t")
    assert {e.name: e.pre_existing for e in record.entries} == {"odoo-common": False, "odoo19": False}
    assert outcome.skipped_foreign == []
    assert outcome.installed == 2

    # And revoke still takes them back.
    from sccs.deploy.revoke import build_revoke_plan, execute_revoke

    plan = build_revoke_plan(manager, home=target)
    assert {i.entry.name for i in plan.to_remove} == {"odoo-common", "odoo19"}
    execute_revoke(plan, manager)
    assert not (target / ".claude" / "skills" / "odoo-common").exists()
    assert not (target / ".claude" / "skills" / "odoo19").exists()


def test_foreign_target_is_skipped_not_overwritten(bundle, tmp_path, monkeypatch):
    """A file SCCS did not write is never displaced, and that is reported."""
    target = tmp_path / "foreign"
    _switch_home(monkeypatch, target)
    existing = target / ".claude" / "skills" / "odoo-common"
    existing.mkdir(parents=True)
    customer_text = "the customer's own odoo-common\n"
    (existing / "SKILL.md").write_text(customer_text, encoding="utf-8")
    (existing / "notes.md").write_text("their notes\n", encoding="utf-8")

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    outcome = install_bundle(bundle, config=None, receipt_manager=manager)

    assert outcome.success
    assert outcome.skipped_foreign == ["claude_skills/odoo-common"]
    assert outcome.installed == 1

    # Byte-identical, and their extra file survives — proof nothing of ours
    # landed and no copytree replaced the tree.
    assert (existing / "SKILL.md").read_text(encoding="utf-8") == customer_text
    assert (existing / "notes.md").read_text(encoding="utf-8") == "their notes\n"

    record = manager.load().find("t")
    marks = {e.name: e.pre_existing for e in record.entries}
    assert marks["odoo-common"] is True
    assert marks["odoo19"] is False


def test_foreign_target_stays_foreign_on_reinstall(bundle, tmp_path, monkeypatch):
    """Once seen as somebody else's, always somebody else's."""
    target = tmp_path / "foreign2"
    _switch_home(monkeypatch, target)
    existing = target / ".claude" / "skills" / "odoo-common"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("theirs\n", encoding="utf-8")

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    install_bundle(bundle, config=None, receipt_manager=manager)
    outcome = install_bundle(bundle, config=None, receipt_manager=manager)

    assert outcome.skipped_foreign == ["claude_skills/odoo-common"]
    assert (existing / "SKILL.md").read_text(encoding="utf-8") == "theirs\n"
    record = manager.load().find("t")
    assert {e.name: e.pre_existing for e in record.entries}["odoo-common"] is True


# --- Final review, IMPORTANT 2: no customer file ever reaches the backup dir ---


def test_install_never_backs_anything_up(bundle, tmp_path, monkeypatch):
    """`~/.config/sccs/backups/` must stay empty during a deploy install.

    Nothing foreign is written over, so a backup could only hold a previous
    copy of our own artefact — one more place our knowledge would sit on a
    customer host after `revoke`.
    """
    target = tmp_path / "nobackup"
    _switch_home(monkeypatch, target)
    existing = target / ".claude" / "skills" / "odoo-common"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("theirs\n", encoding="utf-8")

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    install_bundle(bundle, config=None, receipt_manager=manager)
    install_bundle(bundle, config=None, receipt_manager=manager)

    assert not (target / ".config" / "sccs" / "backups").exists()


# --- Final review, IMPORTANT 3: whose ~/.config/sccs/ is it? ---


def test_state_dir_recorded_as_ours_when_we_created_it(bundle, tmp_path, monkeypatch):
    target = tmp_path / "ourstate"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    install_bundle(bundle, config=None, receipt_manager=manager)

    assert manager.load().find("t").state_dir_pre_existing is False


def test_state_dir_recorded_as_the_hosts_own_when_it_existed(bundle, tmp_path, monkeypatch):
    target = tmp_path / "theirstate"
    _switch_home(monkeypatch, target)
    (target / ".config" / "sccs").mkdir(parents=True)
    (target / ".config" / "sccs" / "config.yaml").write_text("repository:\n  path: ~/x\n", encoding="utf-8")

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    install_bundle(bundle, config=None, receipt_manager=manager)

    assert manager.load().find("t").state_dir_pre_existing is True


def test_state_dir_ownership_is_sticky(bundle, tmp_path, monkeypatch):
    """The second install must not conclude the directory is ours.

    By then WE have written the receipt into it, so a fresh `exists()` check
    says True for a directory we did not create.
    """
    target = tmp_path / "stickystate"
    _switch_home(monkeypatch, target)
    (target / ".config" / "sccs").mkdir(parents=True)

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    install_bundle(bundle, config=None, receipt_manager=manager)
    install_bundle(bundle, config=None, receipt_manager=manager)

    assert manager.load().find("t").state_dir_pre_existing is True


# --- Final review, ALSO FIX: a corrupt receipt must be caught before writing ---


def test_corrupt_receipt_aborts_before_any_file_is_written(bundle, tmp_path, monkeypatch):
    target = tmp_path / "corrupt"
    _switch_home(monkeypatch, target)
    receipt_path = target / ".config" / "sccs" / ".deploy_receipt.yaml"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text("version: 1\ninstalls: [ this is not: valid\n", encoding="utf-8")

    manager = ReceiptManager(receipt_path)
    outcome = install_bundle(bundle, config=None, receipt_manager=manager)

    assert not outcome.success
    assert any("receipt" in e.lower() for e in outcome.errors)
    # Nothing was written — no orphaned install without a record.
    assert not (target / ".claude" / "skills").exists()


# --- Final review, CRITICAL 2: a single-file category through deploy install ---


@pytest.fixture
def starship_bundle(tmp_path, monkeypatch):
    """A deployment bundle whose category's local_path IS the file."""
    home = tmp_path / "sf-source"
    (home / ".config").mkdir(parents=True)
    (home / ".config" / "starship.toml").write_text('format = "$all"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)

    config = SccsConfig.model_validate(
        {
            "repository": {"path": str(home / "repo")},
            "sync_categories": {
                "starship_config": {
                    "enabled": True,
                    "local_path": "~/.config/starship.toml",
                    "repo_path": "config/starship.toml",
                    "item_type": "file",
                }
            },
        }
    )
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"starship_config": ["starship.toml"]},
    )
    resolved = resolve_profile(config, "sf", {"sf": profile})
    out = tmp_path / "starship.zip"
    assert build_bundle(config, resolved, out, {}).success
    return out


def test_single_file_category_installs_onto_a_bare_host(starship_bundle, tmp_path, monkeypatch):
    target = tmp_path / "sf-bare"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(starship_bundle, config=None, receipt_manager=manager)

    assert outcome.success, outcome.errors
    assert (target / ".config" / "starship.toml").read_text(encoding="utf-8") == 'format = "$all"\n'
    record = manager.load().find("sf")
    assert [e.target for e in record.entries] == [str(target / ".config" / "starship.toml")]


def test_single_file_category_on_a_host_that_already_has_the_file(starship_bundle, tmp_path, monkeypatch):
    """The crash case: `~/.config/starship.toml` exists, so the old code

    built `~/.config/starship.toml/starship.toml` and `mkdir(parents=True)`
    raised FileExistsError outside the per-item try — a traceback out of
    `install_bundle`, files already on disk and no receipt written.
    """
    target = tmp_path / "sf-occupied"
    _switch_home(monkeypatch, target)
    (target / ".config").mkdir(parents=True)
    (target / ".config" / "starship.toml").write_text("# the customer's prompt\n", encoding="utf-8")

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    outcome = install_bundle(starship_bundle, config=None, receipt_manager=manager)

    # No traceback, a receipt exists, and the customer's file is untouched
    # because it is foreign (CRITICAL 1's ownership rule).
    assert outcome.success, outcome.errors
    assert outcome.skipped_foreign == ["starship_config/starship.toml"]
    assert (target / ".config" / "starship.toml").read_text(encoding="utf-8") == "# the customer's prompt\n"
    record = manager.load().find("sf")
    assert record is not None
    assert record.entries[0].pre_existing is True
