# Tests for sccs.doctor.bundled_mods — Claude Code mods that ship inside the
# package. Every test works on folders under tmp_path; none touches ~/.claude
# or ~/.local/share.

import json
import subprocess
from pathlib import Path

import pytest

from sccs.doctor import bundled_mods as bm
from sccs.doctor.bundled_mods import (
    BUNDLED_MARKETPLACE,
    BundledModDetector,
    available_mods,
    bundled_mod_actions,
    bundled_root,
    stage_marketplace,
)
from sccs.doctor.runner import DoctorError
from sccs.doctor.schema import DoctorConfig


def _marketplace(root: Path, mods: dict[str, str], name: str = BUNDLED_MARKETPLACE) -> Path:
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": name, "plugins": [{"name": m, "source": f"./{m}"} for m in mods]}), encoding="utf-8"
    )
    for mod, version in mods.items():
        (root / mod / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (root / mod / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": mod, "version": version}), encoding="utf-8"
        )
        (root / mod / "hooks").mkdir(exist_ok=True)
        (root / mod / "hooks" / "register.tsx").write_text(f"// {mod} {version}\n", encoding="utf-8")
    return root


@pytest.fixture
def detector(tmp_path: Path) -> BundledModDetector:
    return BundledModDetector(
        root=_marketplace(tmp_path / "pkg", {"paste-lens": "1.2.0"}),
        stage_dir=tmp_path / "stage",
        installed_plugins_path=tmp_path / "installed_plugins.json",
        known_marketplaces_path=tmp_path / "known_marketplaces.json",
    )


def _install(detector: BundledModDetector, version: str) -> None:
    detector.installed_plugins_path.write_text(
        json.dumps({"plugins": {f"paste-lens@{BUNDLED_MARKETPLACE}": [{"scope": "user", "version": version}]}}),
        encoding="utf-8",
    )


def _register(detector: BundledModDetector, path: Path | None = None) -> None:
    detector.known_marketplaces_path.write_text(
        json.dumps({BUNDLED_MARKETPLACE: {"source": {"source": "directory", "path": str(path or detector.stage_dir)}}}),
        encoding="utf-8",
    )


class TestPackage:
    def test_the_wheel_tree_lists_paste_lens_with_its_files(self):
        root = bundled_root()
        assert "paste-lens" in available_mods()
        assert (root / "paste-lens" / "hooks" / "hooks.json").is_file()
        assert (root / "paste-lens" / "hooks" / "register.tsx").is_file()
        assert (root / "paste-lens" / "types" / "index.d.ts").is_file()

    def test_marketplace_and_plugin_manifests_agree(self):
        root = bundled_root()
        manifest = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        assert manifest["name"] == BUNDLED_MARKETPLACE
        for entry in manifest["plugins"]:
            plugin = json.loads((root / entry["name"] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
            assert plugin["name"] == entry["name"]
            assert entry["source"] == f"./{entry['name']}"

    def test_a_name_that_could_be_a_path_is_never_a_mod(self, tmp_path):
        root = _marketplace(tmp_path / "pkg", {"ok-mod": "1.0.0"})
        manifest = root / ".claude-plugin" / "marketplace.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["plugins"].append({"name": "../evil", "source": "./x"})
        manifest.write_text(json.dumps(data), encoding="utf-8")
        assert list(available_mods(root)) == ["ok-mod"]


class TestConfig:
    def test_opt_in_is_empty_by_default(self):
        cfg = DoctorConfig()
        assert cfg.effective_bundled_mods() == []
        assert not any(p.marketplace == BUNDLED_MARKETPLACE for p in cfg.effective_plugins())

    def test_unknown_names_are_ignored(self):
        cfg = DoctorConfig(bundled_mods=["paste-lens", "does-not-exist", "../x"])
        assert cfg.effective_bundled_mods() == ["paste-lens"]

    def test_an_enabled_mod_is_known_but_never_generically_installed(self):
        cfg = DoctorConfig(bundled_mods=["paste-lens"])
        known = [p for p in cfg.effective_plugins() if p.marketplace == BUNDLED_MARKETPLACE]
        assert [p.name for p in known] == ["paste-lens"]
        assert all(p.allowlist_only for p in known)
        assert not any(p.marketplace == BUNDLED_MARKETPLACE for p in cfg.checkable_plugins())


class TestDetector:
    def test_fresh_host_is_missing(self, detector):
        (st,) = detector.get_statuses(["paste-lens", "nope"])
        assert (st.state, st.staged_current, st.marketplace_registered) == ("missing", False, False)
        assert st.bundled_version == "1.2.0"

    def test_older_install_is_outdated(self, detector):
        _install(detector, "1.1.0")
        assert detector.get_statuses(["paste-lens"])[0].state == "outdated"

    def test_current_host_is_ok(self, detector):
        stage_marketplace(detector.root, detector.stage_dir)
        _install(detector, "1.2.0")
        _register(detector)
        (st,) = detector.get_statuses(["paste-lens"])
        assert (st.state, st.staged_current, st.marketplace_registered) == ("ok", True, True)
        assert bundled_mod_actions([st]) == []

    def test_a_marketplace_registered_elsewhere_does_not_count(self, detector, tmp_path):
        _register(detector, tmp_path / "somewhere-else")
        assert detector.get_statuses(["paste-lens"])[0].marketplace_registered is False

    def test_nothing_enabled_reads_no_files(self, detector):
        assert detector.get_statuses([]) == []


class TestStaging:
    def test_copy_replaces_an_older_copy_wholesale(self, detector):
        stage_marketplace(detector.root, detector.stage_dir)
        (detector.stage_dir / "paste-lens" / "left-over.txt").write_text("old", encoding="utf-8")
        stage_marketplace(detector.root, detector.stage_dir)
        assert not (detector.stage_dir / "paste-lens" / "left-over.txt").exists()
        assert (detector.stage_dir / "paste-lens" / "hooks" / "register.tsx").is_file()

    def test_a_foreign_folder_is_refused_and_left_alone(self, detector):
        detector.stage_dir.mkdir()
        (detector.stage_dir / "thesis.txt").write_text("mine", encoding="utf-8")
        with pytest.raises(DoctorError, match="refusing to replace"):
            stage_marketplace(detector.root, detector.stage_dir)
        assert (detector.stage_dir / "thesis.txt").read_text(encoding="utf-8") == "mine"

    def test_another_marketplace_is_refused(self, detector):
        _marketplace(detector.stage_dir, {"x": "1.0.0"}, name="someone-elses")
        with pytest.raises(DoctorError, match="refusing to replace"):
            stage_marketplace(detector.root, detector.stage_dir)

    def test_a_symlink_is_refused(self, detector, tmp_path):
        target = tmp_path / "target"
        target.mkdir()
        try:
            detector.stage_dir.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks not available on this host")
        with pytest.raises(DoctorError, match="not a plain folder"):
            stage_marketplace(detector.root, detector.stage_dir)


class TestActions:
    def test_fresh_host_stages_registers_installs(self, detector):
        actions = bundled_mod_actions(detector.get_statuses(["paste-lens"]))
        assert [a.component for a in actions] == [
            "bundled-mods:staged",
            "bundled-mods:marketplace",
            "bundled-mod:paste-lens",
        ]
        assert actions[1].cmd == ["claude", "plugin", "marketplace", "add", str(detector.stage_dir)]
        assert actions[2].cmd == ["claude", "plugin", "install", f"paste-lens@{BUNDLED_MARKETPLACE}"]
        assert actions[2].depends_on_components == ("bundled-mods:staged", "bundled-mods:marketplace")
        assert all(a.auto_confirm for a in actions)

    def test_new_package_version_restages_refreshes_updates(self, detector, tmp_path):
        stage_marketplace(_marketplace(tmp_path / "old", {"paste-lens": "1.1.0"}), detector.stage_dir)
        _install(detector, "1.1.0")
        _register(detector)
        actions = bundled_mod_actions(detector.get_statuses(["paste-lens"]))
        assert [a.cmd for a in actions[1:]] == [
            ["claude", "plugin", "marketplace", "update", BUNDLED_MARKETPLACE],
            ["claude", "plugin", "update", f"paste-lens@{BUNDLED_MARKETPLACE}"],
        ]

    def test_execute_runs_the_chain_and_a_failed_copy_stops_it(self, detector, monkeypatch):
        from sccs.doctor import installer
        from sccs.doctor.installer import InstallPlan, execute_plan

        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

        monkeypatch.setattr(installer, "_run", fake_run)
        plan = InstallPlan(actions=bundled_mod_actions(detector.get_statuses(["paste-lens"])))
        result = execute_plan(plan, assume_yes=False, print_fn=lambda _: None)
        assert [o.status for o in result.outcomes] == ["executed"] * 3
        assert (detector.stage_dir / ".claude-plugin" / "marketplace.json").is_file()
        assert [c[2:4] for c in calls] == [["marketplace", "add"], ["install", f"paste-lens@{BUNDLED_MARKETPLACE}"]]

        # A foreign folder in the way: nothing is registered or installed.
        calls.clear()
        blocked = BundledModDetector(
            root=detector.root,
            stage_dir=detector.stage_dir.parent / "taken",
            installed_plugins_path=detector.installed_plugins_path,
            known_marketplaces_path=detector.known_marketplaces_path,
        )
        blocked.stage_dir.mkdir()
        (blocked.stage_dir / "mine.txt").write_text("x", encoding="utf-8")
        plan = InstallPlan(actions=bundled_mod_actions(blocked.get_statuses(["paste-lens"])))
        result = execute_plan(plan, assume_yes=False, print_fn=lambda _: None)
        assert result.outcomes[0].status == "failed"
        assert calls == []

    def test_all_three_plans_carry_the_mod(self, detector):
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.installer import build_install_plan, build_optimize_plan, build_update_plan
        from sccs.doctor.schema import NodeInstallSpec

        node = NodeStatus(
            installed=True,
            version="22.0.0",
            major=22,
            meets_minimum=True,
            install_hint=NodeInstallSpec(runnable=False, label="x"),
            platform="macos",
        )
        base = {
            "node": node,
            "claude_cli": ClaudeCliStatus(installed=True, binary_path="/x/claude"),
            "plugins": [],
            "npx_tools": [],
            "bundled_mods": detector.get_statuses(["paste-lens"]),
        }
        cfg = DoctorConfig(bundled_mods=["paste-lens"])
        optimize = build_optimize_plan(cfg, **base, foreign_plugins=[], mcp_servers=[], foreign_mcp_servers=[])
        for plan in (build_install_plan(cfg, **base), build_update_plan(cfg, **base), optimize):
            assert any(a.component == "bundled-mod:paste-lens" for a in plan.actions)


class TestReporter:
    def test_rows_and_problems(self, detector):
        from sccs.doctor.reporter import _MISSING, _OK, _OUTDATED, _bundled_mod_row

        (missing,) = detector.get_statuses(["paste-lens"])
        assert _bundled_mod_row(missing)[1] == _MISSING
        _install(detector, "1.1.0")
        (outdated,) = detector.get_statuses(["paste-lens"])
        assert _bundled_mod_row(outdated)[1:3] == (_OUTDATED, "v1.1.0")
        _install(detector, "1.2.0")
        (ok,) = detector.get_statuses(["paste-lens"])
        assert _bundled_mod_row(ok)[1] == _OK
        assert (missing.needs_action, outdated.needs_action, ok.needs_action) == (True, True, False)


def test_module_constants_point_into_the_home_folder():
    assert bm.DEFAULT_STAGE_DIR.startswith("~/")
