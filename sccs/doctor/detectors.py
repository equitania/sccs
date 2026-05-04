# SCCS Doctor Detectors
# Read-only inspection of Node.js, Claude CLI, Claude plugins, npx tools
# and filesystem permissions for known-fragile paths.

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sccs.doctor.defaults import get_node_install_spec
from sccs.doctor.runner import (
    parse_node_major,
    run_claude_plugin_list,
    run_node_version,
    which,
)
from sccs.doctor.schema import (
    NodeInstallSpec,
    NpxToolSpec,
    PermissionCheckSpec,
    PluginSpec,
)
from sccs.doctor.state import DoctorStateManager
from sccs.utils.platform import get_current_platform

# Cap the per-path recursive ownership scan to avoid pathological wait times
# on huge caches (e.g. ~/.npm with thousands of packages). Whatever permission
# damage there is, the first hundreds of entries usually expose it.
_MAX_PATHS_SCANNED = 500
_MAX_OFFENDERS_REPORTED = 5


@dataclass
class NodeStatus:
    """Result of inspecting Node.js on the current host."""

    installed: bool
    version: str | None
    major: int | None
    meets_minimum: bool
    install_hint: NodeInstallSpec
    platform: str


@dataclass
class ClaudeCliStatus:
    """Result of inspecting the `claude` CLI binary."""

    installed: bool
    binary_path: str | None


@dataclass
class PluginStatus:
    """Result of inspecting a single configured Claude plugin."""

    spec: PluginSpec
    installed: bool
    update_available: bool | None  # None = not detectable from current CLI
    # detection_source values:
    #   "exact"       — plugin found at the exact `name@marketplace` we asked for
    #   "alternative" — plugin found under a *different* marketplace (still installed)
    #   "bare"        — plugin name found without an `@marketplace` suffix
    #   "missing"     — plugin not found in `claude plugin list` output
    detection_source: str = "missing"
    # The marketplace under which the plugin was actually found (only set
    # when detection_source is "exact" or "alternative").
    found_marketplace: str | None = None


@dataclass
class NpxToolStatus:
    """Result of inspecting a single npx helper tool."""

    spec: NpxToolSpec
    available: bool
    binary_path: str | None
    detection_source: str = "path"  # "path" | "state" | "missing"


@dataclass
class PermissionStatus:
    """Result of inspecting filesystem ownership/writability for a path.

    `ok=True` when the path either does not exist (will be created on first
    use) OR every scanned entry is owned by the current user AND the root
    is writable.
    """

    spec: PermissionCheckSpec
    exists: bool
    is_user_owned: bool
    is_writable: bool
    expected_uid: int
    expected_gid: int
    resolved_path: str
    offending_paths: list[str] = field(default_factory=list)
    skipped_reason: str | None = None  # set on Windows / fallback platforms

    @property
    def ok(self) -> bool:
        if self.skipped_reason is not None:
            return True
        if not self.exists:
            return True
        return self.is_user_owned and self.is_writable

    @property
    def fix_command(self) -> str | None:
        """Return the recommended fix command, or None when no fix is needed."""
        if self.ok:
            return None
        # Always print the path WITHOUT shell expansion so a copy-paste works
        # in any shell. We chown the resolved absolute path.
        return f"sudo chown -R {self.expected_uid}:{self.expected_gid} {self.resolved_path}"


class NodeDetector:
    """Detect Node.js installation and major-version compliance."""

    def __init__(self, platform_name: str | None = None) -> None:
        self._platform = platform_name or get_current_platform()

    def get_status(self, min_major: int) -> NodeStatus:
        version = run_node_version()
        major = parse_node_major(version)
        installed = version is not None
        meets = installed and major is not None and major >= min_major
        return NodeStatus(
            installed=installed,
            version=version,
            major=major,
            meets_minimum=bool(meets),
            install_hint=get_node_install_spec(self._platform),
            platform=self._platform,
        )


class ClaudeCliDetector:
    """Detect the presence of the `claude` CLI binary."""

    def get_status(self) -> ClaudeCliStatus:
        path = which("claude")
        return ClaudeCliStatus(installed=path is not None, binary_path=path)


class ClaudePluginDetector:
    """Detect installed Claude plugins by parsing `claude plugin list`.

    Uses regex with word boundaries so 'superpowers' does NOT match the
    longer 'superpowers-developing-for-claude-code' line. When the
    configured marketplace is missing but the plugin is found under a
    different marketplace, it is reported as 'alternative' rather than
    MISSING — the plugin is installed, just from a different source.
    """

    def __init__(self, raw_output: str | None = None) -> None:
        # Allow injection for testing; otherwise lazy-load via runner.
        self._raw_output = raw_output

    def _output(self) -> str:
        if self._raw_output is None:
            self._raw_output = run_claude_plugin_list()
        return self._raw_output

    @staticmethod
    def _detect_plugin(
        name: str,
        marketplace: str | None,
        output: str,
    ) -> tuple[str, str | None]:
        """Classify a single plugin against the raw `claude plugin list` output.

        Returns (detection_source, found_marketplace). detection_source is one
        of "exact", "alternative", "bare", "missing".
        """
        if not output:
            return ("missing", None)

        escaped_name = re.escape(name)
        # Pattern matches "<name>@<some-marketplace>" with a word boundary in
        # front of <name> so 'superpowers' does not match
        # 'superpowers-developing-for-...@...'. Marketplace tokens may contain
        # letters, digits, '_', '-' and '.'.
        any_market_re = re.compile(
            rf"(?<![\w\-]){escaped_name}@([A-Za-z0-9_.\-]+)",
            re.IGNORECASE,
        )

        if marketplace:
            exact_re = re.compile(
                rf"(?<![\w\-]){escaped_name}@{re.escape(marketplace)}\b",
                re.IGNORECASE,
            )
            if exact_re.search(output):
                return ("exact", marketplace)

        # Plugin name found under *some* marketplace — installed via a
        # different source than the user configured (or any source at all
        # when no marketplace was configured).
        match = any_market_re.search(output)
        if match:
            found = match.group(1)
            if marketplace and found.lower() != marketplace.lower():
                return ("alternative", found)
            return ("exact", found)

        # Plugin name appears as a bare token (rare CLI format that omits
        # the '@marketplace' suffix).
        bare_re = re.compile(
            rf"(?<![\w\-]){escaped_name}(?![\w\-@])",
            re.IGNORECASE,
        )
        if bare_re.search(output):
            return ("bare", None)

        return ("missing", None)

    def get_statuses(self, specs: list[PluginSpec]) -> list[PluginStatus]:
        output = self._output()
        statuses: list[PluginStatus] = []
        for spec in specs:
            source, found = self._detect_plugin(spec.name, spec.marketplace, output)
            statuses.append(
                PluginStatus(
                    spec=spec,
                    installed=source != "missing",
                    # `claude plugin` has no `outdated` subcommand we can rely
                    # on today, so we cannot tell whether an update is available.
                    update_available=None,
                    detection_source=source,
                    found_marketplace=found,
                )
            )
        return statuses


class PermissionDetector:
    """Verify filesystem ownership + writability for known-fragile paths.

    Real-world failure mode this guards against: a `~/.npm/_cacache/`
    subtree owned by root (left over from a prior `sudo npm` invocation
    or a container that mounted the user's home) silently breaks every
    subsequent `npx`/`npm install` with EACCES. The detector spots the
    foreign-owned files and surfaces a one-shot `sudo chown -R` fix.

    Skipped on Windows: NT ACLs do not map cleanly onto POSIX uid/gid,
    and the `sudo chown` fix would not apply. `os.getuid()` is also
    unavailable there.
    """

    def get_statuses(self, specs: list[PermissionCheckSpec]) -> list[PermissionStatus]:
        return [self._check(spec) for spec in specs]

    def _check(self, spec: PermissionCheckSpec) -> PermissionStatus:
        resolved = os.path.expanduser(spec.path)

        # Windows: skip entirely. Doctor still records the spec so the
        # reporter can show "skipped (Windows)" without crashing.
        if sys.platform == "win32" or not hasattr(os, "getuid"):
            return PermissionStatus(
                spec=spec,
                exists=Path(resolved).exists(),
                is_user_owned=True,
                is_writable=True,
                expected_uid=-1,
                expected_gid=-1,
                resolved_path=resolved,
                skipped_reason="not applicable on Windows",
            )

        current_uid = os.getuid()
        current_gid = os.getgid()
        path = Path(resolved)

        if not path.exists():
            return PermissionStatus(
                spec=spec,
                exists=False,
                is_user_owned=True,
                is_writable=True,
                expected_uid=current_uid,
                expected_gid=current_gid,
                resolved_path=resolved,
            )

        is_writable = os.access(path, os.W_OK)
        offenders: list[str] = []

        # Check the root path itself first — its ownership is the most
        # diagnostic signal.
        try:
            root_st = path.stat()
            if root_st.st_uid != current_uid:
                offenders.append(resolved)
        except OSError:
            pass

        # Recursive sample. Bail out early on cap or once we have enough
        # offenders to convince the user.
        scanned = 0
        try:
            for entry in path.rglob("*"):
                scanned += 1
                if scanned > _MAX_PATHS_SCANNED:
                    break
                try:
                    st = entry.stat()
                except OSError:
                    continue
                if st.st_uid != current_uid:
                    s = str(entry)
                    if s not in offenders:
                        offenders.append(s)
                        if len(offenders) >= _MAX_OFFENDERS_REPORTED:
                            break
        except OSError:
            pass

        return PermissionStatus(
            spec=spec,
            exists=True,
            is_user_owned=not offenders,
            is_writable=is_writable,
            expected_uid=current_uid,
            expected_gid=current_gid,
            resolved_path=resolved,
            offending_paths=offenders,
        )


class NpxToolDetector:
    """Detect npx-installed helper tools.

    Detection priority:
      1. shutil.which(detect_command or name) — covers the standard case
         where `npx -g` (or a plain global install) drops a binary on PATH.
      2. State-file lookup — covers tools that don't install a binary at
         all (e.g. statusline patchers). Only consulted when the spec sets
         `detect_via_state=True`.
    """

    def __init__(self, state_manager: DoctorStateManager | None = None) -> None:
        self._state = state_manager

    def get_statuses(self, specs: list[NpxToolSpec]) -> list[NpxToolStatus]:
        out: list[NpxToolStatus] = []
        for spec in specs:
            probe = spec.detect_command or spec.name
            path = which(probe)
            if path is not None:
                out.append(
                    NpxToolStatus(
                        spec=spec,
                        available=True,
                        binary_path=path,
                        detection_source="path",
                    )
                )
                continue

            # PATH lookup failed — try the state cache for tools that opt in.
            if spec.detect_via_state and self._state is not None:
                if self._state.is_npx_tool_marked(spec.name, list(spec.invocation)):
                    out.append(
                        NpxToolStatus(
                            spec=spec,
                            available=True,
                            binary_path=None,
                            detection_source="state",
                        )
                    )
                    continue

            out.append(
                NpxToolStatus(
                    spec=spec,
                    available=False,
                    binary_path=None,
                    detection_source="missing",
                )
            )
        return out
