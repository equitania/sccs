# SCCS Sync State
# State management for tracking sync history

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class ItemState:
    """State of a single sync item."""

    name: str
    category: str
    content_hash: Optional[str] = None
    local_mtime: Optional[float] = None
    repo_mtime: Optional[float] = None
    last_synced: Optional[str] = None  # ISO format datetime
    last_action: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ItemState":
        """Create from dictionary."""
        return cls(
            name=data.get("name", ""),
            category=data.get("category", ""),
            content_hash=data.get("content_hash"),
            local_mtime=data.get("local_mtime"),
            repo_mtime=data.get("repo_mtime"),
            last_synced=data.get("last_synced"),
            last_action=data.get("last_action"),
        )


@dataclass
class SyncState:
    """
    Complete sync state for all items.

    Tracks the last known state of all synced items to detect changes.
    """

    version: str = "2.0"
    last_sync: Optional[str] = None  # ISO format datetime
    items: dict[str, ItemState] = field(default_factory=dict)

    def get_item(self, category: str, name: str) -> Optional[ItemState]:
        """Get state for an item."""
        key = f"{category}:{name}"
        return self.items.get(key)

    def set_item(
        self,
        category: str,
        name: str,
        content_hash: Optional[str] = None,
        local_mtime: Optional[float] = None,
        repo_mtime: Optional[float] = None,
        action: Optional[str] = None,
    ) -> ItemState:
        """Set or update state for an item."""
        key = f"{category}:{name}"

        item_state = ItemState(
            name=name,
            category=category,
            content_hash=content_hash,
            local_mtime=local_mtime,
            repo_mtime=repo_mtime,
            last_synced=datetime.now().isoformat(),
            last_action=action,
        )
        self.items[key] = item_state
        return item_state

    def remove_item(self, category: str, name: str) -> bool:
        """Remove an item from state."""
        key = f"{category}:{name}"
        if key in self.items:
            del self.items[key]
            return True
        return False

    def get_items_for_category(self, category: str) -> list[ItemState]:
        """Get all items for a category."""
        return [item for item in self.items.values() if item.category == category]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "version": self.version,
            "last_sync": self.last_sync,
            "items": {key: item.to_dict() for key, item in self.items.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncState":
        """Create from dictionary."""
        items = {}
        for key, item_data in data.get("items", {}).items():
            items[key] = ItemState.from_dict(item_data)

        return cls(
            version=data.get("version", "2.0"),
            last_sync=data.get("last_sync"),
            items=items,
        )


class StateManager:
    """
    Manages sync state persistence.

    Handles loading, saving, and updating sync state.
    """

    def __init__(self, state_path: Optional[Path] = None):
        """
        Initialize state manager.

        Args:
            state_path: Path to state file. Defaults to ~/.config/sccs/.sync_state.yaml
        """
        if state_path is None:
            state_path = Path.home() / ".config" / "sccs" / ".sync_state.yaml"
        self.state_path = state_path
        self._state: Optional[SyncState] = None

    @property
    def state(self) -> SyncState:
        """Get current state, loading if necessary."""
        if self._state is None:
            self._state = self.load()
        return self._state

    def load(self) -> SyncState:
        """Load state from file."""
        if not self.state_path.exists():
            return SyncState()

        try:
            with open(self.state_path, encoding="utf-8") as f:
                # Try YAML first
                data = yaml.safe_load(f)
                if data is None:
                    return SyncState()
                return SyncState.from_dict(data)
        except yaml.YAMLError:
            # Try JSON for backward compatibility
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    data = json.load(f)
                    return SyncState.from_dict(data)
            except json.JSONDecodeError:
                return SyncState()

    def save(self) -> None:
        """Save state to file."""
        # Ensure directory exists
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # Update last sync time
        if self._state:
            self._state.last_sync = datetime.now().isoformat()

            # Write as YAML
            with open(self.state_path, "w", encoding="utf-8") as f:
                yaml.dump(self._state.to_dict(), f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def update_item(
        self,
        category: str,
        name: str,
        content_hash: Optional[str] = None,
        local_mtime: Optional[float] = None,
        repo_mtime: Optional[float] = None,
        action: Optional[str] = None,
    ) -> ItemState:
        """Update state for an item and save."""
        item_state = self.state.set_item(
            category=category,
            name=name,
            content_hash=content_hash,
            local_mtime=local_mtime,
            repo_mtime=repo_mtime,
            action=action,
        )
        self.save()
        return item_state

    def remove_item(self, category: str, name: str) -> bool:
        """Remove an item and save."""
        result = self.state.remove_item(category, name)
        if result:
            self.save()
        return result

    def get_item_hash(self, category: str, name: str) -> Optional[str]:
        """Get last known hash for an item."""
        item = self.state.get_item(category, name)
        return item.content_hash if item else None

    def reset(self) -> None:
        """Reset state to empty."""
        self._state = SyncState()
        self.save()

    def clear_category(self, category: str) -> int:
        """Clear all items for a category."""
        count = 0
        keys_to_remove = [key for key, item in self.state.items.items() if item.category == category]
        for key in keys_to_remove:
            del self.state.items[key]
            count += 1
        if count > 0:
            self.save()
        return count
