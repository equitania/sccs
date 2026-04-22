# SCCS Configuration Module
# Handles YAML-based configuration loading, validation, and defaults

from sccs.config.defaults import DEFAULT_CONFIG, generate_default_config
from sccs.config.loader import (
    ConfigWriteError,
    adopt_new_categories,
    ensure_config_exists,
    get_config_path,
    load_config,
    load_raw_user_data,
    save_config,
    update_category_enabled,
    validate_config_file,
)
from sccs.config.schema import (
    ConflictResolution,
    ItemType,
    OutputConfig,
    PathTransformConfig,
    RepositoryConfig,
    SccsConfig,
    SettingsEnsure,
    SyncCategory,
    SyncMode,
)

__all__ = [
    # Schema
    "SccsConfig",
    "RepositoryConfig",
    "SyncCategory",
    "SettingsEnsure",
    "OutputConfig",
    "PathTransformConfig",
    "SyncMode",
    "ItemType",
    "ConflictResolution",
    # Loader
    "load_config",
    "load_raw_user_data",
    "save_config",
    "get_config_path",
    "ensure_config_exists",
    "validate_config_file",
    "update_category_enabled",
    "adopt_new_categories",
    "ConfigWriteError",
    # Defaults
    "DEFAULT_CONFIG",
    "generate_default_config",
]
