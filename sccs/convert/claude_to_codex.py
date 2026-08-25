# SCCS Claude -> OpenAI Codex Conversion Rules
#
# Pure, I/O-free transformation logic that maps Claude Code artefact metadata
# to the OpenAI Codex CLI equivalent. Mirrors convert/claude_to_opencode.py:
# data and small functions here, file walking / writing lives in the caller
# (integrations/codex.py).
#
# Three artefact families are handled:
#   - Skills   (~/.claude/skills/<name>/      -> ~/.agents/skills/<name>/)
#                Verbatim copy — Codex reads the agentskills.io SKILL.md format,
#                which is identical to Claude Code's. No conversion needed;
#                nothing to do in this module.
#   - Agents   (~/.claude/agents/<name>.md    -> ~/.codex/agents/<name>.toml)
#                Markdown + YAML frontmatter -> a Codex agent TOML file with
#                name / description / developer_instructions (+ model tuning).
#   - Commands (~/.claude/commands/<name>.md  -> ~/.agents/skills/<name>/SKILL.md)
#                Wrapped as a Codex skill. Codex's own custom prompts
#                (~/.codex/prompts/) are officially deprecated; skills are the
#                documented migration target for slash-command-style prompts.
#
# Direction is ONE-WAY (Claude is the source of truth). No reverse mapping.

from __future__ import annotations

import re

from sccs.convert.claude_to_opencode import _split_allowed_tools

# --------------------------------------------------------------------------- #
# Model mapping
# --------------------------------------------------------------------------- #
# Claude Code agents use short model aliases ("sonnet", "opus", "haiku") or a
# bare Anthropic model id. Codex expects an OpenAI model id in `model` plus an
# optional `model_reasoning_effort`.
#
# IMPORTANT: unlike OpenCode there is NO live discovery COMMAND in the Codex
# CLI, so this static map is the only bundled source and WILL age as OpenAI
# model ids drift — it already did once (the v2.53.0 map pointed at the
# retired gpt-5.1-codex family). Override it via `codex.model_map` /
# `codex.extra_model_map` in ~/.config/sccs/config.yaml. An unknown value
# passes through unchanged with a warning — a stale entry here never blocks an
# export, it only shapes the fallback.
#
# To re-check the map against the installed CLI, read the model catalogue Codex
# caches locally (no command, but a machine-readable file):
#
#     python -c "import json,pathlib;print([m['slug'] for m in json.loads(
#       pathlib.Path.home().joinpath('.codex/models_cache.json').read_text())['models']])"
#
# Policy (owner's call): always map onto the CURRENT top model family, never
# onto an older generation's small model. A Claude tier is a depth/cost signal,
# and Codex expresses depth through `model_reasoning_effort` on one family —
# so all three aliases share the newest family and differ only in effort.
DEFAULT_CODEX_MODEL_MAP: dict[str, str] = {
    "opus": "gpt-5.6-terra",
    "sonnet": "gpt-5.6-terra",
    "haiku": "gpt-5.6-luna",
}

# Claude tier -> Codex reasoning effort. The Claude tiers differ mainly in
# depth/cost, which Codex expresses as reasoning effort on one model family.
DEFAULT_CODEX_REASONING_EFFORT_MAP: dict[str, str] = {
    "opus": "high",
    "sonnet": "medium",
    "haiku": "low",
}

# CC permits `model: inherit` (use the parent/main model). Codex has no such
# token — omitting `model` makes the agent fall back to the configured default,
# which is the closest equivalent.
_INHERIT_TOKENS = {"inherit", ""}

# Claude tool tokens that cannot mutate the workspace. An allowlist consisting
# only of these maps cleanly onto Codex `sandbox_mode = "read-only"`.
_READ_ONLY_TOOLS = {
    "read",
    "grep",
    "glob",
    "list",
    "ls",
    "webfetch",
    "websearch",
    "askuserquestion",
    "todoread",
}

# $ARGUMENTS / $1..$9 style placeholders used by Claude command bodies. Codex
# skills have no positional-argument substitution, so their presence is worth
# one warning on command wrapping.
_PLACEHOLDER_RE = re.compile(r"\$(?:ARGUMENTS\b|[1-9]\b)")


def map_model(
    cc_model: str | None,
    model_map: dict[str, str] | None = None,
    reasoning_map: dict[str, str] | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """Map a Claude model alias/id to a Codex model + reasoning effort.

    Args:
        cc_model: the Claude model alias/id from frontmatter (or None).
        model_map: alias -> Codex model id map (defaults to the static
            DEFAULT_CODEX_MODEL_MAP; callers normally inject the effective map
            from CodexConfig).
        reasoning_map: alias -> reasoning effort map (same override pattern).

    Returns (model_or_None, reasoning_effort_or_None, warnings).
    - (None, None) means "omit both fields" (e.g. CC 'inherit' or no model).
    - An unknown value passes through as the model WITH a warning so a
      deliberate literal OpenAI id keeps working.
    """
    effective = DEFAULT_CODEX_MODEL_MAP if model_map is None else model_map
    efforts = DEFAULT_CODEX_REASONING_EFFORT_MAP if reasoning_map is None else reasoning_map
    warnings: list[str] = []
    if cc_model is None:
        return None, None, warnings

    value = str(cc_model).strip()
    lowered = value.lower()
    if lowered in _INHERIT_TOKENS:
        return None, None, warnings

    mapped = effective.get(lowered)
    if mapped is not None:
        return mapped, efforts.get(lowered), warnings

    warnings.append(f"unknown model '{value}' — left as-is; set codex.model_map in config if Codex rejects it")
    return value, None, warnings


def tools_to_sandbox_mode(allowed_tools: object) -> tuple[str | None, list[str]]:
    """Map a Claude tool allowlist onto the closest Codex sandbox_mode.

    Codex has no per-tool permission object — access is governed by
    `sandbox_mode` (read-only | workspace-write | danger-full-access) and the
    approval policy. The only faithful mapping is: an allowlist containing
    exclusively read-only tools -> `sandbox_mode = "read-only"`. Anything else
    is dropped with ONE collected warning (Codex's own default applies).

    Returns (sandbox_mode_or_None, warnings).
    """
    tokens = _split_allowed_tools(allowed_tools)
    if not tokens:
        return None, []

    if all(t.lower() in _READ_ONLY_TOOLS for t in tokens):
        return "read-only", []

    return None, [
        "Claude 'tools' allowlist has no Codex equivalent beyond read-only — dropped "
        "(Codex governs access via sandbox_mode/approval_policy)"
    ]


def convert_agent_frontmatter(
    cc_meta: dict,
    model_map: dict[str, str] | None = None,
    reasoning_map: dict[str, str] | None = None,
) -> tuple[dict, list[str]]:
    """Transform Claude agent frontmatter into Codex agent TOML fields.

    Returns (codex_meta, warnings). ``codex_meta`` holds the optional scalar
    fields (description, model, model_reasoning_effort, sandbox_mode); the
    caller supplies name (from the filename) and developer_instructions (the
    Markdown body) to the TOML renderer separately.
    """
    warnings: list[str] = []
    codex_meta: dict[str, str] = {}

    description = cc_meta.get("description")
    if description:
        codex_meta["description"] = str(description)
    else:
        warnings.append("agent has no 'description' — a placeholder is emitted (Codex requires one)")

    model, effort, model_warnings = map_model(cc_meta.get("model"), model_map, reasoning_map)
    warnings.extend(model_warnings)
    if model is not None:
        codex_meta["model"] = model
    if effort is not None:
        codex_meta["model_reasoning_effort"] = effort

    allowed = cc_meta.get("allowed-tools", cc_meta.get("tools"))
    sandbox_mode, tool_warnings = tools_to_sandbox_mode(allowed)
    warnings.extend(tool_warnings)
    if sandbox_mode is not None:
        codex_meta["sandbox_mode"] = sandbox_mode

    return codex_meta, warnings


def wrap_command_as_skill(name: str, cc_meta: dict, body: str) -> tuple[dict, str, list[str]]:
    """Wrap a Claude command as a Codex skill (agentskills.io SKILL.md).

    Codex custom prompts are deprecated; the official migration target for
    slash-command-style prompts is a skill. The body is kept verbatim — a
    skill's Markdown is instructions either way.

    Returns (skill_meta, body, warnings). ``skill_meta`` is the SKILL.md
    frontmatter ({name, description}).
    """
    warnings: list[str] = []

    description = cc_meta.get("description")
    if not description:
        description = f"Claude Code command '{name}'"
        warnings.append("command has no 'description' — a placeholder is emitted (skills require one)")

    skill_meta = {"name": name, "description": str(description)}

    dropped = [key for key in ("model", "allowed-tools", "tools", "argument-hint") if key in cc_meta]
    if dropped:
        warnings.append(f"dropped {', '.join(dropped)} — Codex skills carry only name/description frontmatter")

    if _PLACEHOLDER_RE.search(body):
        warnings.append(
            "body uses $ARGUMENTS/$1-style placeholders — Codex skills have no argument substitution; "
            "pass arguments as free text when invoking the skill"
        )

    return skill_meta, body, warnings
