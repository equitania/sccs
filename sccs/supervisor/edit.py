"""Change the model of a managed wrapper agent, or adopt a hand-written wrapper.

Both operations are textual: only the model value, the stored hash value or the
inserted marker lines change. Nothing re-dumps YAML, and BOM and line endings of the
file are kept byte for byte.
"""

from __future__ import annotations

import re
from pathlib import Path

from sccs.config.loader import add_supervisor_excludes
from sccs.convert.frontmatter import parse_frontmatter_ex
from sccs.supervisor import SupervisorError
from sccs.supervisor.models import ModelCheck, check_model, list_models
from sccs.supervisor.tools import ToolId
from sccs.supervisor.wrappers import AgentInfo, TemplateId, body_hash, find_model_token_in_file_text, scan_agents
from sccs.utils.paths import atomic_write

_TOOL_FOR_TEMPLATE: dict[str, ToolId] = {"agy": "agy", "opencode": "opencode", "codex": "codex"}
_HASH_LINE = re.compile(r"^([ \t]+hash:[ \t]*)(\S+)", re.MULTILINE)


def _read_raw(path: Path) -> str:
    """File text with BOM and line endings untouched (the BOM stays as U+FEFF)."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_raw(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777
    atomic_write(path, text.encode("utf-8"), mode=mode)


def _frontmatter_close(text: str) -> tuple[int, str] | None:
    """Offset where the closing ``---`` line starts, and the file's line ending."""
    start = 1 if text.startswith("﻿") else 0
    lines = text[start:].splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    eol = "\r\n" if lines[0].endswith("\r\n") else "\n"
    offset = start + len(lines[0])
    for line in lines[1:]:
        if line.strip() == "---":
            return offset, eol
        offset += len(line)
    return None


def _find_agent(name: str, home: Path | None) -> AgentInfo:
    for info in scan_agents(home):
        if info.name == name:
            return info
    raise SupervisorError(f"Agent '{name}' not found.")


def _body_of(text: str) -> str:
    return parse_frontmatter_ex(text.removeprefix("﻿")).body


def set_model(name: str, model: str, home: Path | None = None) -> ModelCheck:
    """Replace the model value in a managed user agent's command; refresh the hash only if it matched."""
    info = _find_agent(name, home)
    if info.source != "user":
        raise SupervisorError(f"'{name}' is a plugin agent and is never edited.")
    if info.managed == "no" or info.template is None or info.path is None:
        raise SupervisorError(f"'{name}' is not managed by sccs; adopt it first.")
    template: TemplateId = info.template
    check = check_model(template, model, list_models(_TOOL_FOR_TEMPLATE[template], home))
    if not check.ok:
        raise SupervisorError(f"Model '{model}' refused: {check.reason}")

    text = _read_raw(info.path)
    span = find_model_token_in_file_text(text, template)
    if span is None:
        raise SupervisorError(f"No model value found in the command of '{name}'.")
    hash_matched = info.hash_ok is True
    new_text = text[: span[0]] + model + text[span[1] :]
    if hash_matched:
        new_text = _replace_stored_hash(new_text, body_hash(_body_of(new_text), template))
    _write_raw(info.path, new_text)
    return check


def _replace_stored_hash(text: str, new_hash: str) -> str:
    close = _frontmatter_close(text)
    if close is None:
        raise SupervisorError("Frontmatter not found; cannot update the stored hash.")
    head = text[: close[0]]
    sccs_at = re.search(r"^sccs:[ \t]*\r?$", head, re.MULTILINE)
    if sccs_at is None:
        raise SupervisorError("No sccs marker block found; cannot update the stored hash.")
    match = _HASH_LINE.search(head, sccs_at.end())
    if match is None:
        raise SupervisorError("No stored hash found in the sccs marker block.")
    return text[: match.start(2)] + new_hash + text[match.end(2) :]


def adopt(name: str, home: Path | None = None, config_path: Path | None = None) -> bool:
    """Mark a hand-written wrapper as managed (``template: adopted``); False if it already is."""
    info = _find_agent(name, home)
    if info.source != "user" or info.path is None:
        raise SupervisorError(f"'{name}' is a plugin agent and is never edited.")
    if info.managed != "no":
        return False
    if info.template is None:
        raise SupervisorError(f"'{name}' matches no known wrapper shape (agy, opencode, codex); cannot adopt.")
    text = _read_raw(info.path)
    close = _frontmatter_close(text)
    if close is None:
        raise SupervisorError(f"'{name}' has no frontmatter; cannot adopt.")
    offset, eol = close
    digest = body_hash(_body_of(text), info.template)
    marker = eol.join(
        [
            "sccs:",
            "  managed: true",
            "  template: adopted",
            f"  shape: {info.template}",
            "  template_version: 1",
            f"  hash: {digest}",
        ]
    )
    _write_raw(info.path, text[:offset] + marker + eol + text[offset:])
    add_supervisor_excludes(name, config_path)
    return True
