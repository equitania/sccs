# SCCS Configuration Loader
# Load, save, and manage YAML configuration files

import logging
import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from sccs.config.defaults import DEFAULT_CONFIG, generate_default_config
from sccs.config.schema import SccsConfig

logger = logging.getLogger(__name__)


class ConfigWriteError(OSError):
    """Raised when the SCCS config cannot be persisted to disk."""


def get_config_dir() -> Path:
    """Get the SCCS configuration directory."""
    return Path.home() / ".config" / "sccs"


def get_config_path() -> Path:
    """Get the path to the configuration file."""
    # Allow override via environment variable
    env_path = os.environ.get("SCCS_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return get_config_dir() / "config.yaml"


def ensure_config_dir() -> Path:
    """Ensure the configuration directory exists."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_config(config_path: Path | None = None) -> SccsConfig:
    """
    Load configuration from YAML file.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        SccsConfig: Validated configuration object.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValidationError: If config file is invalid.
    """
    if config_path is None:
        config_path = get_config_path()

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}\nRun 'sccs config init' to create one.")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        data = {}

    # Merge with defaults for missing values
    merged = _merge_with_defaults(data)

    return SccsConfig.model_validate(merged)


def save_config(config: SccsConfig, config_path: Path | None = None) -> Path:
    """
    Save configuration to YAML file.

    Args:
        config: Configuration object to save.
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Path: Path where config was saved.

    Raises:
        ConfigWriteError: If the target directory cannot be created, the
            config cannot be serialized, or the file cannot be written.
    """
    if config_path is None:
        config_path = get_config_path()

    try:
        ensure_config_dir()
    except OSError as exc:
        logger.error("Could not create config directory for %s: %s", config_path, exc)
        raise ConfigWriteError(f"Cannot create config directory: {exc}") from exc

    # Convert to dict and write as YAML
    # Use mode='json' to serialize Enums as their string values
    data = config.model_dump(exclude_none=True, mode="json")

    try:
        yaml_text = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except yaml.YAMLError as exc:
        logger.error("Could not serialize config to YAML: %s", exc)
        raise ConfigWriteError(f"Cannot serialize config to YAML: {exc}") from exc

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(yaml_text)
    except OSError as exc:
        logger.error("Could not write config %s: %s", config_path, exc)
        raise ConfigWriteError(f"Cannot write config file {config_path}: {exc}") from exc

    logger.debug("Wrote config to %s (%d bytes)", config_path, len(yaml_text))
    return config_path


def ensure_config_exists() -> tuple[Path, bool]:
    """
    Ensure configuration file exists, creating default if needed.

    Returns:
        Tuple of (config_path, was_created).
    """
    config_path = get_config_path()

    if config_path.exists():
        return config_path, False

    ensure_config_dir()
    config_path.write_text(generate_default_config(), encoding="utf-8")
    return config_path, True


def load_or_create_config() -> tuple[SccsConfig, bool]:
    """
    Load config if it exists, or create default.

    Returns:
        Tuple of (config, was_created).
    """
    config_path, was_created = ensure_config_exists()
    config = load_config(config_path)
    return config, was_created


def validate_config_file(config_path: Path | None = None) -> tuple[bool, list[str]]:
    """
    Validate a configuration file without loading it into the system.

    Args:
        config_path: Path to config file to validate.

    Returns:
        Tuple of (is_valid, error_messages).
    """
    if config_path is None:
        config_path = get_config_path()

    errors: list[str] = []

    if not config_path.exists():
        return False, [f"Configuration file not found: {config_path}"]

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return False, [f"Invalid YAML syntax: {e}"]

    if data is None:
        return False, ["Configuration file is empty"]

    try:
        SccsConfig.model_validate(data)
    except ValidationError as e:
        for error in e.errors():
            loc = " -> ".join(str(part) for part in error["loc"])
            errors.append(f"{loc}: {error['msg']}")
        return False, errors

    # Additional validation
    if "repository" not in data:
        errors.append("Missing 'repository' section")

    if "sync_categories" not in data or not data["sync_categories"]:
        errors.append("No sync categories defined")

    return len(errors) == 0, errors


def load_raw_user_data(config_path: Path | None = None) -> dict:
    """
    Load raw YAML config without merging defaults.

    Returns the user's on-disk config as-is, for comparing against
    DEFAULT_CONFIG to detect new categories.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Raw config dict, or empty dict if file doesn't exist.
    """
    if config_path is None:
        config_path = get_config_path()

    if not config_path.exists():
        return {}

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data or {}


def adopt_new_categories(
    category_names: list[str],
    config_path: Path | None = None,
) -> SccsConfig:
    """
    Add specified default categories to the user's config.yaml and save.

    Operates on the raw YAML dict to avoid inflating the user's config
    with all default categories from _merge_with_defaults().

    Args:
        category_names: Names of categories to add from DEFAULT_CONFIG.
        config_path: Optional path to config file.

    Returns:
        Updated SccsConfig after reloading.
    """
    if config_path is None:
        config_path = get_config_path()

    raw = load_raw_user_data(config_path)
    raw.setdefault("sync_categories", {})

    for name in category_names:
        if name in DEFAULT_CONFIG["sync_categories"] and name not in raw["sync_categories"]:
            raw["sync_categories"][name] = DEFAULT_CONFIG["sync_categories"][name]

    try:
        yaml_text = yaml.dump(raw, default_flow_style=False, sort_keys=False, allow_unicode=True)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(yaml_text)
    except (OSError, yaml.YAMLError) as exc:
        logger.error("Could not persist adopted categories to %s: %s", config_path, exc)
        raise ConfigWriteError(f"Cannot persist adopted categories to {config_path}: {exc}") from exc

    return load_config(config_path)


def _merge_with_defaults(data: dict) -> dict:
    """Merge loaded data with default values for missing keys."""
    result = DEFAULT_CONFIG.copy()

    if "repository" in data:
        result["repository"] = {**result["repository"], **data["repository"]}

    if "sync_categories" in data:
        # Keep default categories, update with user values
        for cat_name, cat_data in data["sync_categories"].items():
            if cat_name in result["sync_categories"]:
                result["sync_categories"][cat_name] = {**result["sync_categories"][cat_name], **cat_data}
            else:
                result["sync_categories"][cat_name] = cat_data

    if "global_exclude" in data:
        result["global_exclude"] = data["global_exclude"]

    if "path_transforms" in data:
        result["path_transforms"] = {**result["path_transforms"], **data["path_transforms"]}

    if "conflict_resolution" in data:
        result["conflict_resolution"] = {**result["conflict_resolution"], **data["conflict_resolution"]}

    if "output" in data:
        result["output"] = {**result["output"], **data["output"]}

    return result


def update_category_enabled(category_name: str, enabled: bool, config_path: Path | None = None) -> SccsConfig:
    """
    Update a category's enabled state and save.

    Args:
        category_name: Name of the category to update.
        enabled: New enabled state.
        config_path: Optional path to config file.

    Returns:
        Updated SccsConfig.

    Raises:
        KeyError: If category doesn't exist.
    """
    config = load_config(config_path)

    if category_name not in config.sync_categories:
        raise KeyError(f"Category '{category_name}' not found in configuration")

    config.sync_categories[category_name].enabled = enabled
    save_config(config, config_path)
    return config
