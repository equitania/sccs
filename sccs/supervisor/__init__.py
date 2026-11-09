"""Core of `sccs agents`: configuration of the agent CLIs (no agent work is run here)."""

from __future__ import annotations


class SupervisorError(Exception):
    """Raised for refused or impossible supervisor operations."""


from sccs.supervisor.models import MODEL_PATTERN, ModelCheck, ModelList, check_model, list_models  # noqa: E402
from sccs.supervisor.tools import ToolId, ToolInfo, detect_tools  # noqa: E402
from sccs.supervisor.wrappers import (  # noqa: E402
    AgentInfo,
    TemplateId,
    body_hash,
    detect_shape,
    find_model_token,
    scan_agents,
)

__all__ = [
    "AgentInfo",
    "MODEL_PATTERN",
    "ModelCheck",
    "ModelList",
    "SupervisorError",
    "TemplateId",
    "ToolId",
    "ToolInfo",
    "body_hash",
    "check_model",
    "detect_shape",
    "detect_tools",
    "find_model_token",
    "list_models",
    "scan_agents",
]
