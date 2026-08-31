# SCCS — source-side skill frontmatter limits
#
# Pi, Codex and Claude Code all read the same agentskills.io SKILL.md format,
# and all three silently DROP a skill whose frontmatter breaks the shared
# limits. Both the Pi and the Codex export copy skills verbatim, so a violation
# in ~/.claude/skills/ reaches the target unchanged: the export reports success
# while the skill never loads on the other side. That is a false success, and
# checking the SOURCE is the only place where it can be named — the copy is
# byte-correct, only the content is unacceptable to the reader.
#
# Real driver: Pi 0.84.4 rejected 12 skills for an over-long description and 2
# for frontmatter that YAML could not parse. `sccs integrations pi export-all`
# had reported all of them as successfully written.

from __future__ import annotations

from pathlib import Path

from sccs.convert.frontmatter import parse_frontmatter_ex
from sccs.utils.paths import matches_any_pattern

# Private / disabled by convention — same rule the two exports apply.
_SKIP_PATTERNS = ("_", ".")

# Both limits are the agentskills.io values, enforced identically by Pi
# (MAX_NAME_LENGTH / MAX_DESCRIPTION_LENGTH in its skill loader) and Claude
# Code. Codex reads the same format.
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


def check_skill_text(text: str) -> list[str]:
    """Name every reason an agent CLI will refuse to load this SKILL.md.

    Returns an empty list for an acceptable skill. Each entry is a complete
    sentence naming the measured value against the limit, so the reader does
    not have to go and count characters.
    """
    parsed = parse_frontmatter_ex(text)
    if parsed.error:
        return [f"frontmatter is not valid YAML ({parsed.error}) — the target cannot load this skill"]
    if not parsed.metadata:
        return ["no frontmatter block — the target cannot load this skill"]

    problems: list[str] = []

    name = parsed.metadata.get("name")
    if isinstance(name, str) and len(name) > MAX_NAME_LENGTH:
        problems.append(f"name is {len(name)} characters, limit is {MAX_NAME_LENGTH}")

    description = parsed.metadata.get("description")
    if description is None:
        problems.append("frontmatter has no 'description' — the target cannot load this skill")
    elif isinstance(description, str) and len(description) > MAX_DESCRIPTION_LENGTH:
        problems.append(f"description is {len(description)} characters, limit is {MAX_DESCRIPTION_LENGTH}")

    return problems


def check_skill_file(path: Path) -> list[str]:
    """``check_skill_text`` for a SKILL.md on disk.

    An unreadable file is reported rather than raised: the export has its own
    error path for that, and a limit check must never be the thing that stops a
    run.
    """
    try:
        return check_skill_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return [f"could not read {path.name}: {exc}"]


def scan_claude_skills(cc_skills_dir: Path, *, exclude_patterns: list[str] | None = None) -> dict[str, list[str]]:
    """Limit check across ``~/.claude/skills/``, keyed by skill name.

    Only offending skills appear in the result. This runs independently of gap
    detection on purpose: once an offending skill has been exported it is in
    sync, produces no gap, and would never be mentioned again — while the
    target still refuses to load it.
    """
    violations: dict[str, list[str]] = {}
    if not cc_skills_dir.is_dir():
        return violations

    for skill_dir in sorted(cc_skills_dir.iterdir()):
        name = skill_dir.name
        if not skill_dir.is_dir() or skill_dir.is_symlink() or name.startswith(_SKIP_PATTERNS):
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        if exclude_patterns and matches_any_pattern(name, exclude_patterns):
            continue
        problems = check_skill_file(skill_md)
        if problems:
            violations[name] = problems
    return violations
