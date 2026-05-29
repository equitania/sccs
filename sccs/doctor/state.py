# SCCS Doctor State Tracker
#
# Some npx helper tools (notably @opengsd/get-shit-done-redux) do NOT install a binary
# on PATH — they only write configuration into ~/.claude/. Without state
# tracking the npx-tool detector would always report them as MISSING, so
# `sccs doctor install` would offer to re-run them on every invocation.
#
# This module persists "last successful run" markers in
# ~/.config/sccs/.doctor_state.yaml so detectors can fall back to a state
# lookup when both PATH and marker_path checks fail.

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

DEFAULT_STATE_PATH = Path.home() / ".config" / "sccs" / ".doctor_state.yaml"


def _hash_invocation(invocation: list[str]) -> str:
    """Stable short hash of the npx invocation argv (so changes invalidate state)."""
    joined = "\x00".join(invocation)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


@dataclass
class NpxToolMark:
    """A persisted record that an npx tool was installed/refreshed successfully."""

    last_run: str  # ISO-8601 UTC
    invocation_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {"last_run": self.last_run, "invocation_hash": self.invocation_hash}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NpxToolMark:
        return cls(
            last_run=data.get("last_run", ""),
            invocation_hash=data.get("invocation_hash", ""),
        )


@dataclass
class DoctorState:
    """Aggregate doctor state, persisted as YAML."""

    npx_tools: dict[str, NpxToolMark] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "npx_tools": {name: mark.to_dict() for name, mark in self.npx_tools.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DoctorState:
        npx = {
            name: NpxToolMark.from_dict(payload)
            for name, payload in (data.get("npx_tools") or {}).items()
            if isinstance(payload, dict)
        }
        return cls(npx_tools=npx)


class DoctorStateManager:
    """Read/write wrapper around ~/.config/sccs/.doctor_state.yaml."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or DEFAULT_STATE_PATH

    # ------------------------------------------------------------------ #
    # Persistence                                                        #
    # ------------------------------------------------------------------ #

    def load(self) -> DoctorState:
        if not self.state_path.exists():
            return DoctorState()
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (yaml.YAMLError, OSError):
            return DoctorState()
        if not isinstance(data, dict):
            return DoctorState()
        return DoctorState.from_dict(data)

    def save(self, state: DoctorState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(state.to_dict(), fh, default_flow_style=False, sort_keys=True)

    # ------------------------------------------------------------------ #
    # Convenience: per-tool helpers                                      #
    # ------------------------------------------------------------------ #

    def mark_npx_tool(self, name: str, invocation: list[str]) -> None:
        state = self.load()
        state.npx_tools[name] = NpxToolMark(
            last_run=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            invocation_hash=_hash_invocation(invocation),
        )
        self.save(state)

    def is_npx_tool_marked(self, name: str, invocation: list[str]) -> bool:
        """Return True iff the tool was successfully run with this exact argv."""
        state = self.load()
        mark = state.npx_tools.get(name)
        if mark is None:
            return False
        return mark.invocation_hash == _hash_invocation(invocation)

    def get_npx_tool_mark(self, name: str) -> NpxToolMark | None:
        return self.load().npx_tools.get(name)
