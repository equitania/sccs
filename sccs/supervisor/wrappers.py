"""Scan Claude agents and recognise the thin wrapper shapes (agy, opencode, codex).

Recognition looks only inside the first fenced ``bash`` block of the agent body.
Nothing here writes; edits happen textually in a later step, never via re-rendered
frontmatter.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sccs.convert.frontmatter import parse_frontmatter_ex
from sccs.supervisor.tools import codex_default_model

if TYPE_CHECKING:
    from sccs.config.schema import SccsConfig

TemplateId = Literal["agy", "opencode", "codex"]
Managed = Literal["new", "adopted", "no"]

_TEMPLATES: tuple[str, ...] = ("agy", "opencode", "codex")
_CODEX_PLUGIN_KEY = "codex@openai-codex"
_BASH_BLOCK = re.compile(r"```bash[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL)
_MODEL_FLAG: dict[str, str] = {"agy": "--model", "opencode": "-m", "codex": "-m"}


@dataclass(frozen=True)
class AgentInfo:
    name: str
    path: Path | None
    source: Literal["user", "plugin"]
    template: TemplateId | None
    managed: Managed
    cli_model: str | None
    hash_ok: bool | None
    excluded: bool


def _first_bash_block(body: str) -> tuple[int, str] | None:
    """Offset (in ``body``) and text of the first ```bash fenced block."""
    match = _BASH_BLOCK.search(body)
    return (match.start(1), match.group(1)) if match else None


def detect_shape(body: str) -> TemplateId | None:
    """Which read-only wrapper template the body's first bash block matches, if any."""
    block = _first_bash_block(body)
    if block is None:
        return None
    text = block[1]
    if "agy -p" in text and "--mode plan" in text and '--settings "$AGY_RO"' in text:
        return "agy"
    if "opencode run --agent claude-ro" in text:
        return "opencode"
    if "codex exec -s read-only" in text:
        return "codex"
    return None


def find_model_token(body: str, template: TemplateId) -> tuple[int, int] | None:
    """Span (start, end) in ``body`` of the model value in the first bash block."""
    block = _first_bash_block(body)
    if block is None:
        return None
    offset, text = block
    match = re.search(rf"(?<!\S){re.escape(_MODEL_FLAG[template])}[ \t]+(\S+)", text)
    if match is None:
        return None
    return offset + match.start(1), offset + match.end(1)


def find_model_token_in_file_text(text: str, template: TemplateId) -> tuple[int, int] | None:
    """Like :func:`find_model_token`, but on raw file text: skips the frontmatter itself.

    Offsets index into ``text`` (CRLF and any leading BOM untouched), so a caller can
    edit the file in place.
    """
    start = 1 if text.startswith("\ufeff") else 0
    lines = text[start:].splitlines(keepends=True)
    offset = start
    if lines and lines[0].strip() == "---":
        offset += len(lines[0])
        for line in lines[1:]:
            offset += len(line)
            if line.strip() == "---":
                break
        else:
            offset = start  # unterminated: no frontmatter
    span = find_model_token(text[offset:], template)
    return (span[0] + offset, span[1] + offset) if span else None


def body_hash(body: str, template: TemplateId) -> str:
    """sha256 of the body with the model value masked and line endings normalised to LF."""
    span = find_model_token(body, template)
    if span is not None:
        body = body[: span[0]] + "{{MODEL}}" + body[span[1] :]
    normalised = body.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _read_agent(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def _scan_user_agent(path: Path, excluded: bool) -> AgentInfo | None:
    text = _read_agent(path)
    if text is None:
        return None
    parsed = parse_frontmatter_ex(text)
    meta, body = parsed.metadata, parsed.body
    raw_meta = meta.get("sccs")
    sccs_meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    marked = sccs_meta.get("managed") is True
    declared = sccs_meta.get("template")

    template: TemplateId | None = detect_shape(body)
    managed: Managed = "no"
    if marked and declared == "adopted" and sccs_meta.get("shape") in _TEMPLATES:
        template = sccs_meta["shape"]
        managed = "adopted"
    elif marked and declared in _TEMPLATES:
        template = declared
        managed = "new"

    cli_model = None
    if template is not None:
        span = find_model_token(body, template)
        cli_model = body[span[0] : span[1]] if span else None
    hash_ok = None
    if managed != "no" and template is not None:
        hash_ok = sccs_meta.get("hash") == body_hash(body, template)
    return AgentInfo(path.stem, path, "user", template, managed, cli_model, hash_ok, excluded)


def _is_excluded(name: str, config: SccsConfig | None) -> bool:
    if config is None:
        return False
    return name in config.opencode.exclude and name in config.pi.exclude and name in config.codex.exclude


def _plugin_agents(home: Path) -> list[AgentInfo]:
    try:
        data: Any = json.loads((home / ".claude" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        entries = data["plugins"][_CODEX_PLUGIN_KEY]
        install_paths = [Path(e["installPath"]) for e in entries if isinstance(e, dict) and e.get("installPath")]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if not install_paths:
        return []
    codex_model = codex_default_model(home)
    found: list[AgentInfo] = []
    for install in install_paths:
        try:
            files = sorted((install / "agents").glob("*.md"))
        except OSError:
            continue
        for file in files:
            found.append(AgentInfo(f"codex:{file.stem}", file, "plugin", None, "no", codex_model, None, False))
    return found


def scan_agents(home: Path | None = None, config: SccsConfig | None = None) -> list[AgentInfo]:
    """User agents from ``~/.claude/agents`` followed by Codex plugin agents."""
    home = home if home is not None else Path.home()
    if config is None:
        try:
            from sccs.config.loader import load_config

            config = load_config()
        except Exception:  # noqa: BLE001 - no usable config means "no excludes"
            config = None
    agents: list[AgentInfo] = []
    directory = home / ".claude" / "agents"
    try:
        files = sorted(p for p in directory.glob("*.md") if p.is_file())
    except OSError:
        files = []
    for path in files:
        if path.name.startswith(("_", ".")) or path.name.endswith(".local.md"):
            continue
        info = _scan_user_agent(path, _is_excluded(path.stem, config))
        if info is not None:
            agents.append(info)
    agents.extend(_plugin_agents(home))
    return agents
