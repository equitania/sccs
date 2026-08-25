# SCCS Claude -> OpenAI Codex Hook Conversion Rules
#
# Pure, I/O-free translation of a Claude Code `hooks` block (from
# ~/.claude/settings.json) into the shape Codex reads from ~/.codex/hooks.json.
#
# The two formats are structurally near-identical:
#
#     {"hooks": {"<Event>": [{"matcher": "<regex>",
#                             "hooks": [{"type": "command", "command": "..."}]}]}}
#
# so this module is mostly a filter, not a rewriter. Three things are filtered:
#
#   1. Events Codex does not have (Claude has 19, Codex 11, 10 names overlap).
#   2. Handler types Codex does not have (Claude: command/http/prompt/agent;
#      Codex: command/mcp_tool — only `command` is portable).
#   3. Handler fields Codex does not read.
#
# Matchers are NOT rewritten (owner's decision): a matcher naming tools Codex
# cannot fire on is exported verbatim and warned about, so the entry starts
# working by itself once Codex widens its tool coverage.

from __future__ import annotations

import re

# Event names that exist in BOTH Claude Code and Codex. Anything else in a
# Claude settings.json is dropped — Codex would never fire it.
CODEX_HOOK_EVENTS: frozenset[str] = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "PermissionRequest",
        "PreCompact",
        "SessionStart",
        "SessionEnd",
        "SubagentStart",
        "SubagentStop",
        "UserPromptSubmit",
        "Stop",
    }
)

# Handler fields Codex reads on a command hook. `timeout` is seconds on both
# sides. Codex-only fields (async, statusMessage) have no Claude source, and
# Claude-only fields (continueOnBlock, model, ...) mean nothing to Codex.
_PORTABLE_HANDLER_FIELDS = ("type", "command", "timeout")

# Claude tool names with no Codex equivalent. Codex fires tool events for Bash,
# apply_patch (matcher aliases Edit/Write) and MCP tool names only, so a matcher
# alternative from this set can never match there. Lower-cased for comparison.
UNREACHABLE_TOOL_TOKENS: frozenset[str] = frozenset(
    {
        "read",
        "grep",
        "glob",
        "task",
        "agent",
        "skill",
        "webfetch",
        "websearch",
        "todowrite",
        "todoread",
        "notebookedit",
        "multiedit",
        "bashoutput",
        "killshell",
        "slashcommand",
        "exitplanmode",
        "askuserquestion",
    }
)

# A matcher alternative we are willing to judge: a bare tool name. Anything
# carrying regex metacharacters is left alone — we cannot tell what it matches,
# and a false warning is worse than none.
_PLAIN_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def matcher_warnings(matcher: str) -> list[str]:
    """Name the matcher alternatives that can never fire in Codex.

    Returns [] when every alternative is reachable, unjudgeable (a regex), or
    the matcher is empty (which matches everything on both sides).
    """
    if not matcher:
        return []

    tokens = [tok.strip() for tok in re.split(r"[|,]", matcher) if tok.strip()]
    dead = [tok for tok in tokens if _PLAIN_TOKEN_RE.match(tok) and tok.lower() in UNREACHABLE_TOOL_TOKENS]
    if not dead:
        return []
    return [f"matcher names {', '.join(dead)} — Codex has no matching tool event for these, so they never fire there"]


def _convert_handler(handler: object) -> tuple[dict | None, list[str]]:
    """Convert one handler entry. Returns (codex_handler_or_None, warnings)."""
    if not isinstance(handler, dict):
        return None, ["handler is not an object — dropped"]

    # Claude treats an entry carrying `command` as a command hook even without
    # an explicit type, so mirror that rather than dropping a valid hook.
    handler_type = handler.get("type") or ("command" if "command" in handler else None)
    if handler_type != "command":
        label = handler_type or "untyped"
        return None, [f"handler type '{label}' dropped — Codex command hooks only"]

    command = handler.get("command")
    if not isinstance(command, str) or not command.strip():
        return None, ["command hook without a command string — dropped"]

    converted: dict = {"type": "command", "command": command}
    timeout = handler.get("timeout")
    if isinstance(timeout, int) and not isinstance(timeout, bool):
        converted["timeout"] = timeout

    warnings: list[str] = []
    extra = sorted(k for k in handler if k not in _PORTABLE_HANDLER_FIELDS)
    if extra:
        warnings.append(f"dropped handler field(s) {', '.join(extra)} — not read by Codex")
    return converted, warnings


def convert_hook_group(event: str, group: object) -> tuple[dict | None, list[str]]:
    """Convert one {matcher, hooks[]} group.

    Returns (codex_group_or_None, warnings). None means nothing survived and no
    group should be emitted at all.
    """
    if not isinstance(group, dict):
        return None, [f"{event}: entry is not an object — dropped"]

    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return None, [f"{event}: entry has no 'hooks' list — dropped"]

    warnings: list[str] = []
    converted_handlers: list[dict] = []
    for handler in handlers:
        converted, handler_warnings = _convert_handler(handler)
        warnings.extend(handler_warnings)
        if converted is not None:
            converted_handlers.append(converted)

    if not converted_handlers:
        return None, warnings

    matcher = group.get("matcher")
    codex_group: dict = {}
    if isinstance(matcher, str) and matcher:
        codex_group["matcher"] = matcher
        warnings.extend(matcher_warnings(matcher))
    codex_group["hooks"] = converted_handlers
    return codex_group, warnings


def convert_hooks_block(hooks: object) -> tuple[dict[str, list[dict]], list[str]]:
    """Convert a whole Claude `hooks` block into Codex hook groups.

    Returns (codex_hooks, warnings). Events are returned sorted so callers get a
    deterministic document without having to re-sort.
    """
    if not isinstance(hooks, dict):
        return {}, []

    converted: dict[str, list[dict]] = {}
    warnings: list[str] = []

    for event in sorted(hooks):
        groups = hooks[event]
        if event not in CODEX_HOOK_EVENTS:
            warnings.append(f"event '{event}' dropped — Codex has no such hook event")
            continue
        if not isinstance(groups, list):
            warnings.append(f"event '{event}' dropped — value is not a list")
            continue

        kept: list[dict] = []
        for group in groups:
            codex_group, group_warnings = convert_hook_group(event, group)
            warnings.extend(group_warnings)
            if codex_group is not None:
                kept.append(codex_group)
        if kept:
            converted[event] = kept

    return converted, warnings
