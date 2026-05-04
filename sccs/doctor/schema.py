# SCCS Doctor Schema
# Pydantic models that describe the expected system state. Persisted in
# config.yaml under the top-level `doctor:` key — every field carries a
# default so the block is fully optional.

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# Plugin & tool names: strict allowlist. Mirrors the pattern used in
# sccs/git/operations.py — no leading '-' (option-injection guard) and only
# characters that are valid in npm package names + the '@' separator we use
# for "<name>@<marketplace>" plugin specs.
_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./@\-]*$")
# Marketplace source spec is "owner/repo" or a longer slash path. Same
# allowlist as plugin name to keep the policy uniform.
_SAFE_SOURCE_PATTERN = _SAFE_NAME_PATTERN


def _validate_safe_name(value: str, field: str) -> str:
    if value.startswith("-"):
        raise ValueError(f"{field} must not start with '-': {value!r}")
    if not _SAFE_NAME_PATTERN.match(value):
        raise ValueError(f"{field} contains invalid characters: {value!r}")
    return value


class PluginSpec(BaseModel):
    """A Claude Code plugin to install via the `claude plugin` CLI."""

    name: str = Field(description="Plugin name (e.g. 'skill-creator')")
    marketplace: str | None = Field(
        default=None,
        description="Optional marketplace alias appended as '<name>@<marketplace>'.",
    )
    marketplace_source: str | None = Field(
        default=None,
        description=(
            "Optional 'owner/repo' to register via `claude plugin marketplace add` "
            "before installing. Required when the marketplace is not the default."
        ),
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return _validate_safe_name(v, "Plugin name")

    @field_validator("marketplace")
    @classmethod
    def _validate_marketplace(cls, v: str | None) -> str | None:
        return _validate_safe_name(v, "Plugin marketplace") if v else v

    @field_validator("marketplace_source")
    @classmethod
    def _validate_source(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v.startswith("-"):
            raise ValueError(f"Marketplace source must not start with '-': {v!r}")
        if not _SAFE_SOURCE_PATTERN.match(v):
            raise ValueError(f"Marketplace source contains invalid characters: {v!r}")
        return v

    @property
    def install_target(self) -> str:
        """Return the argument passed to `claude plugin install`."""
        if self.marketplace:
            return f"{self.name}@{self.marketplace}"
        return self.name


class NpxToolSpec(BaseModel):
    """A helper tool that runs via `npx` (e.g. statusline installer)."""

    name: str = Field(description="Tool name as exposed on PATH after install")
    invocation: list[str] = Field(
        description="Full argv list, e.g. ['npx', 'get-shit-done-cc', '--global']",
    )
    detect_command: str | None = Field(
        default=None,
        description=(
            "Optional binary name to look up via shutil.which() to detect a successful install. Defaults to `name`."
        ),
    )
    detect_via_state: bool = Field(
        default=False,
        description=(
            "True for tools that don't install a binary on PATH (e.g. tools that only "
            "patch ~/.claude/ config). Detector falls back to a state-file lookup that "
            "records successful runs."
        ),
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return _validate_safe_name(v, "Npx tool name")

    @field_validator("invocation")
    @classmethod
    def _validate_invocation(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Invocation must contain at least one entry")
        # Only the first token is enforced strictly (must be 'npx' or a known
        # safe binary name). The remaining tokens are allowed to start with '-'
        # because they are intentional CLI flags from a hardcoded default.
        head = v[0]
        if head.startswith("-"):
            raise ValueError(f"Invocation head must not start with '-': {head!r}")
        if not _SAFE_NAME_PATTERN.match(head):
            raise ValueError(f"Invocation head contains invalid characters: {head!r}")
        return v


class NodeInstallSpec(BaseModel):
    """How to install Node.js on a given platform."""

    runnable: bool = Field(
        description=(
            "True if SCCS may execute the install command directly. "
            "False forces SCCS to print the manual block instead — used for "
            "anything requiring sudo."
        ),
    )
    cmd: list[str] | None = Field(
        default=None,
        description="Argv list executed when runnable=True (no shell, no sudo).",
    )
    manual_block: str | None = Field(
        default=None,
        description="Multi-line shell snippet shown to the user when runnable=False.",
    )
    label: str = Field(
        default="install Node.js",
        description="Short human-readable description shown in prompts.",
    )

    @field_validator("cmd")
    @classmethod
    def _validate_cmd(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("cmd must contain at least one entry when set")
        head = v[0]
        if head.startswith("-"):
            raise ValueError(f"cmd head must not start with '-': {head!r}")
        if not _SAFE_NAME_PATTERN.match(head):
            raise ValueError(f"cmd head contains invalid characters: {head!r}")
        if head == "sudo":
            raise ValueError("cmd must not invoke 'sudo' — set runnable=False instead")
        return v


class DoctorConfig(BaseModel):
    """User-overridable doctor configuration."""

    min_node_major: int = Field(
        default=20,
        ge=10,
        le=99,
        description="Minimum acceptable Node.js major version.",
    )
    plugins: list[PluginSpec] | None = Field(
        default=None,
        description=(
            "Override list of Claude plugins. None (default) keeps the bundled "
            "DEFAULT_CLAUDE_PLUGINS — set this only to fully replace the list."
        ),
    )
    extra_plugins: list[PluginSpec] = Field(
        default_factory=list,
        description="Additional plugins appended to the default list.",
    )
    npx_tools: list[NpxToolSpec] | None = Field(
        default=None,
        description=("Override list of npx helper tools. None keeps DEFAULT_NPX_TOOLS."),
    )
    extra_npx_tools: list[NpxToolSpec] = Field(
        default_factory=list,
        description="Additional npx tools appended to the default list.",
    )

    def effective_plugins(self) -> list[PluginSpec]:
        """Return plugins to check: override or default, plus extras."""
        from sccs.doctor.defaults import DEFAULT_CLAUDE_PLUGINS

        base = list(self.plugins) if self.plugins is not None else list(DEFAULT_CLAUDE_PLUGINS)
        return base + list(self.extra_plugins)

    def effective_npx_tools(self) -> list[NpxToolSpec]:
        """Return npx tools to check: override or default, plus extras."""
        from sccs.doctor.defaults import DEFAULT_NPX_TOOLS

        base = list(self.npx_tools) if self.npx_tools is not None else list(DEFAULT_NPX_TOOLS)
        return base + list(self.extra_npx_tools)
