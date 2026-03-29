# SCCS Antigravity Migration
# Migrate Claude Code skills to Antigravity IDE prompts

from __future__ import annotations

from dataclasses import dataclass, field

from sccs.integrations.detectors import AntigravitySkillGap
from sccs.utils.paths import atomic_write, ensure_dir


@dataclass
class AntigravityMigrationResult:
    """Result of skill-to-prompt migration."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    prompts_dir_created: bool = False


def migrate_skills_to_prompts(
    gaps: list[AntigravitySkillGap],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = True,
    selected: list[str] | None = None,
) -> AntigravityMigrationResult:
    """
    Migrate Claude Code SKILL.md files to Antigravity prompt files.

    Args:
        gaps: List of skill gaps from AntigravityDetector.
        dry_run: Preview only, no file writes.
        overwrite_existing: Update prompts that already exist but differ.
        selected: Only migrate these skill names (None = all gaps).

    Returns:
        Migration result with created/updated/skipped/error counts.
    """
    result = AntigravityMigrationResult()

    # Filter to selected skills if specified
    if selected is not None:
        selected_set = set(selected)
        gaps = [g for g in gaps if g.name in selected_set]

    if not gaps:
        return result

    # Ensure prompts directory exists
    prompts_dir = gaps[0].prompt_path.parent
    if not prompts_dir.is_dir():
        if not dry_run:
            ensure_dir(prompts_dir)
        result.prompts_dir_created = True

    for gap in gaps:
        # Skip existing prompts if overwrite not requested
        if gap.prompt_exists and not overwrite_existing:
            result.skipped.append(gap.name)
            continue

        try:
            content = gap.skill_md_path.read_text(encoding="utf-8")
        except OSError as e:
            result.errors[gap.name] = f"Read error: {e}"
            continue

        if not dry_run:
            try:
                atomic_write(gap.prompt_path, content)
            except OSError as e:
                result.errors[gap.name] = f"Write error: {e}"
                continue

        if gap.prompt_exists and gap.needs_update:
            result.updated.append(gap.name)
        else:
            result.created.append(gap.name)

    return result
