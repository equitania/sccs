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
