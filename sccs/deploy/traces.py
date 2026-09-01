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
#
# ~/.config/sccs/ is deliberately NOT hand-listed here: it accumulates state
# files (sync state, doctor state, logs, backups, profile parking, .bak
# copies) that would rot this list the moment a new one is added. It is
# enumerated at runtime instead — see _sccs_state_targets().
_TRACE_SPEC: tuple[tuple[str, str, str], ...] = (
    (".claude/projects", "session transcripts and project memory", "tree"),
    (".claude/plans", "saved plans", "tree"),
    (".claude/todos", "todo lists", "tree"),
    (".claude/shell-snapshots", "shell snapshots", "tree"),
    (".claude.json", "prompt history inside ~/.claude.json", "json_history"),
)

# Relative to home. Kept alive on purpose: `sccs deploy revoke` still needs
# the receipt and removes it last, so it must never show up as a trace.
_SCCS_STATE_DIR = ".config/sccs"
_SCCS_RECEIPT_NAME = ".deploy_receipt.yaml"


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


def _sccs_state_targets(base: Path) -> list[TraceTarget]:
    """Enumerate ~/.config/sccs/ at runtime, one target per entry.

    The receipt is excluded by name — `sccs deploy revoke` still needs it
    and removes it last. Everything else in that directory is a trace: it
    is SCCS's own record of what was synchronised, and a hand-maintained
    filename list would rot the moment a new state file is added.
    """
    state_dir = base / _SCCS_STATE_DIR
    targets: list[TraceTarget] = []
    if not state_dir.is_dir():
        return targets

    for entry in sorted(state_dir.iterdir()):
        if entry.name == _SCCS_RECEIPT_NAME:
            continue
        kind = "tree" if entry.is_dir() else "file"
        try:
            size = _tree_size(entry) if kind == "tree" else entry.stat().st_size
        except OSError:
            size = 0
        targets.append(
            TraceTarget(
                path=entry,
                label=f"SCCS state ({entry.name})",
                kind=kind,
                exists=True,
                size_bytes=size,
            )
        )

    return targets


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

    targets.extend(_sccs_state_targets(base))

    return targets


def strip_claude_json_history(path: Path, *, dry_run: bool = False) -> bool:
    """Remove `history` and `projects[*].history` from ~/.claude.json.

    The file is trimmed, never deleted: it also carries the host user's auth
    and onboarding state, and removing it would cause damage nobody asked
    for.

    Returns:
        True if there was history to remove (also in dry-run), else False.
        A malformed file is left untouched and reported as False.

    A symlinked ``path`` is followed only when its resolved target stays
    under the same home directory (``path``'s parent). ``atomic_write`` ends
    in ``os.replace``, which replaces the *link* rather than the file it
    points to — silently leaving the real file's history untouched while
    reporting success. Resolving first and writing to the resolved target
    closes that gap; a target outside home is refused outright rather than
    followed off the machine's home tree.
    """
    if not path.exists():
        return False

    home_dir = path.parent.resolve()
    target = path.resolve()

    if path.is_symlink():
        try:
            target.relative_to(home_dir)
        except ValueError:
            logger.warning(
                "Leaving %s untouched — it is a symlink to %s, outside home (%s)",
                path,
                target,
                home_dir,
            )
            return False

    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
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

    atomic_write(target, json.dumps(doc, indent=2) + "\n", mode=0o600)
    logger.info("Stripped prompt history from %s", target)
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
            elif target.kind == "tree":
                if dry_run:
                    continue
                shutil.rmtree(target.path)
                logger.info("Removed trace tree: %s", target.path)
            elif target.kind == "file":
                if dry_run:
                    continue
                target.path.unlink()
                logger.info("Removed trace file: %s", target.path)
            else:
                errors.append(f"{target.path}: unknown trace kind {target.kind!r}")
        except OSError as e:
            errors.append(f"{target.path}: {e}")

    return errors
