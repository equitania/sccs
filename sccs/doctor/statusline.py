# SCCS Statusline Presets — pick which statusline Claude Code runs
#
# `settings.json.statusLine` holds exactly one command, and whatever wrote
# it last wins. That is fine until an extension owns it: switching the GSD
# profile off with `sccs profile off gsd` leaves the statusline pointing at
# a script that is no longer wired up, so the line goes blank.
#
# A preset names one statusline — its command, its padding, how to tell
# whether it is installed, and (optionally) how to install it. The active
# preset is recorded in config.yaml so the choice survives a machine
# rebuild, and `sccs profile off` falls back to a preset by name instead of
# to a hardcoded file.
#
# Design rules:
#   1. Installing is opt-in and confirm-gated. The installer is fetched to
#      a temp file and executed as a plain argv list — never `curl | bash`
#      with an interpolated string.
#   2. Install URLs are validated: https only, host allowlist. A config
#      file is data, not a place from which to source arbitrary code.
#   3. A preset that drops files into ~/.claude/ declares them in
#      `managed_paths` so `sccs sync` never pushes a multi-megabyte binary
#      into the git repository.

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from sccs.utils.paths import atomic_write

DEFAULT_CLAUDE_DIR = Path.home() / ".claude"

# Hosts an `install_url` may point at. Anything else is rejected at config
# load time rather than at execution time, so a bad value surfaces on the
# next `sccs config validate` instead of the moment someone confirms an
# install action.
ALLOWED_INSTALL_HOSTS = frozenset(
    {
        "raw.githubusercontent.com",
        "github.com",
        "objects.githubusercontent.com",
    }
)

_SAFE_PRESET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class StatusLineError(Exception):
    """Raised when a statusline operation cannot be completed safely."""


def validate_preset_name(name: str) -> str:
    if not _SAFE_PRESET_NAME_RE.match(name):
        raise StatusLineError(f"invalid preset name {name!r} — use lowercase letters, digits, '.', '-' and '_' only")
    return name


class StatusLinePreset(BaseModel):
    """One selectable statusline."""

    description: str = Field(
        default="",
        description="Human-readable summary shown by `sccs statusline list`.",
    )
    command: str = Field(
        description=(
            "Value written to `statusLine.command` in ~/.claude/settings.json. "
            "Claude Code runs it through a shell, so `~` and `$HOME` expand."
        ),
    )
    padding: int | None = Field(
        default=None,
        ge=0,
        le=20,
        description="Optional `statusLine.padding`. Omitted from settings.json when None.",
    )
    marker_path: str | None = Field(
        default=None,
        description=(
            "Path (relative to ~/.claude/, or absolute) whose existence proves "
            "the statusline is installed. Drives the INSTALLED column and the "
            "doctor's missing-statusline row."
        ),
    )
    install_url: str | None = Field(
        default=None,
        description=(
            "https URL of a POSIX shell installer for this statusline. Must "
            "point at an allowlisted host (see ALLOWED_INSTALL_HOSTS). "
            "`sccs doctor install` downloads it to a temp file and runs it "
            "with bash behind a confirm prompt."
        ),
    )
    install_url_windows: str | None = Field(
        default=None,
        description="https URL of the PowerShell installer, shown as a manual block on Windows.",
    )
    managed_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Names this preset drops into ~/.claude/ (binary, config file). "
            "Merged into the sync exclude list so `sccs sync` never carries "
            "them into the git repository."
        ),
    )
    version_arg: str | None = Field(
        default=None,
        description=(
            "Argument that makes the marker binary print its version (e.g. "
            "'--version'), shown in the doctor's Version column. None for "
            "statuslines that cannot report one, such as a plain shell script."
        ),
    )

    @field_validator("version_arg")
    @classmethod
    def _validate_version_arg(cls, v: str | None) -> str | None:
        # Passed straight to argv, so keep it to a flag — never a path or a
        # value that could smuggle in a second argument.
        if v is not None and (not v.startswith("-") or " " in v):
            raise ValueError(f"version_arg must be a single flag like '--version', got {v!r}")
        return v

    @field_validator("install_url", "install_url_windows")
    @classmethod
    def _validate_install_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parsed = urlparse(v)
        if parsed.scheme != "https":
            raise ValueError(f"install URL must use https, got {v!r}")
        if parsed.hostname not in ALLOWED_INSTALL_HOSTS:
            allowed = ", ".join(sorted(ALLOWED_INSTALL_HOSTS))
            raise ValueError(f"install URL host {parsed.hostname!r} is not allowed (allowed: {allowed})")
        return v

    @field_validator("managed_paths")
    @classmethod
    def _validate_managed_paths(cls, v: list[str]) -> list[str]:
        for item in v:
            if "/" in item or "\\" in item or ".." in item:
                raise ValueError(f"managed_paths entries must be bare names, got {item!r}")
        return v

    def settings_block(self) -> dict[str, Any]:
        """The `statusLine` object to write into settings.json."""
        block: dict[str, Any] = {"type": "command", "command": self.command}
        if self.padding is not None:
            block["padding"] = self.padding
        return block

    def resolve_marker(self, claude_dir: Path) -> Path | None:
        if not self.marker_path:
            return None
        expanded = Path(os.path.expanduser(self.marker_path))
        return expanded if expanded.is_absolute() else claude_dir / self.marker_path

    def is_installed(self, claude_dir: Path | None = None) -> bool:
        """True when no marker is configured (nothing to install) or it exists."""
        marker = self.resolve_marker(claude_dir or DEFAULT_CLAUDE_DIR)
        return True if marker is None else marker.exists()

    def detect_version(self, claude_dir: Path | None = None) -> str | None:
        """Ask the marker binary for its version, or None.

        Deliberately not routed through `doctor.runner._run`: that validator
        requires argv[0] to look like a PATH name and rejects an absolute
        path, which is exactly what a statusline marker is. The safety
        properties are kept locally instead — the path is not user input at
        call time (it comes from `marker_path`, validated as a bare name or
        an absolute path), the process is spawned with `shell=False` and a
        real argv list, `version_arg` is validated to be a single flag, and
        stdin is closed so a confused binary cannot block us.

        Every failure mode degrades to None. A statusline that does not
        answer `--version`, is not executable, or hangs must not take down
        the doctor report over a cosmetic column.
        """
        import subprocess

        if not self.version_arg:
            return None
        marker = self.resolve_marker(claude_dir or DEFAULT_CLAUDE_DIR)
        if marker is None or not marker.is_file() or not os.access(marker, os.X_OK):
            return None

        try:
            result = subprocess.run(  # nosec B603 - shell=False, fixed argv, validated flag
                [str(marker), self.version_arg],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        out = ((result.stdout or "") + (result.stderr or "")).strip()
        if not out:
            return None
        first = out.splitlines()[0].strip()
        # Guard against a binary that answers with a paragraph instead of a
        # version — the Version column is one cell wide.
        return first if len(first) <= 40 else None


class StatusLineConfig(BaseModel):
    """The `statusline:` block in config.yaml."""

    active: str | None = Field(
        default=None,
        description=(
            "Name of the preset that should own `statusLine` in settings.json. "
            "None leaves the current statusline alone — SCCS only writes it "
            "when you run `sccs statusline use` or switch a profile off."
        ),
    )
    presets: dict[str, StatusLinePreset] = Field(
        default_factory=dict,
        description=(
            "Additional or overriding statusline presets. An entry named like a bundled preset fully replaces it."
        ),
    )


# `~/.claude/statusline.sh` is the plain-bash statusline many setups already
# carry; `claude-code-statusline` is the prebuilt binary from
# github.com/glauberlima/claude-code-statusline, which installs itself into
# ~/.claude/ alongside a statusline.toml.
DEFAULT_STATUSLINE_PRESETS: dict[str, StatusLinePreset] = {
    "builtin": StatusLinePreset(
        description="Plain shell script at ~/.claude/statusline.sh",
        command='"$HOME/.claude/statusline.sh"',
        marker_path="statusline.sh",
    ),
    "claude-code-statusline": StatusLinePreset(
        description="glauberlima/claude-code-statusline — directory, git, model, context bar, cost",
        command="~/.claude/statusline",
        padding=0,
        marker_path="statusline",
        version_arg="--version",
        install_url="https://raw.githubusercontent.com/glauberlima/claude-code-statusline/main/install.sh",
        install_url_windows="https://raw.githubusercontent.com/glauberlima/claude-code-statusline/main/install.ps1",
        # The binary is several MB and the toml is machine-local taste —
        # neither belongs in the synced repository.
        managed_paths=["statusline", "statusline.exe", "statusline.toml"],
    ),
}


def resolve_statusline_presets(overrides: dict[str, StatusLinePreset] | None) -> dict[str, StatusLinePreset]:
    """Merge user-configured presets over the bundled defaults."""
    resolved = dict(DEFAULT_STATUSLINE_PRESETS)
    for name, preset in (overrides or {}).items():
        validate_preset_name(name)
        resolved[name] = preset
    return resolved


def statusline_managed_paths(presets: dict[str, StatusLinePreset]) -> list[str]:
    """Every file the known presets drop into ~/.claude/.

    Returned unconditionally — not only for the active preset — so that
    switching away from a statusline does not suddenly make `sccs sync`
    pick up the binary it left behind.
    """
    out: set[str] = set()
    for preset in presets.values():
        out.update(preset.managed_paths)
    return sorted(out)


# --------------------------------------------------------------------- #
# Status / manager                                                       #
# --------------------------------------------------------------------- #


@dataclass
class StatusLinePresetStatus:
    name: str
    description: str
    command: str
    installed: bool
    is_active: bool  # matches settings.json right now
    is_configured: bool  # named as `statusline.active` in config.yaml
    installable: bool
    version: str | None = None


class StatusLineManager:
    """Read and write `statusLine` in ~/.claude/settings.json."""

    def __init__(
        self,
        presets: dict[str, StatusLinePreset],
        *,
        active: str | None = None,
        claude_dir: Path | None = None,
    ) -> None:
        self.presets = presets
        self.active = active
        self.claude_dir = claude_dir or DEFAULT_CLAUDE_DIR

    @property
    def settings_path(self) -> Path:
        return self.claude_dir / "settings.json"

    def preset(self, name: str) -> StatusLinePreset:
        validate_preset_name(name)
        found = self.presets.get(name)
        if found is None:
            known = ", ".join(sorted(self.presets)) or "none"
            raise StatusLineError(f"unknown statusline preset {name!r} — configured presets: {known}")
        return found

    def current_command(self) -> str | None:
        """The `statusLine.command` currently in settings.json, if any."""
        p = self.settings_path
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StatusLineError(f"{p} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            return None
        sl = data.get("statusLine")
        cmd = sl.get("command") if isinstance(sl, dict) else None
        return cmd if isinstance(cmd, str) else None

    def match_current(self) -> str | None:
        """Name of the preset matching the live statusline, or None."""
        cmd = self.current_command()
        if cmd is None:
            return None
        for name, preset in self.presets.items():
            if preset.command == cmd:
                return name
        return None

    def status(self, name: str, *, detect_version: bool = False) -> StatusLinePresetStatus:
        """Status of one preset.

        `detect_version` runs the marker binary, so it is opt-in: the doctor
        wants it for its Version column, but `sccs statusline list` should
        not spawn a subprocess per preset just to print a name.
        """
        preset = self.preset(name)
        installed = preset.is_installed(self.claude_dir)
        return StatusLinePresetStatus(
            name=name,
            description=preset.description,
            command=preset.command,
            installed=installed,
            is_active=self.match_current() == name,
            is_configured=self.active == name,
            installable=bool(preset.install_url or preset.install_url_windows),
            version=preset.detect_version(self.claude_dir) if (detect_version and installed) else None,
        )

    def all_status(self, *, detect_version: bool = False) -> list[StatusLinePresetStatus]:
        return [self.status(name, detect_version=detect_version) for name in sorted(self.presets)]

    def current_block(self) -> dict[str, Any] | None:
        """The whole `statusLine` object currently in settings.json."""
        p = self.settings_path
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StatusLineError(f"{p} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            return None
        sl = data.get("statusLine")
        return sl if isinstance(sl, dict) else None

    def restore_block(self, block: dict[str, Any] | None) -> None:
        """Put a previously captured `statusLine` object back.

        Needed because third-party installers write `statusLine` themselves
        (claude-code-statusline's install.sh does), which would otherwise
        make `sccs statusline install --no-use` silently change the active
        statusline anyway.
        """
        p = self.settings_path
        if not p.is_file():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StatusLineError(f"{p} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            return
        if block is None:
            data.pop("statusLine", None)
        else:
            data["statusLine"] = block
        atomic_write(p, json.dumps(data, indent=2) + "\n", mode=0o600)

    def apply(self, name: str) -> dict[str, Any]:
        """Write the preset's block into settings.json and return it.

        Does not check whether the statusline is installed — a user may
        legitimately configure it before installing. `sccs statusline use`
        warns about that separately.
        """
        preset = self.preset(name)
        p = self.settings_path
        if not p.is_file():
            raise StatusLineError(f"{p} does not exist — cannot set a statusline")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StatusLineError(f"{p} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise StatusLineError(f"{p} does not contain a JSON object")

        block = preset.settings_block()
        data["statusLine"] = block
        atomic_write(p, json.dumps(data, indent=2) + "\n", mode=0o600)
        return block


# --------------------------------------------------------------------- #
# Installation                                                           #
# --------------------------------------------------------------------- #

# A shell installer that is bigger than this is not the small bootstrap
# script we expect, and refusing is cheaper than running it.
MAX_INSTALLER_BYTES = 512 * 1024


def install_command_hint(preset: StatusLinePreset, *, windows: bool = False) -> str | None:
    """The copy-pasteable install command, for manual blocks and messages."""
    if windows:
        if not preset.install_url_windows:
            return None
        return f"& ([scriptblock]::Create((irm '{preset.install_url_windows}')))"
    if not preset.install_url:
        return None
    return f"curl -fsSL {preset.install_url} | bash"


def install_preset(preset: StatusLinePreset, *, timeout: int = 300) -> None:
    """Download the preset's installer and run it.

    Deliberately NOT `curl <url> | bash` through a shell: the URL is
    fetched into a temp file with a plain argv list, sanity-checked, and
    then handed to `bash` as a file argument. Nothing this function builds
    is ever interpreted by a shell, so a hostile value in config.yaml
    cannot become a command — and the URL is host-allowlisted at
    validation time on top of that.

    The caller is responsible for the confirm prompt; by the time this
    runs the user has already agreed to execute third-party code.
    """
    import tempfile

    from sccs.doctor.runner import DoctorError, _run

    if not preset.install_url:
        raise StatusLineError(f"preset {preset.description or 'this statusline'} has no install_url")

    if os.name == "nt":
        hint = install_command_hint(preset, windows=True) or "see the project's README"
        raise StatusLineError(f"automatic install is POSIX-only — run this in PowerShell instead:\n  {hint}")

    with tempfile.TemporaryDirectory(prefix="sccs-statusline-") as tmpdir:
        script = Path(tmpdir) / "install.sh"
        try:
            _run(["curl", "-fsSL", preset.install_url, "-o", str(script)], timeout=120)
        except DoctorError as exc:
            raise StatusLineError(f"downloading the installer failed: {exc}") from exc

        if not script.is_file():
            raise StatusLineError("the installer download produced no file")
        size = script.stat().st_size
        if size == 0:
            raise StatusLineError("the downloaded installer is empty")
        if size > MAX_INSTALLER_BYTES:
            raise StatusLineError(f"the downloaded installer is {size} bytes — refusing to run anything that large")

        try:
            _run(["bash", str(script)], timeout=timeout, capture=False)
        except DoctorError as exc:
            raise StatusLineError(f"the installer failed: {exc}") from exc
