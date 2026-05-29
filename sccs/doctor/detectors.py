# SCCS Doctor Detectors
# Read-only inspection of Node.js, Claude CLI, Claude plugins, npx tools
# and filesystem permissions for known-fragile paths.

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sccs.doctor._paths import is_home_path
from sccs.doctor.defaults import get_node_install_spec
from sccs.doctor.runner import (
    DoctorError,
    _run,
    parse_node_major,
    run_claude_marketplace_list,
    run_claude_mcp_list,
    run_claude_plugin_list,
    run_node_version,
    which,
)
from sccs.doctor.schema import (
    MCPServerSpec,
    NodeInstallSpec,
    NpxToolSpec,
    PathPrefixCheckSpec,
    PermissionCheckSpec,
    PluginSpec,
    StatusLineCheckSpec,
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
    # The version reported by the `Version:` line of `claude plugin list`, or
    # None if the parser couldn't extract it. Display-only (the reporter shows
    # it in the Version column); not used for any update decision.
    version: str | None = None


@dataclass
class ForeignPluginStatus:
    """A Claude plugin that is installed but NOT in the user's doctor.plugins
    spec.

    Surfaced by ClaudePluginDetector.get_foreign_plugins() so `sccs doctor
    optimize` can warn about drift between what the user declares and what
    the local Claude install actually has. With `--strict`, doctor optimize
    queues an uninstall action against each entry.
    """

    name: str
    marketplace: str | None
    scope: str | None


@dataclass
class NpxToolStatus:
    """Result of inspecting a single npx helper tool."""

    spec: NpxToolSpec
    available: bool
    binary_path: str | None
    detection_source: str = "path"  # "path" | "state" | "missing"
    # Installed version for display in the doctor-check Version column, or None
    # when the spec declares no source (version_file/version_args) or the lookup
    # failed. Never used for any install/update decision.
    version: str | None = None


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
class MarketplaceStatus:
    """Result of checking whether a Claude plugin marketplace is registered.

    Built by `ClaudeMarketplaceDetector` against `claude plugin marketplace
    list`. Used by the installer to decide whether to queue plugin installs
    for that marketplace at all — installing into a non-existent marketplace
    can never succeed, so the install is reported as `⊘ skipped` instead of
    spawning a guaranteed-failed subprocess.

    `suggested_source` is the `marketplace_source` (`owner/repo` or URL)
    learned from the user's PluginSpec list, surfaced in the manual block
    so the user can copy-paste a `claude plugin marketplace add …` command.
    None when no spec for this marketplace carries a source.
    """

    name: str
    registered: bool
    suggested_source: str | None = None
    skipped_reason: str | None = None  # set when claude CLI is missing

    @property
    def ok(self) -> bool:
        if self.skipped_reason is not None:
            return True
        return self.registered


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
    # UIDs of any non-root, non-current-user owners found among the scanned
    # offenders. Triggered by the Debian-13 terminal-server incident: a
    # multi-user box has packages installed by *several* users under
    # `/usr/local/lib/node_modules/`. Recommending `sudo chown -R <me>:<me>`
    # there would silently destroy the other users' installs. Populated by
    # `PermissionDetector._check`; consumed by `_npm_root_global_fix_block`
    # to suppress Option B when ≥2 distinct foreign uids are present.
    foreign_uids: set[int] = field(default_factory=set)
    skipped_reason: str | None = None  # set on Windows / fallback platforms

    @property
    def ok(self) -> bool:
        if self.skipped_reason is not None:
            return True
        if not self.exists:
            return True
        return self.is_user_owned and self.is_writable

    @property
    def is_multi_user(self) -> bool:
        """True when the path is owned by ≥2 distinct non-root users.

        Heuristic for the terminal-server scenario: if more than one foreign
        non-root uid is present in the offenders, this is a shared resource
        and `sudo chown -R` is unsafe. Root-only ownership (single uid 0)
        is the single-admin case where chown is fine.
        """
        non_root = {uid for uid in self.foreign_uids if uid != 0}
        return len(non_root) >= 2

    @property
    def fix_command(self) -> str | None:
        """Return the recommended fix command, or None when no safe single-line fix exists.

        `sudo chown -R UID:GID PATH` is only offered when it is BOTH safe and
        complete. Returns None when:
          * the status is OK (no fix needed),
          * the directory is multi-user owned (chown would destroy other users'
            installs — terminal-server scenario, see v2.28.1),
          * the path lives outside $HOME (system prefix like /usr — chowning
            the lib dir alone is incomplete and chowning /usr/bin is dangerous;
            the correct remediation is a user-local npm prefix, surfaced by
            `_npm_global_fix_block` in installer.py).
        Callers (reporter, installer) must handle None by delegating to the
        richer manual-fix block.
        """
        if self.ok:
            return None
        if self.is_multi_user:
            return None
        if not is_home_path(self.resolved_path):
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
    def _extract_version_from_block(output: str, match_end: int) -> str | None:
        """Read the `Version: <ver>` line that follows a plugin header match.

        Same block-slicing strategy as `_extract_scope_from_block` (stop at the
        next `❯ ` header). Display-only: the value feeds the doctor-check
        Version column. Returns None when the CLI omits the line.
        """
        block = output[match_end : match_end + 300]
        next_header = re.search(r"\n\s*❯", block)
        if next_header:
            block = block[: next_header.start()]
        m = re.search(r"\bVersion:\s*(\S+)", block, re.IGNORECASE)
        if not m:
            return None
        ver = m.group(1)
        # `claude plugin list` prints `Version: unknown` for plugins that
        # expose no version; treat that as "no version" so the reporter shows
        # a blank cell instead of a misleading `vunknown`.
        return None if ver.lower() == "unknown" else ver

    @staticmethod
    def _detect_plugin(
        name: str,
        marketplace: str | None,
        output: str,
    ) -> tuple[str, str | None, str | None, str | None]:
        """Classify a single plugin against the raw `claude plugin list` output.

        Returns (detection_source, found_marketplace, scope, version).
        detection_source is one of "exact", "alternative", "bare", "missing".
        `scope` is the value of the `Scope:` line in the matched plugin's
        metadata block, `version` the `Version:` line — either None if no match
        or the respective line was not found.
        """
        if not output:
            return ("missing", None, None, None)

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
                version = ClaudePluginDetector._extract_version_from_block(output, m.end())
                return ("exact", marketplace, scope, version)

        # Plugin name found under *some* marketplace — installed via a
        # different source than the user configured (or any source at all
        # when no marketplace was configured).
        match = any_market_re.search(output)
        if match:
            found = match.group(1)
            scope = ClaudePluginDetector._extract_scope_from_block(output, match.end())
            version = ClaudePluginDetector._extract_version_from_block(output, match.end())
            if marketplace and found.lower() != marketplace.lower():
                return ("alternative", found, scope, version)
            return ("exact", found, scope, version)

        # Plugin name appears as a bare token (rare CLI format that omits
        # the '@marketplace' suffix).
        bare_re = re.compile(
            rf"(?<![\w\-]){escaped_name}(?![\w\-@])",
            re.IGNORECASE,
        )
        bare = bare_re.search(output)
        if bare:
            scope = ClaudePluginDetector._extract_scope_from_block(output, bare.end())
            version = ClaudePluginDetector._extract_version_from_block(output, bare.end())
            return ("bare", None, scope, version)

        return ("missing", None, None, None)

    def get_statuses(self, specs: list[PluginSpec]) -> list[PluginStatus]:
        output = self._output()
        statuses: list[PluginStatus] = []
        for spec in specs:
            source, found, scope, version = self._detect_plugin(spec.name, spec.marketplace, output)
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
                    version=version,
                )
            )
        return statuses

    def get_foreign_plugins(self, specs: list[PluginSpec]) -> list[ForeignPluginStatus]:
        """Return plugins that are installed locally but NOT in `specs`.

        Used by `sccs doctor optimize` to surface drift: a plugin the user
        removed from `doctor.plugins:` is no longer managed, but stays
        physically installed until either the user runs
        `claude plugin uninstall …` manually OR `doctor optimize --strict`
        queues the removal. Matching is name-based, marketplace-aware: a
        plugin counts as "in spec" if (a) its name matches a spec entry
        AND (b) the spec either omits the marketplace or matches the
        installed one. The latter clause means `frontend-design@A` in spec
        does NOT excuse `frontend-design@B` from being marked foreign —
        the user wanted exactly @A.
        """
        output = self._output()
        if not output:
            return []

        # Parse every `❯ <name>@<marketplace>` (or bare `❯ <name>`) header
        # from the plugin-list output. The same marketplace-token charset
        # as _detect_plugin keeps these two helpers in sync.
        header_re = re.compile(
            r"❯\s+([A-Za-z0-9_\-][A-Za-z0-9_.\-]*)(?:@([A-Za-z0-9_.\-]+))?",
        )

        # Index the spec for O(1) lookups. Marketplace=None means "any source
        # of this plugin is fine" — matches the semantics of _detect_plugin's
        # `bare` branch.
        spec_index: dict[str, set[str | None]] = {}
        for spec in specs:
            spec_index.setdefault(spec.name.lower(), set()).add(spec.marketplace.lower() if spec.marketplace else None)

        foreign: list[ForeignPluginStatus] = []
        seen: set[tuple[str, str | None]] = set()
        for m in header_re.finditer(output):
            name = m.group(1)
            marketplace = m.group(2)
            key = (name.lower(), marketplace.lower() if marketplace else None)
            if key in seen:
                continue
            seen.add(key)

            spec_marketplaces = spec_index.get(name.lower())
            if spec_marketplaces is not None:
                # In spec under any marketplace (None) → covered.
                # In spec under the installed marketplace → covered.
                installed_mp = marketplace.lower() if marketplace else None
                if None in spec_marketplaces or installed_mp in spec_marketplaces:
                    continue

            scope = ClaudePluginDetector._extract_scope_from_block(output, m.end())
            foreign.append(ForeignPluginStatus(name=name, marketplace=marketplace, scope=scope))

        return foreign


class ClaudeMarketplaceDetector:
    """Detect which Claude plugin marketplaces are registered locally.

    Real-world failure mode (Debian 13 terminal server, 2026-05-06):
    `/usr/local/lib/node_modules/` was root-owned with packages from
    multiple users, so the user switched to a per-user setup. The
    `claude-plugins-official` marketplace was *never registered* on that
    box (it is not a built-in default — the user's home machine had it
    because someone added it once). Every `claude plugin install
    <name>@claude-plugins-official` then died with "Plugin not found in
    marketplace …", yet doctor's auto-update step couldn't help because
    you cannot UPDATE a marketplace that does not exist; you must ADD it.

    The detector reads `claude plugin marketplace list` once and reports a
    `MarketplaceStatus` per configured marketplace. The installer uses the
    `registered=False` rows to:
      1. Emit a manual_block with `blocks_downstream=True` per missing
         marketplace (component `plugin-marketplace:<name>:exists`).
      2. Skip every plugin install for that marketplace (instead of
         spawning a guaranteed-failed `claude plugin install …`).
    """

    def __init__(self, raw_output: str | None = None) -> None:
        # Test-friendly injection. Production lazy-loads via the runner.
        self._raw_output = raw_output

    def _output(self) -> str:
        if self._raw_output is None:
            self._raw_output = run_claude_marketplace_list()
        return self._raw_output

    @staticmethod
    def _parse_registered(output: str) -> set[str]:
        """Return the set of marketplace names present in
        `claude plugin marketplace list` output.

        The CLI formats each marketplace block roughly as:

            ❯ <name>
              Source: <owner/repo>
              Plugins: <count>

        We extract the leading `❯ <name>` tokens. If the CLI later changes
        format we silently fall back to scanning every word that matches the
        plugin/marketplace allowlist — better to over-report (treating a
        marketplace as registered when it isn't) than under-report (false
        manual_blocks blocking installs unnecessarily).
        """
        if not output:
            return set()
        names: set[str] = set()
        for line in output.splitlines():
            stripped = line.strip()
            # Primary format: `❯ <name>` header.
            m = re.match(r"^[❯>]\s+([A-Za-z0-9_.\-]+)\s*$", stripped)
            if m:
                names.add(m.group(1))
                continue
            # Secondary format: lines like "Name: <name>" or
            # "<name> (<n> plugins)" — defensive fallback.
            m2 = re.match(r"^Name:\s*([A-Za-z0-9_.\-]+)\s*$", stripped, re.IGNORECASE)
            if m2:
                names.add(m2.group(1))
        return names

    def get_statuses(
        self,
        plugin_specs: list[PluginSpec],
        *,
        claude_cli_installed: bool = True,
    ) -> list[MarketplaceStatus]:
        """Return one status per distinct configured marketplace.

        `claude_cli_installed=False` causes every status to come back with a
        `skipped_reason` so doctor doesn't queue marketplace manual blocks
        on a host that hasn't even installed `claude` yet — the missing
        CLI is reported elsewhere.
        """
        # Aggregate the list of {marketplace → suggested_source} from the
        # plugin specs, dropping plugins without a marketplace (they install
        # by bare name and don't need a marketplace registration).
        sources: dict[str, str | None] = {}
        for spec in plugin_specs:
            if not spec.marketplace:
                continue
            sources.setdefault(spec.marketplace, None)
            if spec.marketplace_source and not sources[spec.marketplace]:
                sources[spec.marketplace] = spec.marketplace_source

        if not sources:
            return []

        if not claude_cli_installed:
            return [
                MarketplaceStatus(
                    name=name,
                    registered=False,
                    suggested_source=src,
                    skipped_reason="claude CLI not installed",
                )
                for name, src in sources.items()
            ]

        registered = self._parse_registered(self._output())
        return [
            MarketplaceStatus(
                name=name,
                registered=name in registered,
                suggested_source=src,
            )
            for name, src in sources.items()
        ]


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


_STATUS_LINE_OPAQUE_MARKERS = ("|", "&&", ";", "$(", "`", "||")
_STATUS_LINE_SCRIPT_CANDIDATES = (
    "statusline.sh",
    "statusline.py",
    "statusline.ps1",
    "statusline.fish",
    "hooks/gsd-statusline.js",
)
# /opt/homebrew/Cellar/<pkg>/<version>/<rest>. Apple Silicon only — Intel
# Homebrew (`/usr/local/Cellar/...`) and Linuxbrew are deferred to a future
# phase per CONTEXT.md D2.
_STATUS_LINE_CELLAR_RE = re.compile(r"^/opt/homebrew/Cellar/([^/]+)/([^/]+)/(.+)$")
_STATUS_LINE_SCRIPT_EXTS = (".sh", ".py", ".js", ".mjs", ".ps1", ".fish")


@dataclass
class StatusLineStatus:
    """Result of inspecting ~/.claude/settings.json `statusLine.command`.

    `state` is one of:
      - 'ok'              — command parses and binary (+ script if any) exist
      - 'missing'         — settings.json present but statusLine key absent
                            *and* `required_mode` resolves to required=True
      - 'missing_binary'  — first argv token unresolvable
      - 'missing_script'  — second argv token looks like a script path
                            but file does not exist
      - 'stale_cellar'    — first argv token matches the Apple-Silicon
                            Homebrew Cellar pattern but the version directory
                            no longer exists (typical Homebrew upgrade
                            collateral)
      - 'opaque'          — command shape not parseable (pipes, env prefix,
                            command substitution, …) — explicitly skipped to
                            avoid false positives
      - 'no_settings_file'— settings.json does not exist
    """

    spec: StatusLineCheckSpec
    state: str
    settings_path: str
    raw_command: str | None
    binary: str | None
    script: str | None
    detail: str
    cellar_pkg: str | None = None
    cellar_version: str | None = None

    @property
    def ok(self) -> bool:
        # opaque + no_settings_file are not faults: opaque is user-chosen
        # complexity, no_settings_file is a fresh-install state. Only
        # missing/missing_binary/missing_script/stale_cellar are problems.
        return self.state in {"ok", "opaque", "no_settings_file"}


class StatusLineDetector:
    """Parse settings.json `statusLine.command` and classify invokability.

    `smart_required` is the runtime evaluation of D1 from CONTEXT.md: True
    when the `claude_statusline` sync category is enabled in the user's
    config. Combined with on-disk script presence at check-time when the
    spec's `required_mode='smart'`. The CLI layer computes the boolean
    (it owns config access); the detector consumes it.
    """

    def __init__(self, smart_required: bool = False) -> None:
        self._smart_required = smart_required

    def get_statuses(self, specs: list[StatusLineCheckSpec]) -> list[StatusLineStatus]:
        out: list[StatusLineStatus] = []
        for spec in specs:
            out.append(self._evaluate(spec))
        return out

    def _evaluate(self, spec: StatusLineCheckSpec) -> StatusLineStatus:
        resolved = Path(os.path.expanduser(spec.settings_path))
        if not resolved.is_file():
            return StatusLineStatus(
                spec=spec,
                state="no_settings_file",
                settings_path=str(resolved),
                raw_command=None,
                binary=None,
                script=None,
                detail="no settings.json",
            )
        try:
            data = json.loads(resolved.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return StatusLineStatus(
                spec=spec,
                state="opaque",
                settings_path=str(resolved),
                raw_command=None,
                binary=None,
                script=None,
                detail=f"settings.json unreadable: {exc}",
            )

        sl = data.get("statusLine") if isinstance(data, dict) else None
        if not isinstance(sl, dict) or "command" not in sl:
            if self._is_required(spec, resolved.parent):
                return StatusLineStatus(
                    spec=spec,
                    state="missing",
                    settings_path=str(resolved),
                    raw_command=None,
                    binary=None,
                    script=None,
                    detail="statusLine key absent (sync category enabled, script present)",
                )
            return StatusLineStatus(
                spec=spec,
                state="ok",
                settings_path=str(resolved),
                raw_command=None,
                binary=None,
                script=None,
                detail="not configured (opt-in)",
            )

        cmd = sl.get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            return StatusLineStatus(
                spec=spec,
                state="opaque",
                settings_path=str(resolved),
                raw_command=cmd if isinstance(cmd, str) else None,
                binary=None,
                script=None,
                detail="command is not a non-empty string",
            )

        if any(marker in cmd for marker in _STATUS_LINE_OPAQUE_MARKERS):
            return StatusLineStatus(
                spec=spec,
                state="opaque",
                settings_path=str(resolved),
                raw_command=cmd,
                binary=None,
                script=None,
                detail="custom command shape, not checked",
            )

        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError as exc:
            return StatusLineStatus(
                spec=spec,
                state="opaque",
                settings_path=str(resolved),
                raw_command=cmd,
                binary=None,
                script=None,
                detail=f"unparseable command: {exc}",
            )
        if not tokens:
            return StatusLineStatus(
                spec=spec,
                state="opaque",
                settings_path=str(resolved),
                raw_command=cmd,
                binary=None,
                script=None,
                detail="empty command after parsing",
            )

        # env-var prefix (FOO=bar node script.js) — first token has '=' before
        # any '/', so it's not a path.
        if "=" in tokens[0] and "/" not in tokens[0].split("=", 1)[0]:
            return StatusLineStatus(
                spec=spec,
                state="opaque",
                settings_path=str(resolved),
                raw_command=cmd,
                binary=None,
                script=None,
                detail="env-prefixed command, not checked",
            )

        binary = tokens[0]
        script = tokens[1] if len(tokens) > 1 else None

        # Stale-Cellar check first (highest-signal failure mode).
        cellar = _STATUS_LINE_CELLAR_RE.match(binary)
        if cellar is not None:
            pkg, version, _rest = cellar.groups()
            if not Path(f"/opt/homebrew/Cellar/{pkg}/{version}").is_dir():
                return StatusLineStatus(
                    spec=spec,
                    state="stale_cellar",
                    settings_path=str(resolved),
                    raw_command=cmd,
                    binary=binary,
                    script=script,
                    detail=(f"Cellar path stale: {pkg}/{version} no longer exists (Homebrew upgraded?)"),
                    cellar_pkg=pkg,
                    cellar_version=version,
                )
            # Cellar dir still exists — treat as a literal path below.

        # Binary existence.
        if "/" in binary:
            if not Path(binary).is_file():
                return StatusLineStatus(
                    spec=spec,
                    state="missing_binary",
                    settings_path=str(resolved),
                    raw_command=cmd,
                    binary=binary,
                    script=script,
                    detail=f"binary not found: {binary}",
                )
        else:
            if which(binary) is None:
                return StatusLineStatus(
                    spec=spec,
                    state="missing_binary",
                    settings_path=str(resolved),
                    raw_command=cmd,
                    binary=binary,
                    script=script,
                    detail=f"binary not on PATH: {binary}",
                )

        # Script existence — only check when second token plausibly *is* a
        # script (contains '/' or ends with a known script extension). This
        # avoids false positives for commands like `bash -c '...'` where
        # the second token is a flag.
        if script is not None and self._looks_like_script(script):
            script_path = Path(os.path.expanduser(script))
            if not script_path.is_file():
                return StatusLineStatus(
                    spec=spec,
                    state="missing_script",
                    settings_path=str(resolved),
                    raw_command=cmd,
                    binary=binary,
                    script=script,
                    detail=f"script not found: {script}",
                )

        return StatusLineStatus(
            spec=spec,
            state="ok",
            settings_path=str(resolved),
            raw_command=cmd,
            binary=binary,
            script=script,
            detail=binary,
        )

    def _is_required(self, spec: StatusLineCheckSpec, home_dir: Path) -> bool:
        mode = spec.required_mode
        if mode == "always":
            return True
        if mode == "never":
            return False
        # smart: gated by both config (sync category enabled) and on-disk
        # script presence. The sync flag is supplied by the CLI; the script
        # check is done here so the detector remains the single source of
        # truth for filesystem facts.
        if not self._smart_required:
            return False
        return any((home_dir / candidate).is_file() for candidate in _STATUS_LINE_SCRIPT_CANDIDATES)

    @staticmethod
    def _looks_like_script(token: str) -> bool:
        if "/" in token:
            return True
        return token.lower().endswith(_STATUS_LINE_SCRIPT_EXTS)


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
        elif spec.path_kind == "npm-bin-global":
            npm_bin = _resolve_npm_prefix_bin()
            if npm_bin is None:
                return PermissionStatus(
                    spec=spec,
                    exists=False,
                    is_user_owned=True,
                    is_writable=True,
                    expected_uid=-1,
                    expected_gid=-1,
                    resolved_path=spec.path,
                    skipped_reason="npm not on PATH — cannot resolve global bin",
                )
            resolved = npm_bin
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

        if spec.path_kind == "npm-bin-global":
            # Simple writability check only. We never recursively scan or chown
            # a global bin dir (e.g. /usr/bin): the only safe fix for a
            # non-writable system bin dir is a user-local npm prefix, surfaced
            # by the manual block. A recursive scan here would also be wasteful
            # (hundreds of unrelated /usr/bin entries) and misleadingly suggest
            # chowning system binaries.
            return PermissionStatus(
                spec=spec,
                exists=True,
                is_user_owned=True,
                is_writable=os.access(path, os.W_OK),
                expected_uid=current_uid,
                expected_gid=current_gid,
                resolved_path=resolved,
            )

        is_writable = os.access(path, os.W_OK)
        offenders: list[str] = []
        # Track every non-self uid seen during the scan — needed for the
        # multi-user heuristic (`is_multi_user`). We deliberately do *not*
        # cap this set at `_MAX_OFFENDERS_REPORTED`: knowing whether two
        # vs. three foreign uids own the tree changes the remediation,
        # while the offender path list can be capped for display.
        foreign_uids: set[int] = set()

        # Check the root path itself first — its ownership is the most
        # diagnostic signal.
        try:
            root_st = path.stat()
            if root_st.st_uid != current_uid:
                offenders.append(resolved)
                foreign_uids.add(root_st.st_uid)
        except OSError:
            pass

        # Recursive sample. Cap path collection for display, but keep
        # scanning to populate `foreign_uids` until the path-scan cap.
        scanned = 0
        offender_cap_hit = False
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
                    foreign_uids.add(st.st_uid)
                    if not offender_cap_hit:
                        s = str(entry)
                        if s not in offenders:
                            offenders.append(s)
                            if len(offenders) >= _MAX_OFFENDERS_REPORTED:
                                offender_cap_hit = True
                    # Two distinct non-root foreign uids → multi-user
                    # already proven. Stop early to avoid scanning the rest
                    # of a huge tree just to confirm a heuristic that
                    # already flipped.
                    if len({u for u in foreign_uids if u != 0}) >= 2 and offender_cap_hit:
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
            foreign_uids=foreign_uids,
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

    @staticmethod
    def _resolve_version(spec: NpxToolSpec) -> str | None:
        """Best-effort installed-version lookup for the Version column.

        `version_file` (zero-cost file read) takes precedence over
        `version_args` (one subprocess). Any failure — unreadable file, missing
        binary, timeout, non-version output — returns None so the column simply
        stays blank; it never raises into the detection flow.
        """
        if spec.version_file:
            try:
                text = Path(spec.version_file).expanduser().read_text(encoding="utf-8")
            except OSError:
                return None
            for line in text.splitlines():
                stripped = line.strip()
                if stripped:
                    return stripped
            return None
        if spec.version_args:
            cmd = [spec.detect_command or spec.name, *spec.version_args]
            try:
                proc = _run(cmd, check=False, capture=True, timeout=10)
            except DoctorError:
                return None
            blob = f"{proc.stdout or ''} {proc.stderr or ''}"
            m = re.search(r"\d+\.\d+\.\d+\S*", blob)
            return m.group(0) if m else None
        return None

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
                        version=self._resolve_version(spec),
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
                            version=self._resolve_version(spec),
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


@dataclass
class MCPServerStatus:
    """Result of inspecting a single spec'd MCP server."""

    spec: MCPServerSpec
    installed: bool


@dataclass
class SettingsHookViolation:
    """A hook entry in settings.json that matches a `disallowed_hooks` pattern.

    Carries enough information for the reporter to print "PreToolUse:
    Write|Edit → gsd-read-guard.js" without re-parsing settings.json,
    and for the action builder to construct an idempotent removal closure.
    """

    event: str  # PreToolUse | PostToolUse | SessionStart | Stop | ...
    matcher: str | None  # the matcher string, or None when omitted
    command: str  # the full command string from the hook entry
    matched_pattern: str  # which `disallowed_hooks` substring matched


class SettingsHookDetector:
    """Find hook entries in settings.json whose command matches a disallowed
    pattern.

    Real driver: third-party doctor tools (npx @opengsd/get-shit-done-redux
    --force-statusline, …) overwrite settings.json on every run, re-
    injecting hooks the user explicitly removed in a setup audit. The
    detector surfaces those violations so `_settings_hook_cleanup_actions`
    can queue a sanitiser that re-removes them after every doctor pass.

    Pattern matching is plain substring (case-sensitive) against the
    `command` field of each hook entry — same shape as glob-free
    filtering elsewhere in doctor. Globs would be overkill: hook commands
    are file paths the user themselves chose, so substring matching on
    the script basename (e.g. "gsd-read-guard.js") is precise enough.
    """

    def __init__(self, settings_path: Path | str = "~/.claude/settings.json") -> None:
        self._settings_path = Path(os.path.expanduser(str(settings_path)))

    @property
    def settings_path(self) -> Path:
        return self._settings_path

    def get_violations(
        self,
        disallowed: list[str],
        *,
        protected: list[str] | None = None,
    ) -> list[SettingsHookViolation]:
        """Return one violation per hook entry that matches any disallowed pattern.

        Empty `disallowed` list short-circuits to []. Missing or malformed
        settings.json also returns [] — the detector is read-only and the
        cleanup-action layer makes the same safety call when it runs.

        `protected` wins over `disallowed`: a command whose string contains any
        protected substring is never reported, even if a disallowed pattern
        also matches. This is the hard guard that keeps GSD hooks
        (DEFAULT_PROTECTED_HOOKS = ['gsd-']) from ever being stripped, even if a
        user accidentally re-adds them to `disallowed_hooks`.
        """
        if not disallowed:
            return []
        protected = protected or []
        if not self._settings_path.is_file():
            return []
        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        hooks_root = data.get("hooks")
        if not isinstance(hooks_root, dict):
            return []

        violations: list[SettingsHookViolation] = []
        for event, entries in hooks_root.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                inner_hooks = entry.get("hooks")
                if not isinstance(inner_hooks, list):
                    continue
                matcher = entry.get("matcher") if entry.get("matcher") != "" else ""
                # matcher may be None / "" / "Bash|Edit" — kept verbatim for
                # display, no normalisation here.
                for inner in inner_hooks:
                    if not isinstance(inner, dict):
                        continue
                    cmd = inner.get("command")
                    if not isinstance(cmd, str):
                        continue
                    # Protected hooks (e.g. GSD) are never reported — protection
                    # wins over removal regardless of disallowed matches.
                    if any(p and p in cmd for p in protected):
                        continue
                    for pattern in disallowed:
                        if pattern and pattern in cmd:
                            violations.append(
                                SettingsHookViolation(
                                    event=str(event),
                                    matcher=matcher if matcher is not None else None,
                                    command=cmd,
                                    matched_pattern=pattern,
                                )
                            )
                            break  # one pattern is enough — don't double-report
        return violations


@dataclass
class ForeignMCPServerStatus:
    """An MCP server registered locally but NOT in the spec and not ignored.

    Surfaced by MCPServerDetector.get_foreign_servers() so `sccs doctor
    optimize` can flag drift between `doctor.mcp_servers` and what the
    local `claude mcp list` actually contains. With `--strict`, doctor
    optimize queues a `claude mcp remove <name> -s user` action per entry.
    """

    name: str


class MCPServerDetector:
    """Detect MCP servers registered with the local Claude install.

    Parses the line-based output of `claude mcp list`:

        <name>: <command-or-url> - <status>

    The `<name>:` token (left of the first colon) is the only field we
    care about — the rest is opaque to the detector. Status text is not
    inspected (a foreign server is foreign whether it's connected or not).
    """

    def __init__(self, raw_output: str | None = None) -> None:
        # Allow injection for testing; otherwise lazy-load via runner.
        self._raw_output = raw_output

    def _output(self) -> str:
        if self._raw_output is None:
            self._raw_output = run_claude_mcp_list()
        return self._raw_output

    # Regex used to split `<name>: <command-or-url> - <status>` lines.
    # We split on `: ` (colon + space) rather than the first bare `:` so
    # server names containing colons survive — concretely `claude mcp list`
    # emits plugin-internal MCPs as `plugin:context-mode:context-mode: node
    # …`, where the name itself has two colons. The space requirement
    # disambiguates: the body always starts with whitespace after the
    # delimiter colon.
    _NAME_SPLIT_RE = re.compile(r":\s")

    @staticmethod
    def _parse_server_names(output: str) -> list[str]:
        """Extract the `<name>` tokens from `claude mcp list` stdout.

        Skips the leading "Checking MCP server health…" banner and any
        empty lines. A server line is recognised by the `<name>: <rest>`
        shape — lines without a colon-space delimiter are noise. Names may
        themselves contain colons (see `plugin:<plugin-name>:<server-name>`),
        which is why we split on the first `: ` rather than the first `:`.
        """
        names: list[str] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("Checking "):
                continue
            split = MCPServerDetector._NAME_SPLIT_RE.split(stripped, maxsplit=1)
            if len(split) != 2:
                continue
            name = split[0].strip()
            # Defensive: reject empty or obviously broken names so a
            # mangled line in the CLI output cannot leak into the
            # `claude mcp remove` action queue.
            if name and re.match(r"^[A-Za-z0-9_:\-./ ]+$", name):
                names.append(name)
        return names

    def get_statuses(self, specs: list[MCPServerSpec]) -> list[MCPServerStatus]:
        """Classify each spec'd server as installed or missing."""
        installed = set(self._parse_server_names(self._output()))
        return [MCPServerStatus(spec=spec, installed=spec.name in installed) for spec in specs]

    def get_foreign_servers(
        self,
        specs: list[MCPServerSpec],
        ignored_patterns: list[str],
    ) -> list[ForeignMCPServerStatus]:
        """Return MCP servers installed locally but NOT in specs/ignored.

        Filtering order:
          1. Drop any server whose name matches a `spec.name`.
          2. Drop any server whose name matches an fnmatch glob in
             `ignored_patterns` (DEFAULT_IGNORED_MCP_PATTERNS covers
             `claude.ai *` OAuth services and `plugin:*` plugin-internal
             MCPs out of the box).
          3. Whatever's left is foreign.
        """
        import fnmatch as _fnmatch

        spec_names = {s.name for s in specs}
        foreign: list[ForeignMCPServerStatus] = []
        seen: set[str] = set()
        for name in self._parse_server_names(self._output()):
            if name in spec_names or name in seen:
                continue
            if any(_fnmatch.fnmatchcase(name, pat) for pat in ignored_patterns):
                continue
            seen.add(name)
            foreign.append(ForeignMCPServerStatus(name=name))
        return foreign
