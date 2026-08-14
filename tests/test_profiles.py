# Tests for sccs.doctor.profiles — switching artefact groups on and off.
#
# Every test builds its own ~/.claude/ tree and parking area under tmp_path;
# none of them touch the real home directory.

import json
from pathlib import Path

import pytest
import yaml

from sccs.doctor.managed import get_doctor_managed_excludes
from sccs.doctor.profiles import (
    DEFAULT_PROFILES,
    ProfileError,
    ProfileManager,
    ProfileSpec,
    ProfileStateManager,
    disabled_npx_tools,
    resolve_profiles,
    validate_profile_name,
)
from sccs.doctor.schema import DoctorConfig

SETTINGS = {
    "permissions": {"allow": ["Skill(*)"]},
    "statusLine": {"type": "command", "command": '"/node" "/home/.claude/hooks/gsd-statusline.js"'},
    "hooks": {
        "SessionStart": [
            {
                "hooks": [
                    {"type": "command", "command": 'python3 "$HOME/.claude/hooks/discover-skills.py"'},
                    {"type": "command", "command": '"/node" "/home/.claude/hooks/gsd-check-update.js"'},
                ]
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [{"type": "command", "command": '"/node" "/home/.claude/hooks/gsd-write-guard.js"'}],
            }
        ],
        "Stop": [
            {
                "hooks": [{"type": "command", "command": 'python3 "$HOME/.claude/hooks/cost-tracker.py"'}],
            }
        ],
    },
}


@pytest.fixture
def claude_dir(tmp_path: Path) -> Path:
    """A ~/.claude/ tree with two GSD skills, two GSD agents and own artefacts."""
    root = tmp_path / "claude"
    (root / "skills").mkdir(parents=True)
    (root / "agents").mkdir(parents=True)

    for name in ("gsd-manager", "gsd-debug", "odoo18"):
        d = root / "skills" / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")

    for name in ("gsd-planner.md", "gsd-executor.md", "odoo-developer.md"):
        (root / "agents" / name).write_text(f"# {name}\n", encoding="utf-8")

    (root / "statusline.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (root / "settings.json").write_text(json.dumps(SETTINGS, indent=2), encoding="utf-8")
    return root


@pytest.fixture
def manager(tmp_path: Path, claude_dir: Path) -> ProfileManager:
    state = ProfileStateManager(state_path=tmp_path / ".profile_state.yaml")
    return ProfileManager(
        resolve_profiles(None),
        claude_dir=claude_dir,
        park_root=tmp_path / "park",
        state_manager=state,
    )


def _settings(claude_dir: Path) -> dict:
    return json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))


def _hook_commands(data: dict) -> list[str]:
    out = []
    for entries in (data.get("hooks") or {}).values():
        for entry in entries:
            for h in entry.get("hooks", []):
                out.append(h.get("command", ""))
    return out


# --------------------------------------------------------------------- #
# Spec resolution                                                        #
# --------------------------------------------------------------------- #


def test_default_profiles_contain_gsd():
    assert "gsd" in DEFAULT_PROFILES
    spec = DEFAULT_PROFILES["gsd"]
    assert spec.skills == ["gsd-*"]
    assert spec.agents == ["gsd-*"]
    assert spec.hooks == ["gsd-"]
    assert spec.npx_tools == ["@opengsd/gsd-core"]


def test_user_override_replaces_bundled_spec():
    resolved = resolve_profiles({"gsd": ProfileSpec(skills=["custom-*"])})
    assert resolved["gsd"].skills == ["custom-*"]
    assert resolved["gsd"].agents == []  # full replacement, not a merge


def test_user_profile_is_added_alongside_defaults():
    resolved = resolve_profiles({"odoo": ProfileSpec(skills=["odoo*"])})
    assert set(resolved) == {"gsd", "odoo"}


@pytest.mark.parametrize("bad", ["GSD", "-gsd", "gsd/../etc", "", "gsd profile"])
def test_invalid_profile_names_rejected(bad):
    with pytest.raises(ProfileError):
        validate_profile_name(bad)


def test_statusline_fallback_preset_must_be_a_preset_name():
    with pytest.raises(ValueError):
        ProfileSpec(statusline_fallback_preset="../../etc/passwd")


# --------------------------------------------------------------------- #
# Deactivate                                                             #
# --------------------------------------------------------------------- #


def test_deactivate_parks_matching_artefacts_only(manager: ProfileManager, claude_dir: Path):
    change = manager.deactivate("gsd")

    assert sorted(change.skills) == ["gsd-debug", "gsd-manager"]
    assert sorted(change.agents) == ["gsd-executor.md", "gsd-planner.md"]

    # Own artefacts untouched.
    assert (claude_dir / "skills" / "odoo18").is_dir()
    assert (claude_dir / "agents" / "odoo-developer.md").is_file()
    # GSD artefacts gone from ~/.claude ...
    assert not (claude_dir / "skills" / "gsd-manager").exists()
    # ... and present in the parking area, content intact.
    parked = manager.park_root / "gsd" / "skills" / "gsd-manager" / "SKILL.md"
    assert parked.read_text(encoding="utf-8") == "# gsd-manager\n"


def test_deactivate_removes_only_matching_hooks(manager: ProfileManager, claude_dir: Path):
    change = manager.deactivate("gsd")

    assert change.hooks == 2
    commands = _hook_commands(_settings(claude_dir))
    assert not any("gsd-" in c for c in commands)
    assert any("discover-skills.py" in c for c in commands)
    assert any("cost-tracker.py" in c for c in commands)


def test_deactivate_drops_emptied_entries_and_events(manager: ProfileManager, claude_dir: Path):
    manager.deactivate("gsd")
    hooks = _settings(claude_dir)["hooks"]
    # PreToolUse held only the gsd write-guard → the whole event key goes.
    assert "PreToolUse" not in hooks
    # SessionStart keeps its non-gsd entry.
    assert len(hooks["SessionStart"][0]["hooks"]) == 1


def test_deactivate_points_statusline_at_fallback_preset(manager: ProfileManager, claude_dir: Path):
    change = manager.deactivate("gsd")
    assert change.statusline == "claude-code-statusline"
    sl = _settings(claude_dir)["statusLine"]
    assert sl == {"type": "command", "command": "~/.claude/statusline", "padding": 0}


def test_unknown_fallback_preset_aborts_the_switch(tmp_path: Path, claude_dir: Path):
    """A typo in the profile must not silently leave a dead statusline."""
    profiles = resolve_profiles({"gsd": ProfileSpec(hooks=["gsd-"], statusline_fallback_preset="typo-preset")})
    mgr = ProfileManager(
        profiles,
        claude_dir=claude_dir,
        park_root=tmp_path / "park",
        state_manager=ProfileStateManager(state_path=tmp_path / "s.yaml"),
    )
    with pytest.raises(ProfileError, match="not a known preset"):
        mgr.deactivate("gsd")


def test_unrelated_statusline_is_left_alone(tmp_path: Path, claude_dir: Path):
    data = _settings(claude_dir)
    data["statusLine"] = {"type": "command", "command": '"/usr/bin/starship"'}
    (claude_dir / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    mgr = ProfileManager(
        resolve_profiles(None),
        claude_dir=claude_dir,
        park_root=tmp_path / "park",
        state_manager=ProfileStateManager(state_path=tmp_path / "s.yaml"),
    )
    change = mgr.deactivate("gsd")
    assert change.statusline is None
    assert _settings(claude_dir)["statusLine"]["command"] == '"/usr/bin/starship"'


def test_deactivate_is_idempotent(manager: ProfileManager):
    manager.deactivate("gsd")
    second = manager.deactivate("gsd")
    assert second.noop is True
    assert second.total == 0


def test_deactivate_persists_state(manager: ProfileManager, tmp_path: Path):
    manager.deactivate("gsd")
    raw = yaml.safe_load((tmp_path / ".profile_state.yaml").read_text(encoding="utf-8"))
    rec = raw["profiles"]["gsd"]
    assert rec["enabled"] is False
    assert sorted(rec["parked_skills"]) == ["gsd-debug", "gsd-manager"]
    assert len(rec["removed_hooks"]) == 2
    assert rec["changed_at"]


# --------------------------------------------------------------------- #
# Activate / round trip                                                  #
# --------------------------------------------------------------------- #


def test_round_trip_restores_everything(manager: ProfileManager, claude_dir: Path):
    before_settings = _settings(claude_dir)
    before_skills = sorted(p.name for p in (claude_dir / "skills").iterdir())
    before_agents = sorted(p.name for p in (claude_dir / "agents").iterdir())

    manager.deactivate("gsd")
    manager.activate("gsd")

    assert sorted(p.name for p in (claude_dir / "skills").iterdir()) == before_skills
    assert sorted(p.name for p in (claude_dir / "agents").iterdir()) == before_agents

    after = _settings(claude_dir)
    assert sorted(_hook_commands(after)) == sorted(_hook_commands(before_settings))
    assert after["statusLine"] == before_settings["statusLine"]
    assert after["permissions"] == before_settings["permissions"]


def test_activate_restores_hooks_into_their_matcher_slot(manager: ProfileManager, claude_dir: Path):
    manager.deactivate("gsd")
    manager.activate("gsd")
    pre = _settings(claude_dir)["hooks"]["PreToolUse"]
    assert len(pre) == 1
    assert pre[0]["matcher"] == "Write|Edit"
    assert "gsd-write-guard.js" in pre[0]["hooks"][0]["command"]


def test_activate_keeps_edits_made_while_parked(manager: ProfileManager, claude_dir: Path):
    manager.deactivate("gsd")

    data = _settings(claude_dir)
    data["hooks"].setdefault("Stop", [])[0]["hooks"].append({"type": "command", "command": "echo new"})
    (claude_dir / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    manager.activate("gsd")
    commands = _hook_commands(_settings(claude_dir))
    assert "echo new" in commands  # survived
    assert any("gsd-write-guard.js" in c for c in commands)  # and gsd is back


def test_round_trip_preserves_hook_grouping(tmp_path: Path, claude_dir: Path):
    """Several outer entries may share one matcher — the shape must survive.

    Regression: restoring by matcher alone merged separate entries into the
    first match, so a real settings.json came back with fewer outer entries
    than it started with (functionally equal, structurally rewritten).
    """
    data = _settings(claude_dir)
    data["hooks"]["PreToolUse"] = [
        {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "/hooks/gsd-prompt-guard.js"}]},
        {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "/hooks/gsd-read-guard.js"}]},
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "/hooks/own-guard.sh"}]},
        {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "/hooks/gsd-write-guard.js"}]},
    ]
    (claude_dir / "settings.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    before = _settings(claude_dir)

    mgr = ProfileManager(
        resolve_profiles(None),
        claude_dir=claude_dir,
        park_root=tmp_path / "park",
        state_manager=ProfileStateManager(state_path=tmp_path / "s.yaml"),
    )
    mgr.deactivate("gsd")
    # While parked only the non-gsd entry remains.
    assert len(_settings(claude_dir)["hooks"]["PreToolUse"]) == 1

    mgr.activate("gsd")
    assert _settings(claude_dir)["hooks"] == before["hooks"]


def test_round_trip_keeps_user_deletion_made_while_parked(tmp_path: Path, claude_dir: Path):
    """A hook the user removed while parked must not come back."""
    mgr = ProfileManager(
        resolve_profiles(None),
        claude_dir=claude_dir,
        park_root=tmp_path / "park",
        state_manager=ProfileStateManager(state_path=tmp_path / "s.yaml"),
    )
    mgr.deactivate("gsd")

    data = _settings(claude_dir)
    data["hooks"]["SessionStart"][0]["hooks"] = []  # user drops discover-skills.py
    (claude_dir / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    mgr.activate("gsd")
    commands = _hook_commands(_settings(claude_dir))
    assert not any("discover-skills.py" in c for c in commands)  # stays deleted
    assert any("gsd-check-update.js" in c for c in commands)  # ours is back


def test_activate_is_idempotent(manager: ProfileManager, claude_dir: Path):
    manager.deactivate("gsd")
    manager.activate("gsd")
    second = manager.activate("gsd")
    assert second.noop is True
    # No duplicated hook entries from a second restore.
    commands = _hook_commands(_settings(claude_dir))
    assert len(commands) == len(set(commands))


def test_activate_removes_empty_parking_dirs(manager: ProfileManager):
    manager.deactivate("gsd")
    manager.activate("gsd")
    assert not (manager.park_root / "gsd" / "skills").exists()
    assert not (manager.park_root / "gsd" / "agents").exists()


# --------------------------------------------------------------------- #
# Safety                                                                 #
# --------------------------------------------------------------------- #


def test_collision_raises_instead_of_clobbering(manager: ProfileManager, claude_dir: Path):
    # Pre-seed the parking area with a same-named skill carrying other content.
    park = manager.park_root / "gsd" / "skills" / "gsd-manager"
    park.mkdir(parents=True)
    (park / "SKILL.md").write_text("# pre-existing\n", encoding="utf-8")

    with pytest.raises(ProfileError, match="already exists"):
        manager.deactivate("gsd")

    # Neither copy was destroyed.
    assert (park / "SKILL.md").read_text(encoding="utf-8") == "# pre-existing\n"
    assert (claude_dir / "skills" / "gsd-manager" / "SKILL.md").is_file()


def test_unknown_profile_raises(manager: ProfileManager):
    with pytest.raises(ProfileError, match="unknown profile"):
        manager.deactivate("nope")


def test_malformed_settings_raises_before_moving_anything(manager: ProfileManager, claude_dir: Path):
    (claude_dir / "settings.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ProfileError, match="not valid JSON"):
        manager.deactivate("gsd")

    # Filesystem untouched — settings.json is handled before any move.
    assert (claude_dir / "skills" / "gsd-manager").is_dir()
    assert not (manager.park_root / "gsd").exists()


def test_missing_settings_file_still_parks_artefacts(manager: ProfileManager, claude_dir: Path):
    (claude_dir / "settings.json").unlink()
    change = manager.deactivate("gsd")
    assert len(change.skills) == 2
    assert change.hooks == 0


# --------------------------------------------------------------------- #
# Doctor integration                                                     #
# --------------------------------------------------------------------- #


def test_disabled_npx_tools_reports_gsd(manager: ProfileManager, tmp_path: Path):
    profiles = resolve_profiles(None)
    state = ProfileStateManager(state_path=tmp_path / ".profile_state.yaml")

    assert disabled_npx_tools(profiles, state) == set()
    manager.deactivate("gsd")
    assert disabled_npx_tools(profiles, state) == {"@opengsd/gsd-core"}


def test_installable_npx_tools_drops_disabled_profile_tools(manager: ProfileManager, tmp_path: Path):
    cfg = DoctorConfig()
    profiles = resolve_profiles(None)
    state = ProfileStateManager(state_path=tmp_path / ".profile_state.yaml")

    assert "@opengsd/gsd-core" in [t.name for t in cfg.installable_npx_tools(profiles, state)]
    manager.deactivate("gsd")
    names = [t.name for t in cfg.installable_npx_tools(profiles, state)]
    assert "@opengsd/gsd-core" not in names
    assert "playwright-cli" in names  # unrelated tool survives


def test_sync_excludes_stay_intact_while_parked(manager: ProfileManager):
    """The sync exclude list must keep matching gsd-* even when parked.

    effective_npx_tools() is deliberately profile-blind: if parking GSD
    dropped the pattern, `sccs sync` would start picking up any gsd-*
    leftovers in ~/.claude/ and push them to the repo.
    """
    cfg = DoctorConfig()
    manager.deactivate("gsd")
    assert "@opengsd/gsd-core" in [t.name for t in cfg.effective_npx_tools()]
    assert "gsd-*" in get_doctor_managed_excludes(cfg)


# --------------------------------------------------------------------- #
# State manager                                                          #
# --------------------------------------------------------------------- #


def test_corrupt_state_degrades_to_enabled(tmp_path: Path):
    path = tmp_path / ".profile_state.yaml"
    path.write_text(":::not yaml:::", encoding="utf-8")
    mgr = ProfileStateManager(state_path=path)
    assert mgr.load().profiles == {}
    assert mgr.is_enabled("gsd") is True  # safe default: artefacts present


def test_missing_state_reports_enabled(tmp_path: Path):
    mgr = ProfileStateManager(state_path=tmp_path / "nope.yaml")
    assert mgr.is_enabled("gsd") is True
    assert mgr.disabled_names() == set()


# --------------------------------------------------------------------- #
# Status                                                                 #
# --------------------------------------------------------------------- #


def test_status_counts_live_then_parked(manager: ProfileManager):
    live = manager.status("gsd")
    assert live.enabled is True
    assert (live.live_skills, live.live_agents) == (2, 2)
    assert (live.parked_skills, live.parked_agents) == (0, 0)

    manager.deactivate("gsd")
    parked = manager.status("gsd")
    assert parked.enabled is False
    assert (parked.live_skills, parked.live_agents) == (0, 0)
    assert (parked.parked_skills, parked.parked_agents) == (2, 2)
    assert parked.removed_hooks == 2
