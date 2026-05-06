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
    DoctorError,
    _run,
    parse_node_major,
    run_claude_plugin_list,
    run_node_version,
    which,
)
from sccs.doctor.schema import (
    NodeInstallSpec,
    NpxToolSpec,
    PathPrefixCheckSpec,
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
    # The installation scope reported by `claude plugin list` — one of
    # user|project|local|managed (or None if the parser couldn't extract it).
    # Forwarded as `--scope <value>` to `claude plugin update`, which would
    # otherwise default to `user` and fail with "Plugin … is not installed
    # at scope user" for plugins installed under a different scope.
    scope: str | None = None


@dataclass
class NpxToolStatus:
    """Result of inspecting a single npx helper tool."""

    spec: NpxToolSpec
    available: bool
    binary_path: str | None
    detection_source: str = "path"  # "path" | "state" | "missing"


@dataclass
class BundledSkillStatus:
    """Result of checking whether an npm-bundled Claude skill landed in
    `~/.claude/skills/`. The directory is *managed* by `sccs doctor` (it
    re-syncs on every install/update), so the diagnostic asks only one
    question: does the SKILL.md exist at the configured target?
    """

    spec: NpxToolSpec
    target_path: str  # expanded absolute path to the skill directory
    skill_md_present: bool


@dataclass
class BrowserBundleStatus:
    """Result of scanning a tool's browser cache directory for bundles
    declared in `spec.browser_bundles` (e.g. ['chromium', 'firefox']).

    `present` maps each declared bundle to True/False. `all_present` is the
    convenience aggregate the reporter and has_problems() use.
    `cache_dir_exists` is False when the entire cache directory is missing
    — useful detail for the reporter (`MISSING (cache empty)` is friendlier
    than enumerating every bundle).
    """

    spec: NpxToolSpec
    cache_dir: str
    cache_dir_exists: bool
    present: dict[str, bool]
    all_present: bool


@dataclass
class PathPrefixStatus:
    """Result of checking whether a resolved directory is on $PATH.

    Resolved at check-time so a freshly switched npm prefix is reflected
    immediately. `expected_path` is the directory we expect on $PATH;
    `in_path` is the boolean check. `skipped_reason` is set when the
    resolution itself failed (e.g. npm not installed) — in that case the
    rest of the doctor pass should treat the check as "ok, not applicable".
    """

    spec: PathPrefixCheckSpec
    expected_path: str
    in_path: bool
    skipped_reason: str | None = None

    @property
    def ok(self) -> bool:
        if self.skipped_reason is not None:
            return True
        return self.in_path


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
    def _extract_scope_from_block(output: str, match_end: int) -> str | None:
        """Read the `Scope: <value>` line that follows a plugin header match.

        `claude plugin list` formats each plugin as a 4-line block:

            ❯ <name>@<marketplace>
              Version: <ver>
              Scope: <user|project|local|managed>
              Status: <enabled|disabled>

        We slice ~300 chars after the matched header and stop at the next
        `❯ ` to avoid bleeding into the neighbouring plugin's metadata
        block.
        """
        block = output[match_end : match_end + 300]
        next_header = re.search(r"\n\s*❯", block)
        if next_header:
            block = block[: next_header.start()]
        m = re.search(r"\bScope:\s*(\S+)", block, re.IGNORECASE)
        return m.group(1) if m else None

    @staticmethod
    def _detect_plugin(
        name: str,
        marketplace: str | None,
        output: str,
    ) -> tuple[str, str | None, str | None]:
        """Classify a single plugin against the raw `claude plugin list` output.

        Returns (detection_source, found_marketplace, scope). detection_source
        is one of "exact", "alternative", "bare", "missing". `scope` is the
        value of the `Scope:` line in the matched plugin's metadata block, or
        None if no match or no scope line was found.
        """
        if not output:
            return ("missing", None, None)

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
            m = exact_re.search(output)
            if m:
                scope = ClaudePluginDetector._extract_scope_from_block(output, m.end())
                return ("exact", marketplace, scope)

        # Plugin name found under *some* marketplace — installed via a
        # different source than the user configured (or any source at all
        # when no marketplace was configured).
        match = any_market_re.search(output)
        if match:
            found = match.group(1)
            scope = ClaudePluginDetector._extract_scope_from_block(output, match.end())
            if marketplace and found.lower() != marketplace.lower():
                return ("alternative", found, scope)
            return ("exact", found, scope)

        # Plugin name appears as a bare token (rare CLI format that omits
        # the '@marketplace' suffix).
        bare_re = re.compile(
            rf"(?<![\w\-]){escaped_name}(?![\w\-@])",
            re.IGNORECASE,
        )
        bare = bare_re.search(output)
        if bare:
            scope = ClaudePluginDetector._extract_scope_from_block(output, bare.end())
            return ("bare", None, scope)

        return ("missing", None, None)

    def get_statuses(self, specs: list[PluginSpec]) -> list[PluginStatus]:
        output = self._output()
        statuses: list[PluginStatus] = []
        for spec in specs:
            source, found, scope = self._detect_plugin(spec.name, spec.marketplace, output)
            statuses.append(
                PluginStatus(
                    spec=spec,
                    installed=source != "missing",
                    # `claude plugin` has no `outdated` subcommand we can rely
                    # on today, so we cannot tell whether an update is available.
                    update_available=None,
                    detection_source=source,
                    found_marketplace=found,
                    scope=scope,
                )
            )
        return statuses


def _resolve_npm_root_global() -> str | None:
    """Return the directory `npm root -g` reports, or None if npm is missing.

    Used to spot the Debian-13 failure mode where `/usr/lib/node_modules/` is
    root-owned and any `npm install -g` dies with EACCES — without having to
    hardcode the path in defaults.py (it varies across Homebrew, Debian-apt,
    nvm, NodeSource, etc.).
    """
    try:
        proc = _run(["npm", "root", "-g"], check=True, capture=True, timeout=15)
    except DoctorError:
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    return raw.splitlines()[0].strip() or None


def _resolve_npm_prefix_bin() -> str | None:
    """Return `<npm config get prefix>/bin`, or None if npm is missing.

    Used by PathPrefixDetector to spot the Debian 13 follow-up failure mode:
    user fixes ownership by switching the prefix to `~/.npm-global`, but
    that bin directory is not yet on $PATH for the current shell — so the
    next `playwright-cli install-browser …` dies with `command not found`
    even though `npm install -g @playwright/cli` succeeded one second earlier.
    """
    try:
        proc = _run(["npm", "config", "get", "prefix"], check=True, capture=True, timeout=15)
    except DoctorError:
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    prefix = raw.splitlines()[0].strip()
    if not prefix:
        return None
    return str(Path(prefix) / "bin")


class PathPrefixDetector:
    """Verify that key directories are on $PATH for the current process.

    Currently single-purpose (`npm-prefix-bin`) but kept generic so future
    PATH-mismatches (e.g. a Python user-site bin dir) can plug in without
    rewriting the detector. Checks `os.environ["PATH"]` rather than calling
    out to a shell so the result reflects what doctor's own subprocesses
    will actually see when they shell out.
    """

    def __init__(self, env: dict[str, str] | None = None) -> None:
        # Test-friendly: pass a custom env mapping to avoid mutating
        # os.environ during unit tests.
        self._env = env

    def _path_entries(self) -> list[str]:
        path = (self._env or os.environ).get("PATH", "")
        return [p for p in path.split(os.pathsep) if p]

    def get_statuses(self, specs: list[PathPrefixCheckSpec]) -> list[PathPrefixStatus]:
        out: list[PathPrefixStatus] = []
        entries = self._path_entries()
        for spec in specs:
            if spec.path_kind == "npm-prefix-bin":
                expected = _resolve_npm_prefix_bin()
                if expected is None:
                    out.append(
                        PathPrefixStatus(
                            spec=spec,
                            expected_path="",
                            in_path=False,
                            skipped_reason="npm not on PATH — cannot resolve prefix",
                        )
                    )
                    continue
                # Compare resolved paths to handle symlinks (e.g. /usr/local
                # vs /opt/homebrew on macOS) consistently. Fall back to a
                # literal string match if resolution fails.
                normalized_expected = _normalize_path(expected)
                normalized_entries = {_normalize_path(p) for p in entries}
                in_path = normalized_expected in normalized_entries
                out.append(
                    PathPrefixStatus(
                        spec=spec,
                        expected_path=expected,
                        in_path=in_path,
                    )
                )
            else:  # pragma: no cover — schema validation forbids other values
                out.append(
                    PathPrefixStatus(
                        spec=spec,
                        expected_path="",
                        in_path=False,
                        skipped_reason=f"unsupported path_kind: {spec.path_kind}",
                    )
                )
        return out


def _normalize_path(p: str) -> str:
    """Best-effort path normalization for $PATH comparisons.

    `os.path.realpath` resolves symlinks; if the directory does not exist
    yet (fresh `~/.npm-global`), realpath still returns a normalized
    absolute string we can compare.
    """
    try:
        return os.path.realpath(os.path.expanduser(p))
    except OSError:
        return os.path.normpath(os.path.expanduser(p))


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
        # Resolve runtime-determined paths (e.g. `npm root -g`) before the
        # standard ownership/writability scan. Each kind handles the
        # "couldn't resolve" case as a graceful skip rather than a crash.
        if spec.path_kind == "npm-root-global":
            npm_root = _resolve_npm_root_global()
            if npm_root is None:
                return PermissionStatus(
                    spec=spec,
                    exists=False,
                    is_user_owned=True,
                    is_writable=True,
                    expected_uid=-1,
                    expected_gid=-1,
                    resolved_path=spec.path,
                    skipped_reason="npm not on PATH — cannot resolve global root",
                )
            resolved = npm_root
        else:
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


class BundledSkillDetector:
    """Verify each `NpxToolSpec.bundled_skill` landed in its target directory.

    Doctor's install/update path runs `_sync_bundled_skill` to copy the
    skill out of the npm package into `~/.claude/skills/<name>/`. The
    directory is then *managed* — `sccs sync` is configured to skip it
    (see managed.DEFAULT_MANAGED_PATTERNS). This detector closes the
    inspection loop: if the user removed the directory or starts on a
    fresh machine, `sccs doctor check` should surface the gap rather than
    silently report OK because the binary is on PATH.
    """

    def get_statuses(self, specs: list[NpxToolSpec]) -> list[BundledSkillStatus]:
        out: list[BundledSkillStatus] = []
        for spec in specs:
            if spec.bundled_skill is None:
                continue
            target = Path(os.path.expanduser(spec.bundled_skill.target))
            skill_md = target / "SKILL.md"
            out.append(
                BundledSkillStatus(
                    spec=spec,
                    target_path=str(target),
                    skill_md_present=skill_md.is_file(),
                )
            )
        return out


def _resolve_playwright_cache() -> Path:
    """Resolve the directory `playwright-cli install-browser` writes to.

    Resolution order (matches Playwright's own `Browser.install` semantics):
      1. `$PLAYWRIGHT_BROWSERS_PATH` if set and non-empty.
      2. Platform default:
         - Linux:   `~/.cache/ms-playwright`
         - macOS:   `~/Library/Caches/ms-playwright`
         - Windows: `%LOCALAPPDATA%/ms-playwright` (falls back to
                    `~/AppData/Local/ms-playwright`)

    The returned path may not exist — callers must handle that case.
    """
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else home / "AppData" / "Local"
        return base / "ms-playwright"
    return home / ".cache" / "ms-playwright"


class BrowserBundleDetector:
    """Detect browser bundles declared via `NpxToolSpec.browser_bundles`.

    Only `playwright-cli` ships browser bundles today — the detector is
    intentionally generic so any future tool that downloads runtime assets
    via a `<binary> install-browser <name>` step gets diagnosed for free.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        # `cache_dir` is injection-friendly for tests. Production code lets
        # it default to None so each call resolves the platform-specific
        # cache root via `_resolve_playwright_cache()`.
        self._cache_dir = cache_dir

    def _resolve(self) -> Path:
        return self._cache_dir if self._cache_dir is not None else _resolve_playwright_cache()

    def get_statuses(self, specs: list[NpxToolSpec]) -> list[BrowserBundleStatus]:
        out: list[BrowserBundleStatus] = []
        for spec in specs:
            if not spec.browser_bundles:
                continue
            cache_dir = self._resolve()
            cache_exists = cache_dir.is_dir()
            present: dict[str, bool] = {}
            if cache_exists:
                # `install-browser <name>` writes `<cache>/<name>-<version>/`
                # so we glob with `<name>-*` and accept any version match.
                for bundle in spec.browser_bundles:
                    matches = list(cache_dir.glob(f"{bundle}-*"))
                    present[bundle] = any(p.is_dir() for p in matches)
            else:
                present = dict.fromkeys(spec.browser_bundles, False)
            out.append(
                BrowserBundleStatus(
                    spec=spec,
                    cache_dir=str(cache_dir),
                    cache_dir_exists=cache_exists,
                    present=present,
                    all_present=all(present.values()) if present else True,
                )
            )
        return out


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
