# SCCS Minimal TOML Emitter (Codex agent files)
#
# Hand-rolled, dependency-free TOML writer for the ONE narrow document shape
# SCCS emits: an OpenAI Codex agent file (~/.codex/agents/<name>.toml) with a
# handful of short string fields plus one arbitrary Markdown body
# (developer_instructions). We deliberately do NOT add a tomli-w runtime
# dependency for this (mirrors convert/frontmatter.py, which avoids
# python-frontmatter for the same reason); the emitted documents are
# round-trip-verified against a real TOML parser in the test suite.
#
# Only strings are supported — the Codex agent shape needs nothing else.

from __future__ import annotations

# Characters that must be escaped inside a single-line TOML basic string.
_BASIC_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def toml_basic_string(value: str) -> str:
    """Render ``value`` as a single-line TOML basic string ("...")."""
    out: list[str] = []
    for ch in value:
        mapped = _BASIC_ESCAPES.get(ch)
        if mapped is not None:
            out.append(mapped)
        elif ord(ch) < 0x20 or ch == "\x7f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _literal_multiline_safe(value: str) -> bool:
    """True when ``value`` can go into a '''...''' literal block unescaped.

    TOML multi-line literal strings allow any content except a run of three
    single quotes and control characters other than tab/newline (CRLF is only
    valid as part of a newline — a lone CR is not, so we reject CR entirely
    and let the escaped fallback handle it).
    """
    if "'''" in value:
        return False
    for ch in value:
        if ch in ("\n", "\t"):
            continue
        if ord(ch) < 0x20 or ch == "\x7f":
            return False
    return True


def toml_multiline_string(value: str) -> str:
    """Render ``value`` as a TOML multi-line string block.

    Prefers a literal '''...''' block (zero escaping — the Markdown body stays
    byte-identical and human-readable). Falls back to an escaped multi-line
    basic string only when the content itself contains a ''' run or a control
    character literals cannot carry.

    The value is normalised to end with exactly one newline so the closing
    delimiter sits on its own line (TOML trims the newline right after the
    opening delimiter, so the round-tripped value equals the normalised input).
    """
    normalized = value.rstrip("\n") + "\n" if value else ""
    if not normalized:
        return "''"

    if _literal_multiline_safe(normalized):
        return f"'''\n{normalized}'''"

    # Escaped fallback: multi-line basic string. Literal newlines are allowed;
    # backslashes, quotes and remaining control chars must be escaped.
    out: list[str] = []
    for ch in normalized:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch in ("\n", "\t"):
            out.append(ch)
        elif ord(ch) < 0x20 or ch == "\x7f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"""\n' + "".join(out) + '"""'


def render_codex_agent_toml(
    name: str,
    description: str,
    developer_instructions: str,
    *,
    model: str | None = None,
    model_reasoning_effort: str | None = None,
    sandbox_mode: str | None = None,
) -> str:
    """Render a complete Codex agent TOML document.

    Field order matches the Codex docs examples: identity first, tuning knobs
    next, the (long) developer_instructions block last.
    """
    lines = [
        f"name = {toml_basic_string(name)}",
        f"description = {toml_basic_string(description)}",
    ]
    if model is not None:
        lines.append(f"model = {toml_basic_string(model)}")
    if model_reasoning_effort is not None:
        lines.append(f"model_reasoning_effort = {toml_basic_string(model_reasoning_effort)}")
    if sandbox_mode is not None:
        lines.append(f"sandbox_mode = {toml_basic_string(sandbox_mode)}")
    lines.append(f"developer_instructions = {toml_multiline_string(developer_instructions)}")
    return "\n".join(lines) + "\n"
