"""Core of `sccs agents`: configuration of the agent CLIs (no agent work is run here)."""

from __future__ import annotations


class SupervisorError(Exception):
    """Raised for refused or impossible supervisor operations."""


from sccs.supervisor.tools import ToolId, ToolInfo, detect_tools  # noqa: E402

__all__ = ["SupervisorError", "ToolId", "ToolInfo", "detect_tools"]
