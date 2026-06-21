# SCCS Integrations
# Detection and migration for Antigravity IDE, Claude Desktop and OpenCode

from sccs.integrations.antigravity import AntigravityMigrationResult, migrate_skills_to_prompts
from sccs.integrations.claude_desktop import TrustRegistrationResult, register_trusted_folder
from sccs.integrations.detectors import (
    AntigravityDetector,
    AntigravityInfo,
    AntigravitySkillGap,
    ClaudeDesktopDetector,
    ClaudeDesktopInfo,
)
from sccs.integrations.opencode import (
    ConversionResult,
    McpMergeResult,
    OpenCodeArtifactGap,
    OpenCodeDetector,
    OpenCodeInfo,
    convert_agents_to_opencode,
    convert_commands_to_opencode,
    list_opencode_models,
    merge_mcp_to_opencode,
    resolve_model_map,
)
from sccs.integrations.pi import (
    PiArtifactGap,
    PiDetector,
    PiExportResult,
    PiInfo,
    export_agents_to_pi,
    export_commands_to_pi,
    export_skills_to_pi,
)

__all__ = [
    "AntigravityDetector",
    "AntigravityInfo",
    "AntigravitySkillGap",
    "AntigravityMigrationResult",
    "ClaudeDesktopDetector",
    "ClaudeDesktopInfo",
    "ConversionResult",
    "McpMergeResult",
    "OpenCodeArtifactGap",
    "OpenCodeDetector",
    "OpenCodeInfo",
    "PiArtifactGap",
    "PiDetector",
    "PiExportResult",
    "PiInfo",
    "TrustRegistrationResult",
    "convert_agents_to_opencode",
    "convert_commands_to_opencode",
    "export_agents_to_pi",
    "export_commands_to_pi",
    "export_skills_to_pi",
    "list_opencode_models",
    "merge_mcp_to_opencode",
    "migrate_skills_to_prompts",
    "register_trusted_folder",
    "resolve_model_map",
]
