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
# for "<name>@<marketplace>" plugin specs. A leading '@' is allowed so that
# scoped npm packages (e.g. "@opengsd/get-shit-done-redux") are valid npx-tool
# names; '@' is not an option-injection vector — only a leading '-' is, and
# that stays blocked below.
_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_@][A-Za-z0-9_./@\-]*$")
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
    allowlist_only: bool = Field(
        default=False,
        description=(
            "If True, this entry exists ONLY to keep an installed plugin off the "
            "foreign-drift removal list. It is never install-/marketplace-checked "
            "(no MISSING/OUTDATED row, no marketplace registration block) but still "
            "counts toward foreign-drift coverage via effective_plugins()."
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
        description="Full argv list, e.g. ['npx', '@opengsd/get-shit-done-redux', '--global']",
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


_VALID_PATH_KINDS = {"literal", "npm-root-global", "npm-bin-global"}
_VALID_PATH_PREFIX_KINDS = {"npm-prefix-bin"}
_VALID_STATUS_LINE_REQUIRED_MODES = {"always", "never", "smart"}


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
            "How `path` is interpreted: 'literal' (filesystem path, default), "
            "'npm-root-global' (resolved at check-time via `npm root -g`), or "
            "'npm-bin-global' (resolved via `<npm config get prefix>/bin` — the "
            "dir `npm install -g` symlinks CLI binaries into; simple writability "
            "check, never recursively scanned or chowned). For non-literal kinds "
            "the `path` field is a display label only."
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


class PathPrefixCheckSpec(BaseModel):
    """A directory that must be on $PATH for downstream doctor actions to work.

    Triggered by the Debian 13 follow-up incident: after the user fixes
    `npm root -g` permissions by switching the prefix to `~/.npm-global`,
    the new bin directory still isn't on $PATH for the current shell —
    so `npm install -g @playwright/cli` succeeds but every subsequent
    `playwright-cli install-browser …` step dies with "Command not found".
    The mismatch turns into noise; this check makes it a single explicit
    manual block.

    `path_kind="npm-prefix-bin"` resolves `<npm config get prefix>/bin` at
    check-time and verifies it appears in `os.environ["PATH"]`. The
    `path` field is therefore a display label, not a literal filesystem
    path — same convention as `PermissionCheckSpec.path_kind="npm-root-global"`.
    """

    identifier: str = Field(
        description=(
            "Stable component-string slug used by the doctor cascade engine. "
            "Doctor uses `path:<identifier>` as the component key; downstream "
            "actions list this in `depends_on_components` to opt into "
            "skip-on-mismatch behaviour."
        ),
    )
    path_kind: str = Field(
        default="npm-prefix-bin",
        description=("Resolution rule: 'npm-prefix-bin' resolves `npm config get prefix`/bin at check-time."),
    )
    label: str = Field(description="Short human-readable name (e.g. 'npm global bin in PATH').")
    purpose: str = Field(
        description=("Why doctor cares about this PATH entry — surfaced to the user when an issue is found."),
    )

    @field_validator("identifier")
    @classmethod
    def _validate_identifier(cls, v: str) -> str:
        return _validate_safe_name(v, "PathPrefix identifier")

    @field_validator("path_kind")
    @classmethod
    def _validate_path_kind(cls, v: str) -> str:
        if v not in _VALID_PATH_PREFIX_KINDS:
            raise ValueError(f"path_kind must be one of {sorted(_VALID_PATH_PREFIX_KINDS)}, got {v!r}")
        return v


class StatusLineCheckSpec(BaseModel):
    """Verify that ~/.claude/settings.json `statusLine.command` is invokable.

    Triggered by the 2026-05-11 incident: a user's settings.json contained a
    hardcoded Homebrew Cellar path
    (`/opt/homebrew/Cellar/node/25.9.0_3/bin/node`). Homebrew bumped Node to
    26.0.0 and pruned the old Cellar directory; the statusline silently
    disappeared because the binary path no longer existed. `sccs doctor check`
    showed all-green because nothing inspected settings.json.

    The detector parses `statusLine.command` and classifies it into states:
      - ok / missing / missing_binary / missing_script / stale_cellar
      - opaque (pipelines, env-prefixes — not parsed, not faulted)
      - no_settings_file

    `required_mode` controls how a missing `statusLine` key is treated:
      - 'always': missing key → MISSING (FAIL)
      - 'never':  missing key → OK (statusline is opt-in)
      - 'smart':  required iff the `claude_statusline` sync category is
                  enabled AND a statusline script exists at one of the
                  conventional paths (statusline.sh/.py/.ps1/.fish or
                  hooks/gsd-statusline.js). Default — avoids nagging users
                  who never wanted a statusline.
    """

    identifier: str = Field(
        description=(
            "Stable component-string slug used by the doctor cascade engine. "
            "Doctor uses `statusline:<identifier>` as the component key."
        ),
    )
    settings_path: str = Field(
        default="~/.claude/settings.json",
        description="Settings file to inspect (tilde-expanded at check-time).",
    )
    required_mode: str = Field(
        default="smart",
        description=(
            "How a missing statusLine key is treated: 'always' (FAIL), 'never' "
            "(OK), or 'smart' (FAIL only when claude_statusline sync category "
            "is enabled and a statusline script is present)."
        ),
    )
    auto_fix_stale_cellar: bool = Field(
        default=True,
        description=(
            "If True, doctor install offers to rewrite Apple-Silicon Homebrew "
            "Cellar paths (/opt/homebrew/Cellar/<pkg>/<ver>/bin/X) to the "
            "stable /opt/homebrew/bin/X symlink that Homebrew maintains."
        ),
    )
    auto_fix_stale_script: bool = Field(
        default=True,
        description=(
            "If True, doctor offers to rewrite a statusLine.command pointing at "
            "the old GSD hooks/statusline.js to hooks/gsd-statusline.js — but "
            "only when the new script exists on disk. GSD renamed the script "
            "during the get-shit-done-redux move; a command still pointing at "
            "the old name leaves the statusline dead (missing_script). Other "
            "missing-script cases stay manual (no guessing where to rewrite)."
        ),
    )

    @field_validator("identifier")
    @classmethod
    def _validate_identifier(cls, v: str) -> str:
        return _validate_safe_name(v, "StatusLine identifier")

    @field_validator("required_mode")
    @classmethod
    def _validate_required_mode(cls, v: str) -> str:
        if v not in _VALID_STATUS_LINE_REQUIRED_MODES:
            raise ValueError(f"required_mode must be one of {sorted(_VALID_STATUS_LINE_REQUIRED_MODES)}, got {v!r}")
        return v

    @field_validator("settings_path")
    @classmethod
    def _validate_settings_path(cls, v: str) -> str:
        if not v or v.isspace():
            raise ValueError("settings_path must not be empty")
        if v.startswith("-"):
            raise ValueError(f"settings_path must not start with '-': {v!r}")
        body = v[1:] if v.startswith("~") else v
        if any(ch in body for ch in (";", "|", "&", "$", "`", "\n", "\r")):
            raise ValueError(f"settings_path contains shell metacharacters: {v!r}")
        return v


class MCPServerSpec(BaseModel):
    """An explicitly-managed Claude MCP server.

    Used by `sccs doctor optimize` to decide which MCP servers (as
    reported by `claude mcp list`) are "in spec" and which are
    foreign. Built-in `claude.ai *` OAuth servers and plugin-internal
    `plugin:* *` MCPs are auto-ignored via `ignored_mcp_patterns`
    (DEFAULT_IGNORED_MCP_PATTERNS) so the spec only needs to enumerate
    custom MCP integrations.
    """

    name: str = Field(description="MCP server name as it appears in `claude mcp list` (left of ':').")
    scope: str = Field(
        default="user",
        description="Installation scope: user | project | local.",
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("MCP server name cannot be empty")
        # MCP server names in `claude mcp` are user-chosen labels — we allow
        # the same charset as plugin names plus ':' for the plugin:* prefix
        # and ' ' for built-in claude.ai labels like "claude.ai Gmail".
        if not re.match(r"^[A-Za-z0-9_:\-./ ]+$", v):
            raise ValueError(f"MCP server name contains unsafe characters: {v!r}")
        return v

    @field_validator("scope")
    @classmethod
    def _validate_scope(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"user", "project", "local"}:
            raise ValueError(f"MCP scope must be user/project/local, got: {v!r}")
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
            "@opengsd/get-shit-done-redux already contribute their own patterns "
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
    path_prefix_checks: list[PathPrefixCheckSpec] | None = Field(
        default=None,
        description=("Override list of $PATH-prefix checks. None (default) keeps DEFAULT_PATH_PREFIX_CHECKS."),
    )
    extra_path_prefix_checks: list[PathPrefixCheckSpec] = Field(
        default_factory=list,
        description="Additional PATH-prefix checks appended to the default list.",
    )
    status_line_checks: list[StatusLineCheckSpec] | None = Field(
        default=None,
        description=("Override list of statusline checks. None (default) keeps DEFAULT_STATUS_LINE_CHECKS."),
    )
    extra_status_line_checks: list[StatusLineCheckSpec] = Field(
        default_factory=list,
        description="Additional statusline checks appended to the default list.",
    )
    mcp_servers: list[MCPServerSpec] | None = Field(
        default=None,
        description=(
            "Override list of explicitly-managed MCP servers (matched against "
            "`claude mcp list` output). None keeps DEFAULT_MCP_SERVERS (empty). "
            "`sccs doctor optimize` removes installed servers not on this list "
            "unless they match an `ignored_mcp_patterns` entry."
        ),
    )
    extra_mcp_servers: list[MCPServerSpec] = Field(
        default_factory=list,
        description="Additional MCP servers appended to the default list.",
    )
    ignored_mcp_patterns: list[str] | None = Field(
        default=None,
        description=(
            "fnmatch-style globs against MCP server names that should be treated "
            "as system-supplied and never flagged foreign. None keeps "
            "DEFAULT_IGNORED_MCP_PATTERNS (claude.ai OAuth services, plugin:* "
            "internal MCPs). Set to [] to flag every non-spec entry as foreign."
        ),
    )
    disallowed_hooks: list[str] | None = Field(
        default=None,
        description=(
            "Substring patterns matched against `hooks[*].hooks[*].command` "
            "entries in ~/.claude/settings.json. After every doctor install/"
            "update/optimize pass, SCCS sanitises settings.json by removing "
            "hook entries whose command contains any of these substrings. "
            "Real driver: third-party doctor tools (npx @opengsd/get-shit-done-redux "
            "--force-statusline, …) overwrite settings.json on every run, "
            "re-injecting hooks the user had explicitly removed in a setup "
            "audit. This list re-applies the removal after each tool run. "
            "None keeps DEFAULT_DISALLOWED_HOOKS (empty); pass [] explicitly "
            "to make that intent visible in the config."
        ),
    )
    protected_hooks: list[str] | None = Field(
        default=None,
        description=(
            "Substring patterns identifying hook commands the sanitiser must "
            "NEVER strip, even when a `disallowed_hooks` pattern would match. "
            "Protection wins over removal. Real driver: GSD (@opengsd/get-shit-done-redux) "
            "re-injects its hooks (gsd-read-guard.js, …) into settings.json on "
            "every run and they must be preserved — removing them breaks the "
            "plugin. None keeps DEFAULT_PROTECTED_HOOKS (['gsd-']); pass [] "
            "explicitly to disable protection entirely."
        ),
    )

    def effective_plugins(self) -> list[PluginSpec]:
        """Return plugins to check: override or default, plus extras."""
        from sccs.doctor.defaults import DEFAULT_CLAUDE_PLUGINS

        base = list(self.plugins) if self.plugins is not None else list(DEFAULT_CLAUDE_PLUGINS)
        return base + list(self.extra_plugins)

    def checkable_plugins(self) -> list[PluginSpec]:
        """Plugins to install-/marketplace-check on this host.

        Excludes ``allowlist_only`` entries — those count only toward
        foreign-drift coverage (via ``effective_plugins()``) and must never
        produce a MISSING/OUTDATED row or a marketplace-registration block.
        """
        return [s for s in self.effective_plugins() if not s.allowlist_only]

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

    def effective_mcp_servers(self) -> list[MCPServerSpec]:
        """Return MCP servers to manage: override or default, plus extras."""
        from sccs.doctor.defaults import DEFAULT_MCP_SERVERS

        base = list(self.mcp_servers) if self.mcp_servers is not None else list(DEFAULT_MCP_SERVERS)
        return base + list(self.extra_mcp_servers)

    def effective_ignored_mcp_patterns(self) -> list[str]:
        """Return fnmatch globs whose match excludes an MCP from foreign-flagging."""
        from sccs.doctor.defaults import DEFAULT_IGNORED_MCP_PATTERNS

        return (
            list(self.ignored_mcp_patterns)
            if self.ignored_mcp_patterns is not None
            else list(DEFAULT_IGNORED_MCP_PATTERNS)
        )

    def effective_disallowed_hooks(self) -> list[str]:
        """Return substring patterns identifying hooks to strip from settings.json."""
        from sccs.doctor.defaults import DEFAULT_DISALLOWED_HOOKS

        return list(self.disallowed_hooks) if self.disallowed_hooks is not None else list(DEFAULT_DISALLOWED_HOOKS)

    def effective_protected_hooks(self) -> list[str]:
        """Return substring patterns identifying hooks the sanitiser must never strip."""
        from sccs.doctor.defaults import DEFAULT_PROTECTED_HOOKS

        return list(self.protected_hooks) if self.protected_hooks is not None else list(DEFAULT_PROTECTED_HOOKS)

    def effective_path_prefix_checks(self) -> list[PathPrefixCheckSpec]:
        """Return PATH-prefix checks to run: override or default, plus extras."""
        from sccs.doctor.defaults import DEFAULT_PATH_PREFIX_CHECKS

        base = (
            list(self.path_prefix_checks) if self.path_prefix_checks is not None else list(DEFAULT_PATH_PREFIX_CHECKS)
        )
        return base + list(self.extra_path_prefix_checks)

    def effective_status_line_checks(self) -> list[StatusLineCheckSpec]:
        """Return statusline checks to run: override or default, plus extras."""
        from sccs.doctor.defaults import DEFAULT_STATUS_LINE_CHECKS

        base = (
            list(self.status_line_checks) if self.status_line_checks is not None else list(DEFAULT_STATUS_LINE_CHECKS)
        )
        return base + list(self.extra_status_line_checks)
