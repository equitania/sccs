# Tests for sccs.doctor.skill_packages — skill bundles installed through the
# `skills` CLI (HyperFrames). Every test builds its own lock file and skill
# directory under tmp_path; none touches ~/.agents or ~/.claude.

import json
from pathlib import Path

import pytest

from sccs.doctor import skill_packages as sp
from sccs.doctor.managed import get_doctor_managed_excludes
from sccs.doctor.profiles import (
    DEFAULT_PROFILES,
    ProfileManager,
    ProfileRecord,
    ProfileStateManager,
    disabled_skill_packages,
)
from sccs.doctor.runner import validate_command_head
from sccs.doctor.schema import DoctorConfig
from sccs.doctor.skill_packages import (
    SkillPackageDetector,
    SkillPackageSpec,
    SkillPackageStatus,
    lock_skill_names,
    package_skill_names,
    skill_package_install_actions,
    skill_package_update_actions,
)

SOURCE = "heygen-com/hyperframes"


def _write_lock(path: Path, entries: dict[str, str], updated: str = "2026-09-13T09:44:21.725Z") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 3,
                "skills": {name: {"source": src, "updatedAt": updated} for name, src in entries.items()},
            }
        ),
        encoding="utf-8",
    )


def _make_skill(root: Path, name: str, description: str = "A skill.") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\nBody\n", encoding="utf-8")
    return d


@pytest.fixture
def spec(tmp_path: Path) -> SkillPackageSpec:
    return SkillPackageSpec(
        name="hyperframes",
        source=SOURCE,
        target_dir=str(tmp_path / "claude" / "skills"),
        lock_file=str(tmp_path / "agents" / ".skill-lock.json"),
        known_skills=["figma", "hyperframes", "slideshow"],
    )


@pytest.fixture
def skills_root(spec: SkillPackageSpec) -> Path:
    root = Path(spec.target_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


# --------------------------------------------------------------------- #
# Spec                                                                   #
# --------------------------------------------------------------------- #


class TestSpec:
    def test_invocation_copies_globally_for_claude_code(self, spec):
        argv = spec.invocation()
        assert argv[:5] == ["npx", "-y", "skills", "add", SOURCE]
        # --copy: a symlink would be skipped by the sync scan and parked as a bare link.
        for flag in ("--global", "--yes", "--copy"):
            assert flag in argv
        assert argv[argv.index("--agent") + 1] == "claude-code"
        assert argv[argv.index("--skill") + 1] == "*"
        validate_command_head(argv[0])  # passes the runner allowlist

    @pytest.mark.parametrize("bad", ["--registry=evil/x", "owner/repo;rm", "no-slash", "a/b/c"])
    def test_source_must_be_owner_repo(self, bad):
        with pytest.raises(ValueError):
            SkillPackageSpec(name="x", source=bad)

    def test_bundled_hyperframes_lists_all_twenty_skills(self):
        bundled = sp.BUILTIN_SKILL_PACKAGES["hyperframes"]
        assert bundled.source == SOURCE
        assert len(bundled.known_skills) == 20
        assert "figma" in bundled.known_skills  # prefix-less names are the point


# --------------------------------------------------------------------- #
# Lock file                                                              #
# --------------------------------------------------------------------- #


class TestLockFile:
    def test_names_are_filtered_by_source(self, spec):
        _write_lock(
            Path(spec.lock_file),
            {"figma": SOURCE, "media-use": "HeyGen-com/HyperFrames", "find-skills": "vercel-labs/skills"},
        )
        # Source match is case-insensitive; the CLI's own find-skills is not ours.
        assert lock_skill_names(spec) == ["figma", "media-use"]

    def test_lock_names_win_over_fallback(self, spec):
        _write_lock(Path(spec.lock_file), {"brand-new-skill": SOURCE})
        assert package_skill_names(spec) == ["brand-new-skill"]

    def test_missing_lock_falls_back_to_known_skills(self, spec):
        assert lock_skill_names(spec) == []
        assert package_skill_names(spec) == ["figma", "hyperframes", "slideshow"]

    def test_malformed_lock_falls_back_instead_of_raising(self, spec):
        Path(spec.lock_file).parent.mkdir(parents=True)
        Path(spec.lock_file).write_text("{not json", encoding="utf-8")
        assert package_skill_names(spec) == ["figma", "hyperframes", "slideshow"]


# --------------------------------------------------------------------- #
# Detector                                                               #
# --------------------------------------------------------------------- #


class TestDetector:
    def test_all_present_is_ok_and_shows_lock_date(self, spec, skills_root):
        _write_lock(Path(spec.lock_file), {"figma": SOURCE, "slideshow": SOURCE})
        _make_skill(skills_root, "figma")
        _make_skill(skills_root, "slideshow")
        st = SkillPackageDetector().get_statuses([spec])[0]
        assert st.state == "ok"
        assert st.lock_found is True
        assert st.updated_at == "2026-09-13"

    def test_installed_for_other_agents_only_is_missing(self, spec, skills_root):
        """The real starting point: `skills add` without claude-code wrote only ~/.agents."""
        _write_lock(Path(spec.lock_file), {"figma": SOURCE, "slideshow": SOURCE})
        st = SkillPackageDetector().get_statuses([spec])[0]
        assert st.state == "missing"
        assert st.needs_install is True

    def test_some_missing_is_partial(self, spec, skills_root):
        _write_lock(Path(spec.lock_file), {"figma": SOURCE, "slideshow": SOURCE})
        _make_skill(skills_root, "figma")
        st = SkillPackageDetector().get_statuses([spec])[0]
        assert st.state == "partial"
        assert st.missing == ["slideshow"]

    def test_symlinked_skill_needs_a_copy_install(self, spec, skills_root, tmp_path):
        _write_lock(Path(spec.lock_file), {"figma": SOURCE})
        real = _make_skill(tmp_path / "agents" / "skills", "figma")
        (skills_root / "figma").symlink_to(real, target_is_directory=True)
        st = SkillPackageDetector().get_statuses([spec])[0]
        assert st.state == "partial"
        assert st.symlinked == ["figma"]

    def test_unloadable_skill_md_is_invalid_not_missing(self, spec, skills_root):
        _write_lock(Path(spec.lock_file), {"figma": SOURCE})
        _make_skill(skills_root, "figma", description="x" * 1100)
        st = SkillPackageDetector().get_statuses([spec])[0]
        assert st.state == "invalid"
        assert "figma" in st.invalid
        assert st.needs_install is False

    def test_no_lock_uses_known_skills(self, spec, skills_root):
        for name in spec.known_skills:
            _make_skill(skills_root, name)
        st = SkillPackageDetector().get_statuses([spec])[0]
        assert st.state == "ok"
        assert st.lock_found is False
        assert st.updated_at is None


# --------------------------------------------------------------------- #
# Actions                                                                #
# --------------------------------------------------------------------- #


def _status(spec, state):
    return SkillPackageStatus(spec=spec, state=state, expected=["figma"])


class TestActions:
    def test_install_only_for_missing_or_partial(self, spec):
        statuses = [_status(spec, s) for s in ("ok", "missing", "partial", "invalid")]
        actions = skill_package_install_actions(statuses, install_deps=("perm:npm root -g",))
        assert len(actions) == 2
        assert all(a.cmd == spec.invocation() for a in actions)
        assert actions[0].component == "skill-package:hyperframes"
        assert actions[0].depends_on_components == ("perm:npm root -g",)
        assert actions[0].auto_confirm is True

    def test_update_refreshes_every_enabled_package(self, spec):
        actions = skill_package_update_actions([_status(spec, "ok"), _status(spec, "missing")])
        assert [a.label.split()[0] for a in actions] == ["refresh", "install"]

    def test_nothing_enabled_means_no_actions(self):
        assert skill_package_install_actions(None) == []
        assert skill_package_update_actions([]) == []


# --------------------------------------------------------------------- #
# Config opt-in and profiles                                             #
# --------------------------------------------------------------------- #


def _state_with_disabled(tmp_path: Path, name: str) -> ProfileStateManager:
    mgr = ProfileStateManager(tmp_path / "profile_state.yaml")
    state = mgr.load()
    state.profiles[name] = ProfileRecord(enabled=False)
    mgr.save(state)
    return mgr


class TestConfig:
    def test_opt_in_is_empty_by_default(self):
        assert DoctorConfig().effective_skill_packages() == []

    def test_unknown_names_are_ignored(self):
        cfg = DoctorConfig(skill_packages=["hyperframes", "does-not-exist"])
        assert [p.name for p in cfg.effective_skill_packages()] == ["hyperframes"]

    def test_switched_off_profile_is_not_reinstalled(self, tmp_path):
        cfg = DoctorConfig(skill_packages=["hyperframes"])
        state = _state_with_disabled(tmp_path, "hyperframes")
        assert disabled_skill_packages(DEFAULT_PROFILES, state) == {"hyperframes"}
        assert cfg.installable_skill_packages(None, state) == []
        # Profile-blind on purpose: the sync excludes must still resolve the package.
        assert [p.name for p in cfg.effective_skill_packages()] == ["hyperframes"]


class TestSyncExcludes:
    def test_lock_names_are_excluded_even_without_opt_in(self, spec, monkeypatch):
        monkeypatch.setitem(sp.BUILTIN_SKILL_PACKAGES, "hyperframes", spec)
        _write_lock(Path(spec.lock_file), {"figma": SOURCE, "find-skills": "vercel-labs/skills"})
        excludes = get_doctor_managed_excludes(DoctorConfig())
        assert "figma" in excludes
        assert "find-skills" not in excludes
        assert "gsd-*" in excludes  # existing registry untouched

    def test_fallback_names_never_hide_a_private_skill_without_opt_in(self, spec, monkeypatch):
        monkeypatch.setitem(sp.BUILTIN_SKILL_PACKAGES, "hyperframes", spec)
        excludes = get_doctor_managed_excludes(DoctorConfig())
        assert "figma" not in excludes

    def test_fallback_names_apply_when_opted_in_without_lock(self, spec, monkeypatch):
        monkeypatch.setitem(sp.BUILTIN_SKILL_PACKAGES, "hyperframes", spec)
        excludes = get_doctor_managed_excludes(DoctorConfig(skill_packages=["hyperframes"]))
        assert {"figma", "hyperframes", "slideshow"} <= set(excludes)


class TestProfile:
    def test_bundled_profile_exists(self):
        prof = DEFAULT_PROFILES["hyperframes"]
        assert prof.skill_packages == ["hyperframes"]
        assert prof.hooks == [] and prof.npx_tools == []

    def test_off_parks_lock_named_skills_and_on_restores(self, spec, tmp_path):
        claude = tmp_path / "claude"
        root = claude / "skills"
        _write_lock(Path(spec.lock_file), {"figma": SOURCE, "slideshow": SOURCE})
        for name in ("figma", "slideshow", "my-own-skill"):
            _make_skill(root, name)
        mgr = ProfileManager(
            {"hyperframes": DEFAULT_PROFILES["hyperframes"]},
            claude_dir=claude,
            park_root=tmp_path / "park",
            state_manager=ProfileStateManager(tmp_path / "state.yaml"),
            skill_packages={"hyperframes": spec},
        )

        change = mgr.deactivate("hyperframes")
        assert sorted(change.skills) == ["figma", "slideshow"]
        assert sorted(p.name for p in root.iterdir()) == ["my-own-skill"]
        assert (tmp_path / "park" / "hyperframes" / "skills" / "figma" / "SKILL.md").is_file()

        mgr.activate("hyperframes")
        assert sorted(p.name for p in root.iterdir()) == ["figma", "my-own-skill", "slideshow"]


# --------------------------------------------------------------------- #
# Reporter                                                               #
# --------------------------------------------------------------------- #


class TestReporter:
    def test_rows(self, spec):
        from sccs.doctor.reporter import _MISSING, _OK, _STALE, _skill_package_row

        ok = SkillPackageStatus(spec=spec, state="ok", expected=["figma"], updated_at="2026-09-13")
        assert _skill_package_row(ok)[1:3] == (_OK, "2026-09-13")
        assert _skill_package_row(_status(spec, "missing"))[1] == _MISSING
        partial = SkillPackageStatus(spec=spec, state="partial", expected=["a", "b"], missing=["a"])
        assert "1 missing of 2" in _skill_package_row(partial)[3]
        invalid = SkillPackageStatus(spec=spec, state="invalid", expected=["a"], invalid={"a": ["too long"]})
        assert _skill_package_row(invalid)[1] == _STALE

    def test_only_an_installable_gap_is_a_problem(self, spec):
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.reporter import has_problems
        from sccs.doctor.schema import NodeInstallSpec

        node = NodeStatus(
            installed=True,
            version="22.0.0",
            major=22,
            meets_minimum=True,
            install_hint=NodeInstallSpec(runnable=False, label="x"),
            platform="macos",
        )
        cli = ClaudeCliStatus(installed=True, binary_path="/x/claude")
        base = {"node": node, "claude_cli": cli, "plugins": [], "npx_tools": []}
        assert has_problems(**base, skill_packages=[_status(spec, "missing")]) is True
        assert has_problems(**base, skill_packages=[_status(spec, "invalid")]) is False
        assert has_problems(**base, skill_packages=[_status(spec, "ok")]) is False
