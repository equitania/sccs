# SCCS Configuration Schema
# Pydantic models for YAML configuration validation

import re
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from sccs.doctor.profiles import ProfileSpec
from sccs.doctor.schema import DoctorConfig
from sccs.doctor.statusline import StatusLineConfig

# Git remote name: alphanumeric start, then alphanumerics/underscore/dot/hyphen.
# Leading hyphen is forbidden to block option-injection (e.g. "--upload-pack=evil").
_GIT_REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


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
    auto_pull: bool = Field(default=False, description="Auto-pull before sync if behind remote")
    commit_prefix: str = Field(default="[SYNC]", description="Commit message prefix")

    @field_validator("path")
    @classmethod
    def expand_path(cls, v: str) -> str:
        """Expand ~ in path."""
        return str(Path(v).expanduser())

    @field_validator("remote")
    @classmethod
    def validate_remote(cls, v: str) -> str:
        """Reject remote names that could be interpreted as git options (e.g. '--upload-pack=...')."""
        if not _GIT_REMOTE_PATTERN.match(v):
            raise ValueError(
                f"Invalid git remote name: {v!r}. "
                "Only alphanumerics, '_', '.', '-' are allowed, and it must not start with '-'."
            )
        return v


class SettingsEnsure(BaseModel):
    """Configuration for ensuring JSON settings entries exist after sync."""

    target_file: str = Field(description="Path to target JSON settings file (supports ~)")
    entries: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value pairs to ensure exist. Missing keys are added, existing keys are never overwritten.",
    )
    platform_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Per-platform overrides keyed by platform name (macos, linux, windows). "
            "Values from the matching platform are deep-merged into `entries` and, "
            "unlike normal entries, OVERWRITE existing values in the target file — "
            "platform overrides express explicit per-OS choices."
        ),
    )
    create_if_missing: bool = Field(default=True, description="Create the target file if it doesn't exist")
    backup_before_modify: bool = Field(default=True, description="Create backup before modifying")

    @field_validator("target_file")
    @classmethod
    def expand_target_path(cls, v: str) -> str:
        """Expand ~ in target file path."""
        return str(Path(v).expanduser())


class SyncCategory(BaseModel):
    """Configuration for a single sync category."""

    enabled: bool = Field(default=True, description="Whether this category is enabled")
    description: str = Field(default="", description="Human-readable description")
    local_path: str = Field(description="Local path to sync from")
    repo_path: str = Field(description="Repository path to sync to")
    sync_mode: SyncMode = Field(default=SyncMode.BIDIRECTIONAL, description="Sync direction mode")
    item_type: ItemType = Field(default=ItemType.FILE, description="Type of items")
    item_marker: str | None = Field(default=None, description="File that marks a valid directory item (e.g., SKILL.md)")
    item_pattern: str | None = Field(default=None, description="Glob pattern for file items (e.g., *.md)")
    include: list[str] = Field(default_factory=lambda: ["*"], description="Include patterns")
    exclude: list[str] = Field(default_factory=list, description="Exclude patterns")
    conflict_resolution: ConflictResolution | None = Field(
        default=None, description="Category-specific conflict resolution"
    )
    platforms: list[str] | None = Field(
        default=None,
        description="Platform filter: macos, linux, windows. None = all platforms.",
    )
    settings_ensure: SettingsEnsure | None = Field(
        default=None,
        description="Optional JSON settings entries to ensure after sync.",
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
    log_file: str | None = Field(default=None, description="Path to log file")
    sync_history: str | None = Field(default=None, description="Path to sync history file")

    @field_validator("log_file", "sync_history")
    @classmethod
    def expand_optional_paths(cls, v: str | None) -> str | None:
        """Expand ~ in optional paths."""
        if v is None:
            return None
        return str(Path(v).expanduser())


class OpenCodeConfig(BaseModel):
    """OpenCode integration settings (model mapping for artefact conversion).

    Mirrors the DoctorConfig override pattern: a None field keeps the bundled
    default, an `extra_*` field is merged on top.
    """

    # None keeps the bundled DEFAULT_OPENCODE_MODEL_MAP; a dict fully replaces it.
    model_map: dict[str, str] | None = Field(
        default=None,
        description="Override map of Claude model alias/id -> OpenCode 'provider/model'. None keeps defaults.",
    )
    # Additive: merged on top of the effective map (wins over base entries).
    extra_model_map: dict[str, str] = Field(
        default_factory=dict,
        description="Additional model aliases merged on top of the effective map.",
    )
    # Provider preference order for live `opencode models` family matching.
    preferred_providers: list[str] = Field(
        default_factory=lambda: ["anthropic"],
        description="Provider order preferred when matching discovered OpenCode models.",
    )
    # Extra glob patterns (matched against the agent/command basename) skipped
    # on export, on top of the doctor-managed patterns (e.g. gsd-*). Lets a
    # user drop their own additional artefacts from the OpenCode export.
    exclude: list[str] = Field(
        default_factory=list,
        description=(
            "Extra glob patterns (matched against artefact basename) skipped on export, "
            "added to doctor-managed patterns."
        ),
    )

    @property
    def effective_model_map(self) -> dict[str, str]:
        """Bundled default (or full override) merged with extra_model_map."""
        from sccs.convert.claude_to_opencode import DEFAULT_OPENCODE_MODEL_MAP

        base = dict(self.model_map) if self.model_map is not None else dict(DEFAULT_OPENCODE_MODEL_MAP)
        return {**base, **self.extra_model_map}


class PiConfig(BaseModel):
    """Pi integration settings (pi.dev — @earendil-works/pi-coding-agent).

    The export is a one-way copy: skills and agents become Pi skills, commands
    become Pi prompt templates. No model mapping is needed because Pi ignores
    unknown frontmatter and prompt templates carry no per-item model.
    """

    # None keeps the default Pi agent resource root (~/.pi/agent); a path
    # overrides it (mainly for tests and non-standard installs).
    base_dir: str | None = Field(
        default=None,
        description="Pi agent resource root. None keeps the default ~/.pi/agent.",
    )
    # Extra glob patterns (matched against the artefact basename) skipped on
    # export, on top of the doctor-managed patterns (e.g. gsd-*).
    exclude: list[str] = Field(
        default_factory=list,
        description=(
            "Extra glob patterns (matched against artefact basename) skipped on export, "
            "added to doctor-managed patterns."
        ),
    )


class CodexConfig(BaseModel):
    """OpenAI Codex integration settings (codex CLI artefact export).

    The export is one-way: skills are copied verbatim to ~/.agents/skills
    (identical agentskills.io SKILL.md format), agents are converted to
    ~/.codex/agents/*.toml, commands are wrapped as Codex skills. Codex has no
    model-discovery command, so the model map is static + config override only.
    """

    # None keeps the default Codex home (~/.codex); a path overrides it
    # (mainly for tests and non-standard installs).
    base_dir: str | None = Field(
        default=None,
        description="Codex home directory. None keeps the default ~/.codex.",
    )
    # None keeps the default user skills root (~/.agents/skills — the
    # agentskills.io location Codex scans; NOT ~/.codex/skills, which is
    # reserved for OpenAI-bundled system skills).
    skills_dir: str | None = Field(
        default=None,
        description="Codex user skills root. None keeps the default ~/.agents/skills.",
    )
    # None keeps the bundled DEFAULT_CODEX_MODEL_MAP; a dict fully replaces it.
    model_map: dict[str, str] | None = Field(
        default=None,
        description="Override map of Claude model alias -> Codex model id. None keeps defaults.",
    )
    # Additive: merged on top of the effective map (wins over base entries).
    extra_model_map: dict[str, str] = Field(
        default_factory=dict,
        description="Additional model aliases merged on top of the effective map.",
    )
    # None keeps the bundled DEFAULT_CODEX_REASONING_EFFORT_MAP.
    reasoning_effort_map: dict[str, str] | None = Field(
        default=None,
        description="Override map of Claude model alias -> Codex model_reasoning_effort. None keeps defaults.",
    )
    # Extra glob patterns (matched against the artefact basename) skipped on
    # export, on top of the doctor-managed patterns (e.g. gsd-*).
    exclude: list[str] = Field(
        default_factory=list,
        description=(
            "Extra glob patterns (matched against artefact basename) skipped on export, "
            "added to doctor-managed patterns."
        ),
    )

    @property
    def effective_model_map(self) -> dict[str, str]:
        """Bundled default (or full override) merged with extra_model_map."""
        from sccs.convert.claude_to_codex import DEFAULT_CODEX_MODEL_MAP

        base = dict(self.model_map) if self.model_map is not None else dict(DEFAULT_CODEX_MODEL_MAP)
        return {**base, **self.extra_model_map}

    @property
    def effective_reasoning_effort_map(self) -> dict[str, str]:
        """Bundled default reasoning-effort map or the full override."""
        from sccs.convert.claude_to_codex import DEFAULT_CODEX_REASONING_EFFORT_MAP

        if self.reasoning_effort_map is not None:
            return dict(self.reasoning_effort_map)
        return dict(DEFAULT_CODEX_REASONING_EFFORT_MAP)


class SccsConfig(BaseModel):
    """Root configuration model for SCCS."""

    repository: RepositoryConfig = Field(description="Repository settings")
    sync_categories: dict[str, SyncCategory] = Field(default_factory=dict, description="Sync category definitions")
    # Doctor block is fully optional and backwards-compatible: legacy
    # config.yaml files without a `doctor:` key get the bundled defaults
    # via Field(default_factory=DoctorConfig).
    doctor: DoctorConfig = Field(
        default_factory=DoctorConfig,
        description="System & plugin health-check configuration (sccs doctor).",
    )
    # OpenCode integration is fully optional and backwards-compatible: legacy
    # config.yaml files without an `opencode:` key get the bundled defaults.
    opencode: OpenCodeConfig = Field(
        default_factory=OpenCodeConfig,
        description="OpenCode integration settings (model mapping).",
    )
    # Pi integration is fully optional and backwards-compatible: legacy
    # config.yaml files without a `pi:` key get the bundled defaults.
    pi: PiConfig = Field(
        default_factory=PiConfig,
        description="Pi integration settings (pi.dev artefact export).",
    )
    # Codex integration is fully optional and backwards-compatible: legacy
    # config.yaml files without a `codex:` key get the bundled defaults.
    codex: CodexConfig = Field(
        default_factory=CodexConfig,
        description="OpenAI Codex integration settings (codex CLI artefact export).",
    )
    # Profiles are fully optional: legacy config.yaml files without a
    # `profiles:` key get the bundled DEFAULT_PROFILES (currently `gsd`).
    # An entry here fully replaces the bundled spec of the same name, so a
    # profile can be re-scoped without patching the package.
    profiles: dict[str, ProfileSpec] = Field(
        default_factory=dict,
        description=(
            "Named groups of ~/.claude/ artefacts that `sccs profile on|off` "
            "switches together (skills, agents, settings.json hooks, "
            "statusline). Merged over the bundled defaults in "
            "sccs/doctor/profiles.py:DEFAULT_PROFILES."
        ),
    )
    # Statusline block is fully optional: without it the bundled presets
    # apply and `active` stays None, meaning SCCS never touches statusLine
    # on its own.
    statusline: StatusLineConfig = Field(
        default_factory=StatusLineConfig,
        description=(
            "Which statusline Claude Code runs. `active` names the preset "
            "SCCS should keep in settings.json; `presets` adds to or "
            "overrides the bundled ones (sccs/doctor/statusline.py)."
        ),
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

    def get_category(self, name: str) -> SyncCategory | None:
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
