# SCCS Configuration Module
# Handles YAML-based configuration loading, validation, and defaults

from sccs.config.schema import (
    SccsConfig,
    RepositoryConfig,
    SyncCategory,
    OutputConfig,
    PathTransformConfig,
    SyncMode,
    ItemType,
    ConflictResolution,
)
from sccs.config.loader import (
    load_config,
    save_config,
    get_config_path,
    ensure_config_exists,
    validate_config_file,
    update_category_enabled,
)
from sccs.config.defaults import DEFAULT_CONFIG, generate_default_config

__all__ = [
    # Schema
    "SccsConfig",
    "RepositoryConfig",
    "SyncCategory",
    "OutputConfig",
    "PathTransformConfig",
    "SyncMode",
    "ItemType",
    "ConflictResolution",
    # Loader
    "load_config",
    "save_config",
    "get_config_path",
    "ensure_config_exists",
    "validate_config_file",
    "update_category_enabled",
    # Defaults
    "DEFAULT_CONFIG",
    "generate_default_config",
]
