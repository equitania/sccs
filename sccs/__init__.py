# SCCS - SkillsCommandsConfigsSync
# Unified YAML-configured synchronization for Claude Code files
#
# Version: 2.16.0
# Date: 26.03.2026

__version__ = "2.16.0"
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
    elif name == "DocsGenerator":
        from sccs.docs.generator import DocsGenerator

        return DocsGenerator
    elif name == "Exporter":
        from sccs.transfer.exporter import Exporter

        return Exporter
    elif name == "Importer":
        from sccs.transfer.importer import Importer

        return Importer
    raise AttributeError(f"module 'sccs' has no attribute '{name}'")


__all__ = [
    "__version__",
    "__author__",
    "SyncEngine",
    "SccsConfig",
    "load_config",
    "Console",
    "DocsGenerator",
    "Exporter",
    "Importer",
]
