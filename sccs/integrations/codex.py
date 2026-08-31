# SCCS OpenAI Codex Integration
#
# Detect a Codex CLI installation (~/.codex/) and materialise Claude Code
# artefacts into the Codex resource layout:
#
#   - Skills   : ~/.claude/skills/<name>/      -> ~/.agents/skills/<name>/
#                Codex discovers user skills from ~/.agents/skills (the
#                agentskills.io standard location; ~/.codex/skills/.system is
#                reserved for OpenAI-bundled system skills). The SKILL.md
#                format is identical to Claude Code, so the whole skill
#                directory is copied verbatim — no re-rendering.
#   - Agents   : ~/.claude/agents/<name>.md    -> ~/.codex/agents/<name>.toml
#                Codex subagents are standalone TOML files with name /
#                description / developer_instructions (+ model tuning). The
#                Markdown body becomes developer_instructions; the model alias
#                is mapped to a Codex model id + reasoning effort.
#   - Commands : ~/.claude/commands/<name>.md  -> ~/.agents/skills/<name>/SKILL.md
#                Wrapped as Codex skills. Codex custom prompts
#                (~/.codex/prompts/) are officially deprecated; skills are the
#                documented migration target for slash-command-style prompts.
#
# Direction is ONE-WAY (Claude is the source of truth). Mirrors the Pi
# (integrations/pi.py — verbatim skill copy) and OpenCode
# (integrations/opencode.py — converted-content gaps) patterns.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sccs.convert.claude_to_codex import convert_agent_frontmatter, wrap_command_as_skill
from sccs.convert.frontmatter import parse_frontmatter_ex, render_frontmatter
from sccs.convert.toml_write import render_codex_agent_toml
from sccs.integrations.skill_limits import check_skill_file
from sccs.utils.hashing import directory_hash, file_hash, quick_compare
from sccs.utils.paths import atomic_write, ensure_dir, matches_any_pattern, safe_copy

# CC artefact files we never export (private / disabled by convention).
_SKIP_PATTERNS = ("_", ".")
_LOCAL_SUFFIX = ".local.md"
DEFAULT_CODEX_EXPORT_STATE_PATH = Path.home() / ".config" / "sccs" / ".codex_export_state.yaml"

# Stated as a fact about the target, not as a verdict on the outcome: whether
# the target is kept or refreshed depends on --replace-foreign, which the gap
# builder cannot know. The writer appends the outcome.
FOREIGN_TARGET_WARNING = "target differs and was not written by SCCS"
FOREIGN_TARGET_KEPT = "kept — pass --replace-foreign to replace it from the source"
FOREIGN_TARGET_REPLACED = "replaced from the source (--replace-foreign)"


@dataclass
class CodexInfo:
    """Information about a Codex CLI installation."""

    installed: bool
    codex_dir: Path  # ~/.codex
    skills_dir: Path  # ~/.agents/skills
    agents_dir: Path  # ~/.codex/agents
    skills_dir_exists: bool
    agents_dir_exists: bool


@dataclass
class CodexArtifactGap:
    """A Claude artefact (skill dir, agent file or command file) missing or
    outdated in the Codex resource tree.

    Shared shape for all three export kinds. ``is_dir`` marks a verbatim skill
    directory copy; file gaps carry the already-converted target content so the
    writer does not have to re-run the conversion. ``collision`` marks a
    command whose skill slot is claimed by a real skill — never written.

    ``foreign_target`` is a WEAKER guard than ``collision``: the target exists,
    differs from the source and carries no ownership record, so a default run
    leaves it alone. Unlike a collision it is releasable, but by its OWN switch
    (``--replace-foreign``), never by ``--overwrite``: the two mark different
    risks — a stale target SCCS wrote versus one that may hold somebody's hand
    edits. Without a release of some kind a drifted target could never be
    refreshed except by deleting it by hand.
    """

    name: str
    src_path: Path  # source in ~/.claude/...
    dst_path: Path  # target in ~/.agents/skills/... or ~/.codex/agents/...
    dst_exists: bool
    needs_update: bool
    is_dir: bool
    converted_content: str | None = None  # None for verbatim skill copies
    warnings: list[str] = field(default_factory=list)
    collision: bool = False
    blocked: bool = False
    foreign_target: bool = False


@dataclass
class CodexExportResult:
    """Result of materialising Claude artefacts into Codex."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    target_dir_created: bool = False


@dataclass
class CodexExportState:
    """Digests of targets SCCS created, keyed as ``kind:name``.

    A missing record deliberately claims no existing target. That is the safe
    default: an unrelated Codex skill must never be replaced merely because it
    happens to have the same name as a Claude skill.
    """

    managed: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def key(kind: str, name: str) -> str:
        return f"{kind}:{name}"

    def owns(self, kind: str, name: str, path: Path) -> bool:
        digest = _artifact_digest(path)
        return digest is not None and self.managed.get(self.key(kind, name)) == digest

    def record(self, kind: str, name: str, path: Path) -> None:
        digest = _artifact_digest(path)
        if digest is not None:
            self.managed[self.key(kind, name)] = digest

    def to_dict(self) -> dict:
        return {"managed": dict(sorted(self.managed.items()))}

    @classmethod
    def from_dict(cls, data: dict) -> CodexExportState:
        raw = data.get("managed")
        if not isinstance(raw, dict):
            return cls()
        return cls(
            managed={key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)}
        )


class CodexExportStateManager:
    """Persist ownership without ever treating a missing/corrupt state as ownership."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or DEFAULT_CODEX_EXPORT_STATE_PATH

    def load(self) -> CodexExportState:
        if not self.state_path.exists():
            return CodexExportState()
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError):
            return CodexExportState()
        return CodexExportState.from_dict(data) if isinstance(data, dict) else CodexExportState()

    def save(self, state: CodexExportState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self.state_path,
            yaml.safe_dump(state.to_dict(), default_flow_style=False, sort_keys=True, allow_unicode=True),
            mode=0o600,
        )


def validate_model_map_against_cache(model_map: dict[str, str], cache_path: Path) -> tuple[list[str], list[str]]:
    """Validate configured model slugs against Codex's local catalogue.

    The cache is optional (for example before Codex has fetched it), so an
    absent or unreadable cache produces a warning rather than preventing a
    first export. Once a valid cache is present, a missing slug is a hard
    error: exporting a TOML file Codex cannot run is a false success.
    """
    if not cache_path.is_file():
        return [], [f"Codex model cache not found at {cache_path}; model mapping could not be verified"]
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        models = data.get("models") if isinstance(data, dict) else None
        available = {
            entry.get("slug")
            for entry in models or []
            if isinstance(entry, dict) and isinstance(entry.get("slug"), str)
        }
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [], [f"Codex model cache at {cache_path} could not be read; model mapping could not be verified"]
    if not available:
        return [], [f"Codex model cache at {cache_path} contains no model slugs; model mapping could not be verified"]
    return (
        [
            f"{alias}: model '{model}' is not in Codex's local model cache"
            for alias, model in sorted(model_map.items())
            if model not in available
        ],
        [],
    )


# --------------------------------------------------------------------------- #
# Detector
# --------------------------------------------------------------------------- #


class CodexDetector:
    """Detects Codex CLI and compares skill/agent/command availability."""

    def __init__(
        self,
        codex_dir: Path | None = None,
        skills_dir: Path | None = None,
        cc_skills_dir: Path | None = None,
        cc_agents_dir: Path | None = None,
        cc_commands_dir: Path | None = None,
    ) -> None:
        # codex_dir (~/.codex) is the install marker AND the agents target
        # root. skills_dir is a SEPARATE tree (~/.agents/skills — shared
        # agentskills.io location), so it is deliberately not used as an
        # install marker: it could exist because of an unrelated tool.
        self._codex_dir = codex_dir or Path.home() / ".codex"
        self._skills_dir = skills_dir or Path.home() / ".agents" / "skills"
        self._cc_skills_dir = cc_skills_dir or Path.home() / ".claude" / "skills"
        self._cc_agents_dir = cc_agents_dir or Path.home() / ".claude" / "agents"
        self._cc_commands_dir = cc_commands_dir or Path.home() / ".claude" / "commands"

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir

    @property
    def agents_dir(self) -> Path:
        return self._codex_dir / "agents"

    def is_installed(self) -> bool:
        return self._codex_dir.is_dir()

    def get_info(self) -> CodexInfo | None:
        if not self.is_installed():
            return None
        return CodexInfo(
            installed=True,
            codex_dir=self._codex_dir,
            skills_dir=self._skills_dir,
            agents_dir=self.agents_dir,
            skills_dir_exists=self._skills_dir.is_dir(),
            agents_dir_exists=self.agents_dir.is_dir(),
        )

    # ----- gap detection ------------------------------------------------- #

    def get_skill_gaps(
        self, *, exclude_patterns: list[str] | None = None, state: CodexExportState | None = None
    ) -> list[CodexArtifactGap]:
        """Find CC skill directories missing or outdated as Codex skills.

        Each ``~/.claude/skills/<name>/`` (containing SKILL.md) maps to
        ``~/.agents/skills/<name>/`` and is copied verbatim.

        Returns [] when Codex is not installed.
        """
        if not self.is_installed():
            return []

        gaps: list[CodexArtifactGap] = []
        if not self._cc_skills_dir.is_dir():
            return gaps

        for skill_dir in sorted(self._cc_skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            name = skill_dir.name
            if name.startswith(_SKIP_PATTERNS):
                continue
            if skill_dir.is_symlink():
                # Defence-in-depth: never follow links out of the skills dir.
                continue
            marker = skill_dir / "SKILL.md"
            if marker.is_symlink():
                gaps.append(
                    _blocked_gap(
                        name,
                        skill_dir,
                        self._skills_dir / name,
                        False,
                        "skill contains a symlink (SKILL.md) — not exported",
                    )
                )
                continue
            if not marker.is_file():
                continue
            if exclude_patterns and matches_any_pattern(name, exclude_patterns):
                continue

            dst = self._skills_dir / name
            dst_exists = dst.exists()
            try:
                linked_path = _first_symlink(skill_dir)
                needs_update = dst_exists and not quick_compare(skill_dir, dst)
            except OSError as exc:
                gaps.append(_blocked_gap(name, skill_dir, dst, True, f"could not scan skill: {exc}"))
                continue

            if linked_path is not None:
                gaps.append(
                    _blocked_gap(
                        name,
                        skill_dir,
                        dst,
                        dst_exists,
                        f"skill contains a symlink ({linked_path.relative_to(skill_dir)}) — not exported",
                    )
                )
                continue

            if not dst_exists or needs_update:
                # The copy will be byte-correct; these say Codex will refuse to
                # load the result anyway. Reported, never blocking.
                limit_warnings = [
                    f"{problem} — Codex will not load this skill"
                    for problem in check_skill_file(skill_dir / "SKILL.md")
                ]
                if dst_exists and needs_update and state is not None and not state.owns("skills", name, dst):
                    gaps.append(
                        _foreign_target_gap(
                            name, skill_dir, dst, is_dir=True, converted_content=None, warnings=limit_warnings
                        )
                    )
                    continue
                gaps.append(
                    CodexArtifactGap(
                        name=name,
                        src_path=skill_dir,
                        dst_path=dst,
                        dst_exists=dst_exists,
                        needs_update=needs_update,
                        is_dir=True,
                        warnings=limit_warnings,
                    )
                )
        return gaps

    def get_agent_gaps(
        self,
        model_map: dict[str, str] | None = None,
        reasoning_map: dict[str, str] | None = None,
        *,
        exclude_patterns: list[str] | None = None,
        state: CodexExportState | None = None,
    ) -> list[CodexArtifactGap]:
        """Find CC agents missing or outdated as Codex agent TOML files.

        Args:
            model_map: effective Claude-alias -> Codex-model map (defaults to
                the static bundled map; callers normally inject
                ``config.codex.effective_model_map``).
            reasoning_map: alias -> model_reasoning_effort map (same pattern).
            exclude_patterns: glob patterns matched against the agent basename;
                matching agents are skipped (e.g. doctor-managed ``gsd-*``).

        Returns [] when Codex is not installed.
        """
        if not self.is_installed():
            return []

        gaps: list[CodexArtifactGap] = []
        if not self._cc_agents_dir.is_dir():
            return gaps

        for cc_path in sorted(self._cc_agents_dir.glob("*.md")):
            name = cc_path.stem
            if cc_path.name.startswith(_SKIP_PATTERNS) or cc_path.name.endswith(_LOCAL_SUFFIX):
                continue
            if cc_path.is_symlink():
                continue
            if exclude_patterns and matches_any_pattern(name, exclude_patterns):
                continue

            try:
                converted, warnings = _render_agent(cc_path, model_map, reasoning_map)
            except (OSError, UnicodeDecodeError) as exc:
                gaps.append(
                    _blocked_gap(
                        name, cc_path, self.agents_dir / f"{name}.toml", False, f"could not read source file: {exc}"
                    )
                )
                continue

            dst = self.agents_dir / f"{name}.toml"
            gap = _content_gap(name, cc_path, dst, converted, warnings)
            if gap is not None:
                if gap.dst_exists and gap.needs_update and state is not None and not state.owns("agents", name, dst):
                    gap = _foreign_target_gap(
                        name, cc_path, dst, is_dir=False, converted_content=converted, warnings=warnings
                    )
                gaps.append(gap)
        return gaps

    def get_command_gaps(
        self, *, exclude_patterns: list[str] | None = None, state: CodexExportState | None = None
    ) -> list[CodexArtifactGap]:
        """Find CC commands missing or outdated as wrapped Codex skills.

        Each command maps to ``~/.agents/skills/<name>/SKILL.md``. A command
        whose name is claimed by a real skill — a Claude skill of the same
        name, or an on-disk skill directory that carries more than the wrapped
        SKILL.md — is flagged as a collision and never written (skills win).

        Returns [] when Codex is not installed.
        """
        if not self.is_installed():
            return []

        gaps: list[CodexArtifactGap] = []
        if not self._cc_commands_dir.is_dir():
            return gaps

        cc_skill_names = self._cc_skill_names()

        for cc_path in sorted(self._cc_commands_dir.glob("*.md")):
            name = cc_path.stem
            if cc_path.name.startswith(_SKIP_PATTERNS) or cc_path.name.endswith(_LOCAL_SUFFIX):
                continue
            if cc_path.is_symlink():
                continue
            if exclude_patterns and matches_any_pattern(name, exclude_patterns):
                continue

            try:
                converted, warnings = _render_command(name, cc_path)
            except (OSError, UnicodeDecodeError) as exc:
                gaps.append(
                    _blocked_gap(
                        name,
                        cc_path,
                        self._skills_dir / name / "SKILL.md",
                        False,
                        f"could not read source file: {exc}",
                    )
                )
                continue

            dst = self._skills_dir / name / "SKILL.md"

            collision_reason = self._command_collision(name, cc_skill_names)
            if collision_reason is not None:
                gaps.append(
                    CodexArtifactGap(
                        name=name,
                        src_path=cc_path,
                        dst_path=dst,
                        dst_exists=dst.is_file(),
                        needs_update=False,
                        is_dir=False,
                        converted_content=converted,
                        warnings=[*warnings, collision_reason],
                        collision=True,
                    )
                )
                continue

            gap = _content_gap(name, cc_path, dst, converted, warnings)
            if gap is not None:
                if gap.dst_exists and gap.needs_update and state is not None and not state.owns("commands", name, dst):
                    gap = _foreign_target_gap(
                        name, cc_path, dst, is_dir=False, converted_content=converted, warnings=warnings
                    )
                gaps.append(gap)
        return gaps

    # ----- helpers -------------------------------------------------------- #

    def source_names(self, kind: str) -> set[str]:
        """Names of exportable Claude artefacts of ``kind`` (skills/agents/commands).

        A gap list alone cannot tell "already up to date" apart from "no such
        artefact" — an artefact in sync produces no gap, and so does a typo.
        Callers selecting by name compare against this set to reject typos
        instead of silently exporting nothing.
        """
        if kind == "skills":
            return self._cc_skill_names()

        directory = self._cc_agents_dir if kind == "agents" else self._cc_commands_dir
        if not directory.is_dir():
            return set()

        names: set[str] = set()
        for path in directory.glob("*.md"):
            if path.name.startswith(_SKIP_PATTERNS) or path.name.endswith(_LOCAL_SUFFIX):
                continue
            if path.is_symlink():
                continue
            names.add(path.stem)
        return names

    def _cc_skill_names(self) -> set[str]:
        """Names of exportable Claude skills (they claim the skill slots)."""
        names: set[str] = set()
        if not self._cc_skills_dir.is_dir():
            return names
        for skill_dir in self._cc_skills_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.is_symlink():
                continue
            if skill_dir.name.startswith(_SKIP_PATTERNS):
                continue
            if (skill_dir / "SKILL.md").is_file():
                names.add(skill_dir.name)
        return names

    def _command_collision(self, name: str, cc_skill_names: set[str]) -> str | None:
        """Return a collision reason when a real skill claims ``name``.

        A previously wrapped command (a target dir holding exactly one
        SKILL.md) is NOT a collision — re-exports stay idempotent.
        """
        if name in cc_skill_names:
            return "name collides with a Claude skill — the skill wins, command not exported"

        target_dir = self._skills_dir / name
        if not target_dir.is_dir():
            return None
        if not (target_dir / "SKILL.md").is_file():
            return "target skill directory exists without SKILL.md — not touching it"
        extra = [p for p in target_dir.iterdir() if p.name != "SKILL.md"]
        if extra:
            return "target skill directory carries additional files (a real skill) — command not exported"
        return None


# --------------------------------------------------------------------------- #
# File renderers (read CC file -> converted Codex document)
# --------------------------------------------------------------------------- #


def _artifact_digest(path: Path) -> str | None:
    """Content digest without following a target symlink."""
    try:
        if path.is_symlink():
            return None
        if path.is_dir():
            return directory_hash(path)
        if path.is_file():
            return file_hash(path)
        return None
    except OSError:
        return None


def _first_symlink(path: Path) -> Path | None:
    """Return the first symlink in a skill tree, if any.

    A copied symlink is not a portable skill asset: it may resolve outside the
    Claude tree and then become broken in ``~/.agents/skills``. Rejecting it is
    safer and makes the failure visible rather than silently exporting a skill
    Codex cannot load.
    """
    if path.is_symlink():
        return path
    for child in path.rglob("*"):
        if child.is_symlink():
            return child
    return None


def _blocked_gap(name: str, src: Path, dst: Path, dst_exists: bool, warning: str) -> CodexArtifactGap:
    return CodexArtifactGap(
        name=name,
        src_path=src,
        dst_path=dst,
        dst_exists=dst_exists,
        needs_update=False,
        is_dir=src.is_dir(),
        warnings=[warning],
        blocked=True,
    )


def _foreign_target_gap(
    name: str,
    src: Path,
    dst: Path,
    *,
    is_dir: bool,
    converted_content: str | None,
    warnings: list[str] | None = None,
) -> CodexArtifactGap:
    return CodexArtifactGap(
        name=name,
        src_path=src,
        dst_path=dst,
        dst_exists=True,
        needs_update=True,
        is_dir=is_dir,
        converted_content=converted_content,
        warnings=[*(warnings or []), FOREIGN_TARGET_WARNING],
        foreign_target=True,
    )


def _render_agent(
    cc_path: Path,
    model_map: dict[str, str] | None = None,
    reasoning_map: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Render a CC agent Markdown file as a Codex agent TOML document.

    Uses ``parse_frontmatter_ex`` rather than ``parse_frontmatter``: we emit our
    OWN frontmatter/TOML header, so a block that failed to parse must not be
    left in the body (that produced documents with two stacked headers).
    """
    parsed = parse_frontmatter_ex(cc_path.read_text(encoding="utf-8"))
    body = parsed.body
    codex_meta, warnings = convert_agent_frontmatter(
        parsed.metadata, model_map, reasoning_map, parse_error=parsed.error
    )
    name = cc_path.stem
    description = codex_meta.get("description") or f"Claude Code agent '{name}'"
    document = render_codex_agent_toml(
        name,
        description,
        body,
        model=codex_meta.get("model"),
        model_reasoning_effort=codex_meta.get("model_reasoning_effort"),
        sandbox_mode=codex_meta.get("sandbox_mode"),
    )
    return document, warnings


def _render_command(name: str, cc_path: Path) -> tuple[str, list[str]]:
    """Render a CC command Markdown file as a wrapped Codex SKILL.md.

    See ``_render_agent`` for why this uses ``parse_frontmatter_ex``.
    """
    parsed = parse_frontmatter_ex(cc_path.read_text(encoding="utf-8"))
    skill_meta, body, warnings = wrap_command_as_skill(name, parsed.metadata, parsed.body, parse_error=parsed.error)
    return render_frontmatter(skill_meta, body), warnings


def _content_gap(
    name: str,
    src_path: Path,
    dst_path: Path,
    converted: str,
    warnings: list[str],
) -> CodexArtifactGap | None:
    """Build a file gap by comparing rendered content against the target."""
    dst_exists = dst_path.is_file()
    needs_update = False
    if dst_exists:
        try:
            needs_update = dst_path.read_text(encoding="utf-8") != converted
        except (OSError, UnicodeDecodeError):
            needs_update = True

    if dst_exists and not needs_update:
        return None
    return CodexArtifactGap(
        name=name,
        src_path=src_path,
        dst_path=dst_path,
        dst_exists=dst_exists,
        needs_update=needs_update,
        is_dir=False,
        converted_content=converted,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def export_skills_to_codex(
    gaps: list[CodexArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    replace_foreign: bool = False,
    selected: list[str] | None = None,
    state: CodexExportState | None = None,
) -> CodexExportResult:
    """Materialise CC skill directories into ~/.agents/skills/."""
    return _materialize_codex(
        gaps,
        dry_run=dry_run,
        overwrite_existing=overwrite_existing,
        replace_foreign=replace_foreign,
        selected=selected,
        kind="skills",
        state=state,
    )


def convert_agents_to_codex(
    gaps: list[CodexArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    replace_foreign: bool = False,
    selected: list[str] | None = None,
    state: CodexExportState | None = None,
) -> CodexExportResult:
    """Materialise converted agent gaps into ~/.codex/agents/."""
    return _materialize_codex(
        gaps,
        dry_run=dry_run,
        overwrite_existing=overwrite_existing,
        replace_foreign=replace_foreign,
        selected=selected,
        kind="agents",
        state=state,
    )


def convert_commands_to_codex(
    gaps: list[CodexArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    replace_foreign: bool = False,
    selected: list[str] | None = None,
    state: CodexExportState | None = None,
) -> CodexExportResult:
    """Materialise wrapped command gaps into ~/.agents/skills/<name>/SKILL.md."""
    return _materialize_codex(
        gaps,
        dry_run=dry_run,
        overwrite_existing=overwrite_existing,
        replace_foreign=replace_foreign,
        selected=selected,
        kind="commands",
        state=state,
    )


def _materialize_codex(
    gaps: list[CodexArtifactGap],
    *,
    dry_run: bool,
    overwrite_existing: bool,
    replace_foreign: bool,
    selected: list[str] | None,
    kind: str,
    state: CodexExportState | None,
) -> CodexExportResult:
    result = CodexExportResult()

    if selected is not None:
        selected_set = set(selected)
        gaps = [g for g in gaps if g.name in selected_set]

    if not gaps:
        return result

    for gap in gaps:
        warnings = list(gap.warnings)

        if gap.collision or gap.blocked:
            # A real skill claims this slot — never written (see detector).
            if warnings:
                result.warnings[gap.name] = warnings
            result.skipped.append(gap.name)
            continue

        # Two risk classes, two switches, no interaction between them: a target
        # SCCS wrote is governed by --overwrite alone, a foreign one — which may
        # hold somebody's hand edits — by --replace-foreign alone.
        if gap.foreign_target:
            if not replace_foreign:
                warnings.append(FOREIGN_TARGET_KEPT)
                result.warnings[gap.name] = warnings
                result.skipped.append(gap.name)
                continue
            warnings.append(FOREIGN_TARGET_REPLACED)
        elif gap.dst_exists and not overwrite_existing:
            if warnings:
                result.warnings[gap.name] = warnings
            result.skipped.append(gap.name)
            continue

        if warnings:
            result.warnings[gap.name] = warnings

        if not gap.is_dir and not gap.converted_content:
            result.errors[gap.name] = "no converted content (source unreadable)"
            continue

        target_parent = gap.dst_path.parent
        if not target_parent.is_dir():
            if not dry_run:
                try:
                    ensure_dir(target_parent)
                except OSError as exc:
                    result.errors[gap.name] = f"Cannot create target directory: {exc}"
                    continue
            result.target_dir_created = True

        if not dry_run:
            try:
                if gap.is_dir:
                    # safe_copy handles directories atomically and refuses
                    # symlinks (defence-in-depth against link-following).
                    safe_copy(gap.src_path, gap.dst_path)
                else:
                    atomic_write(gap.dst_path, gap.converted_content or "")
            except (OSError, ValueError) as exc:
                result.errors[gap.name] = f"Write error: {exc}"
                continue

        if state is not None:
            state.record(kind, gap.name, gap.dst_path)

        if gap.dst_exists and gap.needs_update:
            result.updated.append(gap.name)
        else:
            result.created.append(gap.name)

    return result
