"""Core of `sccs agents`: configuration of the agent CLIs (no agent work is run here)."""

from __future__ import annotations


class SupervisorError(Exception):
    """Raised for refused or impossible supervisor operations."""


from sccs.supervisor.models import MODEL_PATTERN, ModelCheck, ModelList, check_model, list_models  # noqa: E402
from sccs.supervisor.tools import ToolId, ToolInfo, detect_tools  # noqa: E402

__all__ = [
    "MODEL_PATTERN",
    "ModelCheck",
    "ModelList",
    "SupervisorError",
    "ToolId",
    "ToolInfo",
    "check_model",
    "detect_tools",
    "list_models",
]
