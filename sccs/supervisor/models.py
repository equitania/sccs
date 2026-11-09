"""Per-tool model lists and model-name validation for supervisor wrappers.

A model name ends up in a wrapper file that a shell runs, so it must pass
`MODEL_PATTERN` before anything else; a readable list can then veto it further.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sccs.doctor.runner import run_agy_models, run_opencode_models
from sccs.supervisor.tools import ToolId, codex_default_model

MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/~][A-Za-z0-9._:/~-]*$")

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")
_CLAUDE_MODELS = ("haiku", "sonnet", "opus", "fable")


@dataclass(frozen=True)
class ModelList:
    tool: ToolId
    models: tuple[str, ...]
    readable: bool


@dataclass(frozen=True)
class ModelCheck:
    ok: bool
    status: Literal["verified", "unverified", "rejected"]
    reason: str | None


def _parse_lines(raw: str) -> tuple[str, ...]:
    lines = (_ANSI.sub("", line).strip() for line in raw.splitlines())
    return tuple(dict.fromkeys(line for line in lines if line))


def _pi_models(home: Path) -> tuple[str, ...] | None:
    try:
        data = json.loads((home / ".pi" / "agent" / "models.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        return None
    ids: list[str] = []
    for provider in providers.values():
        models = provider.get("models") if isinstance(provider, dict) else None
        if not isinstance(models, list):
            continue
        for entry in models:
            mid = entry.get("id") if isinstance(entry, dict) else None
            if isinstance(mid, str) and mid and mid not in ids:
                ids.append(mid)
    return tuple(ids) if ids else None


def list_models(tool: ToolId, home: Path | None = None) -> ModelList:
    """Return the models a tool offers; `readable` says whether the list is authoritative."""
    base = home if home is not None else Path.home()
    if tool == "claude":
        return ModelList(tool, _CLAUDE_MODELS, True)
    if tool == "codex":
        model = codex_default_model(base)
        return ModelList(tool, (model,) if model else (), False)
    if tool == "pi":
        ids = _pi_models(base)
        return ModelList(tool, ids or (), ids is not None)
    raw = run_agy_models() if tool == "agy" else run_opencode_models()
    models = _parse_lines(raw)
    return ModelList(tool, models, bool(models))


def check_model(template: str, model: str, available: ModelList) -> ModelCheck:
    """Validate `model` for a wrapper template ("agy" | "opencode" | "codex")."""
    if not MODEL_PATTERN.match(model) or "\n" in model:
        return ModelCheck(False, "rejected", "model name contains characters that are not allowed")
    if template == "agy" and not model.startswith("gemini-"):
        return ModelCheck(False, "rejected", "the Gemini template requires a model starting with 'gemini-'")
    if not available.readable:
        return ModelCheck(True, "unverified", "model list could not be read")
    if model not in available.models:
        return ModelCheck(False, "rejected", "model is not offered by the tool")
    return ModelCheck(True, "verified", None)


FREE_MODEL_WARNING = "Free opencode/* models have an unclear data policy \u2014 not for code with customer data."


def model_warning(template: str, model: str) -> str | None:
    """Warning text for models with an unclear data policy (free ``opencode/*``), else None."""
    if template == "opencode" and model.startswith("opencode/"):
        return FREE_MODEL_WARNING
    return None
