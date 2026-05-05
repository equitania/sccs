# SCCS Doctor Defaults
# Hardcoded baseline of what a fresh Claude Code environment should look
# like. Every entry can be overridden in `~/.config/sccs/config.yaml` under
# the top-level `doctor:` block.

from __future__ import annotations

from sccs.doctor.schema import (
    BundledSkillSpec,
    NodeInstallSpec,
    NpxToolSpec,
    PermissionCheckSpec,
    PluginSpec,
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
