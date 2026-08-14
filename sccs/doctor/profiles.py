# SCCS Profiles — switch whole artefact groups off without deleting them
#
# `sccs doctor install` pulls in extensions that write dozens of skills,
# agents and hooks into ~/.claude/ (notably @opengsd/gsd-core: 71 skills,
# 34 agents, 19 hook entries). Every one of those descriptions is loaded
# into the model's system prompt at session start, and every PreToolUse
# hook spawns a process on each Read/Write/Bash call — whether or not the
# extension is being used that day.
#
# A profile groups those artefacts under one name so they can be switched
# off for everyday work and switched back on when actually needed.
#
# Design rules:
#   1. NOTHING IS DELETED. Skills and agents are *moved* to a parking area
#      under ~/.config/sccs/profiles/<name>/ and moved back on activate.
#   2. The parking area lives outside ~/.claude/, so parked artefacts drop
#      out of `sccs sync` scope without any exclude-pattern gymnastics.
#   3. Hook removal reuses the same semantics as the settings.json
#      sanitiser in installer.py (substring match on `command`), and the
#      removed entries are recorded so activate() can put them back where
#      they came from.
#   4. `doctor install/update` must not resurrect a disabled profile —
#      see DoctorConfig.installable_npx_tools() and the statusline guard
#      in installer.py.

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from sccs.utils.paths import atomic_write, matches_any_pattern

DEFAULT_PROFILE_STATE_PATH = Path.home() / ".config" / "sccs" / ".profile_state.yaml"
DEFAULT_PARK_ROOT = Path.home() / ".config" / "sccs" / "profiles"
DEFAULT_CLAUDE_DIR = Path.home() / ".claude"

_SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ProfileError(Exception):
    """Raised when a profile operation cannot be completed safely."""


# --------------------------------------------------------------------- #
# Spec                                                                   #
# --------------------------------------------------------------------- #


class ProfileSpec(BaseModel):
    """A named group of ~/.claude/ artefacts that can be switched off."""

    description: str = Field(
        default="",
        description="Human-readable summary shown by `sccs profile list`.",
    )
    skills: list[str] = Field(
        default_factory=list,
        description=(
            "fnmatch globs matched against directory names in ~/.claude/skills/. "
            "Matching directories are moved to the parking area while the "
            "profile is off."
        ),
    )
    agents: list[str] = Field(
        default_factory=list,
        description="fnmatch globs matched against file names in ~/.claude/agents/.",
    )
    hooks: list[str] = Field(
        default_factory=list,
        description=(
            "Substring patterns matched against `hooks[*].hooks[*].command` in "
            "~/.claude/settings.json — same semantics as doctor.disallowed_hooks. "
            "Matching entries are removed while the profile is off and restored "
            "on activate."
        ),
    )
    statusline_fallback_preset: str | None = Field(
        default=None,
        description=(
            "Name of the statusline preset to switch to while the profile is "
            "off (see sccs/doctor/statusline.py). Only applied when the current "
            "statusLine command matches one of the `hooks` patterns — i.e. when "
            "this profile actually owns the statusline — so an unrelated one is "
            "never touched. The previous block is stored and restored on activate."
        ),
    )
    npx_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Names of doctor npx tools that reinstall this profile's artefacts. "
            "While the profile is off, `sccs doctor install/update` skips them "
            "instead of writing the artefacts straight back."
        ),
    )

    @field_validator("statusline_fallback_preset")
    @classmethod
    def _validate_fallback_preset(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError(f"statusline_fallback_preset must be a preset name, got {v!r}")
        return v


# Bundled profiles. Keys must be safe names; values describe what the
# corresponding doctor tool writes into ~/.claude/.
DEFAULT_PROFILES: dict[str, ProfileSpec] = {
    # `npx @opengsd/gsd-core --claude --global --force-statusline` writes
    # gsd-* skills, agents and hooks plus a gsd-statusline.js statusline.
    # Same glob as managed.py:DEFAULT_MANAGED_PATTERNS, same `gsd-` hook
    # prefix as defaults.py:DEFAULT_PROTECTED_HOOKS.
    "gsd": ProfileSpec(
        description="GSD extension — skills, agents, hooks and statusline",
        skills=["gsd-*"],
        agents=["gsd-*"],
        hooks=["gsd-"],
        statusline_fallback_preset="claude-code-statusline",
        npx_tools=["@opengsd/gsd-core"],
    ),
}


def resolve_profiles(overrides: dict[str, ProfileSpec] | None) -> dict[str, ProfileSpec]:
    """Merge user-configured profiles over the bundled defaults.

    A user entry with the same key fully replaces the bundled spec, so a
    profile can be re-scoped (or emptied) without patching the package.
    """
    resolved = dict(DEFAULT_PROFILES)
    for name, spec in (overrides or {}).items():
        validate_profile_name(name)
        resolved[name] = spec
    return resolved


def validate_profile_name(name: str) -> str:
    if not _SAFE_NAME_RE.match(name):
        raise ProfileError(f"invalid profile name {name!r} — use lowercase letters, digits, '-' and '_' only")
    return name


# --------------------------------------------------------------------- #
# State                                                                  #
# --------------------------------------------------------------------- #


@dataclass
class RemovedHook:
    """One settings.json hook entry removed while a profile is off."""

    event: str
    matcher: str | None
    hook: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"event": self.event, "matcher": self.matcher, "hook": self.hook}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemovedHook:
        return cls(
            event=str(data.get("event", "")),
            matcher=data.get("matcher"),
            hook=data.get("hook") or {},
        )


@dataclass
class ProfileRecord:
    """Persisted state for one profile."""

    enabled: bool = True
    changed_at: str = ""
    parked_skills: list[str] = field(default_factory=list)
    parked_agents: list[str] = field(default_factory=list)
    removed_hooks: list[RemovedHook] = field(default_factory=list)
    # Full pre-strip entry list of every event we touched, keyed by event
    # name. Restoring from the individual RemovedHook entries alone would
    # lose the grouping: a real settings.json often holds SEVERAL outer
    # entries with the same matcher under one event, and re-inserting by
    # matcher collapses them into one. Keeping the original shape lets
    # activate() rebuild the event exactly as it was.
    original_hook_events: dict[str, list[Any]] = field(default_factory=dict)
    previous_statusline: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "changed_at": self.changed_at,
            "parked_skills": list(self.parked_skills),
            "parked_agents": list(self.parked_agents),
            "removed_hooks": [h.to_dict() for h in self.removed_hooks],
            "original_hook_events": self.original_hook_events,
            "previous_statusline": self.previous_statusline,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileRecord:
        events = data.get("original_hook_events") or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            changed_at=str(data.get("changed_at", "")),
            parked_skills=[str(s) for s in (data.get("parked_skills") or [])],
            parked_agents=[str(s) for s in (data.get("parked_agents") or [])],
            removed_hooks=[RemovedHook.from_dict(h) for h in (data.get("removed_hooks") or []) if isinstance(h, dict)],
            original_hook_events={k: v for k, v in events.items() if isinstance(v, list)},
            previous_statusline=data.get("previous_statusline"),
        )


@dataclass
class ProfileState:
    profiles: dict[str, ProfileRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"profiles": {name: rec.to_dict() for name, rec in self.profiles.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileState:
        recs = {
            name: ProfileRecord.from_dict(payload)
            for name, payload in (data.get("profiles") or {}).items()
            if isinstance(payload, dict)
        }
        return cls(profiles=recs)


class ProfileStateManager:
    """Read/write wrapper around ~/.config/sccs/.profile_state.yaml.

    Mirrors DoctorStateManager: a missing or corrupt file degrades to an
    empty state rather than raising, so a damaged state file can never
    make the CLI unusable — worst case a profile reads as enabled, which
    is the safe default (artefacts present).
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or DEFAULT_PROFILE_STATE_PATH

    def load(self) -> ProfileState:
        if not self.state_path.exists():
            return ProfileState()
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (yaml.YAMLError, OSError):
            return ProfileState()
        if not isinstance(data, dict):
            return ProfileState()
        return ProfileState.from_dict(data)

    def save(self, state: ProfileState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self.state_path,
            yaml.safe_dump(state.to_dict(), default_flow_style=False, sort_keys=True, allow_unicode=True),
            mode=0o600,
        )

    def record(self, name: str) -> ProfileRecord:
        return self.load().profiles.get(name) or ProfileRecord()

    def is_enabled(self, name: str) -> bool:
        return self.record(name).enabled

    def disabled_names(self) -> set[str]:
        return {name for name, rec in self.load().profiles.items() if not rec.enabled}


def disabled_npx_tools(
    profiles: dict[str, ProfileSpec],
    state_manager: ProfileStateManager | None = None,
) -> set[str]:
    """npx tool names belonging to profiles that are currently switched off.

    Used by DoctorConfig.installable_npx_tools() so `doctor install/update`
    does not write a disabled profile's artefacts straight back into
    ~/.claude/.
    """
    mgr = state_manager or ProfileStateManager()
    disabled = mgr.disabled_names()
    tools: set[str] = set()
    for name in disabled:
        spec = profiles.get(name)
        if spec:
            tools.update(spec.npx_tools)
    return tools


def disabled_hook_patterns(
    profiles: dict[str, ProfileSpec],
    state_manager: ProfileStateManager | None = None,
) -> set[str]:
    """Hook substring patterns owned by profiles that are switched off.

    The statusline installer consults this so `--force-statusline` tools
    cannot re-point statusLine at a disabled profile's script.
    """
    mgr = state_manager or ProfileStateManager()
    patterns: set[str] = set()
    for name in mgr.disabled_names():
        spec = profiles.get(name)
        if spec:
            patterns.update(spec.hooks)
    return patterns


# --------------------------------------------------------------------- #
# Status / change reporting                                              #
# --------------------------------------------------------------------- #


@dataclass
class ProfileStatus:
    name: str
    description: str
    enabled: bool
    changed_at: str
    live_skills: int
    live_agents: int
    parked_skills: int
    parked_agents: int
    removed_hooks: int


@dataclass
class ProfileChange:
    """What a deactivate/activate call actually did."""

    name: str
    enabled: bool
    skills: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    hooks: int = 0
    statusline: str | None = None
    noop: bool = False

    @property
    def total(self) -> int:
        return len(self.skills) + len(self.agents) + self.hooks


# --------------------------------------------------------------------- #
# Manager                                                                #
# --------------------------------------------------------------------- #


class ProfileManager:
    """Move a profile's artefacts between ~/.claude/ and the parking area."""

    def __init__(
        self,
        profiles: dict[str, ProfileSpec],
        *,
        claude_dir: Path | None = None,
        park_root: Path | None = None,
        state_manager: ProfileStateManager | None = None,
        statusline_presets: dict[str, Any] | None = None,
    ) -> None:
        self.profiles = profiles
        self.claude_dir = claude_dir or DEFAULT_CLAUDE_DIR
        self.park_root = park_root or DEFAULT_PARK_ROOT
        self.state = state_manager or ProfileStateManager()
        # Resolved lazily so importing profiles.py does not drag in the
        # statusline module for callers that never switch a profile.
        self._statusline_presets = statusline_presets

    # -- paths -------------------------------------------------------- #

    @property
    def settings_path(self) -> Path:
        return self.claude_dir / "settings.json"

    def _park_dir(self, name: str, kind: str) -> Path:
        return self.park_root / name / kind

    def _spec(self, name: str) -> ProfileSpec:
        validate_profile_name(name)
        spec = self.profiles.get(name)
        if spec is None:
            known = ", ".join(sorted(self.profiles)) or "none"
            raise ProfileError(f"unknown profile {name!r} — configured profiles: {known}")
        return spec

    # -- discovery ---------------------------------------------------- #

    def _live_skills(self, spec: ProfileSpec) -> list[Path]:
        root = self.claude_dir / "skills"
        if not spec.skills or not root.is_dir():
            return []
        return sorted(p for p in root.iterdir() if p.is_dir() and matches_any_pattern(p.name, spec.skills))

    def _live_agents(self, spec: ProfileSpec) -> list[Path]:
        root = self.claude_dir / "agents"
        if not spec.agents or not root.is_dir():
            return []
        return sorted(p for p in root.iterdir() if p.is_file() and matches_any_pattern(p.name, spec.agents))

    def _parked(self, name: str, kind: str) -> list[Path]:
        park = self._park_dir(name, kind)
        if not park.is_dir():
            return []
        return sorted(park.iterdir())

    # -- status ------------------------------------------------------- #

    def status(self, name: str) -> ProfileStatus:
        spec = self._spec(name)
        rec = self.state.record(name)
        return ProfileStatus(
            name=name,
            description=spec.description,
            enabled=rec.enabled,
            changed_at=rec.changed_at,
            live_skills=len(self._live_skills(spec)),
            live_agents=len(self._live_agents(spec)),
            parked_skills=len(self._parked(name, "skills")),
            parked_agents=len(self._parked(name, "agents")),
            removed_hooks=len(rec.removed_hooks),
        )

    def all_status(self) -> list[ProfileStatus]:
        return [self.status(name) for name in sorted(self.profiles)]

    # -- move helpers ------------------------------------------------- #

    @staticmethod
    def _move(src: Path, dest_dir: Path) -> None:
        """Move one artefact, refusing to clobber an existing target.

        A collision means the parking area and ~/.claude/ both hold the
        same item — an inconsistent state that a blind overwrite would
        turn into data loss. Surfacing it is the only safe option.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if dest.exists():
            raise ProfileError(f"cannot move {src} — {dest} already exists. Resolve the duplicate by hand, then retry.")
        shutil.move(str(src), str(dest))

    # -- settings.json ------------------------------------------------ #

    def _read_settings(self) -> dict[str, Any] | None:
        p = self.settings_path
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProfileError(f"{p} is not valid JSON: {exc}") from exc
        return data if isinstance(data, dict) else None

    def _write_settings(self, data: dict[str, Any]) -> None:
        atomic_write(self.settings_path, json.dumps(data, indent=2) + "\n", mode=0o600)

    def _strip_hooks(self, data: dict[str, Any], patterns: list[str]) -> tuple[list[RemovedHook], dict[str, list[Any]]]:
        """Remove matching hook entries.

        Returns what was taken out plus the pre-strip entry list of every
        event that was touched — activate() needs the latter to rebuild the
        original grouping (see ProfileRecord.original_hook_events).

        Mirrors installer.py:_settings_hook_cleanup_actions — including the
        cleanup of outer entries and event keys left empty — so a profile
        switch and a doctor sanitiser pass leave settings.json in the same
        shape.
        """
        hooks_root = data.get("hooks")
        if not isinstance(hooks_root, dict) or not patterns:
            return [], {}

        removed: list[RemovedHook] = []
        originals: dict[str, list[Any]] = {}
        new_hooks: dict[str, Any] = {}

        for event, entries in hooks_root.items():
            if not isinstance(entries, list):
                new_hooks[event] = entries
                continue
            kept_entries: list[Any] = []
            touched = False
            for entry in entries:
                if not isinstance(entry, dict):
                    kept_entries.append(entry)
                    continue
                inner = entry.get("hooks")
                if not isinstance(inner, list):
                    kept_entries.append(entry)
                    continue
                matcher = entry.get("matcher")
                kept_inner: list[Any] = []
                for ih in inner:
                    cmd = ih.get("command") if isinstance(ih, dict) else None
                    if isinstance(cmd, str) and any(pat in cmd for pat in patterns):
                        removed.append(RemovedHook(event=event, matcher=matcher, hook=ih))
                        touched = True
                    else:
                        kept_inner.append(ih)
                if kept_inner:
                    new_entry = dict(entry)
                    new_entry["hooks"] = kept_inner
                    kept_entries.append(new_entry)
                # else: drop the outer entry — its hooks list is now empty.
            if touched:
                originals[event] = entries
            if kept_entries:
                new_hooks[event] = kept_entries
            # else: drop the event key — no entries left.

        if removed:
            data["hooks"] = new_hooks
        return removed, originals

    @staticmethod
    def _entry_commands(entries: list[Any]) -> set[str]:
        out: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for ih in entry.get("hooks") or []:
                cmd = ih.get("command") if isinstance(ih, dict) else None
                if isinstance(cmd, str):
                    out.add(cmd)
        return out

    def _restore_hooks(self, data: dict[str, Any], rec: ProfileRecord) -> int:
        """Rebuild each touched event from its pre-strip shape.

        A three-way merge against the stored original, so that switching a
        profile on is loss-free in both directions:

          * a hook we removed comes back in its original outer entry — the
            grouping survives even when several entries share a matcher;
          * a hook the user added while the profile was parked is kept and
            appended;
          * a hook the user deliberately deleted while the profile was
            parked stays deleted (it is in the original but neither in the
            current file nor in our removed set).

        Repeating the operation is a no-op: the second pass finds every
        command already present and merges to the same result.
        """
        removed = rec.removed_hooks
        if not removed:
            return 0

        hooks_root = data.setdefault("hooks", {})
        if not isinstance(hooks_root, dict):
            raise ProfileError("settings.json 'hooks' is not an object — refusing to restore")

        removed_by_event: dict[str, set[str]] = {}
        for item in removed:
            cmd = item.hook.get("command")
            if isinstance(cmd, str):
                removed_by_event.setdefault(item.event, set()).add(cmd)

        restored = 0
        for event, removed_cmds in removed_by_event.items():
            current = hooks_root.get(event)
            current = current if isinstance(current, list) else []
            current_cmds = self._entry_commands(current)

            original = rec.original_hook_events.get(event)
            if not original:
                # No stored shape (state written by an older version) —
                # fall back to appending into a matching matcher slot.
                restored += self._append_removed(hooks_root, event, removed, current_cmds)
                continue

            rebuilt: list[Any] = []
            for entry in original:
                if not isinstance(entry, dict):
                    rebuilt.append(entry)
                    continue
                inner = entry.get("hooks")
                if not isinstance(inner, list):
                    rebuilt.append(entry)
                    continue
                kept: list[Any] = []
                for ih in inner:
                    cmd = ih.get("command") if isinstance(ih, dict) else None
                    if not isinstance(cmd, str):
                        kept.append(ih)
                    elif cmd in removed_cmds:
                        kept.append(ih)  # ours — bring it back
                        restored += 1
                    elif cmd in current_cmds:
                        kept.append(ih)  # untouched by us and still there
                    # else: user deleted it while parked — leave it gone.
                if kept:
                    new_entry = dict(entry)
                    new_entry["hooks"] = kept
                    rebuilt.append(new_entry)

            # Anything added while the profile was parked is appended with
            # its current grouping intact.
            rebuilt_cmds = self._entry_commands(rebuilt)
            for entry in current:
                if not isinstance(entry, dict):
                    continue
                extra = [
                    ih
                    for ih in (entry.get("hooks") or [])
                    if isinstance(ih, dict) and isinstance(ih.get("command"), str) and ih["command"] not in rebuilt_cmds
                ]
                if extra:
                    new_entry = dict(entry)
                    new_entry["hooks"] = extra
                    rebuilt.append(new_entry)

            hooks_root[event] = rebuilt

        return restored

    def _append_removed(
        self,
        hooks_root: dict[str, Any],
        event: str,
        removed: list[RemovedHook],
        current_cmds: set[str],
    ) -> int:
        """Fallback restore for state files without a stored original shape."""
        entries = hooks_root.setdefault(event, [])
        if not isinstance(entries, list):
            return 0
        restored = 0
        for item in (r for r in removed if r.event == event):
            cmd = item.hook.get("command")
            if isinstance(cmd, str) and cmd in current_cmds:
                continue
            slot = next(
                (e for e in entries if isinstance(e, dict) and e.get("matcher") == item.matcher),
                None,
            )
            if slot is None:
                slot = {"hooks": []}
                if item.matcher is not None:
                    slot["matcher"] = item.matcher
                entries.append(slot)
            inner = slot.setdefault("hooks", [])
            if isinstance(inner, list):
                inner.append(item.hook)
                restored += 1
        return restored

    def _statusline_matches(self, data: dict[str, Any], patterns: list[str]) -> bool:
        sl = data.get("statusLine")
        cmd = sl.get("command") if isinstance(sl, dict) else None
        return isinstance(cmd, str) and any(pat in cmd for pat in patterns)

    def _fallback_block(self, preset_name: str) -> dict[str, Any]:
        """Resolve a profile's fallback preset to a settings.json block.

        An unknown preset name is a configuration error and stops the
        switch: silently leaving the statusline pointing at the parked
        extension would give the user a blank status line with no clue why.
        """
        from sccs.doctor.statusline import StatusLineError, resolve_statusline_presets

        presets = resolve_statusline_presets(self._statusline_presets)
        preset = presets.get(preset_name)
        if preset is None:
            known = ", ".join(sorted(presets)) or "none"
            raise ProfileError(
                f"statusline_fallback_preset {preset_name!r} is not a known preset (known: {known}). "
                f"Fix the profile in config.yaml, or run `sccs statusline list`."
            )
        try:
            return preset.settings_block()
        except StatusLineError as exc:  # pragma: no cover - defensive
            raise ProfileError(str(exc)) from exc

    # -- operations --------------------------------------------------- #

    def deactivate(self, name: str) -> ProfileChange:
        """Park a profile's artefacts and strip its hooks. Nothing is deleted."""
        spec = self._spec(name)
        state = self.state.load()
        rec = state.profiles.get(name) or ProfileRecord()

        if not rec.enabled:
            return ProfileChange(name=name, enabled=False, noop=True)

        skills = self._live_skills(spec)
        agents = self._live_agents(spec)

        # settings.json first: if it is malformed we fail before touching
        # the filesystem, leaving ~/.claude/ untouched.
        removed_hooks: list[RemovedHook] = []
        original_events: dict[str, list[Any]] = {}
        statusline_note: str | None = None
        data = self._read_settings()
        if data is not None:
            removed_hooks, original_events = self._strip_hooks(data, spec.hooks)
            if spec.statusline_fallback_preset and self._statusline_matches(data, spec.hooks):
                rec.previous_statusline = data.get("statusLine")
                data["statusLine"] = self._fallback_block(spec.statusline_fallback_preset)
                statusline_note = spec.statusline_fallback_preset
            if removed_hooks or statusline_note:
                self._write_settings(data)

        for path in skills:
            self._move(path, self._park_dir(name, "skills"))
        for path in agents:
            self._move(path, self._park_dir(name, "agents"))

        rec.enabled = False
        rec.changed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rec.parked_skills = [p.name for p in skills]
        rec.parked_agents = [p.name for p in agents]
        rec.removed_hooks = removed_hooks
        rec.original_hook_events = original_events
        state.profiles[name] = rec
        self.state.save(state)

        return ProfileChange(
            name=name,
            enabled=False,
            skills=[p.name for p in skills],
            agents=[p.name for p in agents],
            hooks=len(removed_hooks),
            statusline=statusline_note,
        )

    def activate(self, name: str) -> ProfileChange:
        """Move a profile's artefacts back and restore its hooks."""
        self._spec(name)  # validates the name and that the profile is known
        state = self.state.load()
        rec = state.profiles.get(name) or ProfileRecord()

        if rec.enabled:
            return ProfileChange(name=name, enabled=True, noop=True)

        skills = self._parked(name, "skills")
        agents = self._parked(name, "agents")

        restored_hooks = 0
        statusline_note: str | None = None
        data = self._read_settings()
        if data is not None:
            restored_hooks = self._restore_hooks(data, rec)
            if rec.previous_statusline is not None:
                data["statusLine"] = rec.previous_statusline
                statusline_note = "restored"
            if restored_hooks or statusline_note:
                self._write_settings(data)

        for path in skills:
            self._move(path, self.claude_dir / "skills")
        for path in agents:
            self._move(path, self.claude_dir / "agents")

        # Drop now-empty parking directories; keep the profile root so the
        # location stays discoverable.
        for kind in ("skills", "agents"):
            park = self._park_dir(name, kind)
            if park.is_dir() and not any(park.iterdir()):
                park.rmdir()

        rec.enabled = True
        rec.changed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rec.parked_skills = []
        rec.parked_agents = []
        rec.removed_hooks = []
        rec.original_hook_events = {}
        rec.previous_statusline = None
        state.profiles[name] = rec
        self.state.save(state)

        return ProfileChange(
            name=name,
            enabled=True,
            skills=[p.name for p in skills],
            agents=[p.name for p in agents],
            hooks=restored_hooks,
            statusline=statusline_note,
        )
