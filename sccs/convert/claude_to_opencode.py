# SCCS Claude -> OpenCode Conversion Rules
#
# Pure, I/O-free transformation logic that maps Claude Code artefact metadata
# to the OpenCode equivalent. Mirrors the design of convert/rules.py: data and
# small functions here, file walking / writing lives in the caller
# (integrations/opencode.py).
#
# Three artefact families are handled:
#   - Agents   (~/.claude/agents/<name>.md      -> ~/.config/opencode/agent/<name>.md)
#   - Commands (~/.claude/commands/<name>.md    -> ~/.config/opencode/command/<name>.md)
#   - MCP      (settings.json::mcpServers[name]  -> opencode.json::mcp[name])
#
# Direction is ONE-WAY (Claude is the source of truth). No reverse mapping.

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Model-ID mapping
# --------------------------------------------------------------------------- #
# Claude Code agents use short model aliases ("sonnet", "opus", "haiku") or a
# bare Anthropic model id. OpenCode expects a fully-qualified "provider/model"
# string.
#
# This static table is the LAST-RESORT fallback only. The preferred path is the
# layered resolver in integrations/opencode.py::resolve_model_map(), which (1)
# honours an explicit user map from config, then (2) discovers the models the
# local OpenCode install actually offers (`opencode models`) and matches by
# family — so we map to a model that REALLY EXISTS instead of guessing an id.
#
# IMPORTANT: this static map is a LAST-RESORT OFFLINE FALLBACK only. The normal
# export path resolves models via integrations.opencode.resolve_model_map(),
# which runs `opencode models` live and picks a really-available id — that
# discovery layer returns the actual provider prefix your install uses (e.g.
# `openrouter/anthropic/claude-sonnet-4.5`, which may NOT be a bare `anthropic/`
# provider at all, and uses dot-notation). These `anthropic/...` values are just
# a plausible guess for a fully-offline run with no authenticated provider; they
# WILL age as models drift. Discovery always wins over them, and an unknown value
# passes through unchanged with a warning — so a stale entry here never blocks a
# correct export, it only shapes the offline fallback. Prefer `opencode
# map-models` (persists real ids into config) over trusting these.
DEFAULT_OPENCODE_MODEL_MAP: dict[str, str] = {
    "sonnet": "anthropic/claude-sonnet-4-5",
    "opus": "anthropic/claude-opus-4",
    "haiku": "anthropic/claude-haiku-4-5",
    # Bare Anthropic ids people sometimes put in CC frontmatter.
    "claude-sonnet-4-5": "anthropic/claude-sonnet-4-5",
    "claude-opus-4": "anthropic/claude-opus-4",
    "claude-haiku-4-5": "anthropic/claude-haiku-4-5",
}

# Backwards-compatible alias (kept so external importers don't break).
MODEL_MAP = DEFAULT_OPENCODE_MODEL_MAP

# CC tier aliases -> the keyword we look for inside an OpenCode model id when
# matching against the live `opencode models` list.
TIER_KEYWORDS: dict[str, str] = {
    "sonnet": "sonnet",
    "opus": "opus",
    "haiku": "haiku",
}

# CC permits `model: inherit` (use the parent/main model). OpenCode has no such
# token — omitting `model` makes the agent fall back to the default, which is
# the closest equivalent.
_INHERIT_TOKENS = {"inherit", ""}


def map_model(cc_model: str | None, model_map: dict[str, str] | None = None) -> tuple[str | None, list[str]]:
    """Map a Claude model alias/id to an OpenCode 'provider/model' string.

    Args:
        cc_model: the Claude model alias/id from frontmatter (or None).
        model_map: the effective alias->'provider/model' map to use. Defaults to
            the static DEFAULT_OPENCODE_MODEL_MAP; callers normally inject the
            resolved map from integrations.opencode.resolve_model_map().

    Returns (oc_model_or_None, warnings).
    - None means "omit the model field" (e.g. CC 'inherit').
    - An already-qualified 'provider/model' value passes through untouched.
    - An unknown bare value passes through unchanged WITH a warning.
    """
    effective = DEFAULT_OPENCODE_MODEL_MAP if model_map is None else model_map
    warnings: list[str] = []
    if cc_model is None:
        return None, warnings

    value = str(cc_model).strip()
    if value.lower() in _INHERIT_TOKENS:
        return None, warnings

    # Already provider-qualified (contains a slash) -> trust it.
    if "/" in value:
        return value, warnings

    mapped = effective.get(value.lower())
    if mapped is not None:
        return mapped, warnings

    warnings.append(f"unknown model '{value}' — left as-is; set a 'provider/model' value in OpenCode if it is rejected")
    return value, warnings


def match_models(
    cc_tokens: list[str],
    available_models: list[str],
    *,
    preferred_providers: list[str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Match Claude model aliases to OpenCode models discovered at runtime.

    For each CC alias (e.g. ``sonnet``) find the best ``provider/model`` among
    ``available_models`` (the output of ``opencode models``) whose id contains
    the tier keyword. Providers in ``preferred_providers`` win; within a
    provider group the lexicographically greatest id is chosen (a deterministic
    "newest-ish" heuristic). Ambiguity adds a warning.

    Pure function — no subprocess; the caller supplies ``available_models``.

    Returns (alias->model map, warnings). Aliases with no match are omitted.
    """
    preferred = preferred_providers if preferred_providers is not None else ["anthropic"]
    warnings: list[str] = []
    result: dict[str, str] = {}

    if not available_models:
        return result, warnings

    for token in cc_tokens:
        keyword = TIER_KEYWORDS.get(token.lower())
        if keyword is None:
            continue

        candidates = [m for m in available_models if keyword in m.lower()]
        if not candidates:
            continue

        # Rank: preferred-provider order first, then lexical (≈ newest) desc.
        def _rank(model: str) -> tuple[int, str]:
            provider = model.split("/", 1)[0].lower()
            try:
                provider_rank = preferred.index(provider)
            except ValueError:
                provider_rank = len(preferred)  # non-preferred providers last
            return (provider_rank, model)

        best = sorted(candidates, key=_rank)
        # Top of the preferred group = smallest provider_rank, greatest id.
        top_provider_rank = _rank(best[0])[0]
        in_group = [m for m in best if _rank(m)[0] == top_provider_rank]
        chosen = max(in_group)
        result[token] = chosen

        if len(in_group) > 1:
            warnings.append(
                f"model '{token}' matched {len(in_group)} candidates ({', '.join(sorted(in_group))}); "
                f"chose '{chosen}' — set opencode.model_map to pin a different one"
            )

    return result, warnings


# --------------------------------------------------------------------------- #
# allowed-tools -> permission
# --------------------------------------------------------------------------- #
# CC `tools` / `allowed-tools` is a positive allowlist — usually COMMA-separated
# ("Read, Write, Edit, Bash, Grep, Glob"), occasionally space-separated or a
# YAML list. OpenCode expresses tool access via a `permission` object whose keys
# are matched as wildcard patterns against tool names and whose values are
# "allow" | "ask" | "deny" (a few keys also accept a glob→action map).
#
# We reproduce the allowlist FAITHFULLY: emit a catch-all `"*": "deny"` and then
# grant exactly the listed tools. OpenCode resolves most-specific-wins, so an
# agent restricted to Read+Bash in Claude is restricted to Read+Bash in OpenCode.
#
# Authoritative permission keys (opencode.ai/docs/agents): read, edit (gates
# write+edit+apply_patch), glob, grep, list, bash, task, webfetch, websearch,
# lsp, skill, question. Bash & task additionally accept a glob→action map.

# CC tool token (lowercased) -> OpenCode permission key. Note `write`/`edit` BOTH
# map to `edit` (OpenCode's single edit key gates write/edit/apply_patch).
_TOOL_KEY_MAP: dict[str, str] = {
    "read": "read",
    "write": "edit",
    "edit": "edit",
    "bash": "bash",
    "grep": "grep",
    "glob": "glob",
    "list": "list",
    "ls": "list",
    "webfetch": "webfetch",
    "websearch": "websearch",
    "skill": "skill",
    "task": "task",
    "agent": "task",  # CC's Agent (subagent dispatch) == OpenCode's task tool
    "askuserquestion": "question",
    "lsp": "lsp",
}


def _split_allowed_tools(allowed_tools: object) -> list[str]:
    """Normalise allowed-tools (str or list) into a flat token list.

    Splits on commas AND whitespace — real Claude Code frontmatter is almost
    always comma-separated ("Read, Write, Edit"), so a whitespace-only split
    left a trailing comma on every token and nothing matched.
    """
    if allowed_tools is None:
        return []
    if isinstance(allowed_tools, str):
        raw = re.split(r"[,\s]+", allowed_tools)
    elif isinstance(allowed_tools, list):
        raw = []
        for entry in allowed_tools:
            raw.extend(re.split(r"[,\s]+", str(entry)))
    else:
        return []
    return [t for t in (tok.strip() for tok in raw) if t]


def _mcp_permission_key(token: str) -> str | None:
    """Map a CC MCP tool token to an OpenCode wildcard permission key.

    `mcp__context7__*`            -> `context7_*`
    `mcp__context7__resolve-lib`  -> `context7_resolve-lib`
    OpenCode names MCP tools `<server>_<tool>` and matches permission keys as
    wildcards, so both forms are valid grants.
    """
    if not token.lower().startswith("mcp__"):
        return None
    rest = token[len("mcp__") :]
    if not rest:
        return None
    return rest.replace("__", "_")


def tools_to_permission(allowed_tools: object) -> tuple[dict | None, list[str]]:
    """Convert a CC tool allowlist into an OpenCode `permission` object.

    Returns (permission_or_None, warnings). None when there is nothing to map.
    The result reproduces the allowlist faithfully via a catch-all deny.
    """
    tokens = _split_allowed_tools(allowed_tools)
    if not tokens:
        return None, []

    grants: dict[str, str] = {}
    bash_rules: dict[str, str] = {}
    unknown: list[str] = []
    warnings: list[str] = []

    for token in tokens:
        lowered = token.lower()

        # Bash(scope:pattern) / Bash(scope:*) / bare Bash
        if lowered.startswith("bash(") and token.endswith(")"):
            inner = token[5:-1]
            # CC uses "git:*" style; OpenCode bash globs are shell-like "git *".
            glob = inner.replace(":", " ").strip() or "*"
            bash_rules[glob] = "allow"
            continue
        if lowered == "bash":
            grants["bash"] = "allow"
            continue

        # MCP tools (mcp__server__tool) -> OpenCode wildcard permission key.
        mcp_key = _mcp_permission_key(token)
        if mcp_key is not None:
            grants[mcp_key] = "allow"
            continue

        key = _TOOL_KEY_MAP.get(lowered)
        if key is not None:
            grants[key] = "allow"
            continue

        unknown.append(token)

    # A bare `bash` grant and scoped `Bash(...)` globs both target the bash key;
    # the glob map wins (more specific) when present.
    if bash_rules:
        grants.pop("bash", None)

    if not grants and not bash_rules:
        if unknown:
            warnings.append(f"no OpenCode permission mapping for: {', '.join(unknown)} — skipped")
        return None, warnings

    # Faithful allowlist: deny everything, then grant the listed tools. OpenCode
    # resolves most-specific-wins, so the catch-all only affects unlisted tools.
    permission: dict[str, object] = {"*": "deny"}
    permission.update(grants)
    if bash_rules:
        permission["bash"] = bash_rules

    if unknown:
        warnings.append(f"no OpenCode permission mapping for: {', '.join(unknown)} — skipped")
    return permission, warnings


# --------------------------------------------------------------------------- #
# Agent frontmatter
# --------------------------------------------------------------------------- #
# CC agent frontmatter fields seen in this repo: name, description, model,
# allowed-tools (sometimes `tools`). OpenCode agent fields: description, mode,
# model, temperature, permission. The `name` field is dropped (OpenCode derives
# the name from the filename).


def convert_agent_frontmatter(
    cc_meta: dict, model_map: dict[str, str] | None = None, *, parse_error: str | None = None
) -> tuple[dict, list[str]]:
    """Transform Claude agent frontmatter into OpenCode agent frontmatter.

    Args:
        cc_meta: the Claude agent frontmatter dict (empty when unreadable).
        model_map: effective alias->'provider/model' map (see map_model).
        parse_error: set when the source HAS a frontmatter block that failed to
            parse. Suppresses the "has no description" warning, which is false
            and misleading when the field exists but could not be read.

    Returns (oc_meta, warnings).
    """
    warnings: list[str] = []
    oc_meta: dict[str, object] = {}

    if parse_error is not None:
        warnings.append(f"{parse_error} — no fields could be read from it (description, model, tools)")

    description = cc_meta.get("description")
    if description:
        oc_meta["description"] = description
    elif parse_error is None:
        warnings.append("agent has no 'description' — OpenCode requires one for markdown agents")

    # Sub-agents are the closest analog to Claude Code agents.
    oc_meta["mode"] = "subagent"

    oc_model, model_warnings = map_model(cc_meta.get("model"), model_map)
    warnings.extend(model_warnings)
    if oc_model is not None:
        oc_meta["model"] = oc_model

    # CC carries tool permissions either as `allowed-tools` or `tools`.
    allowed = cc_meta.get("allowed-tools", cc_meta.get("tools"))
    permission, perm_warnings = tools_to_permission(allowed)
    warnings.extend(perm_warnings)
    if permission is not None:
        oc_meta["permission"] = permission

    # Pass through a temperature if the CC author set one.
    if "temperature" in cc_meta:
        oc_meta["temperature"] = cc_meta["temperature"]

    return oc_meta, warnings


# --------------------------------------------------------------------------- #
# Command frontmatter
# --------------------------------------------------------------------------- #
# CC command frontmatter: description, tags, allowed-tools (+ occasionally the
# OpenCode-native `agent`/`subtask` when a command is authored cross-tool).
# OpenCode command frontmatter: description, agent, model, subtask. `agent` and
# `subtask` are passed through when present; tags/allowed-tools are dropped
# (OpenCode commands ignore them — a command has no permission block of its own).


def convert_command_frontmatter(cc_meta: dict, model_map: dict[str, str] | None = None) -> tuple[dict, list[str]]:
    """Transform Claude command frontmatter into OpenCode command frontmatter.

    Args:
        cc_meta: the Claude command frontmatter dict.
        model_map: effective alias->'provider/model' map (see map_model).

    Returns (oc_meta, warnings).
    """
    warnings: list[str] = []
    oc_meta: dict[str, object] = {}

    description = cc_meta.get("description")
    if description:
        oc_meta["description"] = description

    # `agent` (which OpenCode agent runs the command) is a native OpenCode
    # command field — pass it through verbatim when authored cross-tool.
    agent = cc_meta.get("agent")
    if agent:
        oc_meta["agent"] = agent

    oc_model, model_warnings = map_model(cc_meta.get("model"), model_map)
    warnings.extend(model_warnings)
    if oc_model is not None:
        oc_meta["model"] = oc_model

    # `subtask` (force subagent invocation to avoid polluting the main context)
    # is a native OpenCode command field — pass it through when present.
    if "subtask" in cc_meta:
        oc_meta["subtask"] = cc_meta["subtask"]

    # `tags` is cosmetic CC-only metadata — drop it silently (not worth a warning).
    # `allowed-tools` on a command is meaningless in OpenCode (a command runs
    # under an agent and inherits that agent's tool access), so note it once, softly.
    if "allowed-tools" in cc_meta:
        warnings.append("dropped 'allowed-tools' — OpenCode commands inherit tool access from their agent")

    return oc_meta, warnings


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #
# CC settings.json mcpServers entry:
#     {"command": "npx", "args": ["-y", "x"], "env": {"K": "V"}}
#     {"type": "sse"|"http", "url": "https://..."}
# OpenCode opencode.json mcp entry:
#     local:  {"type": "local",  "command": ["npx","-y","x"], "environment": {...}, "enabled": true}
#     remote: {"type": "remote", "url": "https://...", "enabled": true}


def convert_mcp_server(cc_server: dict) -> tuple[dict, list[str]]:
    """Transform one CC mcpServers entry into an OpenCode mcp entry.

    Returns (oc_server, warnings).
    """
    warnings: list[str] = []

    cc_type = str(cc_server.get("type", "")).lower()
    url = cc_server.get("url")

    # Remote server: CC marks these with type sse/http and a url.
    if url and cc_type in {"sse", "http", "https", "remote"}:
        oc_server: dict[str, object] = {
            "type": "remote",
            "url": url,
            "enabled": True,
        }
        if "headers" in cc_server:
            oc_server["headers"] = cc_server["headers"]
        return oc_server, warnings

    # Local (stdio) server: merge command + args into a single argv list.
    command = cc_server.get("command")
    args = cc_server.get("args", [])
    argv: list[str] = []
    if isinstance(command, str):
        argv.append(command)
    elif isinstance(command, list):
        argv.extend(str(c) for c in command)
    elif command is not None:
        warnings.append(f"unexpected 'command' type {type(command).__name__} — coerced to string")
        argv.append(str(command))

    if isinstance(args, list):
        argv.extend(str(a) for a in args)
    elif args:
        warnings.append("'args' was not a list — coerced to a single argument")
        argv.append(str(args))

    if not argv:
        warnings.append("MCP server has no 'command' — emitted an empty command array")

    oc_local: dict[str, object] = {
        "type": "local",
        "command": argv,
        "enabled": True,
    }

    # CC 'env' -> OpenCode 'environment'.
    env = cc_server.get("env")
    if isinstance(env, dict) and env:
        oc_local["environment"] = dict(env)

    if "cwd" in cc_server:
        oc_local["cwd"] = cc_server["cwd"]

    return oc_local, warnings
