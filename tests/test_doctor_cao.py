"""Tests for the CAO provider patch subsystem (`sccs/doctor/cao.py`).

CAO (AWS Labs CLI Agent Orchestrator) hard-codes its provider registry in an
if/elif chain, so an extra provider has to be patched into the *installed*
package — and every `cao update` wipes it again. These tests use a synthetic
package tree, so they run on a host (and on CI) that has no CAO at all.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from sccs.doctor.cao import (
    CaoDetector,
    apply_provider_patch,
    find_cao_package,
)
from sccs.doctor.defaults import DEFAULT_CAO_PROVIDERS
from sccs.doctor.schema import CaoPatchSite, CaoProviderSpec, DoctorConfig

# --------------------------------------------------------------------------
# Fixtures: a synthetic CAO package + provider source
# --------------------------------------------------------------------------

_PROVIDER_PY = "class PiCliProvider:\n    pass\n"

_ENUM_PY = """class ProviderType(str, Enum):
    CLAUDE_CODE = "claude_code"
    MOCK_CLI = "mock_cli"
"""

_MANAGER_PY = """from cli_agent_orchestrator.providers.opencode_cli import OpenCodeCliProvider


class ProviderManager:
    def create(self):
        if provider_type == ProviderType.CLAUDE_CODE.value:
            provider = ClaudeCodeProvider(terminal_id)
        elif provider_type == ProviderType.OPENCODE_CLI.value:
            provider = OpenCodeCliProvider(
                terminal_id,
                tmux_session,
            )
"""


def _make_spec(tmp_path) -> CaoProviderSpec:
    """A two-site spec against the synthetic tree — enough to exercise every state."""
    return CaoProviderSpec(
        name="pi_cli",
        binary="pi",
        source_dir=str(tmp_path / "source"),
        source_file="pi_cli.py",
        package_subpath="providers/pi_cli.py",
        sites=[
            CaoPatchSite(
                rel_path="models/provider.py",
                anchor='    MOCK_CLI = "mock_cli"',
                insertion='\n    PI_CLI = "pi_cli"',
                marker='PI_CLI = "pi_cli"',
            ),
            CaoPatchSite(
                rel_path="providers/manager.py",
                anchor="from cli_agent_orchestrator.providers.opencode_cli import OpenCodeCliProvider",
                insertion="\nfrom cli_agent_orchestrator.providers.pi_cli import PiCliProvider",
                marker="from cli_agent_orchestrator.providers.pi_cli import PiCliProvider",
            ),
        ],
    )


@pytest.fixture
def cao_tree(tmp_path):
    """Synthetic installed package + a synced provider source next to it."""
    pkg = tmp_path / "cli_agent_orchestrator"
    (pkg / "models").mkdir(parents=True)
    (pkg / "providers").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "models" / "provider.py").write_text(_ENUM_PY, encoding="utf-8")
    (pkg / "providers" / "manager.py").write_text(_MANAGER_PY, encoding="utf-8")

    source = tmp_path / "source"
    source.mkdir()
    (source / "pi_cli.py").write_text(_PROVIDER_PY, encoding="utf-8")

    return pkg, _make_spec(tmp_path)


# --------------------------------------------------------------------------
# find_cao_package
# --------------------------------------------------------------------------


class TestFindCaoPackage:
    def test_finds_package_in_uv_tool_layout(self, tmp_path):
        """uv installs a tool as <root>/lib/python3.X/site-packages/<pkg>."""
        pkg = tmp_path / "lib" / "python3.13" / "site-packages" / "cli_agent_orchestrator"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")

        assert find_cao_package(roots=[tmp_path]) == pkg

    def test_returns_none_when_no_cao_installed(self, tmp_path):
        assert find_cao_package(roots=[tmp_path]) is None

    def test_ignores_directory_without_init(self, tmp_path):
        """A bare directory of the right name is not an importable package."""
        pkg = tmp_path / "lib" / "python3.13" / "site-packages" / "cli_agent_orchestrator"
        pkg.mkdir(parents=True)

        assert find_cao_package(roots=[tmp_path]) is None

    def test_root_derived_from_cao_binary(self, tmp_path):
        """`which cao` yields ~/.local/bin/cao → ~/.local/share/uv/tools/<tool>."""
        binary = tmp_path / "bin" / "cao"
        binary.parent.mkdir(parents=True)
        binary.write_text("", encoding="utf-8")
        pkg = (
            tmp_path
            / "share"
            / "uv"
            / "tools"
            / "cli-agent-orchestrator"
            / "lib"
            / "python3.13"
            / "site-packages"
            / "cli_agent_orchestrator"
        )
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")

        assert find_cao_package(which=lambda _: str(binary)) == pkg

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
    def test_root_derived_through_the_uv_shim_symlink(self, tmp_path, monkeypatch):
        """The real layout: ~/.local/bin/cao is a SYMLINK into the tool root.

        Resolving it yields <tool>/bin/cao, whose grandparent is the tool root
        itself — appending share/uv/tools/… a second time then looks under
        <tool>/share and finds nothing. Both readings have to be tried.
        """
        tool = tmp_path / ".local" / "share" / "uv" / "tools" / "cli-agent-orchestrator"
        real_bin = tool / "bin" / "cao"
        real_bin.parent.mkdir(parents=True)
        real_bin.write_text("", encoding="utf-8")
        shim = tmp_path / ".local" / "bin" / "cao"
        shim.parent.mkdir(parents=True)
        shim.symlink_to(real_bin)

        pkg = tool / "lib" / "python3.13" / "site-packages" / "cli_agent_orchestrator"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        assert find_cao_package(which=lambda _: str(shim)) == pkg

    def test_falls_back_to_the_home_uv_tools_location(self, tmp_path, monkeypatch):
        """No `cao` on PATH → still found under ~/.local/share/uv/tools/…"""
        pkg = (
            tmp_path
            / ".local"
            / "share"
            / "uv"
            / "tools"
            / "cli-agent-orchestrator"
            / "lib"
            / "python3.13"
            / "site-packages"
            / "cli_agent_orchestrator"
        )
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        assert find_cao_package(which=lambda _: None) == pkg


# --------------------------------------------------------------------------
# Detector states
# --------------------------------------------------------------------------


class TestCaoDetector:
    def test_no_package_yields_no_row(self, cao_tree):
        """No CAO on this host → the subsystem is silent, not red."""
        _, spec = cao_tree
        detector = CaoDetector(package_path=None)

        assert detector.get_statuses([spec]) == []

    def test_missing_source_yields_no_row(self, cao_tree, tmp_path):
        """The presence of the synced source IS the opt-in: without it, no row.

        Someone who never synced the private provider repo has not asked for
        this feature and must not be advertised at.
        """
        pkg, spec = cao_tree
        (tmp_path / "source" / "pi_cli.py").unlink()
        detector = CaoDetector(package_path=pkg)

        assert detector.get_statuses([spec]) == []

    def test_unpatched_package_reports_missing(self, cao_tree):
        pkg, spec = cao_tree
        status = CaoDetector(package_path=pkg).get_statuses([spec])[0]

        assert status.state == "missing"
        assert set(status.pending) == {
            "providers/pi_cli.py",
            "models/provider.py",
            "providers/manager.py",
        }
        assert status.problems == []

    def test_fully_patched_package_reports_patched(self, cao_tree):
        pkg, spec = cao_tree
        apply_provider_patch(spec, pkg)

        status = CaoDetector(package_path=pkg).get_statuses([spec])[0]
        assert status.state == "patched"
        assert status.pending == []

    def test_partially_patched_package_reports_partial(self, cao_tree):
        """A half-patched package is the state a failed run leaves behind."""
        pkg, spec = cao_tree
        target = pkg / "models" / "provider.py"
        target.write_text(_ENUM_PY + '    PI_CLI = "pi_cli"\n', encoding="utf-8")

        status = CaoDetector(package_path=pkg).get_statuses([spec])[0]
        assert status.state == "partial"
        assert "models/provider.py" not in status.pending
        assert "providers/manager.py" in status.pending

    def test_lost_anchor_reports_anchor_lost(self, cao_tree):
        """CAO restructured → the patch must refuse, not guess a location."""
        pkg, spec = cao_tree
        (pkg / "models" / "provider.py").write_text("class Whatever:\n    pass\n", encoding="utf-8")

        status = CaoDetector(package_path=pkg).get_statuses([spec])[0]
        assert status.state == "anchor_lost"
        assert any("models/provider.py" in p for p in status.problems)

    def test_stale_provider_file_counts_as_pending(self, cao_tree, tmp_path):
        """The synced source changed → the copy in the package is outdated."""
        pkg, spec = cao_tree
        apply_provider_patch(spec, pkg)
        (tmp_path / "source" / "pi_cli.py").write_text(_PROVIDER_PY + "# newer\n", encoding="utf-8")

        status = CaoDetector(package_path=pkg).get_statuses([spec])[0]
        assert status.state == "partial"
        assert status.pending == ["providers/pi_cli.py"]

    def test_missing_binary_is_reported_but_not_fatal(self, cao_tree):
        """The provider installs fine without `pi`; no worker can start, though."""
        pkg, spec = cao_tree
        status = CaoDetector(package_path=pkg, which=lambda _: None).get_statuses([spec])[0]

        assert status.binary_on_path is False
        assert status.state == "missing"


# --------------------------------------------------------------------------
# apply_provider_patch
# --------------------------------------------------------------------------


class TestApplyProviderPatch:
    def test_patches_every_site_and_copies_provider(self, cao_tree):
        pkg, spec = cao_tree
        changed = apply_provider_patch(spec, pkg)

        assert (pkg / "providers" / "pi_cli.py").read_text(encoding="utf-8") == _PROVIDER_PY
        assert 'PI_CLI = "pi_cli"' in (pkg / "models" / "provider.py").read_text(encoding="utf-8")
        assert "import PiCliProvider" in (pkg / "providers" / "manager.py").read_text(encoding="utf-8")
        assert len(changed) == 3

    def test_insertion_lands_after_the_anchor(self, cao_tree):
        pkg, spec = cao_tree
        apply_provider_patch(spec, pkg)

        text = (pkg / "models" / "provider.py").read_text(encoding="utf-8")
        assert text.index('MOCK_CLI = "mock_cli"') < text.index('PI_CLI = "pi_cli"')

    def test_two_sites_in_one_file_both_survive(self, cao_tree, tmp_path):
        """The real pi_cli spec patches providers/manager.py twice — import and
        instantiation branch. Deriving both from the same on-disk text and
        writing them in turn makes the second write discard the first, leaving
        a package that imports cleanly but never launches a worker. Found by
        running against a real CAO install, not by the synthetic fixture."""
        pkg, spec = cao_tree
        spec.sites.append(
            CaoPatchSite(
                rel_path="providers/manager.py",
                anchor="        elif provider_type == ProviderType.OPENCODE_CLI.value:",
                insertion="\n        elif provider_type == ProviderType.PI_CLI.value:\n            pass",
                marker="ProviderType.PI_CLI.value",
            )
        )

        apply_provider_patch(spec, pkg)

        text = (pkg / "providers" / "manager.py").read_text(encoding="utf-8")
        assert "import PiCliProvider" in text
        assert "ProviderType.PI_CLI.value" in text
        assert CaoDetector(package_path=pkg).get_statuses([spec])[0].state == "patched"
        assert apply_provider_patch(spec, pkg) == []

    def test_is_idempotent(self, cao_tree):
        pkg, spec = cao_tree
        apply_provider_patch(spec, pkg)
        before = (pkg / "models" / "provider.py").read_text(encoding="utf-8")

        changed = apply_provider_patch(spec, pkg)

        assert changed == []
        assert (pkg / "models" / "provider.py").read_text(encoding="utf-8") == before

    def test_refreshes_a_stale_provider_copy(self, cao_tree, tmp_path):
        pkg, spec = cao_tree
        apply_provider_patch(spec, pkg)
        (tmp_path / "source" / "pi_cli.py").write_text("# v2\n", encoding="utf-8")

        changed = apply_provider_patch(spec, pkg)

        assert changed == ["providers/pi_cli.py"]
        assert (pkg / "providers" / "pi_cli.py").read_text(encoding="utf-8") == "# v2\n"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_preserves_file_permissions(self, cao_tree):
        """atomic_write would otherwise leave the mkstemp default 0600 behind,
        making an importable module unreadable for other users of a shared install."""
        pkg, spec = cao_tree
        target = pkg / "models" / "provider.py"
        target.chmod(0o644)

        apply_provider_patch(spec, pkg)

        assert stat.S_IMODE(target.stat().st_mode) == 0o644

    def test_refuses_when_an_anchor_is_gone(self, cao_tree):
        """Partial application is worse than none: an unimportable package."""
        pkg, spec = cao_tree
        (pkg / "models" / "provider.py").write_text("nothing familiar here\n", encoding="utf-8")
        manager_before = (pkg / "providers" / "manager.py").read_text(encoding="utf-8")

        with pytest.raises(RuntimeError, match="anchor not found"):
            apply_provider_patch(spec, pkg)

        assert (pkg / "providers" / "manager.py").read_text(encoding="utf-8") == manager_before

    def test_refuses_when_a_target_file_is_gone(self, cao_tree):
        pkg, spec = cao_tree
        (pkg / "models" / "provider.py").unlink()

        with pytest.raises(RuntimeError, match="not found"):
            apply_provider_patch(spec, pkg)

    def test_refuses_a_missing_source(self, cao_tree, tmp_path):
        pkg, spec = cao_tree
        (tmp_path / "source" / "pi_cli.py").unlink()

        with pytest.raises(RuntimeError, match="source"):
            apply_provider_patch(spec, pkg)


# --------------------------------------------------------------------------
# Path safety — the patcher writes into a foreign installed package
# --------------------------------------------------------------------------


class TestPathSafety:
    @pytest.mark.parametrize(
        "bad",
        ["../evil.py", "providers/../../evil.py", "/etc/passwd", "providers/./../../x.py"],
    )
    def test_rel_path_escaping_the_package_is_rejected(self, bad):
        with pytest.raises(ValidationError):
            CaoPatchSite(rel_path=bad, anchor="a", insertion="b", marker="c")

    def test_package_subpath_escaping_is_rejected(self):
        with pytest.raises(ValidationError):
            CaoProviderSpec(
                name="x",
                binary="x",
                source_dir="~/somewhere",
                source_file="x.py",
                package_subpath="../../x.py",
                sites=[],
            )

    def test_source_file_may_not_be_a_path(self):
        with pytest.raises(ValidationError):
            CaoProviderSpec(
                name="x",
                binary="x",
                source_dir="~/somewhere",
                source_file="../../../etc/passwd",
                package_subpath="providers/x.py",
                sites=[],
            )

    def test_symlinked_target_is_refused(self, cao_tree, tmp_path):
        """A planted symlink must not turn a package patch into a write anywhere."""
        pkg, spec = cao_tree
        outside = tmp_path / "outside.py"
        outside.write_text("untouched\n", encoding="utf-8")
        target = pkg / "models" / "provider.py"
        target.unlink()
        target.symlink_to(outside)

        with pytest.raises(RuntimeError, match="symlink"):
            apply_provider_patch(spec, pkg)

        assert outside.read_text(encoding="utf-8") == "untouched\n"


# --------------------------------------------------------------------------
# The bundled pi_cli spec must stay in step with the source of truth
# --------------------------------------------------------------------------


class TestBundledPiProviderSpec:
    def test_pi_provider_is_bundled(self):
        names = [s.name for s in DEFAULT_CAO_PROVIDERS]
        assert "pi_cli" in names

    def test_covers_every_registration_site(self):
        """Six sites; miss one and CAO imports but never launches a pi worker."""
        spec = next(s for s in DEFAULT_CAO_PROVIDERS if s.name == "pi_cli")
        assert {site.rel_path for site in spec.sites} == {
            "models/provider.py",
            "providers/manager.py",
            "cli/commands/launch.py",
            "api/main.py",
            "utils/tool_mapping.py",
        }
        assert len(spec.sites) == 6  # manager.py carries two: import + branch

    def test_every_marker_appears_in_its_own_insertion(self):
        """Otherwise the patch is not idempotent — it would re-apply forever."""
        for spec in DEFAULT_CAO_PROVIDERS:
            for site in spec.sites:
                assert site.marker in site.insertion, f"{spec.name}/{site.rel_path}"

    def test_source_dir_is_the_synced_private_location(self):
        """The provider source stays in the private sync repo — never bundled
        into this package, which publishes to PyPI and GitHub."""
        spec = next(s for s in DEFAULT_CAO_PROVIDERS if s.name == "pi_cli")
        assert spec.source_dir == "~/.config/cao/provider"

    def test_config_exposes_the_defaults(self):
        assert DoctorConfig().effective_cao_providers() == DEFAULT_CAO_PROVIDERS

    def test_config_can_replace_and_extend(self, tmp_path):
        extra = _make_spec(tmp_path)
        assert DoctorConfig(cao_providers=[]).effective_cao_providers() == []
        assert extra in DoctorConfig(extra_cao_providers=[extra]).effective_cao_providers()


# --------------------------------------------------------------------------
# Installer actions
# --------------------------------------------------------------------------


class TestCaoProviderActions:
    @staticmethod
    def _status(spec, state, **kw):
        from sccs.doctor.cao import CaoProviderStatus

        return CaoProviderStatus(spec=spec, state=state, **kw)

    def test_patched_provider_produces_no_action(self, cao_tree):
        from sccs.doctor.installer import _cao_provider_actions

        pkg, spec = cao_tree
        assert _cao_provider_actions([self._status(spec, "patched", package_path=pkg)]) == []

    def test_no_statuses_produces_no_action(self):
        from sccs.doctor.installer import _cao_provider_actions

        assert _cao_provider_actions(None) == []

    def test_missing_provider_yields_a_runnable_action(self, cao_tree):
        from sccs.doctor.installer import _cao_provider_actions

        pkg, spec = cao_tree
        actions = _cao_provider_actions([self._status(spec, "missing", package_path=pkg, pending=["a", "b"])])

        assert len(actions) == 1
        assert actions[0].runnable is True
        assert actions[0].component == "cao-provider:pi_cli"

    def test_the_action_actually_patches(self, cao_tree):
        from sccs.doctor.installer import _cao_provider_actions

        pkg, spec = cao_tree
        actions = _cao_provider_actions([self._status(spec, "missing", package_path=pkg, pending=["x"])])

        actions[0].python_callable()

        assert CaoDetector(package_path=pkg).get_statuses([spec])[0].state == "patched"

    def test_anchor_lost_is_never_runnable(self, cao_tree):
        """A half-applied patch leaves a package that imports but cannot launch,
        so a moved anchor gets a report and a pointer — never a guess."""
        from sccs.doctor.installer import _cao_provider_actions

        pkg, spec = cao_tree
        actions = _cao_provider_actions(
            [self._status(spec, "anchor_lost", package_path=pkg, problems=["models/provider.py: anchor not found"])]
        )

        assert actions[0].runnable is False
        assert actions[0].python_callable is None
        assert "models/provider.py" in actions[0].manual_block
        assert "DEFAULT_CAO_PROVIDERS" in actions[0].manual_block

    def test_one_action_per_provider(self, cao_tree, tmp_path):
        from sccs.doctor.installer import _cao_provider_actions

        pkg, spec = cao_tree
        second = _make_spec(tmp_path)
        second.name = "other_cli"
        actions = _cao_provider_actions(
            [
                self._status(spec, "missing", package_path=pkg, pending=["x"]),
                self._status(second, "partial", package_path=pkg, pending=["y"]),
            ]
        )

        assert [a.component for a in actions] == ["cao-provider:pi_cli", "cao-provider:other_cli"]


# --------------------------------------------------------------------------
# Reporter
# --------------------------------------------------------------------------


class TestCaoProviderReporting:
    @staticmethod
    def _status(spec, state, **kw):
        from sccs.doctor.cao import CaoProviderStatus

        return CaoProviderStatus(spec=spec, state=state, **kw)

    def test_patched_row_is_green(self, cao_tree):
        from sccs.doctor.reporter import _cao_provider_row

        pkg, spec = cao_tree
        label, status, _, detail = _cao_provider_row(self._status(spec, "patched", package_path=pkg))

        assert label == "cao provider: pi_cli"
        assert "OK" in status
        assert str(pkg) in detail

    def test_missing_row_names_the_cause(self, cao_tree):
        from sccs.doctor.reporter import _cao_provider_row

        pkg, spec = cao_tree
        _, status, _, detail = _cao_provider_row(self._status(spec, "missing", package_path=pkg))

        assert "MISSING" in status
        assert "CAO update" in detail
        assert "sccs doctor install" in detail

    def test_row_flags_a_missing_binary(self, cao_tree):
        """The patch applies fine without `pi`; no worker can start, though."""
        from sccs.doctor.reporter import _cao_provider_row

        pkg, spec = cao_tree
        _, _, _, detail = _cao_provider_row(self._status(spec, "patched", package_path=pkg, binary_on_path=False))

        assert "pi not on PATH" in detail

    def test_unpatched_provider_counts_as_a_problem(self, cao_tree):
        """A wiped provider must flip the exit code: the fleet still advertises
        pi workers that can no longer start."""
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.reporter import has_problems

        _, spec = cao_tree
        healthy = {
            "node": NodeStatus(
                installed=True,
                version="22.0.0",
                major=22,
                meets_minimum=True,
                install_hint=None,
                platform="macos",
            ),
            "claude_cli": ClaudeCliStatus(installed=True, binary_path="/usr/local/bin/claude"),
            "plugins": [],
            "npx_tools": [],
        }

        assert has_problems(**healthy) is False
        assert has_problems(**healthy, cao_providers=[self._status(spec, "missing")]) is True
        assert has_problems(**healthy, cao_providers=[self._status(spec, "anchor_lost")]) is True
        assert has_problems(**healthy, cao_providers=[self._status(spec, "patched")]) is False
