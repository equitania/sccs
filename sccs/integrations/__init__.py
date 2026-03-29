# SCCS Integrations
# Detection and migration for Antigravity IDE and Claude Desktop

from sccs.integrations.antigravity import AntigravityMigrationResult, migrate_skills_to_prompts
from sccs.integrations.claude_desktop import TrustRegistrationResult, register_trusted_folder
from sccs.integrations.detectors import (
    AntigravityDetector,
    AntigravityInfo,
    AntigravitySkillGap,
    ClaudeDesktopDetector,
    ClaudeDesktopInfo,
)

__all__ = [
    "AntigravityDetector",
    "AntigravityInfo",
    "AntigravitySkillGap",
    "AntigravityMigrationResult",
    "ClaudeDesktopDetector",
    "ClaudeDesktopInfo",
    "TrustRegistrationResult",
    "migrate_skills_to_prompts",
    "register_trusted_folder",
]
