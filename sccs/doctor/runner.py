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

import re
import shutil
import subprocess  # nosec B404 - subprocess is intentional, see HARD RULES above

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
    try:
        result = subprocess.run(  # nosec B603 - shell=False, head validated above
            cmd,
            check=False,
            capture_output=capture,
            text=True,
            timeout=timeout,
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


def run_claude_plugin_list() -> str:
    """Return raw stdout of `claude plugin list`. Empty on failure."""
    try:
        proc = _run(["claude", "plugin", "list"], timeout=15, check=False)
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
