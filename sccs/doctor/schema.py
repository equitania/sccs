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


class BundledSkillSpec(BaseModel):
    """A Claude skill bundled inside an npm package.

    Some npm packages (e.g. `@playwright/cli`) ship a `skills/<name>/SKILL.md`
    directory intended for Claude Code consumption. Claude only discovers
    skills under `~/.claude/skills/`, so doctor resolves the npm global root
    at runtime and copies the bundled directory into place. The target
    directory is added to `DEFAULT_MANAGED_PATTERNS` so it is automatically
    excluded from `sccs sync` — otherwise two machines that both run
    `sccs doctor` produce conflicting trees.
    """

    package_subpath: str = Field(
        description=(
            "Path inside `npm root -g` to the bundled skill directory (e.g. '@playwright/cli/skills/playwright-cli')."
        ),
    )
    target: str = Field(
        description=(
            "Target directory the skill is copied to. `~` is expanded to the "
            "user's home (e.g. '~/.claude/skills/playwright-cli')."
        ),
    )

    @field_validator("package_subpath", "target")
    @classmethod
    def _validate_path(cls, v: str) -> str:
        if not v or v.isspace():
            raise ValueError("path must not be empty")
        if v.startswith("-"):
            raise ValueError(f"path must not start with '-': {v!r}")
        body = v[1:] if v.startswith("~") else v
        if any(ch in body for ch in (";", "|", "&", "$", "`", "\n", "\r")):
            raise ValueError(f"path contains shell metacharacters: {v!r}")
        return v


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
    post_install: list[list[str]] = Field(
        default_factory=list,
        description=(
            "Argv lists executed sequentially AFTER the main `invocation` succeeds. "
            "Used for tools that need a second step the wrapper itself owns "
            "(e.g. `playwright-cli install-browser chromium` to fetch a browser bundle). "
            "Each entry must be a non-empty argv list whose head passes the same "
            "safe-name validation as `invocation`. The same actions are appended "
            "in `sccs doctor update`, so idempotent commands also serve as "
            "automated update checks."
        ),
    )
    bundled_skill: BundledSkillSpec | None = Field(
        default=None,
        description=(
            "Optional Claude skill that ships inside the npm package. If set, "
            "doctor resolves the npm global root and copies the directory into "
            "the configured target after a successful install/update."
        ),
    )
    browser_bundles: list[str] = Field(
        default_factory=list,
        description=(
            "Names of browser bundles the tool fetches via a separate post-install "
            "step (e.g. `playwright-cli install-browser <name>` writes "
            "`<cache>/<name>-<version>/`). Doctor scans the tool's cache "
            "directory for matching subdirectories so the bundles appear in "
            "`sccs doctor check` and trigger re-install when missing."
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

    @field_validator("post_install")
    @classmethod
    def _validate_post_install(cls, v: list[list[str]]) -> list[list[str]]:
        for cmd in v:
            if not cmd:
                raise ValueError("post_install entries must contain at least one argv element")
            head = cmd[0]
            if head.startswith("-"):
                raise ValueError(f"post_install head must not start with '-': {head!r}")
            if not _SAFE_NAME_PATTERN.match(head):
                raise ValueError(f"post_install head contains invalid characters: {head!r}")
        return v

    @field_validator("browser_bundles")
    @classmethod
    def _validate_browser_bundles(cls, v: list[str]) -> list[str]:
        # Same allowlist as `name`: alphanumeric + `-`, no leading dash. We
        # don't whitelist specific browser names (chromium/firefox/webkit) —
        # that's the upstream tool's concern. Doctor only checks for
        # directories matching `<name>-*` in the tool's cache.
        for entry in v:
            _validate_safe_name(entry, "browser_bundles entry")
        return v


_VALID_PATH_KINDS = {"literal", "npm-root-global"}


class PermissionCheckSpec(BaseModel):
    """A filesystem path whose ownership/writability the doctor should verify.

    Triggered by real-world failure mode on Debian 13: a `~/.npm/_cacache/`
    directory tree owned by root (left over from a prior `sudo npm` run)
    silently breaks `npx` / `npm install` with EACCES. The fix is always a
    one-liner `sudo chown -R UID:GID <path>`, but the user has to know to
    run it. Doctor surfaces the issue and prints the exact command.

    `path_kind="npm-root-global"` is a special case: `path` is then a
    display label only and the detector resolves the actual path via
    `npm root -g` at check-time. Used to catch the second Debian failure
    mode where `/usr/lib/node_modules/` is root-owned and `npm install -g`
    dies with EACCES — caught *before* the npm install action runs.
    """

    path: str = Field(
        description="Filesystem path to check. `~` is expanded to the user's home.",
    )
    path_kind: str = Field(
        default="literal",
        description=(
            "How `path` is interpreted: 'literal' (filesystem path, default) "
            "or 'npm-root-global' (resolved at check-time via `npm root -g`). "
            "For non-literal kinds the `path` field is a display label only."
        ),
    )
    label: str = Field(
        description="Short human-readable name (e.g. 'npm cache directory').",
    )
    purpose: str = Field(
        description=(
            "Why doctor cares about this path — surfaced to the user when an "
            "issue is found (e.g. 'npx writes here when installing tools')."
        ),
    )

    @field_validator("path")
    @classmethod
    def _validate_path(cls, v: str) -> str:
        # Reject empty, shell metacharacters and absolute traversal hacks. Tilde
        # at the front is fine (we expand it). Other tildes are rejected.
        if not v or v.isspace():
            raise ValueError("path must not be empty")
        if v.startswith("-"):
            raise ValueError(f"path must not start with '-': {v!r}")
        # Strip a single leading '~' before validating the rest.
        body = v[1:] if v.startswith("~") else v
        # Allow absolute or relative paths but no shell metacharacters.
        if any(ch in body for ch in (";", "|", "&", "$", "`", "\n", "\r")):
            raise ValueError(f"path contains shell metacharacters: {v!r}")
        return v

    @field_validator("path_kind")
    @classmethod
    def _validate_path_kind(cls, v: str) -> str:
        if v not in _VALID_PATH_KINDS:
            raise ValueError(f"path_kind must be one of {sorted(_VALID_PATH_KINDS)}, got {v!r}")
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
    managed_excludes: list[str] = Field(
        default_factory=list,
        description=(
            "Extra glob patterns for files installed by doctor tools that "
            "should be excluded from `sccs sync`. Bundled tools such as "
            "get-shit-done-cc already contribute their own patterns "
            "automatically (see sccs/doctor/managed.py:DEFAULT_MANAGED_PATTERNS)."
        ),
    )
    permission_checks: list[PermissionCheckSpec] | None = Field(
        default=None,
        description=(
            "Override list of filesystem paths whose ownership/writability "
            "should be verified. None (default) keeps DEFAULT_PERMISSION_CHECKS."
        ),
    )
    extra_permission_checks: list[PermissionCheckSpec] = Field(
        default_factory=list,
        description="Additional permission checks appended to the default list.",
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

    def effective_permission_checks(self) -> list[PermissionCheckSpec]:
        """Return permission checks to run: override or default, plus extras."""
        from sccs.doctor.defaults import DEFAULT_PERMISSION_CHECKS

        base = list(self.permission_checks) if self.permission_checks is not None else list(DEFAULT_PERMISSION_CHECKS)
        return base + list(self.extra_permission_checks)
