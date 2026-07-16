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

from dataclasses import dataclass, field
from pathlib import Path

from sccs.convert.claude_to_codex import convert_agent_frontmatter, wrap_command_as_skill
from sccs.convert.frontmatter import parse_frontmatter, render_frontmatter
from sccs.convert.toml_write import render_codex_agent_toml
from sccs.utils.hashing import quick_compare
from sccs.utils.paths import atomic_write, ensure_dir, matches_any_pattern, safe_copy

# CC artefact files we never export (private / disabled by convention).
_SKIP_PATTERNS = ("_", ".")
_LOCAL_SUFFIX = ".local.md"


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


@dataclass
class CodexExportResult:
    """Result of materialising Claude artefacts into Codex."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    target_dir_created: bool = False


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

    def get_skill_gaps(self, *, exclude_patterns: list[str] | None = None) -> list[CodexArtifactGap]:
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
            if not (skill_dir / "SKILL.md").is_file():
                continue
            if exclude_patterns and matches_any_pattern(name, exclude_patterns):
                continue

            dst = self._skills_dir / name
            dst_exists = dst.exists()
            needs_update = dst_exists and not quick_compare(skill_dir, dst)

            if not dst_exists or needs_update:
                gaps.append(
                    CodexArtifactGap(
                        name=name,
                        src_path=skill_dir,
                        dst_path=dst,
                        dst_exists=dst_exists,
                        needs_update=needs_update,
                        is_dir=True,
                    )
                )
        return gaps

    def get_agent_gaps(
        self,
        model_map: dict[str, str] | None = None,
        reasoning_map: dict[str, str] | None = None,
        *,
        exclude_patterns: list[str] | None = None,
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
            except OSError:
                converted, warnings = "", ["could not read source file"]

            dst = self.agents_dir / f"{name}.toml"
            gap = _content_gap(name, cc_path, dst, converted, warnings)
            if gap is not None:
                gaps.append(gap)
        return gaps

    def get_command_gaps(self, *, exclude_patterns: list[str] | None = None) -> list[CodexArtifactGap]:
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
            except OSError:
                converted, warnings = "", ["could not read source file"]

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
                gaps.append(gap)
        return gaps

    # ----- helpers -------------------------------------------------------- #

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


def _render_agent(
    cc_path: Path,
    model_map: dict[str, str] | None = None,
    reasoning_map: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Render a CC agent Markdown file as a Codex agent TOML document."""
    meta, body = parse_frontmatter(cc_path.read_text(encoding="utf-8"))
    codex_meta, warnings = convert_agent_frontmatter(meta, model_map, reasoning_map)
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
    """Render a CC command Markdown file as a wrapped Codex SKILL.md."""
    meta, body = parse_frontmatter(cc_path.read_text(encoding="utf-8"))
    skill_meta, body, warnings = wrap_command_as_skill(name, meta, body)
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
        except OSError:
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
    selected: list[str] | None = None,
) -> CodexExportResult:
    """Materialise CC skill directories into ~/.agents/skills/."""
    return _materialize_codex(gaps, dry_run=dry_run, overwrite_existing=overwrite_existing, selected=selected)


def convert_agents_to_codex(
    gaps: list[CodexArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    selected: list[str] | None = None,
) -> CodexExportResult:
    """Materialise converted agent gaps into ~/.codex/agents/."""
    return _materialize_codex(gaps, dry_run=dry_run, overwrite_existing=overwrite_existing, selected=selected)


def convert_commands_to_codex(
    gaps: list[CodexArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    selected: list[str] | None = None,
) -> CodexExportResult:
    """Materialise wrapped command gaps into ~/.agents/skills/<name>/SKILL.md."""
    return _materialize_codex(gaps, dry_run=dry_run, overwrite_existing=overwrite_existing, selected=selected)


def _materialize_codex(
    gaps: list[CodexArtifactGap],
    *,
    dry_run: bool,
    overwrite_existing: bool,
    selected: list[str] | None,
) -> CodexExportResult:
    result = CodexExportResult()

    if selected is not None:
        selected_set = set(selected)
        gaps = [g for g in gaps if g.name in selected_set]

    if not gaps:
        return result

    for gap in gaps:
        if gap.warnings:
            result.warnings[gap.name] = gap.warnings

        if gap.collision:
            # A real skill claims this slot — never written (see detector).
            result.skipped.append(gap.name)
            continue

        if gap.dst_exists and not overwrite_existing:
            result.skipped.append(gap.name)
            continue

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

        if gap.dst_exists and gap.needs_update:
            result.updated.append(gap.name)
        else:
            result.created.append(gap.name)

    return result
