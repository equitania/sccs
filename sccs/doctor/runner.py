# SCCS Doctor Subprocess Runner
#
# HARD RULES — these constraints are part of the security contract:
#   1. NEVER pass shell=True to subprocess.
#   2. NEVER call sudo. Privileged install steps are surfaced as text only.
#   3. Every command is built as a list[str]; no string interpolation into
#      the argv head, and the head is validated against an allowlist regex.
#
# Mirrors the pattern used by sccs/git/operations.py so existing reviewers
# recognise the structure.

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 - subprocess is intentional, see HARD RULES above

# Characters that cmd.exe treats specially. When we have to launch a Windows
# batch wrapper (npm.cmd/npx.cmd) via `cmd.exe /c`, any argument containing
# one of these is refused outright — defense-in-depth so a wrapper invocation
# can never become a shell-injection vector (our package/flag args never carry
# them, so this guard is invisible in practice).
_CMD_METACHARS = frozenset('&|<>^%"()!\r\n')

# Allowlist for the head (program) of any command we execute. Same character
# class as sccs/git/operations.py:_GIT_REMOTE_PATTERN, plus '/' and '@' so we
# can pass absolute paths and scoped npm packages downstream when needed.
_SAFE_HEAD_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./@\-]*$")


class DoctorError(Exception):
    """Raised by doctor subprocess wrappers on validation or exec failure."""

    def __init__(self, message: str, returncode: int = 1, stderr: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.returncode = returncode
        self.stderr = stderr


def _validate_head(value: str, label: str = "command") -> None:
    """Reject argv[0] values that look like option flags or shell metachars."""
    if value.startswith("-"):
        raise DoctorError(f"{label} must not start with '-': {value!r}")
    if not _SAFE_HEAD_PATTERN.match(value):
        raise DoctorError(f"{label} contains invalid characters: {value!r}")
    if value == "sudo":
        raise DoctorError("sccs doctor refuses to invoke sudo")


def _resolve_exec_command(
    cmd: list[str],
    *,
    is_windows: bool,
    which=None,
) -> list[str]:
    """Rewrite a command so a Windows batch wrapper (npm.cmd/npx.cmd) is launchable.

    On Windows `npm`/`npx` are `.cmd` batch wrappers, not real `.exe` files;
    `subprocess.run(shell=False)` → CreateProcess cannot launch a `.cmd`/`.bat`
    directly (only PE executables) and raises FileNotFoundError. The documented
    shell-free fix is to invoke the wrapper through the command interpreter:
    `cmd.exe /c <resolved-path> <args>` (NOT shell=True — argv stays a list, no
    string interpolation). Real `.exe` targets and every non-Windows platform
    are returned untouched, so behaviour off-Windows is identical to before.

    Pure + injectable (`which`) for testing.
    """
    if not is_windows or not cmd:
        return cmd
    resolver = which if which is not None else shutil.which
    resolved = resolver(cmd[0])
    if resolved is None:
        return cmd  # let subprocess raise the usual "Command not found"
    if resolved.lower().endswith((".cmd", ".bat")):
        bad = [a for a in cmd[1:] if any(ch in _CMD_METACHARS for ch in a)]
        if bad:
            raise DoctorError(f"refusing to pass cmd.exe metacharacters to a batch wrapper: {bad!r}")
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/c", resolved, *cmd[1:]]
    return cmd  # real .exe — CreateProcess handles it as today


def _run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Execute a command list. Validates argv[0] before exec."""
    if not cmd:
        raise DoctorError("Empty command")
    _validate_head(cmd[0])
    exec_cmd = _resolve_exec_command(cmd, is_windows=(os.name == "nt"))
    try:
        result = subprocess.run(  # nosec B603 - shell=False, head validated above
            exec_cmd,
            check=False,
            capture_output=capture,
            text=True,
            # Decode child output as UTF-8 regardless of the OS locale. On
            # Windows `text=True` alone defaults to the cp1252 code page, which
            # crashes the subprocess reader thread on the UTF-8 bytes that
            # `claude plugin list` / `npm` emit (box-drawing glyphs, emoji) —
            # truncating stdout and making the doctor report plugins falsely
            # MISSING. `errors="replace"` keeps parsing robust against odd bytes.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            # Doctor child processes are non-interactive by contract — any
            # subprocess that asks for stdin should fail fast, not hang the
            # parent for `timeout` seconds (see #npx-y-fix).
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as err:
        raise DoctorError(f"Command not found: {cmd[0]}") from err
    except subprocess.TimeoutExpired as err:
        raise DoctorError(f"Command timed out: {' '.join(cmd)}") from err
    if check and result.returncode != 0:
        raise DoctorError(
            f"Command failed: {' '.join(cmd)}",
            returncode=result.returncode,
            stderr=(result.stderr or "").strip(),
        )
    return result


def which(binary: str) -> str | None:
    """shutil.which wrapper kept here so detectors only import from runner."""
    if not binary:
        return None
    return shutil.which(binary)


def run_node_version() -> str | None:
    """Return Node.js version (without leading 'v') or None when missing."""
    try:
        proc = _run(["node", "--version"], timeout=10)
    except DoctorError:
        return None
    return proc.stdout.strip().lstrip("vV")


def run_pwsh_version() -> str | None:
    """Return the PowerShell 7+ version (e.g. '7.4.6') or None when missing.

    Probes the modern, cross-platform `pwsh` binary — NOT the legacy Windows
    `powershell.exe` (which is 5.1 and uses a different profile path). Output of
    `pwsh --version` is `PowerShell 7.4.6`; we return the trailing version token.
    Any failure (not installed, error) degrades silently to None.
    """
    if which("pwsh") is None:
        return None
    try:
        proc = _run(["pwsh", "--version"], timeout=10)
    except DoctorError:
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return None
    # "PowerShell 7.4.6" -> "7.4.6"; tolerate a bare version too.
    return out.split()[-1].lstrip("vV") or None


def run_claude_plugin_list() -> str:
    """Return raw stdout of `claude plugin list`. Empty on failure."""
    try:
        proc = _run(["claude", "plugin", "list"], timeout=15, check=False)
    except DoctorError:
        return ""
    return proc.stdout or ""


def run_claude_mcp_list() -> str:
    """Return raw stdout of `claude mcp list`. Empty on failure.

    Used by MCPServerDetector / `sccs doctor optimize` to enumerate every
    MCP server currently registered with the local Claude install. Format
    is one server per line:

        <name>: <command-or-url> - <status>

    where status is `✓ Connected`, `! Needs authentication`, etc. The
    detector parses only the leading `<name>:` token; the rest is treated
    as opaque.
    """
    try:
        proc = _run(["claude", "mcp", "list"], timeout=20, check=False)
    except DoctorError:
        return ""
    return proc.stdout or ""


def run_claude_marketplace_list() -> str:
    """Return raw stdout of `claude plugin marketplace list`. Empty on failure.

    Used by ClaudeMarketplaceDetector to spot the Debian-13 multi-user case:
    a configured marketplace (e.g. `claude-plugins-official`) is not present
    in the local list, so any subsequent `claude plugin install <name>@<market>`
    dies with "Plugin not found in marketplace" — a different failure mode
    from the stale-cache one v2.28.0 already covers via
    `claude plugin marketplace update`.
    """
    try:
        proc = _run(["claude", "plugin", "marketplace", "list"], timeout=15, check=False)
    except DoctorError:
        return ""
    return proc.stdout or ""


def run_npm_view_version(package: str) -> str | None:
    """Return the latest npm-registry version of `package`, or None on failure.

    Read-only registry query (`npm view <package> version`) used by the doctor
    update-check to decide whether an npm-backed npx tool (e.g.
    `@opengsd/gsd-core`) is OUTDATED. Any failure — offline, npm missing,
    unknown package, timeout — degrades to None so the caller shows no version
    and never raises a false "update available". `npm` passes
    `_SAFE_HEAD_PATTERN`; `package` is argv[1] (never the validated head).
    """
    if not package:
        return None
    try:
        proc = _run(["npm", "view", package, "version"], timeout=15, check=False)
    except DoctorError:
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def run_winget_list(winget_id: str) -> bool:
    """Return True if `winget list --id <winget_id> -e` reports the package.

    Used on Windows as the authoritative install check for optional CLI tools
    (zoxide, Microsoft Coreutils): it reflects whether the package is installed
    regardless of whether its binary directory made it onto PATH (the
    WinGet-Links-not-on-PATH trap). Best-effort — winget missing / non-Windows /
    timeout all degrade to False. `winget` passes `_SAFE_HEAD_PATTERN`;
    `winget_id` is argv[3] (never the validated head).
    """
    if not winget_id:
        return False
    try:
        proc = _run(["winget", "list", "--id", winget_id, "-e"], timeout=30, check=False)
    except DoctorError:
        return False
    if proc.returncode != 0:
        return False
    # winget prints a "No installed package found …" line (exit 0 on some
    # versions) when nothing matches; treat the id appearing in stdout as the
    # signal. winget echoes the exact id in the result table.
    return winget_id.lower() in (proc.stdout or "").lower()


def run_claude_marketplace_update(name: str) -> bool:
    """Refresh a single Claude marketplace from its source. Best-effort.

    Runs `claude plugin marketplace update <name>` so the local marketplace
    manifest reflects the latest published plugin versions before the doctor
    update-check reads it. Returns True on success, False otherwise. Pulls
    marketplace metadata only (git pull) — it does NOT install or change any
    plugin. Any failure is swallowed; the caller then compares against whatever
    on-disk manifest exists.
    """
    if not name:
        return False
    try:
        proc = _run(
            ["claude", "plugin", "marketplace", "update", name],
            timeout=30,
            check=False,
        )
    except DoctorError:
        return False
    return proc.returncode == 0


def run_opencode_models() -> str:
    """Return raw stdout of `opencode models`. Empty on failure.

    Used by the OpenCode integration to discover which `provider/model` ids the
    local OpenCode install actually offers, so Claude model aliases can be mapped
    to a model that really exists instead of a guessed id. Format is one model
    per line:

        anthropic/claude-sonnet-4-5
        opencode/big-pickle

    Empty output (no provider authenticated, OpenCode missing) is expected and
    handled by the caller, which then falls back to the static default map.
    """
    try:
        proc = _run(["opencode", "models"], timeout=15, check=False)
    except DoctorError:
        return ""
    return proc.stdout or ""


def parse_node_major(version: str | None) -> int | None:
    """Extract the major version integer from a 'X.Y.Z' string."""
    if not version:
        return None
    head = version.split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None
