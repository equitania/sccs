# SCCS Doctor
# System & plugin health checks for Claude Code environments.
#
# Detects whether Node.js (>= MIN_NODE_MAJOR), Claude CLI, the configured
# Claude plugins and the npx helper tools are installed, and offers
# platform-aware install/update flows behind explicit confirmation prompts.

from sccs.doctor.defaults import (
    BUILTIN_CLI_TOOLS,
    DEFAULT_CLAUDE_PLUGINS,
    DEFAULT_NPX_TOOLS,
    MIN_NODE_MAJOR,
    NODE_INSTALL,
)
from sccs.doctor.detectors import (
    ClaudeCliDetector,
    ClaudeCliStatus,
    ClaudePluginDetector,
    CliToolDetector,
    CliToolStatus,
    NodeDetector,
    NodeStatus,
    NpxToolDetector,
    NpxToolStatus,
    PluginStatus,
)
from sccs.doctor.installer import (
    DoctorAction,
    ExecuteResult,
    InstallPlan,
    build_install_plan,
    build_update_plan,
    execute_plan,
)
from sccs.doctor.managed import DEFAULT_MANAGED_PATTERNS, get_doctor_managed_excludes
from sccs.doctor.runner import DoctorError, validate_command_head, validate_editor
from sccs.doctor.schema import CliToolSpec, DoctorConfig, NodeInstallSpec, NpxToolSpec, PluginSpec
from sccs.doctor.state import DoctorState, DoctorStateManager, NpxToolMark

__all__ = [
    "BUILTIN_CLI_TOOLS",
    "DEFAULT_CLAUDE_PLUGINS",
    "DEFAULT_MANAGED_PATTERNS",
    "DEFAULT_NPX_TOOLS",
    "MIN_NODE_MAJOR",
    "NODE_INSTALL",
    "ClaudeCliDetector",
    "ClaudeCliStatus",
    "ClaudePluginDetector",
    "CliToolDetector",
    "CliToolSpec",
    "CliToolStatus",
    "DoctorAction",
    "DoctorConfig",
    "DoctorError",
    "DoctorState",
    "validate_command_head",
    "validate_editor",
    "DoctorStateManager",
    "NpxToolMark",
    "ExecuteResult",
    "InstallPlan",
    "NodeDetector",
    "NodeInstallSpec",
    "NodeStatus",
    "NpxToolDetector",
    "NpxToolSpec",
    "NpxToolStatus",
    "PluginSpec",
    "PluginStatus",
    "build_install_plan",
    "build_update_plan",
    "execute_plan",
    "get_doctor_managed_excludes",
]
