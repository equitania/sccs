# SCCS Doctor Defaults
# Hardcoded baseline of what a fresh Claude Code environment should look
# like. Every entry can be overridden in `~/.config/sccs/config.yaml` under
# the top-level `doctor:` block.

from __future__ import annotations

from sccs.doctor.schema import (
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
