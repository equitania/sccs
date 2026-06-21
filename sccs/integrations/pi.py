# SCCS Pi Integration
#
# Detect a Pi installation (~/.pi/) and materialise Claude Code artefacts into
# the Pi resource layout (pi.dev — @earendil-works/pi-coding-agent):
#
#   - Skills   : ~/.claude/skills/<name>/      -> ~/.pi/agent/skills/<name>/
#                Pi loads SKILL.md folders recursively. The SKILL.md frontmatter
#                (name/description) is format-identical to Claude Code, so the
#                whole skill directory is copied verbatim — no re-rendering.
#   - Agents   : ~/.claude/agents/<name>.md    -> ~/.pi/agent/skills/<name>.md
#                Pi has no subagent concept; a root .md file in skills/ is loaded
#                as an individual skill. name/description carry over; unknown
#                frontmatter (model, tools) is ignored by Pi.
#   - Commands : ~/.claude/commands/<name>.md  -> ~/.pi/agent/prompts/<name>.md
#                Pi prompt templates are Markdown snippets invoked via /name —
#                a direct match for Claude slash-command prompts.
#
# Direction is ONE-WAY (Claude is the source of truth). Mirrors the OpenCode
# (integrations/opencode.py) and Antigravity (integrations/antigravity.py)
# patterns: a read-only detector + gap detection + a writer using safe_copy
# (which also rejects symlinks as defence-in-depth).

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sccs.utils.hashing import quick_compare
from sccs.utils.paths import ensure_dir, matches_any_pattern, safe_copy

# CC artefact files we never export (private / disabled by convention).
_SKIP_PATTERNS = ("_", ".")
_LOCAL_SUFFIX = ".local.md"


@dataclass
class PiInfo:
    """Information about a Pi installation."""

    installed: bool
    base_dir: Path  # ~/.pi/agent
    skills_dir: Path  # ~/.pi/agent/skills
    prompts_dir: Path  # ~/.pi/agent/prompts
    skills_dir_exists: bool
    prompts_dir_exists: bool


@dataclass
class PiArtifactGap:
    """A Claude artefact (skill dir, agent file or command file) missing or
    outdated in the Pi resource tree.

    Shared shape for all three export kinds. ``is_dir`` distinguishes a skill
    directory copy from a single-file copy; the writer dispatches on it.
    """

    name: str
    src_path: Path  # source in ~/.claude/...
    dst_path: Path  # target in ~/.pi/agent/...
    dst_exists: bool
    needs_update: bool
    is_dir: bool


@dataclass
class PiExportResult:
    """Result of materialising Claude artefacts into Pi."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    # Always empty for Pi (verbatim copy, no frontmatter conversion). Present so
    # the shared CLI renderer (_print_conversion_result) can format the result.
    warnings: dict[str, list[str]] = field(default_factory=dict)
    target_dir_created: bool = False


# --------------------------------------------------------------------------- #
# Detector
# --------------------------------------------------------------------------- #


class PiDetector:
    """Detects Pi and compares skill/agent/command availability."""

    def __init__(
        self,
        base_dir: Path | None = None,
        cc_skills_dir: Path | None = None,
        cc_agents_dir: Path | None = None,
        cc_commands_dir: Path | None = None,
    ) -> None:
        # base_dir is the Pi agent resource root (~/.pi/agent). The install
        # marker is its parent (~/.pi) so a bare ~/.pi (no agent/ yet) still
        # counts as installed and the export creates agent/skills on demand.
        self._base_dir = base_dir or Path.home() / ".pi" / "agent"
        self._cc_skills_dir = cc_skills_dir or Path.home() / ".claude" / "skills"
        self._cc_agents_dir = cc_agents_dir or Path.home() / ".claude" / "agents"
        self._cc_commands_dir = cc_commands_dir or Path.home() / ".claude" / "commands"

    @property
    def skills_dir(self) -> Path:
        return self._base_dir / "skills"

    @property
    def prompts_dir(self) -> Path:
        return self._base_dir / "prompts"

    def is_installed(self) -> bool:
        # Treat either ~/.pi or ~/.pi/agent as an install marker.
        return self._base_dir.is_dir() or self._base_dir.parent.is_dir()

    def get_info(self) -> PiInfo | None:
        if not self.is_installed():
            return None
        return PiInfo(
            installed=True,
            base_dir=self._base_dir,
            skills_dir=self.skills_dir,
            prompts_dir=self.prompts_dir,
            skills_dir_exists=self.skills_dir.is_dir(),
            prompts_dir_exists=self.prompts_dir.is_dir(),
        )

    # ----- gap detection ------------------------------------------------- #

    def get_skill_gaps(self, *, exclude_patterns: list[str] | None = None) -> list[PiArtifactGap]:
        """Find CC skill directories missing or outdated as Pi skills.

        Each ``~/.claude/skills/<name>/`` (containing SKILL.md) maps to
        ``~/.pi/agent/skills/<name>/`` and is copied verbatim.

        Args:
            exclude_patterns: glob patterns matched against the skill basename;
                matching skills are skipped (e.g. doctor-managed ``gsd-*``).

        Returns [] when Pi is not installed.
        """
        if not self.is_installed():
            return []

        gaps: list[PiArtifactGap] = []
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

            dst = self.skills_dir / name
            dst_exists = dst.exists()
            # quick_compare returns True when contents match; gap when they don't.
            needs_update = dst_exists and not quick_compare(skill_dir, dst)

            if not dst_exists or needs_update:
                gaps.append(
                    PiArtifactGap(
                        name=name,
                        src_path=skill_dir,
                        dst_path=dst,
                        dst_exists=dst_exists,
                        needs_update=needs_update,
                        is_dir=True,
                    )
                )
        return gaps

    def get_agent_gaps(self, *, exclude_patterns: list[str] | None = None) -> list[PiArtifactGap]:
        """Find CC agents missing or outdated as Pi skills (root .md)."""
        if not self.is_installed():
            return []
        return self._file_gaps_for(self._cc_agents_dir, self.skills_dir, exclude_patterns)

    def get_command_gaps(self, *, exclude_patterns: list[str] | None = None) -> list[PiArtifactGap]:
        """Find CC commands missing or outdated as Pi prompt templates."""
        if not self.is_installed():
            return []
        return self._file_gaps_for(self._cc_commands_dir, self.prompts_dir, exclude_patterns)

    @staticmethod
    def _file_gaps_for(
        cc_dir: Path,
        dst_dir: Path,
        exclude_patterns: list[str] | None,
    ) -> list[PiArtifactGap]:
        gaps: list[PiArtifactGap] = []
        if not cc_dir.is_dir():
            return gaps

        for src in sorted(cc_dir.glob("*.md")):
            name = src.stem
            if src.name.startswith(_SKIP_PATTERNS) or src.name.endswith(_LOCAL_SUFFIX):
                continue
            if src.is_symlink():
                continue
            if exclude_patterns and matches_any_pattern(name, exclude_patterns):
                continue

            dst = dst_dir / src.name
            dst_exists = dst.is_file()
            needs_update = dst_exists and not quick_compare(src, dst)

            if not dst_exists or needs_update:
                gaps.append(
                    PiArtifactGap(
                        name=name,
                        src_path=src,
                        dst_path=dst,
                        dst_exists=dst_exists,
                        needs_update=needs_update,
                        is_dir=False,
                    )
                )
        return gaps


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def export_skills_to_pi(
    gaps: list[PiArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    selected: list[str] | None = None,
) -> PiExportResult:
    """Materialise CC skill directories into ~/.pi/agent/skills/."""
    return _materialize_pi(gaps, dry_run=dry_run, overwrite_existing=overwrite_existing, selected=selected)


def export_agents_to_pi(
    gaps: list[PiArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    selected: list[str] | None = None,
) -> PiExportResult:
    """Materialise CC agents as individual Pi skills (~/.pi/agent/skills/)."""
    return _materialize_pi(gaps, dry_run=dry_run, overwrite_existing=overwrite_existing, selected=selected)


def export_commands_to_pi(
    gaps: list[PiArtifactGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    selected: list[str] | None = None,
) -> PiExportResult:
    """Materialise CC commands as Pi prompt templates (~/.pi/agent/prompts/)."""
    return _materialize_pi(gaps, dry_run=dry_run, overwrite_existing=overwrite_existing, selected=selected)


def _materialize_pi(
    gaps: list[PiArtifactGap],
    *,
    dry_run: bool,
    overwrite_existing: bool,
    selected: list[str] | None,
) -> PiExportResult:
    result = PiExportResult()

    if selected is not None:
        selected_set = set(selected)
        gaps = [g for g in gaps if g.name in selected_set]

    if not gaps:
        return result

    # All gaps from a single export share one target directory.
    target_dir = gaps[0].dst_path.parent
    if not target_dir.is_dir():
        if not dry_run:
            ensure_dir(target_dir)
        result.target_dir_created = True

    for gap in gaps:
        if gap.dst_exists and not overwrite_existing:
            result.skipped.append(gap.name)
            continue

        if not dry_run:
            try:
                # safe_copy handles both files and directories atomically and
                # refuses symlinks (defence-in-depth against link-following).
                safe_copy(gap.src_path, gap.dst_path)
            except (OSError, ValueError) as exc:
                result.errors[gap.name] = f"Copy error: {exc}"
                continue

        if gap.dst_exists and gap.needs_update:
            result.updated.append(gap.name)
        else:
            result.created.append(gap.name)

    return result
