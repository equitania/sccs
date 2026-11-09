"""Detect the five agent CLIs: installed, version, login presence, default model.

Auth files are checked for existence only; their contents are never read.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sccs.doctor.runner import run_tool_version, which

ToolId = Literal["claude", "codex", "opencode", "agy", "pi"]
Login = Literal["yes", "no", "unknown"]


@dataclass(frozen=True)
class ToolInfo:
    id: ToolId
    label: str
    binary: str
    installed: bool
    version: str | None
    login: Login
    default_model: str | None
    config_path: Path
    config_present: bool


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _claude_model(home: Path) -> str | None:
    data = _read_json(home / ".claude" / "settings.json")
    value = data.get("model") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def _codex_model(home: Path) -> str | None:
    try:
        data = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("model")
    return value if isinstance(value, str) and value else None


def _pi_model(home: Path) -> str | None:
    data = _read_json(home / ".pi" / "agent" / "settings.json")
    value = data.get("defaultModel") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class _Spec:
    id: ToolId
    label: str
    config: str  # relative to home
    auth: str | None  # relative to home; None -> login unknown
    model: Callable[[Path], str | None] | None


_SPECS: tuple[_Spec, ...] = (
    _Spec("claude", "Claude Code", ".claude", None, _claude_model),
    _Spec("codex", "Codex", ".codex", ".codex/auth.json", _codex_model),
    _Spec("opencode", "OpenCode", ".config/opencode", ".local/share/opencode/auth.json", None),
    _Spec("agy", "Antigravity", ".gemini/antigravity", None, None),
    _Spec("pi", "Pi", ".pi/agent", ".pi/agent/auth.json", _pi_model),
)


def detect_tools(home: Path | None = None) -> list[ToolInfo]:
    """Return one ToolInfo per agent CLI in fixed order."""
    base = home if home is not None else Path.home()
    result: list[ToolInfo] = []
    for spec in _SPECS:
        installed = which(spec.id) is not None
        config_path = base / spec.config
        if spec.auth is None:
            login: Login = "unknown"
        else:
            login = "yes" if (base / spec.auth).exists() else "no"
        result.append(
            ToolInfo(
                id=spec.id,
                label=spec.label,
                binary=spec.id,
                installed=installed,
                version=run_tool_version(spec.id) if installed else None,
                login=login,
                default_model=spec.model(base) if spec.model else None,
                config_path=config_path,
                config_present=config_path.exists(),
            )
        )
    return result
