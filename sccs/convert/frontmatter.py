# SCCS Frontmatter Helpers
#
# Minimal YAML-frontmatter parser/renderer used by the Claude -> OpenCode
# converters. Deliberately dependency-free beyond PyYAML (already a hard
# dependency) — we do NOT pull in python-frontmatter for this.
#
# A document looks like:
#
#     ---
#     key: value
#     ---
#     body text...
#
# parse_frontmatter() splits it into (metadata dict, body str); render_frontmatter()
# is the inverse. Round-trips are stable for the field set we emit.

from __future__ import annotations

from typing import NamedTuple

import yaml

# The fence that opens and closes a frontmatter block.
_FENCE = "---"


class FrontmatterParse(NamedTuple):
    """Result of :func:`parse_frontmatter_ex`.

    ``error`` is None on success (including "there simply is no frontmatter").
    It carries a message only when a *terminated* block was found whose YAML
    could not be parsed — the one case where "no metadata" is a failure rather
    than a fact about the document.
    """

    metadata: dict
    body: str
    error: str | None


# Lines the frontmatter block sits below in the file: the opening fence is
# always line 1 (a hard rule of this parser), so a YAML mark inside the block
# is one line further down in the document than in the block we handed PyYAML.
_FENCE_LINE_OFFSET = 1


def _yaml_error_detail(exc: yaml.YAMLError) -> str:
    """Condense a PyYAML error into one actionable line.

    A ``MarkedYAMLError`` carries the offending construct (``problem``) and its
    position (``problem_mark``) separately; its ``str()`` spreads them over four
    lines with a source excerpt. We want "what and where" on one line, because
    the position is what lets the user go fix the file — reported in FILE
    coordinates, not block-relative ones, so it matches what the editor shows.
    Anything else falls back to the exception's first line.
    """
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    if problem and mark is not None:
        # PyYAML marks are 0-based; humans and editors count from 1.
        line = mark.line + 1 + _FENCE_LINE_OFFSET
        return f"{problem} (line {line}, column {mark.column + 1})"
    if problem:
        return str(problem)
    text = str(exc).strip()
    return text.splitlines()[0].strip() if text else exc.__class__.__name__


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split ``content`` into (metadata, body).

    Rules:
    - A frontmatter block must start on the very first line with ``---`` and be
      closed by a second ``---`` on its own line.
    - If there is no leading fence, the whole input is treated as body and the
      metadata is an empty dict.
    - A malformed/unterminated block is treated as "no frontmatter" (body only)
      so we never raise on hand-edited files.

    NOTE ON THE BROKEN-YAML CASE: the whole input — fences included — comes back
    as the body. That is deliberate and load-bearing for the parse/render PAIR
    in ``doctor/scope_patch.py``: ``render_frontmatter({}, body)`` returns the
    body unchanged, so a gsd-* prompt with unparsable frontmatter is patched
    without losing its frontmatter. Callers that BUILD a new document (the
    Codex/OpenCode converters, which emit their own frontmatter) must use
    :func:`parse_frontmatter_ex` instead — prepending a header to a body that
    still carries the original block yields two stacked frontmatter blocks.

    Returns:
        (metadata, body). ``metadata`` is always a dict (never None).
    """
    result = parse_frontmatter_ex(content)
    if result.error is not None:
        # Preserve the historical contract: broken YAML means "no frontmatter",
        # and the block stays in the body so nothing can be dropped.
        return {}, content
    return result.metadata, result.body


def parse_frontmatter_ex(content: str) -> FrontmatterParse:
    """Split ``content`` into (metadata, body, error).

    Same parsing rules as :func:`parse_frontmatter`, with one difference that
    matters to converters: when a *terminated* block is found but its YAML does
    not parse, the block is still stripped from the body and ``error`` explains
    why no metadata came back. The structure is unambiguous in that case (both
    fences are present) — only the content is unreadable, and leaving it in the
    body makes the caller emit a document with two frontmatter blocks.

    A block whose YAML parses to something that is not a mapping (a list, or a
    lone ``# comment`` that YAML reads as None) is NOT treated as an error: that
    is how a Markdown document opening with a horizontal rule looks, and
    stripping it would delete real content. Such input comes back unchanged with
    ``error=None``, exactly as before.

    Returns:
        FrontmatterParse(metadata, body, error). ``metadata`` is always a dict.
    """
    if not content.startswith(_FENCE):
        return FrontmatterParse({}, content, None)

    lines = content.splitlines()
    # lines[0] is the opening fence (possibly "---" with trailing spaces).
    if lines[0].strip() != _FENCE:
        return FrontmatterParse({}, content, None)

    # Find the closing fence.
    closing_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FENCE:
            closing_idx = idx
            break

    if closing_idx is None:
        # Unterminated block — the structure is NOT a frontmatter block at all,
        # so the whole thing is body. No error: this is a fact, not a failure.
        return FrontmatterParse({}, content, None)

    yaml_block = "\n".join(lines[1:closing_idx])
    body = "\n".join(lines[closing_idx + 1 :])

    try:
        meta = yaml.safe_load(yaml_block) if yaml_block.strip() else {}
    except yaml.YAMLError as exc:
        # Terminated block, unreadable content: strip it and say why.
        return FrontmatterParse({}, body, f"invalid YAML in frontmatter: {_yaml_error_detail(exc)}")

    if not isinstance(meta, dict):
        # e.g. a YAML scalar/list in the block, or a Markdown horizontal rule
        # whose "block" is a comment. Not frontmatter for us — and NOT an error,
        # because stripping it could delete authored content.
        return FrontmatterParse({}, content, None)

    return FrontmatterParse(meta, body, None)


def render_frontmatter(metadata: dict, body: str) -> str:
    """Recombine ``metadata`` and ``body`` into a frontmatter document.

    If ``metadata`` is empty, the body is returned unchanged (no empty fence).
    The YAML is emitted with stable key order (``sort_keys=False``) and unicode
    preserved, matching how SCCS writes its other YAML.
    """
    if not metadata:
        return body

    yaml_block = yaml.dump(
        metadata,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip("\n")

    # Ensure the body is separated from the closing fence by a newline and that
    # the document ends with exactly one trailing newline.
    body_clean = body.lstrip("\n")
    document = f"{_FENCE}\n{yaml_block}\n{_FENCE}\n{body_clean}"
    if not document.endswith("\n"):
        document += "\n"
    return document
