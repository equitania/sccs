# SCCS Doctor — GSD scope-boundary auto-patch
#
# The GSD ("Get-Shit-Done") framework is delivered verbatim by `npx
# @opengsd/gsd-core`, which writes gsd-* skills/agents/commands straight into
# ~/.claude/. Several of those prompts run unbounded filesystem scans
# (`find .`, `grep -r <relpath>`) that are NOT pinned to the git project root —
# the same bug class that made `/project-audit` scan sibling projects in a
# monorepo. We have no upstream access, so we patch the files *after* every
# install/update, before they are used.
#
# Strategy: PREPEND a prose SCOPE BOUNDARY directive after the frontmatter.
# GSD prompts are LLM-driven, so the directive governs behaviour exactly like
# the sanctioned project-audit fix — and, unlike rewriting the vendor's own
# shell snippets, it can never break a command whose isolated execution would
# expand an undefined `$PROJECT_ROOT`.
#
# Idempotent: a sentinel marker guards against double-patching within an
# unchanged file; a GSD reinstall overwrites the file (removing the sentinel),
# so the next doctor run re-applies the directive.

from __future__ import annotations

import logging
import re
import stat
from collections.abc import Callable
from pathlib import Path

from sccs.convert.frontmatter import parse_frontmatter, render_frontmatter
from sccs.utils.paths import atomic_write, expand_path

logger = logging.getLogger(__name__)

# Versioned idempotency marker. Bump the version suffix if the directive text
# changes in a way that should trigger re-patching; the presence check below
# matches the version-agnostic prefix so any prior marker still blocks a
# duplicate insert.
SCOPE_BOUNDARY_SENTINEL = "<!-- sccs:scope-boundary v1 -->"
_SENTINEL_PREFIX = "sccs:scope-boundary"

# Directories GSD writes into that hold LLM *prompts* (skills/agents/commands).
# `hooks/` is deliberately excluded — those are executable scripts, not prompts.
_SKILLS_DIRNAME = "skills"
_HOOKS_DIRNAME = "hooks"

# Unbounded-scan detection — mirrors the check-skills.sh "Check 9" heuristic so
# the shell audit and this Python patcher stay in agreement:
#   * `find .` / `find ~` / `find $HOME`
#   * `grep -r…` whose target is a bare `.`, `~`, `$HOME`, or a relative `src`.
_FIND_RE = re.compile(r'(?:^|[\s`])find\s+(?:\.|~|\$HOME|"\$HOME")(?:\s|$)')
_GREP_RE = re.compile(r'grep\s+-[A-Za-z]*r[A-Za-z]*\s.*\s(?:\.|~|\$HOME|"\$HOME"|src|src/|"src"|"src/")(?:\s|\||$)')


def has_unbounded_scan(text: str) -> bool:
    """True if any non-comment line runs an unbounded `find`/`grep -r` scan.

    Shell-comment lines (first non-space char ``#``) are ignored so a commented
    example never counts.
    """
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if _FIND_RE.search(line) or _GREP_RE.search(line):
            return True
    return False


def build_directive() -> str:
    """The SCOPE BOUNDARY prose block prepended to an offending GSD prompt.

    Contains no ``find .`` / ``grep -r`` token itself, so it never re-triggers
    :func:`has_unbounded_scan` on an already-patched file.
    """
    return (
        f"{SCOPE_BOUNDARY_SENTINEL}\n"
        "> **SCOPE BOUNDARY (auto-added by sccs doctor — do not remove)**\n"
        ">\n"
        "> This prompt runs inside a single project. Before any filesystem scan,\n"
        "> pin the project root and stay within it:\n"
        ">\n"
        "> ```\n"
        "> PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)\n"
        "> ```\n"
        ">\n"
        '> Confine every filesystem scan (find, grep, Read, Glob, Task) to "$PROJECT_ROOT".\n'
        "> Never scan sibling, parent, or unrelated directories."
    )


def patch_file(path: Path) -> bool:
    """Prepend the SCOPE BOUNDARY directive to ``path`` if it needs it.

    Returns True if the file was rewritten. Idempotent and conservative:
      * already carries the sentinel  → no-op (False)
      * has no unbounded scan          → no-op (False), leaving clean files alone
    The original file permissions are preserved (``atomic_write`` would otherwise
    yield the mkstemp default 0600, making a public 0644 prompt private).
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    if _SENTINEL_PREFIX in content:
        return False
    if not has_unbounded_scan(content):
        return False

    meta, body = parse_frontmatter(content)
    new_body = f"{build_directive()}\n\n{body.lstrip(chr(10))}"
    new_content = render_frontmatter(meta, new_body)
    if not new_content.endswith("\n"):
        new_content += "\n"

    try:
        orig_mode: int | None = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        orig_mode = None

    atomic_write(path, new_content, mode=orig_mode)
    logger.info("doctor scope-patched %s", path)
    return True


def patch_gsd_scope(
    scan_dirs: list[str],
    glob: str = "gsd-*",
    *,
    print_fn: Callable[[str], None] | None = None,
) -> int:
    """Patch every offending gsd-* prompt across ``scan_dirs``; return the count.

    ``scan_dirs`` are the tool's ``managed_scan_dirs`` (e.g. ``~/.claude/skills``).
    Skills are directories (``gsd-*/SKILL.md``); agents/commands are flat
    ``gsd-*.md`` files. ``hooks/`` is skipped (scripts, not prompts).
    """
    patched = 0
    for raw in scan_dirs:
        base = expand_path(raw)
        if base.name == _HOOKS_DIRNAME or not base.is_dir():
            continue
        if base.name == _SKILLS_DIRNAME:
            candidates = sorted(base.glob(f"{glob}/SKILL.md"))
        else:
            candidates = sorted(base.glob(f"{glob}.md"))
        for f in candidates:
            if patch_file(f):
                patched += 1
                if print_fn is not None:
                    print_fn(f"  scope-boundary added → {f}")
    return patched
