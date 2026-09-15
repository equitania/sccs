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
