# tests/test_doctor_mirror.py
"""v2.68.0: mirror parity — keep a second Mac identical to the live workstation."""

from __future__ import annotations

from pathlib import Path

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
        assert seen == [["brew", "bundle", "dump", "--file", str(tmp_path / "Brewfile"), "--force", "--describe"]]

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

    def test_capture_uses_wrappers_and_tolerates_missing_tools(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror

        monkeypatch.setattr(mirror, "run_uv_tool_list", lambda: UV_LIST)
        monkeypatch.setattr(mirror, "run_npm_global_list", lambda: None)
        inv = mirror.capture_inventory("live-mac")
        assert [p.name for p in inv.uv_tools] == ["agentmgr", "sccs", "odoodev-equitania"]
        assert inv.npm_globals == []
        assert inv.captured_on == "live-mac"
        assert inv.version == 1


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
