# tests/test_doctor_mirror.py
"""v2.68.0: mirror parity — keep a second Mac identical to the live workstation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


class TestMirrorConfig:
    def test_repo_spec_accepts_ssh_and_https(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec

        MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        MirrorRepoSpec(url="https://gitlab.example/org/beam.git", path="~/gitbase/example/beam")

    @pytest.mark.parametrize(
        "url",
        ["ssh://evil/x", "file:///etc/passwd", "-oProxyCommand=x", "git@host:path with space"],
    )
    def test_repo_spec_rejects_other_schemes(self, home: Path, url: str):
        from sccs.doctor.mirror import MirrorRepoSpec

        with pytest.raises(ValidationError):
            MirrorRepoSpec(url=url, path="~/gitbase/example/beam")

    def test_repo_path_must_be_under_home(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec

        with pytest.raises(ValidationError):
            MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="/opt/beam")

    def test_ignore_lists_are_validated_names(self):
        from sccs.doctor.mirror import MirrorConfig

        with pytest.raises(ValidationError):
            MirrorConfig(source_host="live-mac", ignore_brew=["-rf"])

    def test_defaults(self):
        from sccs.doctor.mirror import MirrorConfig

        cfg = MirrorConfig(source_host="live-mac")
        assert cfg.cleanup is True
        assert cfg.brewfile == "~/.config/homebrew/Brewfile"
        assert cfg.inventory_path == "~/.config/sccs/inventory.yaml"
        assert cfg.fish_plugins == "~/.config/fish/fish_plugins"
        assert cfg.repos == []

    def test_doctor_config_carries_mirror(self):
        from sccs.doctor.schema import DoctorConfig

        cfg = DoctorConfig(mirror={"source_host": "live-mac"})
        assert cfg.mirror is not None
        assert cfg.mirror.source_host == "live-mac"
        assert DoctorConfig().mirror is None


class TestRoleResolution:
    def test_normalize_strips_domain_and_case(self):
        from sccs.doctor.mirror import normalize_host

        assert normalize_host("Live-Mac.local") == "live-mac"
        assert normalize_host("live-mac.example.net") == "live-mac"
        assert normalize_host("live-mac") == "live-mac"

    def test_source_when_hostname_matches(self):
        from sccs.doctor.mirror import MirrorConfig, resolve_role

        cfg = MirrorConfig(source_host="live-mac")
        assert resolve_role(cfg, hostname="Live-Mac.local") == "source"
        assert resolve_role(cfg, hostname="demo-mac") == "mirror"

    def test_off_without_config_or_source_host(self):
        from sccs.doctor.mirror import MirrorConfig, resolve_role

        assert resolve_role(None, hostname="x") == "off"
        assert resolve_role(MirrorConfig(source_host=None), hostname="x") == "off"

    def test_uses_current_hostname_by_default(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import MirrorConfig, resolve_role

        monkeypatch.setattr(mirror, "current_hostname", lambda: "live-mac.local")
        assert resolve_role(MirrorConfig(source_host="live-mac")) == "source"


class TestVersionPattern:
    @pytest.mark.parametrize("v", ["2.67.2", "0.1.18", "1.0.0-rc.1", "4.6.4+build"])
    def test_accepts(self, v: str):
        from sccs.doctor.mirror import _VERSION_PATTERN

        assert _VERSION_PATTERN.match(v)

    @pytest.mark.parametrize("v", ["", "-1", "1.0; rm", "v1.0", "1.0 2"])
    def test_rejects(self, v: str):
        from sccs.doctor.mirror import _VERSION_PATTERN

        assert not _VERSION_PATTERN.match(v)


class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class TestRunnerWrappers:
    def test_brew_lines_returns_stripped_nonempty_lines(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import runner

        seen: list[list[str]] = []

        def fake(cmd, **kw):
            seen.append(cmd)
            return _Proc(stdout="bat\n\nanomalyco/tap/opencode \n")

        monkeypatch.setattr(runner, "_run", fake)
        assert runner.run_brew_lines("leaves") == ["bat", "anomalyco/tap/opencode"]
        assert seen == [["brew", "leaves"]]

    def test_brew_lines_none_when_brew_missing(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import runner
        from sccs.doctor.runner import DoctorError

        def boom(cmd, **kw):
            raise DoctorError("brew: not found")

        monkeypatch.setattr(runner, "_run", boom)
        assert runner.run_brew_lines("leaves") is None

    def test_brew_bundle_dump_argv(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor import runner

        seen: list[list[str]] = []
        monkeypatch.setattr(runner, "_run", lambda cmd, **kw: (seen.append(cmd), _Proc())[1])
        assert runner.run_brew_bundle_dump(tmp_path / "Brewfile") is True
        assert seen == [["brew", "bundle", "dump", "--file", str(tmp_path / "Brewfile"), "--force"]]

    def test_brew_bundle_dump_logs_homebrews_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog):
        from sccs.doctor import runner

        monkeypatch.setattr(
            runner, "_run", lambda cmd, **kw: _Proc(stderr="Error: something Homebrew said\n", returncode=1)
        )
        with caplog.at_level("WARNING"):
            assert runner.run_brew_bundle_dump(tmp_path / "Brewfile") is False
        assert "something Homebrew said" in caplog.text

    def test_npm_global_list_returns_stdout_even_on_exit_1(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import runner

        monkeypatch.setattr(runner, "_run", lambda cmd, **kw: _Proc(stdout='{"dependencies": {}}', returncode=1))
        assert runner.run_npm_global_list() == '{"dependencies": {}}'

    def test_git_fetch_false_on_failure(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor import runner

        monkeypatch.setattr(runner, "_run", lambda cmd, **kw: _Proc(returncode=128))
        assert runner.run_git_fetch(tmp_path) is False

    def test_fisher_list_goes_through_fish(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import runner

        seen: list[list[str]] = []
        monkeypatch.setattr(
            runner, "_run", lambda cmd, **kw: (seen.append(cmd), _Proc(stdout="jorgebucaran/fisher\nedc/bass\n"))[1]
        )
        assert runner.run_fisher_list() == ["jorgebucaran/fisher", "edc/bass"]
        assert seen == [["fish", "-c", "fisher list"]]


UV_LIST = """agentmgr v0.2.2
- agentmgr
sccs v2.67.2
- sccs
odoodev-equitania v0.68.0
- odoodev
- odoodev-x
"""

NPM_JSON = """{
  "name": "lib",
  "dependencies": {
    "@playwright/cli": {"version": "0.1.18", "overridden": false},
    "less": {"version": "4.6.4"},
    "npm": {"version": "11.19.1"},
    "corepack": {"version": "0.34.0"}
  }
}"""


class TestInventory:
    def test_parse_uv_tool_list(self):
        from sccs.doctor.mirror import PackageRef, parse_uv_tool_list

        assert parse_uv_tool_list(UV_LIST) == [
            PackageRef(name="agentmgr", version="0.2.2"),
            PackageRef(name="sccs", version="2.67.2"),
            PackageRef(name="odoodev-equitania", version="0.68.0"),
        ]

    def test_parse_npm_drops_npm_and_corepack(self):
        from sccs.doctor.mirror import PackageRef, parse_npm_global_json

        assert parse_npm_global_json(NPM_JSON) == [
            PackageRef(name="@playwright/cli", version="0.1.18"),
            PackageRef(name="less", version="4.6.4"),
        ]

    def test_parse_npm_garbage_is_empty(self):
        from sccs.doctor.mirror import parse_npm_global_json

        assert parse_npm_global_json("not json") == []
        assert parse_npm_global_json('{"dependencies": {"x": {}}}') == []

    def test_roundtrip(self, tmp_path: Path):
        from sccs.doctor.mirror import Inventory, PackageRef, load_inventory, write_inventory

        inv = Inventory(
            captured_at="2026-09-15T10:00:00",
            captured_on="live-mac",
            uv_tools=[PackageRef(name="sccs", version="2.67.2")],
            npm_globals=[PackageRef(name="@playwright/cli", version="0.1.18")],
        )
        path = tmp_path / "inventory.yaml"
        write_inventory(path, inv)
        assert load_inventory(path) == inv
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Written by `sccs doctor update` on the source host")

    def test_load_missing_or_broken_is_none(self, tmp_path: Path):
        from sccs.doctor.mirror import load_inventory

        assert load_inventory(tmp_path / "nope.yaml") is None
        (tmp_path / "bad.yaml").write_text("uv_tools: [", encoding="utf-8")
        assert load_inventory(tmp_path / "bad.yaml") is None
        (tmp_path / "wrong.yaml").write_text("version: 1\nuv_tools: 3\n", encoding="utf-8")
        assert load_inventory(tmp_path / "wrong.yaml") is None

    def test_capture_uses_wrappers(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror

        monkeypatch.setattr(mirror, "run_uv_tool_list", lambda: UV_LIST)
        monkeypatch.setattr(mirror, "run_npm_global_list", lambda: NPM_JSON)
        inv = mirror.capture_inventory("live-mac")
        assert [p.name for p in inv.uv_tools] == ["agentmgr", "sccs", "odoodev-equitania"]
        assert [p.name for p in inv.npm_globals] == ["@playwright/cli", "less"]
        assert inv.captured_on == "live-mac"
        assert inv.version == 1

    def test_capture_carries_forward_previous_when_tool_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """v2.68.1 / finding F1: a transient `uv`/`npm` failure on the source
        must not write an empty inventory — every mirror would then see the
        whole area as extras and `optimize --strict` would propose removing
        it all. `None` from the wrapper (tool absent OR the run failed) keeps
        the PREVIOUS inventory's entries for that area instead."""
        import logging

        from sccs.doctor import mirror
        from sccs.doctor.mirror import Inventory, PackageRef

        monkeypatch.setattr(mirror, "run_uv_tool_list", lambda: None)
        monkeypatch.setattr(mirror, "run_npm_global_list", lambda: NPM_JSON)
        previous = Inventory(
            captured_at="2026-09-14T10:00:00",
            captured_on="live-mac",
            uv_tools=[PackageRef(name="sccs", version="2.67.2")],
            npm_globals=[],
        )
        with caplog.at_level(logging.WARNING, logger="sccs.doctor.mirror"):
            inv = mirror.capture_inventory("live-mac", previous)
        assert inv.uv_tools == previous.uv_tools
        assert [p.name for p in inv.npm_globals] == ["@playwright/cli", "less"]
        assert any("keeping the previous inventory's 1 entries" in r.message for r in caplog.records)

    def test_capture_is_empty_with_warning_when_no_previous(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        import logging

        from sccs.doctor import mirror

        monkeypatch.setattr(mirror, "run_uv_tool_list", lambda: None)
        monkeypatch.setattr(mirror, "run_npm_global_list", lambda: NPM_JSON)
        with caplog.at_level(logging.WARNING, logger="sccs.doctor.mirror"):
            inv = mirror.capture_inventory("live-mac", None)
        assert inv.uv_tools == []
        assert any("no previous inventory, recording an empty list" in r.message for r in caplog.records)


BREWFILE = """tap "anomalyco/tap"
tap "eqms/claude-workbench", trusted: true
brew "bat"
brew "sleepwatcher", restart_service: :changed
brew "anomalyco/tap/opencode", trusted: true
cask "iterm2"
# comment
vscode "ms-python.python"
"""


class TestBrewfile:
    def test_parse_takes_first_quoted_token(self):
        from sccs.doctor.mirror import parse_brewfile

        s = parse_brewfile(BREWFILE)
        assert s.taps == {"anomalyco/tap", "eqms/claude-workbench"}
        assert s.formulae == {"bat", "sleepwatcher", "anomalyco/tap/opencode"}
        assert s.casks == {"iterm2"}


class TestBrewDetector:
    def _stub(self, monkeypatch, *, leaves, formulae, casks, taps):
        from sccs.doctor import mirror

        table = {
            ("leaves",): leaves,
            ("list", "--formula", "--full-name"): formulae,
            ("list", "--cask"): casks,
            ("tap",): taps,
        }
        monkeypatch.setattr(mirror, "run_brew_lines", lambda *args: table[args])

    def test_drift_missing_and_extra(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor.mirror import BrewDetector

        (tmp_path / "Brewfile").write_text(BREWFILE, encoding="utf-8")
        self._stub(
            monkeypatch,
            leaves=["bat", "ffmpeg"],
            formulae=["bat", "ffmpeg", "sleepwatcher", "python@3.13"],  # sleepwatcher is a dependency → present
            casks=["iterm2", "davit"],
            taps=["anomalyco/tap", "leoafarias/fvm"],
        )
        st = BrewDetector().get_status(tmp_path / "Brewfile", ignore=[])
        assert st.state == "drift"
        assert st.missing_formulae == ["anomalyco/tap/opencode"]
        assert st.missing_taps == ["eqms/claude-workbench"]
        assert st.missing_casks == []
        assert st.extra_formulae == ["ffmpeg"]  # python@3.13 is not a leaf → never an extra
        assert st.extra_casks == ["davit"]
        assert st.extra_taps == ["leoafarias/fvm"]

    def test_ignore_list_hides_both_directions(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor.mirror import BrewDetector

        (tmp_path / "Brewfile").write_text('brew "bat"\nbrew "poppler"\n', encoding="utf-8")
        self._stub(monkeypatch, leaves=["bat", "ffmpeg"], formulae=["bat", "ffmpeg"], casks=[], taps=[])
        st = BrewDetector().get_status(tmp_path / "Brewfile", ignore=["ffmpeg", "poppler"])
        assert st.state == "ok"

    def test_unavailable_without_brew(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import BrewDetector

        (tmp_path / "Brewfile").write_text('brew "bat"\n', encoding="utf-8")
        monkeypatch.setattr(mirror, "run_brew_lines", lambda *args: None)
        assert BrewDetector().get_status(tmp_path / "Brewfile", ignore=[]).state == "unavailable"

    def test_no_brewfile(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor.mirror import BrewDetector

        assert BrewDetector().get_status(tmp_path / "Brewfile", ignore=[]).state == "no_brewfile"


class TestPackageDetector:
    def test_compare_reports_all_three_kinds(self):
        from sccs.doctor.mirror import PackageRef, VersionDiff, compare_packages

        wanted = [PackageRef(name="sccs", version="2.68.0"), PackageRef(name="odoodev-equitania", version="0.68.0")]
        installed = [PackageRef(name="sccs", version="2.67.2"), PackageRef(name="build", version="1.6.1")]
        st = compare_packages("uv", wanted, installed, ignore=[])
        assert st.state == "drift"
        assert st.missing == [PackageRef(name="odoodev-equitania", version="0.68.0")]
        assert st.extra == ["build"]
        assert st.version_differs == [VersionDiff(name="sccs", have="2.67.2", want="2.68.0")]

    def test_ignore_hides_everywhere(self):
        from sccs.doctor.mirror import PackageRef, compare_packages

        wanted = [PackageRef(name="a", version="1")]
        installed = [PackageRef(name="b", version="1")]
        assert compare_packages("npm", wanted, installed, ignore=["a", "b"]).state == "ok"

    def test_detector_uv_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import PackageDetector, PackageRef

        monkeypatch.setattr(mirror, "run_uv_tool_list", lambda: None)
        st = PackageDetector().get_status("uv", [PackageRef(name="sccs", version="1")], ignore=[])
        assert st.state == "unavailable"

    def test_detector_npm_reads_json(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import PackageDetector, PackageRef

        monkeypatch.setattr(mirror, "run_npm_global_list", lambda: NPM_JSON)
        st = PackageDetector().get_status("npm", [PackageRef(name="less", version="4.6.4")], ignore=[])
        assert st.state == "drift"
        assert st.extra == ["@playwright/cli"]
        assert st.missing == [] and st.version_differs == []


class TestRepoDetector:
    def _spec(self, home: Path, name: str = "beam"):
        from sccs.doctor.mirror import MirrorRepoSpec

        return MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path=f"~/gitbase/example/{name}")

    def test_parse_status_branch(self):
        from sccs.doctor.mirror import parse_git_status_branch

        assert parse_git_status_branch("## main...origin/main\n") == (False, False)
        assert parse_git_status_branch("## main...origin/main [behind 2]\n") == (True, False)
        assert parse_git_status_branch("## main...origin/main [ahead 1, behind 2]\n M x.fish\n") == (True, True)
        assert parse_git_status_branch("## main...origin/main\n?? new.fish\n") == (False, True)

    def test_missing(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import RepoDetector

        st = RepoDetector().get_statuses([self._spec(home)], fetch=False)[0]
        assert st.state == "missing"

    def test_not_a_repo(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import RepoDetector

        (home / "gitbase/example/beam").mkdir(parents=True)
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: None)
        assert RepoDetector().get_statuses([self._spec(home)], fetch=False)[0].state == "not_a_repo"

    def test_behind_modified_ok(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import RepoDetector

        (home / "gitbase/example/beam").mkdir(parents=True)
        fetched: list[Path] = []
        monkeypatch.setattr(mirror, "run_git_fetch", lambda p: (fetched.append(p), True)[1])
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: "## main...origin/main [behind 3]\n")
        st = RepoDetector().get_statuses([self._spec(home)], fetch=True)[0]
        assert st.state == "behind" and st.fetched is True and fetched
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: "## main...origin/main [behind 3]\n M a\n")
        assert RepoDetector().get_statuses([self._spec(home)], fetch=False)[0].state == "modified"
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: "## main...origin/main\n")
        assert RepoDetector().get_statuses([self._spec(home)], fetch=False)[0].state == "ok"

    def test_fetch_failure_does_not_hide_local_state(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import RepoDetector

        (home / "gitbase/example/beam").mkdir(parents=True)
        monkeypatch.setattr(mirror, "run_git_fetch", lambda p: False)
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: "## main...origin/main\n")
        st = RepoDetector().get_statuses([self._spec(home)], fetch=True)[0]
        assert st.state == "ok" and st.fetched is False and "fetch failed" in st.detail


class TestFisherDetector:
    def test_drift(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import FisherDetector

        plugins = tmp_path / "fish_plugins"
        plugins.write_text("jorgebucaran/fisher\nedc/bass\njethrokuan/z\n", encoding="utf-8")
        monkeypatch.setattr(mirror, "run_fisher_list", lambda: ["jorgebucaran/fisher", "edc/bass", "old/plugin"])
        st = FisherDetector().get_status(plugins)
        assert st.state == "drift"
        assert st.missing == ["jethrokuan/z"] and st.extra == ["old/plugin"]

    def test_ok_unavailable_and_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import FisherDetector

        plugins = tmp_path / "fish_plugins"
        assert FisherDetector().get_status(plugins).state == "no_plugins_file"
        plugins.write_text("edc/bass\n", encoding="utf-8")
        monkeypatch.setattr(mirror, "run_fisher_list", lambda: ["edc/bass"])
        assert FisherDetector().get_status(plugins).state == "ok"
        monkeypatch.setattr(mirror, "run_fisher_list", lambda: None)
        assert FisherDetector().get_status(plugins).state == "unavailable"


def _stub_all(monkeypatch, *, brew_state="ok", uv_state="ok", npm_state="ok"):
    """Stub every detector the report uses; states are set directly.

    A "drift" state carries a real gap (a missing entry), so it matches what
    the real detectors produce — `has_drift` reads the gap, not the coarse
    state string.
    """
    from sccs.doctor import mirror
    from sccs.doctor.mirror import BrewStatus, FisherStatus, PackageAreaStatus, PackageRef

    def brew_status(self, brewfile, ignore):
        missing = ["x"] if brew_state == "drift" else []
        return BrewStatus(state=brew_state, missing_formulae=missing)

    def package_status(self, area, wanted, ignore):
        state = uv_state if area == "uv" else npm_state
        missing = [PackageRef(name="x", version="1")] if state == "drift" else []
        return PackageAreaStatus(area=area, state=state, missing=missing)

    monkeypatch.setattr(mirror.BrewDetector, "get_status", brew_status)
    monkeypatch.setattr(mirror.PackageDetector, "get_status", package_status)
    monkeypatch.setattr(mirror.RepoDetector, "get_statuses", lambda self, specs, fetch: [])
    monkeypatch.setattr(mirror.FisherDetector, "get_status", lambda self, p: FisherStatus(state="ok"))


class TestCollectMirrorReport:
    def test_off_returns_none(self):
        from sccs.doctor.mirror import MirrorConfig, collect_mirror_report

        assert collect_mirror_report(None, hostname="x") is None
        assert collect_mirror_report(MirrorConfig(), hostname="x") is None

    def test_mirror_reads_inventory(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import Inventory, MirrorConfig, PackageRef, collect_mirror_report, write_inventory

        _stub_all(monkeypatch, uv_state="drift")
        cfg = MirrorConfig(source_host="live-mac")
        inv = Inventory(captured_at="t", captured_on="live-mac", uv_tools=[PackageRef(name="sccs", version="1")])
        write_inventory(home / ".config/sccs/inventory.yaml", inv)
        rep = collect_mirror_report(cfg, hostname="demo-mac")
        assert rep is not None and rep.role == "mirror"
        assert rep.inventory == inv
        assert rep.has_drift is True
        assert rep.source_stale is False

    def test_mirror_without_inventory_has_no_package_rows(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import MirrorConfig, collect_mirror_report

        _stub_all(monkeypatch)
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="demo-mac")
        assert rep is not None and rep.inventory is None
        assert rep.uv is None and rep.npm is None
        assert rep.has_drift is False

    def test_source_is_stale_when_brew_or_inventory_drift(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import MirrorConfig, collect_mirror_report

        _stub_all(monkeypatch, brew_state="drift")
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="live-mac")
        assert rep is not None and rep.role == "source"
        assert rep.source_stale is True

    def test_source_with_missing_inventory_is_stale(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import MirrorConfig, collect_mirror_report

        _stub_all(monkeypatch)
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="live-mac")
        assert rep is not None and rep.source_stale is True

    def test_source_current(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import Inventory, MirrorConfig, collect_mirror_report, write_inventory

        _stub_all(monkeypatch)
        write_inventory(home / ".config/sccs/inventory.yaml", Inventory(captured_at="t", captured_on="live-mac"))
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="live-mac")
        assert rep is not None and rep.source_stale is False and rep.has_drift is False

    def test_has_extras(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import BrewStatus, Inventory, MirrorConfig, collect_mirror_report, write_inventory

        _stub_all(monkeypatch)
        monkeypatch.setattr(
            mirror.BrewDetector, "get_status", lambda self, b, i: BrewStatus(state="drift", extra_formulae=["ffmpeg"])
        )
        write_inventory(home / ".config/sccs/inventory.yaml", Inventory(captured_at="t", captured_on="live-mac"))
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="demo-mac")
        assert rep is not None and rep.has_extras is True and rep.has_drift is False

    def test_uv_extras_only_is_not_drift(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import (
            Inventory,
            MirrorConfig,
            PackageAreaStatus,
            collect_mirror_report,
            write_inventory,
        )

        _stub_all(monkeypatch)
        monkeypatch.setattr(
            mirror.PackageDetector,
            "get_status",
            lambda self, area, wanted, ignore: (
                PackageAreaStatus(area="uv", state="drift", extra=["build"])
                if area == "uv"
                else PackageAreaStatus(area=area, state="ok")
            ),
        )
        write_inventory(home / ".config/sccs/inventory.yaml", Inventory(captured_at="t", captured_on="live-mac"))
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="demo-mac")
        assert rep is not None and rep.has_drift is False and rep.has_extras is True


def _report(**kw):
    from sccs.doctor.mirror import MirrorReport

    base = dict(
        role="mirror",
        hostname="demo-mac",
        source_host="live-mac",
        inventory=None,
        inventory_path="/x/inventory.yaml",
        brewfile="/x/Brewfile",
        brew=None,
        uv=None,
        npm=None,
        repos=[],
        fisher=None,
        source_stale=False,
        cleanup=True,
    )
    base.update(kw)
    return MirrorReport(**base)


class TestMirrorActions:
    def test_install_actions_cover_every_area(self, home: Path):
        from sccs.doctor.mirror import (
            BrewStatus,
            FisherStatus,
            MirrorRepoSpec,
            PackageAreaStatus,
            PackageRef,
            RepoStatus,
            VersionDiff,
            mirror_install_actions,
        )

        spec_missing = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        spec_behind = MirrorRepoSpec(
            url="https://gitlab.example/org/two.git", path="~/gitbase/example/two", branch="main"
        )
        rep = _report(
            brew=BrewStatus(state="drift", missing_formulae=["bat"], extra_formulae=["ffmpeg"]),
            uv=PackageAreaStatus(
                area="uv",
                state="drift",
                missing=[PackageRef(name="odoodev-equitania", version="0.68.0")],
                version_differs=[VersionDiff(name="sccs", have="2.67.2", want="2.68.0")],
                extra=["build"],
            ),
            npm=PackageAreaStatus(
                area="npm", state="drift", missing=[PackageRef(name="@playwright/cli", version="0.1.18")]
            ),
            repos=[RepoStatus(spec=spec_missing, state="missing"), RepoStatus(spec=spec_behind, state="behind")],
            fisher=FisherStatus(state="drift", missing=["jethrokuan/z"]),
        )
        cmds = [a.cmd for a in mirror_install_actions(rep)]
        assert ["brew", "bundle", "install", "--file", "/x/Brewfile", "--no-upgrade"] in cmds
        assert ["uv", "tool", "install", "odoodev-equitania==0.68.0", "--reinstall"] in cmds
        assert ["uv", "tool", "install", "sccs==2.68.0", "--reinstall"] in cmds
        assert ["npm", "install", "-g", "@playwright/cli@0.1.18"] in cmds
        assert ["git", "clone", "git@gitlab.example:org/beam.git", str(home / "gitbase/example/beam")] in cmds
        assert ["git", "-C", str(home / "gitbase/example/two"), "pull", "--ff-only"] in cmds
        assert ["fish", "-c", "fisher install jethrokuan/z"] in cmds
        # extras never appear in install actions
        assert not any(a.cmd and "uninstall" in a.cmd for a in mirror_install_actions(rep))

    def test_clone_with_branch(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec, RepoStatus, mirror_install_actions

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam", branch="dev")
        (a,) = mirror_install_actions(_report(repos=[RepoStatus(spec=spec, state="missing")]))
        assert a.cmd == [
            "git",
            "clone",
            "--branch",
            "dev",
            "git@gitlab.example:org/beam.git",
            str(home / "gitbase/example/beam"),
        ]

    def test_modified_repo_is_print_only(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec, RepoStatus, mirror_install_actions

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        (a,) = mirror_install_actions(_report(repos=[RepoStatus(spec=spec, state="modified")]))
        assert a.runnable is False and a.cmd is None and "modified" in (a.manual_block or "")

    def test_pull_is_auto_confirmed_but_installs_are_not(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec, PackageAreaStatus, PackageRef, RepoStatus, mirror_install_actions

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        rep = _report(
            repos=[RepoStatus(spec=spec, state="behind")],
            uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")]),
        )
        by_component = {a.component: a for a in mirror_install_actions(rep)}
        assert by_component["mirror:repo:beam"].auto_confirm is True
        assert by_component["mirror:uv:x"].auto_confirm is False

    def test_long_running_actions_carry_a_timeout_override(self, home: Path):
        from sccs.doctor.mirror import (
            BrewStatus,
            MirrorRepoSpec,
            PackageAreaStatus,
            PackageRef,
            RepoStatus,
            mirror_install_actions,
        )

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        rep = _report(
            brew=BrewStatus(state="drift", missing_formulae=["bat"]),
            uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")]),
            repos=[RepoStatus(spec=spec, state="missing")],
        )
        by_component = {a.component: a for a in mirror_install_actions(rep)}
        assert by_component["mirror:brew"].timeout == 1800
        assert by_component["mirror:repo:beam"].timeout == 900
        assert by_component["mirror:uv:x"].timeout is None

    def test_invalid_version_is_logged_and_skipped(self, home: Path, caplog: pytest.LogCaptureFixture):
        import logging

        from sccs.doctor.mirror import PackageAreaStatus, PackageRef, mirror_install_actions

        # PackageRef itself validates `version` against `_VERSION_PATTERN` on
        # construction, so a normal PackageRef(...) call can never carry an
        # invalid version into mirror_install_actions — `model_construct`
        # bypasses that validator, the way a value loaded from an untrusted
        # source (e.g. a future non-pydantic path) could.
        bad = PackageRef.model_construct(name="x", version="1; rm -rf /")
        rep = _report(uv=PackageAreaStatus(area="uv", state="drift", missing=[bad]))
        with caplog.at_level(logging.WARNING, logger="sccs.doctor.mirror"):
            actions = mirror_install_actions(rep)
        assert actions == []
        assert any("invalid version" in r.message for r in caplog.records)

    # --- the two hard rules ---------------------------------------------

    def test_source_never_receives_install_or_remove_actions(self):
        from sccs.doctor.mirror import (
            BrewStatus,
            PackageAreaStatus,
            PackageRef,
            mirror_install_actions,
            mirror_remove_actions,
        )

        rep = _report(
            role="source",
            source_stale=True,
            brew=BrewStatus(state="drift", missing_formulae=["bat"], extra_formulae=["ffmpeg"]),
            uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")], extra=["y"]),
        )
        assert mirror_install_actions(rep) == []
        assert mirror_remove_actions(rep) == []

    def test_mirror_never_writes_inventory(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import Inventory, mirror_update_actions

        writes: list[Path] = []
        monkeypatch.setattr(mirror, "write_inventory", lambda p, inv: writes.append(p))
        monkeypatch.setattr(mirror, "run_brew_bundle_dump", lambda p: True)
        monkeypatch.setattr(
            mirror, "capture_inventory", lambda host, previous=None: Inventory(captured_at="t", captured_on=host)
        )
        for a in mirror_update_actions(_report(role="mirror")):
            if a.python_callable:
                a.python_callable()
        assert writes == []
        assert all(a.component != "mirror:capture" for a in mirror_update_actions(_report(role="mirror")))

    def test_source_update_captures_both_files(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import Inventory, mirror_update_actions

        dumped: list[Path] = []
        written: list[tuple[Path, Inventory]] = []
        monkeypatch.setattr(mirror, "run_brew_bundle_dump", lambda p: (dumped.append(p), True)[1])
        monkeypatch.setattr(
            mirror, "capture_inventory", lambda host, previous=None: Inventory(captured_at="t", captured_on=host)
        )
        monkeypatch.setattr(mirror, "write_inventory", lambda p, inv: written.append((p, inv)))
        (a,) = mirror_update_actions(_report(role="source", source_stale=True))
        assert a.component == "mirror:capture" and a.auto_confirm is True and a.python_callable
        a.python_callable()
        assert dumped == [Path("/x/Brewfile")]
        assert written[0][0] == Path("/x/inventory.yaml") and written[0][1].captured_on == "demo-mac"

    def test_source_capture_passes_loaded_previous_inventory(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        """Finding F1: `_capture` must load the existing inventory before
        recapturing and hand it to `capture_inventory`, so a transient
        `uv`/`npm` outage can fall back to what was there before."""
        from sccs.doctor import mirror
        from sccs.doctor.mirror import Inventory, mirror_update_actions

        known = Inventory(captured_at="2026-09-14T10:00:00", captured_on="live-mac")
        monkeypatch.setattr(mirror, "load_inventory", lambda p: known)
        monkeypatch.setattr(mirror, "run_brew_bundle_dump", lambda p: True)
        monkeypatch.setattr(mirror, "write_inventory", lambda p, inv: None)
        seen: list[Inventory | None] = []

        def _fake_capture(host, previous=None):
            seen.append(previous)
            return Inventory(captured_at="t", captured_on=host)

        monkeypatch.setattr(mirror, "capture_inventory", _fake_capture)
        (a,) = mirror_update_actions(_report(role="source", source_stale=True))
        a.python_callable()
        assert seen == [known]

    def test_source_update_runs_even_when_current(self):
        """`doctor update` on the source always refreshes — that is what keeps
        the files current; staleness only decides the check row."""
        from sccs.doctor.mirror import mirror_update_actions

        assert len(mirror_update_actions(_report(role="source", source_stale=False))) == 1

    def test_remove_actions_one_per_extra_never_protected(self):
        from sccs.doctor.mirror import BrewStatus, FisherStatus, PackageAreaStatus, mirror_remove_actions

        rep = _report(
            brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"], extra_casks=["davit"], extra_taps=["a/b"]),
            uv=PackageAreaStatus(area="uv", state="drift", extra=["build", "sccs"]),
            npm=PackageAreaStatus(area="npm", state="drift", extra=["pnpm", "npm", "corepack"]),
            fisher=FisherStatus(state="drift", extra=["old/plugin"]),
        )
        actions = mirror_remove_actions(rep)
        cmds = [a.cmd for a in actions]
        assert ["brew", "uninstall", "ffmpeg"] in cmds
        assert ["brew", "uninstall", "--cask", "davit"] in cmds
        assert ["brew", "untap", "a/b"] in cmds
        assert ["uv", "tool", "uninstall", "build"] in cmds
        assert ["npm", "uninstall", "-g", "pnpm"] in cmds
        assert ["fish", "-c", "fisher remove old/plugin"] in cmds
        assert not any("sccs" in (a.cmd or []) for a in actions)
        assert not any(c[-1] in {"npm", "corepack"} for c in cmds if c)
        assert all(a.auto_confirm is False and a.label.startswith("REMOVE ") for a in actions)
        assert len(actions) == 6

    def test_remove_actions_respect_cleanup_false(self):
        from sccs.doctor.mirror import BrewStatus, mirror_remove_actions

        rep = _report(cleanup=False, brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"]))
        assert mirror_remove_actions(rep) == []

    def test_extras_summary_source_yields_nothing(self):
        from sccs.doctor.mirror import BrewStatus, mirror_extras_summary_action

        rep = _report(role="source", brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"]))
        assert mirror_extras_summary_action(rep) == []

    def test_extras_summary_respects_cleanup_false(self):
        from sccs.doctor.mirror import BrewStatus, mirror_extras_summary_action

        rep = _report(cleanup=False, brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"]))
        assert mirror_extras_summary_action(rep) == []

    def test_extras_summary_mirror_with_extras(self):
        from sccs.doctor.mirror import BrewStatus, mirror_extras_summary_action

        rep = _report(brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"]))
        (a,) = mirror_extras_summary_action(rep)
        assert a.runnable is False and a.cmd == [] and "review needed" in a.label
        assert a.component == "mirror:extras:summary"

    def test_fisher_extras_only_is_not_drift_but_is_extra(self):
        from sccs.doctor.mirror import FisherStatus, mirror_install_actions

        rep = _report(fisher=FisherStatus(state="drift", extra=["x"]))
        assert rep.has_drift is False
        assert rep.has_extras is True
        assert mirror_install_actions(rep) == []

    def test_modified_or_not_a_repo_is_not_drift(self, home: Path):
        """Finding F4: a `modified` checkout or a broken git repo is something
        only a human can fix — `sccs doctor install` cannot act on it, so it
        must not fail the check (yellow, exit 0), only `missing`/`behind` do."""
        from sccs.doctor.mirror import MirrorRepoSpec, RepoStatus

        spec_a = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        spec_b = MirrorRepoSpec(url="git@gitlab.example:org/two.git", path="~/gitbase/example/two")
        rep = _report(
            repos=[
                RepoStatus(spec=spec_a, state="modified"),
                RepoStatus(spec=spec_b, state="not_a_repo"),
            ]
        )
        assert rep.has_drift is False

    def test_none_report_yields_nothing(self):
        from sccs.doctor.mirror import mirror_install_actions, mirror_remove_actions, mirror_update_actions

        assert mirror_install_actions(None) == mirror_update_actions(None) == mirror_remove_actions(None) == []


class TestPlanWiring:
    def _base(self):
        from sccs.doctor.defaults import get_node_install_spec
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.schema import DoctorConfig

        return dict(
            config=DoctorConfig(),
            node=NodeStatus(
                installed=True,
                version="22.0.0",
                major=22,
                meets_minimum=True,
                install_hint=get_node_install_spec("macos"),
                platform="macos",
            ),
            claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
            plugins=[],
            npx_tools=[],
        )

    def test_install_plan_contains_mirror_actions(self, home: Path):
        from sccs.doctor.installer import build_install_plan
        from sccs.doctor.mirror import PackageAreaStatus, PackageRef

        rep = _report(uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")]))
        plan = build_install_plan(**self._base(), mirror=rep)
        assert any(a.component == "mirror:uv:x" for a in plan.actions)

    def test_removals_only_in_strict_optimize(self, home: Path):
        from sccs.doctor.installer import build_install_plan, build_optimize_plan, build_update_plan
        from sccs.doctor.mirror import BrewStatus

        rep = _report(brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"]))
        base = self._base()
        opt = dict(foreign_plugins=[], mcp_servers=[], foreign_mcp_servers=[])
        has_remove = lambda plan: any(a.label.startswith("REMOVE ") and "ffmpeg" in a.label for a in plan.actions)  # noqa: E731
        assert not has_remove(build_install_plan(**base, mirror=rep))
        assert not has_remove(build_update_plan(**base, mirror=rep))
        assert not has_remove(build_optimize_plan(**base, **opt, mirror=rep, strict=False))
        assert has_remove(build_optimize_plan(**base, **opt, mirror=rep, strict=True))

    def test_optimize_plan_captures_on_a_source(self, home: Path):
        from sccs.doctor.installer import build_optimize_plan

        base = self._base()
        opt = dict(foreign_plugins=[], mcp_servers=[], foreign_mcp_servers=[])
        rep = _report(role="source", source_stale=True)
        plan = build_optimize_plan(**base, **opt, mirror=rep, strict=False)
        assert any(a.component == "mirror:capture" for a in plan.actions)

    def test_optimize_plan_does_not_duplicate_mirror_install_actions(self, home: Path):
        from sccs.doctor.installer import build_optimize_plan
        from sccs.doctor.mirror import PackageAreaStatus, PackageRef

        base = self._base()
        opt = dict(foreign_plugins=[], mcp_servers=[], foreign_mcp_servers=[])
        rep = _report(uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")]))
        plan = build_optimize_plan(**base, **opt, mirror=rep, strict=False)
        assert sum(1 for a in plan.actions if a.component == "mirror:uv:x") == 1


class TestReporter:
    def test_rows_for_mirror_with_drift(self, home: Path):
        from sccs.doctor.mirror import (
            BrewStatus,
            FisherStatus,
            MirrorRepoSpec,
            PackageAreaStatus,
            PackageRef,
            RepoStatus,
        )
        from sccs.doctor.reporter import _mirror_rows

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        rep = _report(
            brew=BrewStatus(state="drift", missing_formulae=["bat"], extra_formulae=["ffmpeg"]),
            uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")]),
            npm=PackageAreaStatus(area="npm", state="ok"),
            repos=[RepoStatus(spec=spec, state="behind")],
            fisher=FisherStatus(state="ok"),
        )
        rows = {r[0]: r for r in _mirror_rows(rep)}
        assert "mirror of live-mac" in rows["mirror: role"][3]
        assert (
            "MISSING" in rows["mirror: brew"][1]
            and "1 missing" in rows["mirror: brew"][3]
            and "1 extra" in rows["mirror: brew"][3]
        )
        assert "MISSING" in rows["mirror: uv"][1]
        assert "OK" in rows["mirror: npm"][1]
        assert "OUTDATED" in rows["mirror: repo beam"][1]
        assert "OK" in rows["mirror: fisher"][1]

    def test_only_extras_is_stale_not_missing(self):
        from sccs.doctor.mirror import BrewStatus
        from sccs.doctor.reporter import _mirror_rows

        rows = {r[0]: r for r in _mirror_rows(_report(brew=BrewStatus(state="drift", extra_casks=["davit"])))}
        assert "STALE" in rows["mirror: brew"][1]

    def test_fisher_only_extras_is_stale(self):
        from sccs.doctor.mirror import FisherStatus
        from sccs.doctor.reporter import _mirror_rows

        rows = {r[0]: r for r in _mirror_rows(_report(fisher=FisherStatus(state="drift", extra=["old/plugin"])))}
        assert "STALE" in rows["mirror: fisher"][1]

    def test_not_a_repo_row_is_stale(self, home: Path):
        """Finding F4: a broken checkout is yellow like `modified`, never the
        red MISSING a `git clone` action could fix."""
        from sccs.doctor.mirror import MirrorRepoSpec, RepoStatus
        from sccs.doctor.reporter import _mirror_rows

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        rows = {
            r[0]: r
            for r in _mirror_rows(
                _report(repos=[RepoStatus(spec=spec, state="not_a_repo", detail="git status failed")])
            )
        }
        assert "STALE" in rows["mirror: repo beam"][1]

    def test_source_rows(self):
        from sccs.doctor.reporter import _mirror_rows

        rows = {r[0]: r for r in _mirror_rows(_report(role="source", source_stale=True))}
        assert "STALE" in rows["mirror: role"][1] and "sccs doctor update" in rows["mirror: role"][3]
        rows = {r[0]: r for r in _mirror_rows(_report(role="source", source_stale=False))}
        assert "OK" in rows["mirror: role"][1] and "inventory current" in rows["mirror: role"][3]

    def test_no_rows_when_off(self):
        from sccs.doctor.reporter import _mirror_rows

        assert _mirror_rows(None) == []

    def test_has_problems_only_for_mirror_drift(self):
        from sccs.doctor.defaults import get_node_install_spec
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.mirror import BrewStatus
        from sccs.doctor.reporter import has_problems

        base = dict(
            node=NodeStatus(
                installed=True,
                version="22.0.0",
                major=22,
                meets_minimum=True,
                install_hint=get_node_install_spec("macos"),
                platform="macos",
            ),
            claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
            plugins=[],
            npx_tools=[],
        )
        assert has_problems(**base, mirror=_report(brew=BrewStatus(state="drift", missing_formulae=["bat"]))) is True
        assert has_problems(**base, mirror=_report(brew=BrewStatus(state="drift", extra_formulae=["x"]))) is False
        assert has_problems(**base, mirror=_report(role="source", source_stale=True)) is False
        assert has_problems(**base, mirror=None) is False

    def test_render_includes_mirror_block(self, home: Path):
        from rich.console import Console

        from sccs.doctor.defaults import get_node_install_spec
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.mirror import BrewStatus
        from sccs.doctor.reporter import render_doctor_report

        console = Console(record=True, width=120, force_terminal=False)
        render_doctor_report(
            console,
            node=NodeStatus(
                installed=True,
                version="22.0.0",
                major=22,
                meets_minimum=True,
                install_hint=get_node_install_spec("macos"),
                platform="macos",
            ),
            claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
            plugins=[],
            npx_tools=[],
            min_node_major=22,
            mirror=_report(brew=BrewStatus(state="drift", missing_formulae=["bat"])),
        )
        text = console.export_text()
        assert "mirror: brew" in text and "mirror: role" in text


class TestJsonEmit:
    def test_emit_json_serializes_mirror_report(self, capsys: pytest.CaptureFixture):
        from sccs.doctor.mirror import BrewStatus
        from sccs.output.json_emit import emit_json

        emit_json({"m": _report(brew=BrewStatus(state="drift", missing_formulae=["bat"]))})
        output = capsys.readouterr().out
        lines = [line for line in output.splitlines() if line.strip()]
        assert len(lines) == 1, lines
        payload = json.loads(lines[0])
        assert payload["m"]["role"] == "mirror"
        assert payload["m"]["brew"]["missing_formulae"] == ["bat"]


class TestCliWiring:
    def _parse_clean(self, output: str):
        assert "\x1b" not in output
        lines = [line for line in output.splitlines() if line.strip()]
        assert len(lines) == 1, lines
        return json.loads(lines[0])

    @patch("sccs.doctor.reporter.has_updates", return_value=False)
    @patch("sccs.doctor.reporter.has_problems", return_value=True)
    @patch("sccs.cli._collect_doctor_statuses")
    @patch("sccs.cli._load_doctor_config")
    def test_check_json_carries_mirror(self, mock_cfg, mock_collect, mock_probs, mock_upd):
        from click.testing import CliRunner

        from sccs.cli import cli
        from sccs.doctor.mirror import BrewStatus

        mock_cfg.return_value = MagicMock(min_node_major=22)
        mock_collect.return_value = {
            "node": {},
            "claude_cli": {},
            "plugins": [],
            "npx_tools": [],
            "mirror": _report(brew=BrewStatus(state="drift", missing_formulae=["bat"])),
        }

        result = CliRunner().invoke(cli, ["doctor", "check", "--json", "--no-update-check"])
        payload = self._parse_clean(result.output)
        assert payload["mirror"]["role"] == "mirror"
        assert payload["mirror"]["brew"]["missing_formulae"] == ["bat"]
        assert payload["has_problems"] is True

    def test_default_categories(self):
        from sccs.config.defaults import DEFAULT_CONFIG

        cats = DEFAULT_CONFIG["sync_categories"]
        assert cats["homebrew_bundle"]["local_path"] == "~/.config/homebrew/Brewfile"
        assert cats["homebrew_bundle"]["platforms"] == ["macos"]
        assert cats["sccs_inventory"]["local_path"] == "~/.config/sccs/inventory.yaml"
        assert cats["sccs_inventory"]["repo_path"] == ".config/sccs/inventory.yaml"
        assert cats["sccs_inventory"]["enabled"] is True

    def test_install_update_optimize_fetch_repos(self):
        """v2.68.1: `install`/`update`/`optimize` never fetched, so a mirror
        stuck `behind` never saw its `git pull --ff-only` action refresh.
        `_collect_doctor_statuses` is entangled with a lot of detector
        plumbing to invoke directly here, so this pins the wiring two ways:
        the parameter exists, and each of the three call sites in `cli.py`
        passes it."""
        import inspect

        from sccs.cli import _collect_doctor_statuses

        sig = inspect.signature(_collect_doctor_statuses)
        assert "fetch_repos" in sig.parameters
        assert sig.parameters["fetch_repos"].default is None

        source = Path(__file__).resolve().parent.parent / "sccs" / "cli.py"
        text = source.read_text(encoding="utf-8")
        assert text.count("fetch_repos=True") == 3, (
            "expected install, update and optimize to each pass fetch_repos=True"
        )
        assert "def doctor_check" in text and "check_updates=update_check" in text, (
            "doctor check should keep deriving fetch from --update-check/--no-update-check, not fetch_repos"
        )
