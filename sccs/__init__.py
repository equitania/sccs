# SCCS - SkillsCommandsConfigsSync
# Unified YAML-configured synchronization for Claude Code files
#
# Version: 2.1.0
# Date: 27.01.2026

__version__ = "2.1.0"
__author__ = "Equitania Software GmbH"

# Lazy imports for better startup performance
def __getattr__(name: str):
    """Lazy import module attributes."""
    if name == "SyncEngine":
        from sccs.sync.engine import SyncEngine
        return SyncEngine
    elif name == "SccsConfig":
        from sccs.config.schema import SccsConfig
        return SccsConfig
    elif name == "load_config":
        from sccs.config.loader import load_config
        return load_config
    elif name == "Console":
        from sccs.output.console import Console
        return Console
    raise AttributeError(f"module 'sccs' has no attribute '{name}'")


__all__ = [
    "__version__",
    "__author__",
    "SyncEngine",
    "SccsConfig",
    "load_config",
    "Console",
]
