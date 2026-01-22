# SCCS Configuration Schema
# Pydantic models for YAML configuration validation

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SyncMode(str, Enum):
    """Synchronization direction mode."""

    BIDIRECTIONAL = "bidirectional"
    LOCAL_TO_REPO = "local_to_repo"
    REPO_TO_LOCAL = "repo_to_local"


class ItemType(str, Enum):
    """Type of items in a sync category."""

    FILE = "file"
    DIRECTORY = "directory"
    MIXED = "mixed"


class ConflictResolution(str, Enum):
    """Default conflict resolution strategy."""

    PROMPT = "prompt"
    LOCAL = "local"
    REPO = "repo"
    NEWEST = "newest"


class RepositoryConfig(BaseModel):
    """Repository settings for sync operations."""

    path: str = Field(description="Local repository path")
    remote: str = Field(default="origin", description="Git remote name for push")
    auto_commit: bool = Field(default=False, description="Auto-commit after sync")
    auto_push: bool = Field(default=False, description="Auto-push after commit")
    commit_prefix: str = Field(default="[SYNC]", description="Commit message prefix")

    @field_validator("path")
    @classmethod
    def expand_path(cls, v: str) -> str:
        """Expand ~ in path."""
        return str(Path(v).expanduser())


class SyncCategory(BaseModel):
    """Configuration for a single sync category."""

    enabled: bool = Field(default=True, description="Whether this category is enabled")
    description: str = Field(default="", description="Human-readable description")
    local_path: str = Field(description="Local path to sync from")
    repo_path: str = Field(description="Repository path to sync to")
    sync_mode: SyncMode = Field(default=SyncMode.BIDIRECTIONAL, description="Sync direction mode")
    item_type: ItemType = Field(default=ItemType.FILE, description="Type of items")
    item_marker: Optional[str] = Field(default=None, description="File that marks a valid directory item (e.g., SKILL.md)")
    item_pattern: Optional[str] = Field(default=None, description="Glob pattern for file items (e.g., *.md)")
    include: list[str] = Field(default_factory=lambda: ["*"], description="Include patterns")
    exclude: list[str] = Field(default_factory=list, description="Exclude patterns")
    conflict_resolution: Optional[ConflictResolution] = Field(
        default=None, description="Category-specific conflict resolution"
    )

    @field_validator("local_path", "repo_path")
    @classmethod
    def expand_paths(cls, v: str) -> str:
        """Expand ~ in paths."""
        return str(Path(v).expanduser())


class PathTransformConfig(BaseModel):
    """Path transformation configuration for machine-independent sync."""

    placeholders: dict[str, str] = Field(
        default_factory=lambda: {
            "HOME": "{{HOME}}",
            "USER": "{{USER}}",
            "HOSTNAME": "{{HOSTNAME}}",
            "CLAUDE_DIR": "{{CLAUDE_DIR}}",
            "WORKSPACE": "{{WORKSPACE}}",
        },
        description="Placeholder mappings",
    )
    transform_files: list[dict[str, str]] = Field(
        default_factory=list, description="Files that need path transformation"
    )


class ConflictResolutionConfig(BaseModel):
    """Conflict resolution configuration."""

    default: ConflictResolution = Field(default=ConflictResolution.PROMPT, description="Default resolution strategy")
    per_category: dict[str, ConflictResolution] = Field(
        default_factory=dict, description="Category-specific resolution strategies"
    )


class OutputConfig(BaseModel):
    """Output and logging configuration."""

    verbose: bool = Field(default=False, description="Enable verbose output")
    colored: bool = Field(default=True, description="Enable colored output")
    log_file: Optional[str] = Field(default=None, description="Path to log file")
    sync_history: Optional[str] = Field(default=None, description="Path to sync history file")

    @field_validator("log_file", "sync_history")
    @classmethod
    def expand_optional_paths(cls, v: Optional[str]) -> Optional[str]:
        """Expand ~ in optional paths."""
        if v is None:
            return None
        return str(Path(v).expanduser())


class SccsConfig(BaseModel):
    """Root configuration model for SCCS."""

    repository: RepositoryConfig = Field(description="Repository settings")
    sync_categories: dict[str, SyncCategory] = Field(
        default_factory=dict, description="Sync category definitions"
    )
    global_exclude: list[str] = Field(
        default_factory=lambda: [
            # System files
            ".DS_Store",
            "*.swp",
            "*.swo",
            "*~",
            ".git",
            "__pycache__",
            "*.pyc",
            # Local/private files
            ".env",
            ".env.*",
            "*.local",
            "*.local.*",
            # SECURITY: Sensitive files - NEVER sync these!
            "*token*",
            "*secret*",
            "*credential*",
            "*password*",
            "*.pem",
            "*.key",
            "*.p12",
            "*.pfx",
            "*_rsa",
            "*_ed25519",
            "*_ecdsa",
            "*_dsa",
            "id_rsa*",
            "id_ed25519*",
            "known_hosts",
            ".pypirc",
            ".npmrc",
            ".netrc",
            "fish_variables",
            "*.keychain*",
            "*oauth*",
            "*auth*.json",
            "*.gpg",
        ],
        description="Global exclude patterns (includes security-sensitive files)",
    )
    path_transforms: PathTransformConfig = Field(
        default_factory=PathTransformConfig, description="Path transformation settings"
    )
    conflict_resolution: ConflictResolutionConfig = Field(
        default_factory=ConflictResolutionConfig, description="Conflict resolution settings"
    )
    output: OutputConfig = Field(default_factory=OutputConfig, description="Output settings")

    def get_enabled_categories(self) -> dict[str, SyncCategory]:
        """Return only enabled categories."""
        return {name: cat for name, cat in self.sync_categories.items() if cat.enabled}

    def get_category(self, name: str) -> Optional[SyncCategory]:
        """Get a category by name."""
        return self.sync_categories.get(name)

    def get_conflict_resolution(self, category_name: str) -> ConflictResolution:
        """Get conflict resolution strategy for a category."""
        category = self.sync_categories.get(category_name)
        if category and category.conflict_resolution:
            return category.conflict_resolution
        if category_name in self.conflict_resolution.per_category:
            return self.conflict_resolution.per_category[category_name]
        return self.conflict_resolution.default
