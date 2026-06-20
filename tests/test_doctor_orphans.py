# SCCS Doctor — Orphan-cleanup tests
#
# Covers GsdOrphanDetector (manifest-driven orphan detection), the installer's
# move-to-backup cleanup action, and the reporter block. The cleanup exists
# because gsd-core's own legacy cleanup leaves orphaned skills/ and agents/
# from a superseded package (e.g. @opengsd/get-shit-done-redux) behind.

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from rich.console import Console as RichConsole

from sccs.doctor.detectors import (
    ClaudeCliStatus,
    GsdOrphanDetector,
    NodeStatus,
    NpxToolStatus,
)
from sccs.doctor.installer import (
    _managed_orphan_cleanup_actions,
    build_update_plan,
)
from sccs.doctor.reporter import has_problems, render_doctor_report
from sccs.doctor.schema import NpxToolSpec

# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _spec(cfg: Path) -> NpxToolSpec:
    return NpxToolSpec(
        name="@opengsd/gsd-core",
        invocation=["npx", "@opengsd/gsd-core"],
        managed_file_manifest=str(cfg / "gsd-file-manifest.json"),
        managed_scan_dirs=[
            str(cfg / "skills"),
            str(cfg / "agents"),
            str(cfg / "hooks"),
            str(cfg / "commands"),
        ],
        managed_legacy_dirs=[str(cfg / "get-shit-done")],
    )


def _write_manifest(cfg: Path, files: list[str], *, version: str = "1.5.0") -> None:
    (cfg / "gsd-file-manifest.json").write_text(json.dumps({"version": version, "files": {k: "hash" for k in files}}))


def _skill(cfg: Path, name: str) -> None:
    (cfg / "skills" / name).mkdir(parents=True, exist_ok=True)
    (cfg / "skills" / name / "SKILL.md").write_text("x")


def _agent(cfg: Path, name: str) -> None:
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    (cfg / "agents" / name).write_text("x")


def _status(spec: NpxToolSpec) -> NpxToolStatus:
    return NpxToolStatus(spec=spec, available=True, binary_path=None, detection_source="state")


# --------------------------------------------------------------------------- #
# Detector                                                                     #
# --------------------------------------------------------------------------- #


class TestGsdOrphanDetector:
    def test_flags_orphan_skills_and_agents_keeps_owned(self, tmp_path: Path):
        cfg = tmp_path / ".claude"
        _skill(cfg, "gsd-keep")
        _skill(cfg, "gsd-orphan")
        _skill(cfg, "playwright-cli")  # different tool — must be ignored
        _agent(cfg, "gsd-keep.md")
        _agent(cfg, "gsd-dead.md")
        _agent(cfg, "my-own.md")  # not gsd-* — must be ignored
        _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "agents/gsd-keep.md", "gsd-core/VERSION"])

        st = GsdOrphanDetector().get_statuses([_spec(cfg)])[0]

        names = sorted(p.name for p in st.orphan_paths)
        assert names == ["gsd-dead.md", "gsd-orphan"]
        assert st.manifest_found is True
        assert st.scanned is True
        assert st.has_orphans is True

    def test_legacy_dir_not_orphan_before_migration(self, tmp_path: Path):
        """While the manifest still owns the legacy tree, the dir is NOT an
        orphan — but legacy_present flags that a migration is due."""
        cfg = tmp_path / ".claude"
        (cfg / "get-shit-done").mkdir(parents=True)
        (cfg / "get-shit-done" / "VERSION").write_text("1.1.0")
        _skill(cfg, "gsd-keep")
        # redux-style manifest: still owns get-shit-done/
        _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "get-shit-done/VERSION"])

        st = GsdOrphanDetector().get_statuses([_spec(cfg)])[0]

        assert st.legacy_present is True
        assert st.legacy_dirs == []
        assert st.has_orphans is False

    def test_legacy_dir_orphan_after_migration(self, tmp_path: Path):
        """Once the manifest reflects the new layout, the legacy dir becomes an
        orphan."""
        cfg = tmp_path / ".claude"
        (cfg / "get-shit-done").mkdir(parents=True)
        (cfg / "get-shit-done" / "VERSION").write_text("1.1.0")
        _skill(cfg, "gsd-keep")
        _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "gsd-core/VERSION"])

        st = GsdOrphanDetector().get_statuses([_spec(cfg)])[0]

        assert st.legacy_present is True
        assert [p.name for p in st.legacy_dirs] == ["get-shit-done"]
        assert any(p.name == "get-shit-done" for p in st.orphan_paths)

    def test_missing_manifest_reports_unknown(self, tmp_path: Path):
        cfg = tmp_path / ".claude"
        _skill(cfg, "gsd-orphan")
        (cfg / "get-shit-done").mkdir(parents=True)
        # no manifest written

        st = GsdOrphanDetector().get_statuses([_spec(cfg)])[0]

        assert st.manifest_found is False
        assert st.scanned is False
        assert st.has_orphans is False
        # legacy_present still derives from disk, independent of the manifest
        assert st.legacy_present is True

    def test_malformed_manifest_reports_unknown(self, tmp_path: Path):
        cfg = tmp_path / ".claude"
        _skill(cfg, "gsd-orphan")
        (cfg / "gsd-file-manifest.json").write_text("{ not valid json")

        st = GsdOrphanDetector().get_statuses([_spec(cfg)])[0]

        assert st.manifest_found is False
        assert st.has_orphans is False

    def test_skips_tools_without_manifest(self, tmp_path: Path):
        spec = NpxToolSpec(name="playwright-cli", invocation=["npm", "i"])
        assert GsdOrphanDetector().get_statuses([spec]) == []


# --------------------------------------------------------------------------- #
# Installer cleanup action                                                     #
# --------------------------------------------------------------------------- #


class TestOrphanCleanupAction:
    def test_queued_when_orphans_present(self, tmp_path: Path):
        cfg = tmp_path / ".claude"
        _skill(cfg, "gsd-orphan")
        _write_manifest(cfg, ["gsd-core/VERSION"])
        spec = _spec(cfg)
        gsd = GsdOrphanDetector().get_statuses([spec])

        actions = _managed_orphan_cleanup_actions([_status(spec)], gsd)

        assert len(actions) == 1
        action = actions[0]
        assert action.component == "orphan-cleanup:@opengsd/gsd-core"
        assert action.depends_on_components == ("npx:@opengsd/gsd-core",)
        # delete-class operation → never silently auto-confirmed
        assert action.auto_confirm is False

    def test_queued_when_only_legacy_present(self, tmp_path: Path):
        """Pre-migration: manifest owns everything (0 orphans) but the legacy
        dir is on disk → the cleanup must still be queued."""
        cfg = tmp_path / ".claude"
        (cfg / "get-shit-done").mkdir(parents=True)
        _skill(cfg, "gsd-keep")
        _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "get-shit-done/VERSION"])
        spec = _spec(cfg)
        gsd = GsdOrphanDetector().get_statuses([spec])
        assert gsd[0].has_orphans is False and gsd[0].legacy_present is True

        actions = _managed_orphan_cleanup_actions([_status(spec)], gsd)
        assert len(actions) == 1

    def test_not_queued_when_clean(self, tmp_path: Path):
        cfg = tmp_path / ".claude"
        _skill(cfg, "gsd-keep")
        _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "gsd-core/VERSION"])
        spec = _spec(cfg)
        gsd = GsdOrphanDetector().get_statuses([spec])

        assert _managed_orphan_cleanup_actions([_status(spec)], gsd) == []

    def test_builder_does_no_fs_io_when_orphans_none(self, tmp_path: Path):
        """Plan builder stays test-isolated: with gsd_orphans=None it queues
        nothing even though orphans exist on disk."""
        cfg = tmp_path / ".claude"
        _skill(cfg, "gsd-orphan")
        _write_manifest(cfg, ["gsd-core/VERSION"])
        spec = _spec(cfg)

        assert _managed_orphan_cleanup_actions([_status(spec)], None) == []

    def test_move_to_backup_preserves_structure(self, tmp_path: Path, monkeypatch):
        home = tmp_path
        cfg = home / ".claude"
        _skill(cfg, "gsd-keep")
        _skill(cfg, "gsd-orphan")
        _agent(cfg, "gsd-dead.md")
        (cfg / "get-shit-done").mkdir(parents=True)
        (cfg / "get-shit-done" / "VERSION").write_text("1.1.0")
        _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "gsd-core/VERSION"])
        spec = _spec(cfg)
        gsd = GsdOrphanDetector().get_statuses([spec])

        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        actions = _managed_orphan_cleanup_actions([_status(spec)], gsd)
        actions[0].python_callable()

        assert not (cfg / "skills" / "gsd-orphan").exists()
        assert not (cfg / "agents" / "gsd-dead.md").exists()
        assert not (cfg / "get-shit-done").exists()
        # owned artefact untouched
        assert (cfg / "skills" / "gsd-keep").exists()

        backups = list((home / ".config" / "sccs").glob("gsd-orphans-backup-*"))
        assert len(backups) == 1
        moved = {p.relative_to(backups[0]).as_posix() for p in backups[0].rglob("*") if p.is_file()}
        assert moved == {
            "skills/gsd-orphan/SKILL.md",
            "agents/gsd-dead.md",
            "get-shit-done/VERSION",
        }

    def test_closure_redetects_against_fresh_manifest(self, tmp_path: Path, monkeypatch):
        """The action is built from the PRE-migration status (0 orphans, legacy
        present), but the closure re-detects against the manifest as it exists
        when it runs — simulating the install rewriting it in between."""
        home = tmp_path
        cfg = home / ".claude"
        (cfg / "get-shit-done").mkdir(parents=True)
        (cfg / "get-shit-done" / "VERSION").write_text("1.1.0")
        _skill(cfg, "gsd-stale")
        # redux manifest still owns everything → status has 0 orphans
        _write_manifest(cfg, ["skills/gsd-stale/SKILL.md", "get-shit-done/VERSION"])
        spec = _spec(cfg)
        pre = GsdOrphanDetector().get_statuses([spec])
        assert pre[0].has_orphans is False and pre[0].legacy_present is True

        actions = _managed_orphan_cleanup_actions([_status(spec)], pre)
        assert len(actions) == 1

        # Simulate the gsd-core install rewriting the manifest (drops ownership
        # of gsd-stale and the legacy dir).
        _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "gsd-core/VERSION"])

        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        actions[0].python_callable()

        assert not (cfg / "skills" / "gsd-stale").exists()
        assert not (cfg / "get-shit-done").exists()

    def test_idempotent_noop_on_clean_state(self, tmp_path: Path, monkeypatch):
        home = tmp_path
        cfg = home / ".claude"
        _skill(cfg, "gsd-keep")
        _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "gsd-core/VERSION"])
        spec = _spec(cfg)
        # craft a status that *would* queue (pretend orphans), then run closure
        # against the actually-clean tree → no move, no backup dir.
        from sccs.doctor.detectors import GsdOrphanStatus

        fake = GsdOrphanStatus(tool_name=spec.name, manifest_found=True, orphan_paths=[cfg / "skills" / "ghost"])
        actions = _managed_orphan_cleanup_actions([_status(spec)], [fake])
        assert len(actions) == 1

        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        actions[0].python_callable()  # closure re-detects → nothing real → no-op

        assert (cfg / "skills" / "gsd-keep").exists()
        assert not list((home / ".config" / "sccs").glob("gsd-orphans-backup-*"))


# --------------------------------------------------------------------------- #
# build_update_plan integration                                               #
# --------------------------------------------------------------------------- #


def _node_ok() -> NodeStatus:
    return NodeStatus(
        installed=True, version="22.1.0", major=22, meets_minimum=True, install_hint=None, platform="linux"
    )


def test_build_update_plan_queues_cleanup_when_orphans(tmp_path: Path):
    cfg = tmp_path / ".claude"
    _skill(cfg, "gsd-orphan")
    _write_manifest(cfg, ["gsd-core/VERSION"])
    spec = _spec(cfg)
    gsd = GsdOrphanDetector().get_statuses([spec])

    plan = build_update_plan(
        None,
        node=_node_ok(),
        claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
        plugins=[],
        npx_tools=[_status(spec)],
        gsd_orphans=gsd,
    )
    labels = [a.component for a in plan.actions]
    assert "orphan-cleanup:@opengsd/gsd-core" in labels


def test_build_update_plan_no_cleanup_without_gsd_orphans(tmp_path: Path):
    cfg = tmp_path / ".claude"
    _skill(cfg, "gsd-orphan")
    _write_manifest(cfg, ["gsd-core/VERSION"])
    spec = _spec(cfg)

    plan = build_update_plan(
        None,
        node=_node_ok(),
        claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
        plugins=[],
        npx_tools=[_status(spec)],
        gsd_orphans=None,
    )
    assert all(not a.component.startswith("orphan-cleanup:") for a in plan.actions)


# --------------------------------------------------------------------------- #
# Reporter                                                                     #
# --------------------------------------------------------------------------- #


def _render(gsd_orphans):
    buf = StringIO()
    console = RichConsole(file=buf, width=200, force_terminal=False, color_system=None)
    render_doctor_report(
        console,
        node=_node_ok(),
        claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
        plugins=[],
        npx_tools=[],
        min_node_major=22,
        gsd_orphans=gsd_orphans,
    )
    return buf.getvalue()


def test_reporter_shows_orphan_block(tmp_path: Path):
    cfg = tmp_path / ".claude"
    _skill(cfg, "gsd-orphan")
    _write_manifest(cfg, ["gsd-core/VERSION"])
    gsd = GsdOrphanDetector().get_statuses([_spec(cfg)])

    out = _render(gsd)
    assert "Orphaned doctor-managed artefacts" in out
    assert "gsd-orphan" in out


def test_reporter_silent_when_no_orphans(tmp_path: Path):
    cfg = tmp_path / ".claude"
    _skill(cfg, "gsd-keep")
    _write_manifest(cfg, ["skills/gsd-keep/SKILL.md", "gsd-core/VERSION"])
    gsd = GsdOrphanDetector().get_statuses([_spec(cfg)])

    out = _render(gsd)
    assert "Orphaned doctor-managed artefacts" not in out


def test_has_problems_true_with_orphans(tmp_path: Path):
    cfg = tmp_path / ".claude"
    _skill(cfg, "gsd-orphan")
    _write_manifest(cfg, ["gsd-core/VERSION"])
    gsd = GsdOrphanDetector().get_statuses([_spec(cfg)])

    assert (
        has_problems(
            node=_node_ok(),
            claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
            plugins=[],
            npx_tools=[],
            gsd_orphans=gsd,
        )
        is True
    )
