# SCCS Doctor Defaults
# Hardcoded baseline of what a fresh Claude Code environment should look
# like. Every entry can be overridden in `~/.config/sccs/config.yaml` under
# the top-level `doctor:` block.

from __future__ import annotations

from sccs.doctor.schema import (
    BundledSkillSpec,
    MCPServerSpec,
    NodeInstallSpec,
    NpxToolSpec,
    PathPrefixCheckSpec,
    PermissionCheckSpec,
    PluginSpec,
    StatusLineCheckSpec,
)

MIN_NODE_MAJOR = 20

DEFAULT_CLAUDE_PLUGINS: list[PluginSpec] = [
    PluginSpec(name="skill-creator", marketplace="claude-plugins-official"),
    PluginSpec(name="superpowers", marketplace="claude-plugins-official"),
    PluginSpec(name="frontend-design", marketplace="claude-plugins-official"),
    PluginSpec(
        name="context-mode",
        marketplace="context-mode",
        marketplace_source="mksglu/context-mode",
    ),
    PluginSpec(
        name="claude-mem",
        marketplace=None,
        marketplace_source="thedotmack/claude-mem",
    ),
]

DEFAULT_NPX_TOOLS: list[NpxToolSpec] = [
    NpxToolSpec(
        name="get-shit-done-cc",
        # `-y` auto-accepts npx's "Need to install... Ok to proceed?" prompt.
        # Without it, fresh Linux hosts hang on stdin (the prompt is hidden by
        # capture_output=True in runner._run).
        invocation=["npx", "-y", "get-shit-done-cc", "--claude", "--global", "--force-statusline"],
        # `get-shit-done-cc` only patches ~/.claude/ config — it never drops a
        # binary on PATH. Detection therefore falls back to the doctor state
        # file once we've recorded a successful run.
        detect_via_state=True,
    ),
    NpxToolSpec(
        name="playwright-cli",
        # Persistent global install — `playwright-cli` ends up on PATH and is
        # invoked many times per session, so a one-shot `npx -y` would re-fetch
        # the package every time. `npm install -g …@latest` covers both fresh
        # installs and updates: _npx_update_actions re-runs the same invocation,
        # which is exactly what we want here. `npm` is on the runner allowlist
        # in runner._validate_head.
        invocation=["npm", "install", "-g", "@playwright/cli@latest"],
        # Detection uses `shutil.which("playwright-cli")` — the binary is
        # exposed under that name regardless of whether the package itself is
        # called `@playwright/cli` (scoped name).
        detect_command="playwright-cli",
        detect_via_state=False,
        # Browser bundles are downloaded separately. `playwright-cli
        # install-browser <name>` is idempotent: it skips when the requested
        # version is already in `~/.cache/ms-playwright/`, and downloads
        # otherwise — so the same command doubles as the update check on
        # every `sccs doctor update`. Without these, users hit "browser not
        # found" the first time they run any `pw open` / `pw snap` command.
        post_install=[
            ["playwright-cli", "install-browser", "chromium"],
            ["playwright-cli", "install-browser", "firefox"],
        ],
        # `@playwright/cli` ships a Claude skill at `skills/playwright-cli/`
        # (SKILL.md + 11 reference docs). Claude only discovers skills that
        # live under `~/.claude/skills/`, so doctor resolves npm's global
        # root and copies the directory into place. The target is auto-
        # excluded from `sccs sync` via DEFAULT_MANAGED_PATTERNS so two
        # machines that both run `sccs doctor` don't fight over the tree.
        bundled_skill=BundledSkillSpec(
            package_subpath="@playwright/cli/skills/playwright-cli",
            target="~/.claude/skills/playwright-cli",
        ),
        # Names of the browser bundles `playwright-cli install-browser <name>`
        # extracts into the cache directory. Doctor uses these to detect
        # missing browsers in `sccs doctor check`. The cache root is resolved
        # at runtime via `$PLAYWRIGHT_BROWSERS_PATH` or the platform default
        # (see detectors._resolve_playwright_cache).
        browser_bundles=["chromium", "firefox"],
    ),
]

# Filesystem paths whose ownership/writability matters for downstream doctor
# actions. Triggered by the Debian 13 incident where ~/.npm/_cacache/ was
# root-owned and broke every subsequent `npx ...` with EACCES. Each path is
# recorded with the user-facing reason so the reporter can explain *why*
# the check exists.
DEFAULT_PERMISSION_CHECKS: list[PermissionCheckSpec] = [
    PermissionCheckSpec(
        path="~/.npm",
        label="npm cache directory",
        purpose="npx and npm install write here when fetching packages (e.g. get-shit-done-cc)",
    ),
    PermissionCheckSpec(
        path="~/.claude",
        label="Claude config directory",
        purpose="`claude plugin install` writes plugin manifests, skills and agents here",
    ),
    PermissionCheckSpec(
        path="~/.config/sccs",
        label="SCCS config directory",
        purpose="sccs persists doctor state and sync state in this directory",
    ),
    # Resolved at check-time via `npm root -g`. Catches the second Debian
    # failure mode (after the ~/.npm/_cacache/ chown one): system-wide npm
    # installations have their global root under /usr/lib/node_modules/,
    # which is root-owned, so `npm install -g @playwright/cli@latest` dies
    # with EACCES. Doctor surfaces this *before* the npm install action
    # runs and offers two fixes (user-local prefix vs sudo chown) in the
    # manual block — see installer._permission_actions.
    PermissionCheckSpec(
        path="npm root -g",
        path_kind="npm-root-global",
        label="npm global install dir",
        purpose=(
            "`npm install -g` writes here when installing CLI tools "
            "(e.g. @playwright/cli). System-wide npm installs put this under "
            "/usr/lib/node_modules/ (root-owned) — fix with a user-local "
            "prefix or `sudo chown` so doctor can manage tools without sudo."
        ),
    ),
]

# PATH-prefix checks: directories that must be on $PATH for downstream
# doctor actions to find their binaries. Triggered by the second Debian 13
# follow-up: after the user runs `npm config set prefix ~/.npm-global` to
# fix the npm-root-global ownership block, the new bin directory still isn't
# on $PATH for the current shell — so `npm install -g @playwright/cli`
# succeeds but every subsequent `playwright-cli install-browser <name>`
# step dies with "Command not found". Doctor surfaces this as a single
# manual block (with bash/zsh/fish snippets) and fences off downstream
# post_install + browser-bundle actions via blocks_downstream.
DEFAULT_PATH_PREFIX_CHECKS: list[PathPrefixCheckSpec] = [
    PathPrefixCheckSpec(
        identifier="npm-prefix-bin",
        path_kind="npm-prefix-bin",
        label="npm global bin in PATH",
        purpose=(
            "Tools installed via `npm install -g` land in `<npm config get prefix>/bin`. "
            "Without that directory on $PATH, doctor's post_install steps "
            "(e.g. `playwright-cli install-browser chromium`) fail with "
            "'Command not found' even though the binary itself is on disk."
        ),
    ),
]

# Statusline command-integrity check. Triggered by the 2026-05-11 incident
# where Homebrew bumped Node 25.x → 26.0.0 and pruned the old Cellar
# directory, leaving a hardcoded `/opt/homebrew/Cellar/node/25.9.0_3/bin/node`
# in the user's settings.json. Statusline disappeared silently; doctor was
# all-green. The check inspects ~/.claude/settings.json's `statusLine.command`
# and classifies stale Cellar paths, missing binaries, missing scripts, and
# opaque shell expressions.
DEFAULT_STATUS_LINE_CHECKS: list[StatusLineCheckSpec] = [
    StatusLineCheckSpec(
        identifier="claude-statusline",
        settings_path="~/.claude/settings.json",
        required_mode="smart",
        auto_fix_stale_cellar=True,
    ),
]

# Per-platform Node.js install hints. Linux deliberately uses runnable=False
# because the standard NodeSource recipe requires sudo, and SCCS never calls
# sudo on the user's behalf.
NODE_INSTALL: dict[str, NodeInstallSpec] = {
    "windows": NodeInstallSpec(
        runnable=True,
        cmd=["winget", "install", "OpenJS.NodeJS"],
        label="install Node.js via winget",
    ),
    "macos": NodeInstallSpec(
        runnable=True,
        cmd=["brew", "install", "node"],
        label="install Node.js via Homebrew",
    ),
    "linux": NodeInstallSpec(
        runnable=False,
        manual_block=(
            "curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -\nsudo apt-get install -y nodejs"
        ),
        label="install Node.js via NodeSource (manual, requires sudo)",
    ),
}


def get_node_install_spec(platform_name: str) -> NodeInstallSpec:
    """Return the install spec for a platform, falling back to the linux block."""
    return NODE_INSTALL.get(platform_name, NODE_INSTALL["linux"])


# Explicitly-managed MCP servers. Empty by default — `sccs doctor optimize`
# will warn about every installed MCP server outside this list unless the
# server name matches `DEFAULT_IGNORED_MCP_PATTERNS`. Users with custom MCP
# integrations they want to "own" should add entries here.
DEFAULT_MCP_SERVERS: list[MCPServerSpec] = []

# fnmatch-style globs against MCP server names that doctor optimize should
# treat as system-supplied and NEVER flag as foreign. Default skips:
#   * `claude.ai *`           → Claude Code's built-in OAuth services
#                                 (Gmail, Google Calendar, Google Drive)
#   * `plugin:* *`            → MCPs registered automatically by Claude
#                                 plugins (e.g. plugin:context-mode:context-mode);
#                                 their lifecycle is owned by the plugin itself,
#                                 not by the user, so removing them would just
#                                 re-create them on the next session start.
DEFAULT_IGNORED_MCP_PATTERNS: list[str] = [
    "claude.ai *",
    "plugin:*",
]

# Substring patterns matched against `hooks[*].hooks[*].command` entries
# in ~/.claude/settings.json. Doctor install/update/optimize sanitises
# settings.json by removing every hook entry whose command contains one
# of these substrings. Default is empty: the bundled SCCS distribution
# makes no judgements about which hooks a user should or should not
# have. Users opt in by populating `doctor.disallowed_hooks:` in their
# own `~/.config/sccs/config.yaml`.
DEFAULT_DISALLOWED_HOOKS: list[str] = []
