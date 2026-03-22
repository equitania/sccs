# SCCS Configuration Migration
# Detect new default categories and manage migration state

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from sccs.config.defaults import DEFAULT_CONFIG


def detect_new_categories(raw_user_data: dict) -> list[str]:
    """
    Detect categories present in DEFAULT_CONFIG but absent from user's on-disk config.

    Args:
        raw_user_data: Raw YAML data from user's config file (before merge).

    Returns:
        List of category names not present in user's config, in DEFAULT_CONFIG order.
    """
    user_cats = set((raw_user_data.get("sync_categories") or {}).keys())
    return [name for name in DEFAULT_CONFIG["sync_categories"] if name not in user_cats]


def get_category_info(name: str) -> dict[str, Any]:
    """
    Get default category info for display.

    Args:
        name: Category name from DEFAULT_CONFIG.

    Returns:
        Category dict from DEFAULT_CONFIG.
    """
    return DEFAULT_CONFIG["sync_categories"].get(name, {})


@dataclass
class MigrationState:
    """Tracks which categories the user has declined to adopt."""

    declined_categories: list[str] = field(default_factory=list)
    last_checked: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {}
        if self.declined_categories:
            result["declined_categories"] = self.declined_categories
        if self.last_checked:
            result["last_checked"] = self.last_checked
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MigrationState":
        """Create from dictionary."""
        return cls(
            declined_categories=data.get("declined_categories", []),
            last_checked=data.get("last_checked"),
        )


class MigrationStateManager:
    """
    Manages migration state persistence.

    Tracks which default categories the user has declined so they
    are not re-offered during subsequent sync operations.
    """

    def __init__(self, state_path: Path | None = None):
        """
        Initialize migration state manager.

        Args:
            state_path: Path to state file. Defaults to ~/.config/sccs/.migration_state.yaml
        """
        if state_path is None:
            state_path = Path.home() / ".config" / "sccs" / ".migration_state.yaml"
        self.state_path = state_path
        self._state: MigrationState | None = None

    @property
    def state(self) -> MigrationState:
        """Get current state, loading if necessary."""
        if self._state is None:
            self._state = self.load()
        return self._state

    def load(self) -> MigrationState:
        """Load migration state from file."""
        if not self.state_path.exists():
            return MigrationState()

        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data is None:
                    return MigrationState()
                return MigrationState.from_dict(data)
        except (yaml.YAMLError, OSError):
            return MigrationState()

    def save(self) -> None:
        """Save migration state to file. Non-critical: failures are silently ignored."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state.last_checked = datetime.now().isoformat()

            with open(self.state_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    self.state.to_dict(),
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
        except OSError:
            pass  # Non-critical: state not persisted, sync continues

    def is_declined(self, name: str) -> bool:
        """Check if a category was previously declined."""
        return name in self.state.declined_categories

    def mark_declined(self, names: list[str]) -> None:
        """Mark categories as declined and save."""
        for name in names:
            if name not in self.state.declined_categories:
                self.state.declined_categories.append(name)
        self.save()

    def mark_adopted(self, names: list[str]) -> None:
        """Remove adopted categories from declined list and save."""
        self.state.declined_categories = [n for n in self.state.declined_categories if n not in names]
        self.save()


def get_categories_to_offer(
    raw_user_data: dict,
    state_manager: MigrationStateManager | None = None,
) -> list[str]:
    """
    Get new categories to offer the user, filtered by declined list.

    Used during automatic sync check. Previously declined categories
    are not re-offered.

    Args:
        raw_user_data: Raw YAML data from user's config file.
        state_manager: Optional state manager (creates default if None).

    Returns:
        List of category names to offer.
    """
    new_cats = detect_new_categories(raw_user_data)
    if not new_cats:
        return []

    mgr = state_manager or MigrationStateManager()
    return [name for name in new_cats if not mgr.is_declined(name)]
