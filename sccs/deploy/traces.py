# What a working session leaves behind on a foreign host.
#
# The actual leak is not the skill directory — it is the transcript that
# quotes the skill verbatim. Deleting the skills while leaving the
# transcript protects nothing.

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write

logger = get_logger("sccs.deploy")

# (relative path, label, kind)
_TRACE_SPEC: tuple[tuple[str, str, str], ...] = (
    (".claude/projects", "session transcripts and project memory", "tree"),
    (".claude/plans", "saved plans", "tree"),
    (".claude/todos", "todo lists", "tree"),
    (".claude/shell-snapshots", "shell snapshots", "tree"),
    (".config/sccs/config.yaml", "SCCS config (repository path, category layout)", "file"),
    (".claude.json", "prompt history inside ~/.claude.json", "json_history"),
)


@dataclass
class TraceTarget:
    """One location that accumulates traces of our work."""

    path: Path
    label: str
    kind: str
    exists: bool = False
    size_bytes: int = 0


def _tree_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def enumerate_traces(home: Path | None = None) -> list[TraceTarget]:
    """List the trace locations, marking which of them exist."""
    base = home or Path.home()
    targets: list[TraceTarget] = []

    for rel, label, kind in _TRACE_SPEC:
        path = base / rel
        exists = path.exists()
        size = 0
        if exists:
            try:
                size = _tree_size(path) if path.is_dir() else path.stat().st_size
            except OSError:
                size = 0
        targets.append(TraceTarget(path=path, label=label, kind=kind, exists=exists, size_bytes=size))

    return targets


def strip_claude_json_history(path: Path, *, dry_run: bool = False) -> bool:
    """Remove `history` and `projects[*].history` from ~/.claude.json.

    The file is trimmed, never deleted: it also carries the host user's auth
    and onboarding state, and removing it would cause damage nobody asked
    for.

    Returns:
        True if there was history to remove (also in dry-run), else False.
        A malformed file is left untouched and reported as False.
    """
    if not path.exists():
        return False

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Leaving %s untouched — cannot parse it: %s", path, e)
        return False

    if not isinstance(doc, dict):
        return False

    changed = doc.pop("history", None) is not None
    projects = doc.get("projects")
    if isinstance(projects, dict):
        for project in projects.values():
            if isinstance(project, dict) and project.pop("history", None) is not None:
                changed = True

    if not changed or dry_run:
        return changed

    atomic_write(path, json.dumps(doc, indent=2) + "\n", mode=0o600)
    logger.info("Stripped prompt history from %s", path)
    return True


def remove_traces(targets: list[TraceTarget], *, dry_run: bool = False) -> list[str]:
    """Remove the given trace targets. Returns error strings, empty on success."""
    errors: list[str] = []

    for target in targets:
        if not target.path.exists():
            continue
        try:
            if target.kind == "json_history":
                strip_claude_json_history(target.path, dry_run=dry_run)
            elif dry_run:
                continue
            elif target.kind == "tree":
                shutil.rmtree(target.path)
                logger.info("Removed trace tree: %s", target.path)
            else:
                target.path.unlink()
                logger.info("Removed trace file: %s", target.path)
        except OSError as e:
            errors.append(f"{target.path}: {e}")

    return errors
