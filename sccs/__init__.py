"""SCCS - Skills, Commands, Configs Sync for Claude Code.

A bidirectional synchronization tool for Claude Code skills, commands,
and configuration files between local (~/.claude/) and a Git repository.
"""

__version__ = "1.0.0"
__author__ = "Equitania Software GmbH"
__email__ = "info@equitania.de"

__all__ = [
    "__version__",
    "Command",
    "Skill",
    "SyncState",
    "SkillState",
    "CommandState",
    "SyncEngine",
    "SyncAction",
    "SyncResult",
    "ActionType",
    "ItemType",
    "scan_skills_directory",
    "scan_commands_directory",
]


def __getattr__(name: str):
    """Lazy import to avoid loading dependencies during setup."""
    if name == "Command":
        from sccs.command import Command

        return Command
    if name == "scan_commands_directory":
        from sccs.command import scan_commands_directory

        return scan_commands_directory
    if name == "Skill":
        from sccs.skill import Skill

        return Skill
    if name == "scan_skills_directory":
        from sccs.skill import scan_skills_directory

        return scan_skills_directory
    if name in ("SyncState", "SkillState", "CommandState"):
        from sccs import state

        return getattr(state, name)
    if name in ("SyncEngine", "SyncAction", "SyncResult", "ActionType", "ItemType"):
        from sccs import sync_engine

        return getattr(sync_engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
