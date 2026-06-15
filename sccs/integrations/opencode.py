# SCCS OpenCode Integration
#
# Detect an OpenCode installation (~/.config/opencode/) and materialise
# Claude Code artefacts into the OpenCode formats:
#
#   - Skills + Rules  : read natively by OpenCode from ~/.claude/ — NO action
#                       needed here (see get_info().reads_claude_skills).
#   - Agents          : converted CC frontmatter -> ~/.config/opencode/agent/
#   - Commands        : converted CC frontmatter -> ~/.config/opencode/command/
#   - MCP servers      : merged from ~/.claude/settings.json into opencode.json
#
# Direction is ONE-WAY (Claude is the source of truth). Mirrors the Antigravity
# (integrations/antigravity.py) and Claude Desktop (integrations/claude_desktop.py)
# patterns: a read-only detector + gap detection + a writer that uses
# atomic_write and timestamped backups.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sccs.convert.claude_to_opencode import (
    DEFAULT_OPENCODE_MODEL_MAP,
    TIER_KEYWORDS,
    convert_agent_frontmatter,
    convert_command_frontmatter,
    convert_mcp_server,
    match_models,
)
from sccs.convert.frontmatter import parse_frontmatter, render_frontmatter
from sccs.doctor.runner import run_opencode_models
from sccs.utils.paths import atomic_write, create_backup, ensure_dir, matches_any_pattern

# CC artefact files we never convert (private / disabled by convention).
_SKIP_PATTERNS = ("_", ".")
_LOCAL_SUFFIX = ".local.md"


@dataclass
class OpenCodeInfo:
    """Information about an OpenCode installation."""

    installed: bool
    config_dir: Path
    config_file: Path | None  # opencode.jsonc or opencode.json
    agent_dir: Path
    command_dir: Path
    skills_dir_exists: bool
    agent_dir_exists: bool
    command_dir_exists: bool
    reads_claude_skills: bool  # True unless OPENCODE_DISABLE_CLAUDE_CODE_SKILLS is set


@dataclass
class OpenCodeArtifactGap:
    """A Claude artefact (agent or command) missing/outdated in OpenCode.

    Shared shape for agents and commands — both convert a single ``.md`` file
    and carry the already-converted target content so the writer does not have
    to re-run the conversion.
    """

    name: str
    cc_path: Path
    oc_path: Path
    oc_exists: bool
    needs_update: bool
    converted_content: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ConversionResult:
    """Result of materialising converted artefacts into OpenCode."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    target_dir_created: bool = False


@dataclass
class McpMergeResult:
    """Result of merging MCP servers into opencode.json."""

    success: bool = True
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    error: str | None = None


# --------------------------------------------------------------------------- #
# Detector
# --------------------------------------------------------------------------- #


class OpenCodeDetector:
    """Detects OpenCode and compares agent/command/MCP availability."""

    def __init__(
        self,
        config_dir: Path | None = None,
        cc_agents_dir: Path | None = None,
        cc_commands_dir: Path | None = None,
        cc_skills_dir: Path | None = None,
        *,
        disable_claude_skills: bool = False,
    ) -> None:
        self._config_dir = config_dir or Path.home() / ".config" / "opencode"
        self._cc_agents_dir = cc_agents_dir or Path.home() / ".claude" / "agents"
        self._cc_commands_dir = cc_commands_dir or Path.home() / ".claude" / "commands"
        self._cc_skills_dir = cc_skills_dir or Path.home() / ".claude" / "skills"
        self._disable_claude_skills = disable_claude_skills

    # canonical singular dirs (OpenCode also accepts the plural alias)
    @property
    def agent_dir(self) -> Path:
        return self._config_dir / "agent"

    @property
    def command_dir(self) -> Path:
        return self._config_dir / "command"

    def is_installed(self) -> bool:
        return self._config_dir.is_dir()

    def _find_config_file(self) -> Path | None:
        for name in ("opencode.jsonc", "opencode.json"):
            candidate = self._config_dir / name
            if candidate.is_file():
                return candidate
        return None

    def get_info(self) -> OpenCodeInfo | None:
        if not self.is_installed():
            return None
        return OpenCodeInfo(
            installed=True,
            config_dir=self._config_dir,
            config_file=self._find_config_file(),
            agent_dir=self.agent_dir,
            command_dir=self.command_dir,
            skills_dir_exists=(self._config_dir / "skills").is_dir(),
            agent_dir_exists=self.agent_dir.is_dir(),
            command_dir_exists=self.command_dir.is_dir(),
            reads_claude_skills=not self._disable_claude_skills,
        )

    # ----- gap detection ------------------------------------------------- #

    def get_agent_gaps(
        self,
        model_map: dict[str, str] | None = None,
        *,
        exclude_patterns: list[str] | None = None,
    ) -> list[OpenCodeArtifactGap]:
        """Find CC agents missing or outdated as OpenCode agents.

        Args:
            model_map: resolved alias->'provider/model' map for the conversion
                (see resolve_model_map). None uses the static default.
            exclude_patterns: glob patterns matched against the agent basename;
                matching agents are skipped (e.g. doctor-managed ``gsd-*``).

        Returns [] when OpenCode is not installed — there is nothing to export to.
        """
        if not self.is_installed():
            return []
        return self._gaps_for(self._cc_agents_dir, self.agent_dir, _render_agent, model_map, exclude_patterns)

    def get_command_gaps(
        self,
        model_map: dict[str, str] | None = None,
        *,
        exclude_patterns: list[str] | None = None,
    ) -> list[OpenCodeArtifactGap]:
        """Find CC commands missing or outdated as OpenCode commands.

        Args:
            exclude_patterns: glob patterns matched against the command basename;
                matching commands are skipped (e.g. doctor-managed ``gsd-*``).

        Returns [] when OpenCode is not installed.
        """
        if not self.is_installed():
            return []
        return self._gaps_for(self._cc_commands_dir, self.command_dir, _render_command, model_map, exclude_patterns)

    @staticmethod
    def _gaps_for(
        cc_dir: Path,
        oc_dir: Path,
        renderer,
        model_map: dict[str, str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> list[OpenCodeArtifactGap]:
        gaps: list[OpenCodeArtifactGap] = []
        if not cc_dir.is_dir():
            return gaps

        for cc_path in sorted(cc_dir.glob("*.md")):
            name = cc_path.stem
            if cc_path.name.startswith(_SKIP_PATTERNS) or cc_path.name.endswith(_LOCAL_SUFFIX):
                continue
            if cc_path.is_symlink():
                # Defence-in-depth: never follow links out of the artefact dir.
                continue
            if exclude_patterns and matches_any_pattern(name, exclude_patterns):
                # Doctor-managed (gsd-*) or user-excluded artefact — not ours
                # to export. Mirrors the sync engine's global_exclude logic.
                continue

            try:
                converted, warnings = renderer(cc_path, model_map)
            except OSError:
                # Unreadable source — surface as a gap with an empty payload so
                # the writer reports the error rather than silently dropping it.
                converted, warnings = "", ["could not read source file"]

            oc_path = oc_dir / f"{name}.md"
            oc_exists = oc_path.is_file()
            needs_update = False
            if oc_exists:
                try:
                    needs_update = oc_path.read_text(encoding="utf-8") != converted
                except OSError:
                    needs_update = True

            if not oc_exists or needs_update:
                gaps.append(
                    OpenCodeArtifactGap(
                        name=name,
                        cc_path=cc_path,
                        oc_path=oc_path,
                        oc_exists=oc_exists,
                        needs_update=needs_update,
                        converted_content=converted,
                        warnings=warnings,
                    )
                )
        return gaps

    # ----- MCP status ---------------------------------------------------- #

    def get_mcp_status(self, cc_settings_file: Path | None = None) -> dict:
        """Compare CC mcpServers with the servers already in opencode.json.

        Returns a dict with ``cc_servers``, ``oc_servers`` and ``missing``
        (present in CC, absent from OpenCode) — read-only, for status display.
        """
        cc_file = cc_settings_file or Path.home() / ".claude" / "settings.json"
        cc_servers = sorted(_read_cc_mcp_servers(cc_file).keys())

        oc_file = self._find_config_file()
        oc_servers: list[str] = []
        if oc_file is not None:
            try:
                oc_data = _load_jsonc(oc_file.read_text(encoding="utf-8"))
                oc_servers = sorted((oc_data.get("mcp") or {}).keys())
            except (OSError, ValueError):
                oc_servers = []

        missing = [s for s in cc_servers if s not in oc_servers]
        return {"cc_servers": cc_servers, "oc_servers": oc_servers, "missing": missing}


# --------------------------------------------------------------------------- #
# Model discovery & resolution
# --------------------------------------------------------------------------- #


def list_opencode_models() -> list[str]:
    """Return the 'provider/model' ids the local OpenCode install offers.

    Thin wrapper over ``opencode models`` (via the hardened doctor runner).
    Empty list on any failure (OpenCode missing, no provider authenticated).
    """
    raw = run_opencode_models()
    models: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        # A valid model id is 'provider/model' — require exactly one slash and
        # no surrounding noise.
        if token.count("/") == 1 and token not in seen:
            seen.add(token)
            models.append(token)
    return models


def resolve_model_map(config=None, *, discover: bool = True, cc_tokens: list[str] | None = None) -> dict[str, str]:
    """Build the effective Claude-alias -> OpenCode-model map.

    Layered precedence (lowest to highest): static DEFAULT_OPENCODE_MODEL_MAP,
    then live family-match against ``opencode models``, then the user's explicit
    config map (``opencode.model_map`` + ``extra_model_map``). Per-token: an
    alias the user did not pin still falls back to discovery, then to the static
    default — so a partial config map is fine.

    Args:
        config: an SccsConfig (or None). Read defensively via getattr so callers
            without a config still work.
        discover: run live model discovery (set False to stay offline/in tests).
        cc_tokens: which Claude aliases to resolve via discovery (defaults to the
            known tier aliases sonnet/opus/haiku).
    """
    oc = getattr(config, "opencode", None)
    user_map = dict(getattr(oc, "model_map", None) or {}) if oc is not None else {}
    user_extra = dict(getattr(oc, "extra_model_map", {}) or {}) if oc is not None else {}
    preferred = list(getattr(oc, "preferred_providers", None) or ["anthropic"]) if oc is not None else ["anthropic"]
    user_explicit = {**user_map, **user_extra}

    discovered: dict[str, str] = {}
    if discover:
        available = list_opencode_models()
        if available:
            discovered, _ = match_models(
                cc_tokens or list(TIER_KEYWORDS.keys()),
                available,
                preferred_providers=preferred,
            )

    return {**DEFAULT_OPENCODE_MODEL_MAP, **discovered, **user_explicit}


# --------------------------------------------------------------------------- #
# File renderers (read CC file -> converted OpenCode document)
# --------------------------------------------------------------------------- #


def _render_agent(cc_path: Path, model_map: dict[str, str] | None = None) -> tuple[str, list[str]]:
    meta, body = parse_frontmatter(cc_path.read_text(encoding="utf-8"))
    oc_meta, warnings = convert_agent_frontmatter(meta, model_map)
    return render_frontmatter(oc_meta, body), warnings


def _render_command(cc_path: Path, model_map: dict[str, str] | None = None) -> tuple[str, list[str]]:
    meta, body = parse_frontmatter(cc_path.read_text(encoding="utf-8"))
    oc_meta, warnings = convert_command_frontmatter(meta, model_map)
    return render_frontmatter(oc_meta, body), warnings


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def convert_agents_to_opencode(
    gaps: list[OpenCodeArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    selected: list[str] | None = None,
) -> ConversionResult:
    """Materialise converted agent gaps into ~/.config/opencode/agent/."""
    return _materialize(gaps, dry_run=dry_run, overwrite_existing=overwrite_existing, selected=selected)


def convert_commands_to_opencode(
    gaps: list[OpenCodeArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    selected: list[str] | None = None,
) -> ConversionResult:
    """Materialise converted command gaps into ~/.config/opencode/command/."""
    return _materialize(gaps, dry_run=dry_run, overwrite_existing=overwrite_existing, selected=selected)


def _materialize(
    gaps: list[OpenCodeArtifactGap],
    *,
    dry_run: bool,
    overwrite_existing: bool,
    selected: list[str] | None,
) -> ConversionResult:
    result = ConversionResult()

    if selected is not None:
        selected_set = set(selected)
        gaps = [g for g in gaps if g.name in selected_set]

    if not gaps:
        return result

    target_dir = gaps[0].oc_path.parent
    if not target_dir.is_dir():
        if not dry_run:
            ensure_dir(target_dir)
        result.target_dir_created = True

    for gap in gaps:
        if gap.warnings:
            result.warnings[gap.name] = gap.warnings

        if gap.oc_exists and not overwrite_existing:
            result.skipped.append(gap.name)
            continue

        if not gap.converted_content:
            result.errors[gap.name] = "no converted content (source unreadable)"
            continue

        if not dry_run:
            try:
                atomic_write(gap.oc_path, gap.converted_content)
            except OSError as exc:
                result.errors[gap.name] = f"Write error: {exc}"
                continue

        if gap.oc_exists and gap.needs_update:
            result.updated.append(gap.name)
        else:
            result.created.append(gap.name)

    return result


# --------------------------------------------------------------------------- #
# MCP merge
# --------------------------------------------------------------------------- #

_LINE_COMMENT = re.compile(r"(?m)^[ \t]*//.*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _load_jsonc(text: str) -> dict:
    """Parse JSONC (JSON with // and /* */ comments) into a dict.

    Comments are stripped with a conservative regex before json.loads. This is
    intentionally simple: it does not attempt to honour comment-like sequences
    inside string values. OpenCode config files are small and machine-managed,
    so this is adequate and keeps us dependency-free.
    """
    stripped = _BLOCK_COMMENT.sub("", text)
    stripped = _LINE_COMMENT.sub("", stripped)
    if not stripped.strip():
        return {}
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("opencode config root is not a JSON object")
    return data


def _read_cc_mcp_servers(cc_settings_file: Path) -> dict:
    """Read the mcpServers map from a CC settings.json (empty dict on any miss)."""
    if not cc_settings_file.is_file():
        return {}
    try:
        data = json.loads(cc_settings_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    servers = data.get("mcpServers")
    return servers if isinstance(servers, dict) else {}


def merge_mcp_to_opencode(
    *,
    cc_settings_file: Path | None = None,
    oc_config_file: Path | None = None,
    config_dir: Path | None = None,
    server_names: list[str] | None = None,
    dry_run: bool = False,
    overwrite_existing: bool = False,
) -> McpMergeResult:
    """Merge CC mcpServers into the ``mcp`` block of opencode.json.

    Existing OpenCode MCP entries are preserved unless ``overwrite_existing``.
    A timestamped backup is written before any modification.
    """
    result = McpMergeResult()

    cc_file = cc_settings_file or Path.home() / ".claude" / "settings.json"
    cc_servers = _read_cc_mcp_servers(cc_file)
    if not cc_servers:
        result.error = f"No MCP servers found in {cc_file}"
        result.success = False
        return result

    if server_names is not None:
        wanted = set(server_names)
        cc_servers = {k: v for k, v in cc_servers.items() if k in wanted}
        if not cc_servers:
            result.error = "None of the requested MCP servers exist in the Claude settings"
            result.success = False
            return result

    # Resolve the OpenCode config file (prefer .jsonc, then .json).
    if oc_config_file is None:
        base = config_dir or Path.home() / ".config" / "opencode"
        oc_config_file = next(
            (base / n for n in ("opencode.jsonc", "opencode.json") if (base / n).is_file()),
            base / "opencode.jsonc",
        )

    # Load existing OpenCode config (may not exist yet).
    oc_data: dict = {}
    if oc_config_file.is_file():
        try:
            oc_data = _load_jsonc(oc_config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            result.error = f"Failed to read OpenCode config: {exc}"
            result.success = False
            return result

    existing_mcp = oc_data.get("mcp")
    if not isinstance(existing_mcp, dict):
        existing_mcp = {}

    merged_mcp = dict(existing_mcp)

    for name, cc_server in cc_servers.items():
        if not isinstance(cc_server, dict):
            result.warnings[name] = ["entry is not an object — skipped"]
            continue

        oc_server, warnings = convert_mcp_server(cc_server)
        if warnings:
            result.warnings[name] = warnings

        if name in existing_mcp and not overwrite_existing:
            result.already_present.append(name)
            continue

        merged_mcp[name] = oc_server
        if name in existing_mcp:
            result.updated.append(name)
        else:
            result.added.append(name)

    # Nothing to write.
    if not result.added and not result.updated:
        return result

    if dry_run:
        return result

    oc_data["mcp"] = merged_mcp

    # Backup any existing file before overwriting.
    if oc_config_file.is_file():
        create_backup(oc_config_file, category="opencode")

    # We write canonical JSON (comments, if any, are not preserved).
    payload = json.dumps(oc_data, indent=2, ensure_ascii=False) + "\n"
    try:
        atomic_write(oc_config_file, payload, mode=0o600)
    except OSError as exc:
        result.error = f"Failed to write OpenCode config: {exc}"
        result.success = False

    return result
