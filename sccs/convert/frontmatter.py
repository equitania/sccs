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

import yaml

# The fence that opens and closes a frontmatter block.
_FENCE = "---"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split ``content`` into (metadata, body).

    Rules:
    - A frontmatter block must start on the very first line with ``---`` and be
      closed by a second ``---`` on its own line.
    - If there is no leading fence, the whole input is treated as body and the
      metadata is an empty dict.
    - A malformed/unterminated block is treated as "no frontmatter" (body only)
      so we never raise on hand-edited files.

    Returns:
        (metadata, body). ``metadata`` is always a dict (never None).
    """
    # Normalise leading BOM / stray whitespace-only prefix is intentionally NOT
    # stripped — the fence must be the first thing in the file.
    if not content.startswith(_FENCE):
        return {}, content

    lines = content.splitlines()
    # lines[0] is the opening fence (possibly "---" with trailing spaces).
    if lines[0].strip() != _FENCE:
        return {}, content

    # Find the closing fence.
    closing_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FENCE:
            closing_idx = idx
            break

    if closing_idx is None:
        # Unterminated block — treat the whole thing as body.
        return {}, content

    yaml_block = "\n".join(lines[1:closing_idx])
    body_lines = lines[closing_idx + 1 :]
    # Preserve a single trailing newline convention for the body.
    body = "\n".join(body_lines)

    try:
        meta = yaml.safe_load(yaml_block) if yaml_block.strip() else {}
    except yaml.YAMLError:
        # Broken YAML in the block: don't lose the content, return body-only.
        return {}, content

    if not isinstance(meta, dict):
        # e.g. a YAML scalar/list in the block — not valid frontmatter for us.
        return {}, content

    return meta, body


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
