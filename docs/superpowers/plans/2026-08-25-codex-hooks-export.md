# Codex Hooks Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export Claude Code hook entries from `~/.claude/settings.json` into `~/.codex/hooks.json` as a repeatable, non-destructive merge.

**Architecture:** Two new modules mirroring the existing Codex integration split — `sccs/convert/claude_to_codex_hooks.py` holds pure translation (no I/O), `sccs/integrations/codex_hooks.py` holds state, merge and writing. A new CLI command `sccs integrations codex export-hooks` drives it. The merge is keyed on a `(event, matcher, command)` triple recorded in `~/.config/sccs/.codex_hooks_state.yaml`, so entries SCCS did not write are never touched.

**Tech Stack:** Python ≥3.10, Click, Pydantic v2 (config only), PyYAML (state), stdlib `json`. Tests with pytest. Formatting `ruff format`, linting `ruff check`, typing `mypy`.

**Spec:** `docs/superpowers/specs/2026-08-25-codex-hooks-export-design.md`

## Global Constraints

- **Python floor is 3.10.** CI runs 3.10 and 3.12. Never import `tomllib` unguarded; use the `try: import tomllib / except ModuleNotFoundError: import tomli as tomllib` pattern already in `tests/test_codex_convert.py`.
- **Byte-stable serialization is a hard requirement.** Codex records hook trust against the hash of each definition. A re-export with no semantic change MUST produce a byte-identical file, or the user is forced through `/hooks` review every time.
- **Never destroy what SCCS did not write.** Foreign entries in `hooks.json` survive every export. A malformed target file is a refusal, never a silent overwrite.
- **Comments and docstrings in English.** User-facing docs bilingual (DE + EN) where the file already is.
- **Line length 120** (`ruff format`, `[tool.ruff] line-length = 120`).
- **Commit prefixes:** `[ADD]` new features, `[CHG]` modifications, `[FIX]` bug fixes.
- **Version target: 2.59.0** — bumped once, in Task 6, across `pyproject.toml`, `sccs/__init__.py` (version + date `25.08.2026`), `CLAUDE.md`, `README.md`, `usage/AGENT.md`, `.project-tips`, followed by `uv lock`.
- **Target path:** `~/.codex/hooks.json`. NOT `~/.codex/hooks/hooks.json` (plugin path).
- **Exportable events (10):** `PreToolUse`, `PostToolUse`, `PermissionRequest`, `PreCompact`, `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop`, `UserPromptSubmit`, `Stop`.
- **Exportable handler type:** `command` only. `http`, `prompt`, `agent` are dropped with a warning.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `sccs/convert/claude_to_codex_hooks.py` | **Create.** Pure translation: event allowlist, handler filtering, matcher analysis. No I/O. |
| `sccs/integrations/codex_hooks.py` | **Create.** State manager, pure merge, byte-stable serialization, detector, writer. |
| `sccs/convert/__init__.py` | **Modify.** Re-export the new public names. |
| `sccs/cli.py` | **Modify.** `export-hooks` command; hooks line in `codex status`. |
| `tests/test_codex_hooks_convert.py` | **Create.** Translation tests. |
| `tests/test_codex_hooks_merge.py` | **Create.** State, merge, serialization, byte-stability tests. |
| `tests/test_codex_hooks_cli.py` | **Create.** CLI tests. |
| `docs/usage/codex.md` | **Modify.** Hooks section, DE + EN. |
| `usage/AGENT.md`, `README.md`, `CLAUDE.md`, `RELEASE_NOTES.md`, `.project-tips` | **Modify.** Docs + version. |

---

### Task 1: Translation rules (pure)

**Files:**
- Create: `sccs/convert/claude_to_codex_hooks.py`
- Test: `tests/test_codex_hooks_convert.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `CODEX_HOOK_EVENTS: frozenset[str]`
  - `UNREACHABLE_TOOL_TOKENS: frozenset[str]`
  - `convert_hook_group(event: str, group: dict) -> tuple[dict | None, list[str]]`
  - `convert_hooks_block(hooks: dict) -> tuple[dict[str, list[dict]], list[str]]`
  - `matcher_warnings(matcher: str) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_codex_hooks_convert.py`:

```python
# Tests for the pure Claude -> Codex hook translation rules.

from __future__ import annotations

from sccs.convert.claude_to_codex_hooks import (
    CODEX_HOOK_EVENTS,
    convert_hook_group,
    convert_hooks_block,
    matcher_warnings,
)


class TestEventAllowlist:
    def test_exactly_ten_shared_events(self):
        assert CODEX_HOOK_EVENTS == {
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

    def test_claude_only_event_is_dropped_with_a_named_warning(self):
        block = {
            "PostToolUseFailure": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "x.sh"}]}
            ]
        }
        converted, warnings = convert_hooks_block(block)
        assert converted == {}
        assert any("PostToolUseFailure" in w for w in warnings)
        assert any("Codex" in w for w in warnings)

    def test_shared_event_survives(self):
        block = {
            "PostToolUse": [
                {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "q.py"}]}
            ]
        }
        converted, warnings = convert_hooks_block(block)
        assert converted == {
            "PostToolUse": [
                {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "q.py"}]}
            ]
        }
        assert warnings == []


class TestHandlerTypes:
    def test_only_command_handlers_survive(self):
        group = {
            "matcher": "Bash",
            "hooks": [
                {"type": "command", "command": "keep.sh"},
                {"type": "http", "url": "https://example.invalid/hook"},
                {"type": "prompt", "prompt": "check this"},
                {"type": "agent", "prompt": "verify"},
            ],
        }
        converted, warnings = convert_hook_group("PreToolUse", group)
        assert converted == {"matcher": "Bash", "hooks": [{"type": "command", "command": "keep.sh"}]}
        assert len([w for w in warnings if "dropped" in w]) == 3

    def test_group_with_no_surviving_handler_yields_none(self):
        group = {"matcher": "Bash", "hooks": [{"type": "http", "url": "https://example.invalid/h"}]}
        converted, warnings = convert_hook_group("PreToolUse", group)
        assert converted is None
        assert warnings

    def test_handler_without_type_is_treated_as_command(self):
        # Claude Code defaults an entry with a `command` key to a command hook.
        group = {"matcher": "Bash", "hooks": [{"command": "x.sh"}]}
        converted, _ = convert_hook_group("PreToolUse", group)
        assert converted == {"matcher": "Bash", "hooks": [{"type": "command", "command": "x.sh"}]}

    def test_timeout_is_carried_over(self):
        group = {"matcher": "Bash", "hooks": [{"type": "command", "command": "x.sh", "timeout": 30}]}
        converted, _ = convert_hook_group("PreToolUse", group)
        assert converted["hooks"][0]["timeout"] == 30

    def test_unknown_handler_fields_are_dropped_with_a_warning(self):
        group = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "x.sh", "continueOnBlock": True}],
        }
        converted, warnings = convert_hook_group("PreToolUse", group)
        assert converted["hooks"][0] == {"type": "command", "command": "x.sh"}
        assert any("continueOnBlock" in w for w in warnings)


class TestMatcherWarnings:
    def test_names_only_the_unreachable_alternatives(self):
        warnings = matcher_warnings("Bash|Read|Grep|Glob")
        assert len(warnings) == 1
        assert "Read" in warnings[0] and "Grep" in warnings[0] and "Glob" in warnings[0]
        assert "Bash" not in warnings[0]

    def test_fully_reachable_matcher_is_silent(self):
        assert matcher_warnings("Edit|Write") == []
        assert matcher_warnings("Bash") == []
        assert matcher_warnings("") == []

    def test_mcp_names_are_reachable(self):
        assert matcher_warnings("mcp__filesystem__read_file") == []

    def test_regex_tokens_are_not_judged(self):
        # We only flag tokens we recognise as Claude tools Codex lacks.
        assert matcher_warnings("^apply_patch$") == []
        assert matcher_warnings("mcp__.*") == []

    def test_comma_separated_alternatives(self):
        warnings = matcher_warnings("Bash,Read")
        assert len(warnings) == 1
        assert "Read" in warnings[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_codex_hooks_convert.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.convert.claude_to_codex_hooks'`

- [ ] **Step 3: Write the implementation**

Create `sccs/convert/claude_to_codex_hooks.py`:

```python
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
    return [
        f"matcher names {', '.join(dead)} — Codex fires tool events only for Bash, "
        "apply_patch (aliases Edit/Write) and MCP tools, so those never match there"
    ]


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_codex_hooks_convert.py -q`
Expected: PASS, 14 tests.

- [ ] **Step 5: Lint, format, type-check**

Run: `ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add sccs/convert/claude_to_codex_hooks.py tests/test_codex_hooks_convert.py
git commit -m "[ADD] convert: Claude -> Codex hook translation rules"
```

---

### Task 2: State, merge and byte-stable serialization

**Files:**
- Create: `sccs/integrations/codex_hooks.py`
- Test: `tests/test_codex_hooks_merge.py`

**Interfaces:**
- Consumes: `convert_hooks_block` from Task 1.
- Produces:
  - `DEFAULT_CODEX_HOOKS_STATE_PATH: Path`
  - `HookKey = tuple[str, str, str]` — `(event, matcher, command)`; matcher `""` when absent
  - `CodexHooksState` with `.keys: set[HookKey]`, `.to_dict()`, `.from_dict()`
  - `CodexHooksStateManager(state_path=None)` with `.load() -> CodexHooksState`, `.save(state) -> None`
  - `group_keys(event: str, group: dict) -> list[HookKey]`
  - `merge_hooks(existing: dict, managed: dict[str, list[dict]], state: CodexHooksState) -> tuple[dict, CodexHooksState, list[str]]`
  - `serialize_hooks_document(document: dict) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_codex_hooks_merge.py`:

```python
# State, merge and serialization tests for the Codex hooks export.
#
# The merge must never touch entries SCCS did not write, and the serialization
# must be byte-stable: Codex records hook trust against the hash of each
# definition, so a churning file forces the user through /hooks every export.

from __future__ import annotations

import json

from sccs.integrations.codex_hooks import (
    CodexHooksState,
    CodexHooksStateManager,
    group_keys,
    merge_hooks,
    serialize_hooks_document,
)

MANAGED = {
    "PostToolUse": [
        {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "quality-gate.py"}]}
    ]
}

FOREIGN_GROUP = {
    "matcher": "Bash",
    "hooks": [{"type": "command", "command": "codex-native-hook.sh"}],
}


class TestGroupKeys:
    def test_key_is_event_matcher_command(self):
        group = {"matcher": "Bash", "hooks": [{"type": "command", "command": "x.sh"}]}
        assert group_keys("PreToolUse", group) == [("PreToolUse", "Bash", "x.sh")]

    def test_missing_matcher_becomes_empty_string(self):
        group = {"hooks": [{"type": "command", "command": "x.sh"}]}
        assert group_keys("SessionStart", group) == [("SessionStart", "", "x.sh")]

    def test_group_with_two_handlers_yields_two_keys(self):
        group = {
            "matcher": "Bash",
            "hooks": [
                {"type": "command", "command": "a.sh"},
                {"type": "command", "command": "b.sh"},
            ],
        }
        assert group_keys("Stop", group) == [("Stop", "Bash", "a.sh"), ("Stop", "Bash", "b.sh")]


class TestMerge:
    def test_empty_target_gets_the_managed_entries(self):
        document, state, warnings = merge_hooks({}, MANAGED, CodexHooksState())
        assert document["hooks"]["PostToolUse"] == MANAGED["PostToolUse"]
        assert ("PostToolUse", "Edit|Write", "quality-gate.py") in state.keys
        assert warnings == []

    def test_foreign_entries_survive(self):
        existing = {"hooks": {"PostToolUse": [FOREIGN_GROUP]}}
        document, _, _ = merge_hooks(existing, MANAGED, CodexHooksState())
        groups = document["hooks"]["PostToolUse"]
        assert FOREIGN_GROUP in groups
        assert len(groups) == 2

    def test_foreign_groups_come_first_and_keep_their_order(self):
        second_foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "other.sh"}]}
        existing = {"hooks": {"PostToolUse": [FOREIGN_GROUP, second_foreign]}}
        document, _, _ = merge_hooks(existing, MANAGED, CodexHooksState())
        groups = document["hooks"]["PostToolUse"]
        assert groups[0] == FOREIGN_GROUP
        assert groups[1] == second_foreign
        assert groups[2] == MANAGED["PostToolUse"][0]

    def test_previously_managed_entry_is_replaced_not_duplicated(self):
        state = CodexHooksState(keys={("PostToolUse", "Edit|Write", "quality-gate.py")})
        existing = {"hooks": {"PostToolUse": MANAGED["PostToolUse"]}}
        document, _, _ = merge_hooks(existing, MANAGED, state)
        assert len(document["hooks"]["PostToolUse"]) == 1

    def test_removed_claude_hook_disappears_from_the_target(self):
        state = CodexHooksState(keys={("PostToolUse", "Edit|Write", "quality-gate.py")})
        existing = {"hooks": {"PostToolUse": MANAGED["PostToolUse"] + [FOREIGN_GROUP]}}
        document, new_state, _ = merge_hooks(existing, {}, state)
        assert document["hooks"]["PostToolUse"] == [FOREIGN_GROUP]
        assert new_state.keys == set()

    def test_event_with_only_removed_managed_entries_is_dropped(self):
        state = CodexHooksState(keys={("PostToolUse", "Edit|Write", "quality-gate.py")})
        existing = {"hooks": {"PostToolUse": MANAGED["PostToolUse"]}}
        document, _, _ = merge_hooks(existing, {}, state)
        assert "PostToolUse" not in document["hooks"]

    def test_state_key_missing_from_target_produces_a_warning(self):
        state = CodexHooksState(keys={("Stop", "", "vanished.sh")})
        _, _, warnings = merge_hooks({"hooks": {}}, {}, state)
        assert any("vanished.sh" in w for w in warnings)

    def test_empty_state_claims_nothing(self):
        existing = {"hooks": {"PostToolUse": [FOREIGN_GROUP]}}
        document, _, _ = merge_hooks(existing, {}, CodexHooksState())
        assert document["hooks"]["PostToolUse"] == [FOREIGN_GROUP]

    def test_result_always_has_a_hooks_object(self):
        document, _, _ = merge_hooks({}, {}, CodexHooksState())
        assert document == {"hooks": {}}


class TestSerialization:
    def test_output_is_valid_json_with_trailing_newline(self):
        text = serialize_hooks_document({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}})
        assert text.endswith("\n")
        assert json.loads(text)["hooks"]["Stop"][0]["hooks"][0]["command"] == "x"

    def test_events_are_sorted(self):
        document = {"hooks": {"Stop": [], "PreToolUse": [], "SessionStart": []}}
        text = serialize_hooks_document(document)
        assert list(json.loads(text)["hooks"]) == ["PreToolUse", "SessionStart", "Stop"]

    def test_handler_key_order_is_fixed_regardless_of_input_order(self):
        a = {"hooks": {"Stop": [{"hooks": [{"command": "x", "timeout": 5, "type": "command"}]}]}}
        b = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x", "timeout": 5}]}]}}
        assert serialize_hooks_document(a) == serialize_hooks_document(b)
        assert '"type"' in serialize_hooks_document(a).split('"command"')[0]

    def test_matcher_precedes_hooks_in_a_group(self):
        document = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}], "matcher": "Bash"}]}}
        text = serialize_hooks_document(document)
        assert text.index('"matcher"') < text.index('"hooks"', text.index('"matcher"'))

    def test_unicode_is_not_escaped(self):
        document = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo grün"}]}]}}
        assert "grün" in serialize_hooks_document(document)

    def test_reexport_is_byte_identical(self):
        """The trust-hash requirement: no churn without a semantic change."""
        first, state, _ = merge_hooks({}, MANAGED, CodexHooksState())
        text_first = serialize_hooks_document(first)
        second, _, _ = merge_hooks(json.loads(text_first), MANAGED, state)
        assert serialize_hooks_document(second) == text_first


class TestStateManager:
    def test_roundtrip(self, tmp_path):
        manager = CodexHooksStateManager(state_path=tmp_path / ".codex_hooks_state.yaml")
        manager.save(CodexHooksState(keys={("Stop", "", "a.sh")}))
        assert manager.load().keys == {("Stop", "", "a.sh")}

    def test_missing_file_is_empty_state(self, tmp_path):
        manager = CodexHooksStateManager(state_path=tmp_path / "nope.yaml")
        assert manager.load().keys == set()

    def test_corrupt_file_degrades_to_empty(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("{{{not yaml", encoding="utf-8")
        assert CodexHooksStateManager(state_path=path).load().keys == set()

    def test_state_file_is_written_0600(self, tmp_path):
        path = tmp_path / ".codex_hooks_state.yaml"
        CodexHooksStateManager(state_path=path).save(CodexHooksState(keys={("Stop", "", "a.sh")}))
        assert path.stat().st_mode & 0o777 == 0o600
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_codex_hooks_merge.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.integrations.codex_hooks'`

- [ ] **Step 3: Write the implementation**

Create `sccs/integrations/codex_hooks.py`:

```python
# SCCS OpenAI Codex Hooks Export
#
# Exports the `hooks` block of ~/.claude/settings.json into ~/.codex/hooks.json.
# Unlike the skill/agent/command exports (one file per artefact), this one MERGES
# into a file the user also edits, so three properties are load-bearing:
#
#   1. Entries SCCS did not write are never touched. Ownership is tracked in
#      ~/.config/sccs/.codex_hooks_state.yaml, keyed on (event, matcher, command).
#   2. Removing a hook in Claude removes it here — the state still remembers it.
#   3. Serialization is BYTE-STABLE. Codex records hook trust against the hash of
#      each definition, so a file that churns forces the user through /hooks on
#      every export. Ordering and key order are therefore fixed, not incidental.
#
# Direction is ONE-WAY (Claude is the source of truth), like the rest of the
# Codex integration.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sccs.utils.paths import atomic_write

DEFAULT_CODEX_HOOKS_STATE_PATH = Path.home() / ".config" / "sccs" / ".codex_hooks_state.yaml"

# (event, matcher, command). The matcher is "" when the group carries none.
HookKey = tuple[str, str, str]

# Key order inside an emitted group and handler. Fixed so the document is
# byte-stable across runs (see module docstring).
_GROUP_KEY_ORDER = ("matcher", "hooks")
_HANDLER_KEY_ORDER = ("type", "command", "timeout")


@dataclass
class CodexHooksState:
    """The hook entries SCCS wrote into ~/.codex/hooks.json."""

    keys: set[HookKey] = field(default_factory=set)

    def to_dict(self) -> dict:
        # Sorted lists keep the YAML stable, which keeps diffs readable.
        return {"managed": sorted([list(key) for key in self.keys])}

    @classmethod
    def from_dict(cls, data: dict) -> CodexHooksState:
        raw = data.get("managed")
        if not isinstance(raw, list):
            return cls()
        keys: set[HookKey] = set()
        for item in raw:
            if isinstance(item, list) and len(item) == 3 and all(isinstance(part, str) for part in item):
                keys.add((item[0], item[1], item[2]))
        return cls(keys=keys)


class CodexHooksStateManager:
    """Read/write wrapper around ~/.config/sccs/.codex_hooks_state.yaml.

    Mirrors ProfileStateManager: a missing or corrupt file degrades to an empty
    state rather than raising. Empty is the safe default here — SCCS then claims
    nothing and touches nothing, at the cost of possibly leaving one stale entry
    behind, which the user can delete.
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or DEFAULT_CODEX_HOOKS_STATE_PATH

    def load(self) -> CodexHooksState:
        if not self.state_path.exists():
            return CodexHooksState()
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (yaml.YAMLError, OSError):
            return CodexHooksState()
        if not isinstance(data, dict):
            return CodexHooksState()
        return CodexHooksState.from_dict(data)

    def save(self, state: CodexHooksState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self.state_path,
            yaml.safe_dump(state.to_dict(), default_flow_style=False, sort_keys=True, allow_unicode=True),
            mode=0o600,
        )


def group_keys(event: str, group: dict) -> list[HookKey]:
    """Ownership keys for every command handler in one group."""
    matcher = group.get("matcher")
    matcher_str = matcher if isinstance(matcher, str) else ""
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return []
    keys: list[HookKey] = []
    for handler in handlers:
        if isinstance(handler, dict) and isinstance(handler.get("command"), str):
            keys.append((event, matcher_str, handler["command"]))
    return keys


def _is_managed(event: str, group: dict, state: CodexHooksState) -> bool:
    """True when every handler in the group is one SCCS wrote.

    All-or-nothing on purpose: a group mixing managed and foreign handlers was
    hand-edited, and rewriting half of it would mangle the user's work.
    """
    keys = group_keys(event, group)
    return bool(keys) and all(key in state.keys for key in keys)


def merge_hooks(
    existing: dict,
    managed: dict[str, list[dict]],
    state: CodexHooksState,
) -> tuple[dict, CodexHooksState, list[str]]:
    """Merge converted Claude hooks into an existing Codex hooks document.

    Foreign groups keep their relative order and come first; managed groups
    follow in source order. That rule is what makes the output byte-stable when
    nothing changed.

    Returns (document, new_state, warnings).
    """
    existing_hooks = existing.get("hooks") if isinstance(existing, dict) else None
    if not isinstance(existing_hooks, dict):
        existing_hooks = {}

    warnings: list[str] = []
    seen_state_keys: set[HookKey] = set()
    merged: dict[str, list[dict]] = {}

    events = set(existing_hooks) | set(managed)
    for event in sorted(events):
        foreign: list[dict] = []
        for group in existing_hooks.get(event, []) or []:
            if not isinstance(group, dict):
                continue
            if _is_managed(event, group, state):
                seen_state_keys.update(group_keys(event, group))
                continue  # replaced by the current conversion below
            foreign.append(group)

        groups = foreign + list(managed.get(event, []))
        if groups:
            merged[event] = groups

    # A key we own but cannot find: the user edited or deleted it inside Codex.
    # We re-create it from the source, but say so — silently re-adding something
    # the user removed on purpose is worse than a noisy line.
    for key in sorted(state.keys - seen_state_keys):
        warnings.append(
            f"previously exported hook not found in hooks.json: {key[0]} / {key[2]} — "
            "it was edited or removed inside Codex and is being re-created from Claude"
        )

    new_keys: set[HookKey] = set()
    for event, groups in managed.items():
        for group in groups:
            new_keys.update(group_keys(event, group))

    return {"hooks": merged}, CodexHooksState(keys=new_keys), warnings


def _ordered(source: dict, order: tuple[str, ...]) -> dict:
    """Copy `source` with `order` first, then any remaining keys sorted."""
    result = {key: source[key] for key in order if key in source}
    for key in sorted(source):
        if key not in result:
            result[key] = source[key]
    return result


def serialize_hooks_document(document: dict) -> str:
    """Render the hooks document byte-stably.

    Events sorted, group order preserved (the merge already fixed it), key order
    pinned, two-space indent, unicode kept literal, one trailing newline.
    """
    hooks = document.get("hooks") or {}
    normalized: dict[str, list[dict]] = {}
    for event in sorted(hooks):
        groups = []
        for group in hooks[event]:
            ordered_group = _ordered(group, _GROUP_KEY_ORDER)
            handlers = ordered_group.get("hooks")
            if isinstance(handlers, list):
                ordered_group["hooks"] = [
                    _ordered(handler, _HANDLER_KEY_ORDER) if isinstance(handler, dict) else handler
                    for handler in handlers
                ]
            groups.append(ordered_group)
        normalized[event] = groups
    return json.dumps({"hooks": normalized}, indent=2, ensure_ascii=False) + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_codex_hooks_merge.py -q`
Expected: PASS, 21 tests.

- [ ] **Step 5: Verify byte-stability explicitly**

Run: `python -m pytest tests/test_codex_hooks_merge.py::TestSerialization::test_reexport_is_byte_identical -v`
Expected: PASS. This is the trust-hash requirement from the spec; if it fails, stop and fix the ordering rules before continuing.

- [ ] **Step 6: Lint, format, type-check, commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/
git add sccs/integrations/codex_hooks.py tests/test_codex_hooks_merge.py
git commit -m "[ADD] integrations: Codex hooks state, merge and byte-stable serialization"
```

---

### Task 3: Detector and writer

**Files:**
- Modify: `sccs/integrations/codex_hooks.py` (append)
- Modify: `sccs/convert/__init__.py`
- Test: `tests/test_codex_hooks_merge.py` (append a class)

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces:
  - `CodexHooksPlan` dataclass: `.added: list[str]`, `.updated: list[str]`, `.removed: list[str]`, `.warnings: list[str]`, `.document: dict`, `.state: CodexHooksState`, `.unchanged: bool`
  - `read_claude_hooks(settings_path: Path) -> tuple[dict, str | None]`
  - `read_codex_hooks(path: Path) -> tuple[dict, str | None]`
  - `build_hooks_plan(settings_path, hooks_path, state_manager) -> tuple[CodexHooksPlan | None, str | None]`
  - `write_hooks_plan(plan, hooks_path, state_manager, *, dry_run=False) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_codex_hooks_merge.py`:

```python
class TestReaders:
    def test_reads_the_hooks_block(self, tmp_path):
        from sccs.integrations.codex_hooks import read_claude_hooks

        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"hooks": MANAGED, "other": 1}), encoding="utf-8")
        hooks, error = read_claude_hooks(path)
        assert error is None
        assert hooks == MANAGED

    def test_missing_settings_file_is_an_error(self, tmp_path):
        from sccs.integrations.codex_hooks import read_claude_hooks

        hooks, error = read_claude_hooks(tmp_path / "nope.json")
        assert hooks == {}
        assert error is not None

    def test_settings_without_hooks_block_is_empty_not_an_error(self, tmp_path):
        from sccs.integrations.codex_hooks import read_claude_hooks

        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
        hooks, error = read_claude_hooks(path)
        assert (hooks, error) == ({}, None)

    def test_missing_codex_file_is_an_empty_document(self, tmp_path):
        from sccs.integrations.codex_hooks import read_codex_hooks

        document, error = read_codex_hooks(tmp_path / "hooks.json")
        assert (document, error) == ({}, None)

    def test_codex_file_holding_an_array_is_refused(self, tmp_path):
        from sccs.integrations.codex_hooks import read_codex_hooks

        path = tmp_path / "hooks.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        document, error = read_codex_hooks(path)
        assert document == {}
        assert error is not None and "object" in error

    def test_codex_file_with_invalid_json_is_refused(self, tmp_path):
        from sccs.integrations.codex_hooks import read_codex_hooks

        path = tmp_path / "hooks.json"
        path.write_text("{not json", encoding="utf-8")
        _, error = read_codex_hooks(path)
        assert error is not None


class TestPlanAndWrite:
    def _settings(self, tmp_path, hooks):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
        return path

    def test_plan_reports_additions(self, tmp_path):
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan

        settings = self._settings(tmp_path, MANAGED)
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")
        plan, error = build_hooks_plan(settings, tmp_path / "hooks.json", manager)
        assert error is None
        assert plan.added == ["PostToolUse / quality-gate.py"]
        assert plan.removed == []
        assert not plan.unchanged

    def test_write_then_replan_is_unchanged(self, tmp_path):
        from sccs.integrations.codex_hooks import (
            CodexHooksStateManager,
            build_hooks_plan,
            write_hooks_plan,
        )

        settings = self._settings(tmp_path, MANAGED)
        hooks_path = tmp_path / "hooks.json"
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        plan, _ = build_hooks_plan(settings, hooks_path, manager)
        write_hooks_plan(plan, hooks_path, manager)
        first_bytes = hooks_path.read_bytes()

        plan2, _ = build_hooks_plan(settings, hooks_path, manager)
        assert plan2.unchanged
        write_hooks_plan(plan2, hooks_path, manager)
        assert hooks_path.read_bytes() == first_bytes

    def test_dry_run_writes_nothing(self, tmp_path):
        from sccs.integrations.codex_hooks import (
            CodexHooksStateManager,
            build_hooks_plan,
            write_hooks_plan,
        )

        settings = self._settings(tmp_path, MANAGED)
        hooks_path = tmp_path / "hooks.json"
        state_path = tmp_path / "state.yaml"
        manager = CodexHooksStateManager(state_path=state_path)
        plan, _ = build_hooks_plan(settings, hooks_path, manager)
        write_hooks_plan(plan, hooks_path, manager, dry_run=True)
        assert not hooks_path.exists()
        assert not state_path.exists()

    def test_removed_claude_hook_is_reported_and_written(self, tmp_path):
        from sccs.integrations.codex_hooks import (
            CodexHooksStateManager,
            build_hooks_plan,
            write_hooks_plan,
        )

        hooks_path = tmp_path / "hooks.json"
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        settings = self._settings(tmp_path, MANAGED)
        plan, _ = build_hooks_plan(settings, hooks_path, manager)
        write_hooks_plan(plan, hooks_path, manager)

        settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        plan2, _ = build_hooks_plan(settings, hooks_path, manager)
        assert plan2.removed == ["PostToolUse / quality-gate.py"]
        write_hooks_plan(plan2, hooks_path, manager)
        assert json.loads(hooks_path.read_text())["hooks"] == {}

    def test_hooks_file_is_written_0600(self, tmp_path):
        from sccs.integrations.codex_hooks import (
            CodexHooksStateManager,
            build_hooks_plan,
            write_hooks_plan,
        )

        settings = self._settings(tmp_path, MANAGED)
        hooks_path = tmp_path / "hooks.json"
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")
        plan, _ = build_hooks_plan(settings, hooks_path, manager)
        write_hooks_plan(plan, hooks_path, manager)
        assert hooks_path.stat().st_mode & 0o777 == 0o600

    def test_malformed_target_aborts_the_plan(self, tmp_path):
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan

        settings = self._settings(tmp_path, MANAGED)
        hooks_path = tmp_path / "hooks.json"
        hooks_path.write_text("[]", encoding="utf-8")
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")
        plan, error = build_hooks_plan(settings, hooks_path, manager)
        assert plan is None
        assert error is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_codex_hooks_merge.py -q -k "Readers or PlanAndWrite"`
Expected: FAIL — `ImportError: cannot import name 'read_claude_hooks'`

- [ ] **Step 3: Write the implementation**

Append to `sccs/integrations/codex_hooks.py`:

```python
@dataclass
class CodexHooksPlan:
    """What an export would change in ~/.codex/hooks.json."""

    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    document: dict = field(default_factory=dict)
    state: CodexHooksState = field(default_factory=CodexHooksState)
    unchanged: bool = False


def _label(key: HookKey) -> str:
    """Human-readable name for one hook entry: 'Event / command'."""
    return f"{key[0]} / {key[2]}"


def read_claude_hooks(settings_path: Path) -> tuple[dict, str | None]:
    """Read the `hooks` block from ~/.claude/settings.json.

    A file without a hooks block is not an error — there is simply nothing to
    export. A missing or unreadable file is.
    """
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"Cannot read {settings_path}: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"{settings_path} is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return {}, f"{settings_path} does not contain a JSON object"
    hooks = data.get("hooks")
    if hooks is None:
        return {}, None
    if not isinstance(hooks, dict):
        return {}, f"{settings_path}: 'hooks' is not an object"
    return hooks, None


def read_codex_hooks(path: Path) -> tuple[dict, str | None]:
    """Read ~/.codex/hooks.json. A missing file is an empty document.

    Anything present but not shaped like a hooks document is an ERROR, never a
    reason to overwrite: the file may hold work we cannot interpret.
    """
    if not path.exists():
        return {}, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"Cannot read {path}: {exc}"
    if not raw.strip():
        return {}, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"{path} is not valid JSON: {exc} — refusing to overwrite it"
    if not isinstance(data, dict):
        return {}, f"{path} does not contain a JSON object — refusing to overwrite it"
    hooks = data.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        return {}, f"{path}: 'hooks' is not an object — refusing to overwrite it"
    return data, None


def build_hooks_plan(
    settings_path: Path,
    hooks_path: Path,
    state_manager: CodexHooksStateManager,
) -> tuple[CodexHooksPlan | None, str | None]:
    """Work out what an export would change. Returns (plan, error)."""
    from sccs.convert.claude_to_codex_hooks import convert_hooks_block

    claude_hooks, error = read_claude_hooks(settings_path)
    if error is not None:
        return None, error

    existing, error = read_codex_hooks(hooks_path)
    if error is not None:
        return None, error

    managed, warnings = convert_hooks_block(claude_hooks)
    state = state_manager.load()
    document, new_state, merge_warnings = merge_hooks(existing, managed, state)
    warnings.extend(merge_warnings)

    added = sorted(_label(key) for key in new_state.keys - state.keys)
    removed = sorted(_label(key) for key in state.keys - new_state.keys)
    kept = new_state.keys & state.keys

    # "Updated" is measured on bytes, not on keys: a key that survived can still
    # differ in timeout or ordering, and that difference is what re-triggers the
    # Codex trust review.
    rendered = serialize_hooks_document(document)
    try:
        current = hooks_path.read_text(encoding="utf-8")
    except OSError:
        current = ""
    updated = sorted(_label(key) for key in kept) if (rendered != current and kept) else []

    plan = CodexHooksPlan(
        added=added,
        updated=updated,
        removed=removed,
        warnings=warnings,
        document=document,
        state=new_state,
        unchanged=(rendered == current),
    )
    return plan, None


def write_hooks_plan(
    plan: CodexHooksPlan,
    hooks_path: Path,
    state_manager: CodexHooksStateManager,
    *,
    dry_run: bool = False,
) -> None:
    """Write the merged document and record the new ownership state."""
    if dry_run or plan.unchanged:
        return
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(hooks_path, serialize_hooks_document(plan.document), mode=0o600)
    state_manager.save(plan.state)
```

- [ ] **Step 4: Export the new names**

In `sccs/convert/__init__.py`, add to the imports and `__all__`:

```python
from sccs.convert.claude_to_codex_hooks import (
    CODEX_HOOK_EVENTS,
    convert_hooks_block,
    matcher_warnings,
)
```

Add `"CODEX_HOOK_EVENTS"`, `"convert_hooks_block"`, `"matcher_warnings"` to `__all__`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_codex_hooks_merge.py -q`
Expected: PASS, 34 tests.

- [ ] **Step 6: Lint, format, type-check, commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/
git add sccs/integrations/codex_hooks.py sccs/convert/__init__.py tests/test_codex_hooks_merge.py
git commit -m "[ADD] integrations: Codex hooks plan builder and writer"
```

---

### Task 4: CLI command and status line

**Files:**
- Modify: `sccs/cli.py` (new command after `codex_export_all`, around line 2700; status line in `codex_status`)
- Test: `tests/test_codex_hooks_cli.py`

**Interfaces:**
- Consumes: `build_hooks_plan`, `write_hooks_plan`, `CodexHooksStateManager` from Task 3; `_make_codex_detector` (existing, `sccs/cli.py`).
- Produces: `sccs integrations codex export-hooks`; a `Hooks` line in `codex status`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_codex_hooks_cli.py`:

```python
# CLI tests for `sccs integrations codex export-hooks`.

from __future__ import annotations

import json
import re
from unittest.mock import patch

from click.testing import CliRunner

from sccs.cli import cli

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(output: str) -> str:
    """Strip ANSI color codes — CI forces color, local pipes do not."""
    return _ANSI_RE.sub("", output)


SETTINGS = {
    "hooks": {
        "PostToolUse": [
            {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "quality-gate.py"}]}
        ],
        "PostToolUseFailure": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "nono-hook.sh"}]}
        ],
    }
}


def _env(tmp_path):
    """Build a Codex home, a Claude settings.json and a state path."""
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".claude").mkdir()
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
    return settings, tmp_path / ".codex" / "hooks.json", tmp_path / "state.yaml"


class TestExportHooks:
    def test_help(self):
        result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks", "--help"])
        assert result.exit_code == 0

    def test_not_installed_exits_nonzero(self, tmp_path):
        with patch("sccs.cli._codex_hooks_paths", return_value=(tmp_path / "s.json", tmp_path / "h.json")):
            with patch("sccs.cli._make_codex_detector") as detector:
                detector.return_value.is_installed.return_value = False
                result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks"])
        assert result.exit_code == 1
        assert "not installed" in _plain(result.output)

    def test_dry_run_writes_nothing_and_reports(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks", "--dry-run"])
        assert result.exit_code == 0
        output = _plain(result.output)
        assert "Dry run" in output
        assert "PostToolUse / quality-gate.py" in output
        assert not hooks_path.exists()

    def test_export_writes_and_points_at_the_trust_review(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks"])
        assert result.exit_code == 0
        assert "/hooks" in _plain(result.output)
        written = json.loads(hooks_path.read_text())
        assert "PostToolUse" in written["hooks"]
        assert "PostToolUseFailure" not in written["hooks"]

    def test_dropped_event_is_warned_about(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks"])
        assert "PostToolUseFailure" in _plain(result.output)

    def test_second_run_reports_up_to_date(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            runner = CliRunner()
            runner.invoke(cli, ["integrations", "codex", "export-hooks"])
            result = runner.invoke(cli, ["integrations", "codex", "export-hooks"])
        assert "up to date" in _plain(result.output)

    def test_malformed_target_exits_nonzero_without_writing(self, tmp_path):
        settings, hooks_path, state_path = _env(tmp_path)
        hooks_path.write_text("[]", encoding="utf-8")
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._codex_hooks_state_path", return_value=state_path),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = True
            result = CliRunner().invoke(cli, ["integrations", "codex", "export-hooks"])
        assert result.exit_code == 1
        assert hooks_path.read_text() == "[]"

    def test_export_all_does_not_touch_hooks(self, tmp_path):
        """Hooks execute code — they stay behind their own command."""
        settings, hooks_path, state_path = _env(tmp_path)
        with (
            patch("sccs.cli._codex_hooks_paths", return_value=(settings, hooks_path)),
            patch("sccs.cli._make_codex_detector") as detector,
        ):
            detector.return_value.is_installed.return_value = False
            CliRunner().invoke(cli, ["integrations", "codex", "export-all"])
        assert not hooks_path.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_codex_hooks_cli.py -q`
Expected: FAIL — no such command `export-hooks`.

- [ ] **Step 3: Add the path helpers and the command**

In `sccs/cli.py`, directly after `_resolve_codex_model_maps` (around line 2572), add:

```python
def _codex_hooks_paths() -> tuple[Path, Path]:
    """(claude settings.json, codex hooks.json), honouring codex.base_dir."""
    from sccs.utils.paths import expand_path

    settings = Path.home() / ".claude" / "settings.json"
    try:
        config = load_config()
    except (FileNotFoundError, Exception):  # noqa: BLE001 — defensive fallback
        return settings, Path.home() / ".codex" / "hooks.json"
    base = getattr(config.codex, "base_dir", None)
    codex_home = expand_path(base) if base else Path.home() / ".codex"
    return settings, codex_home / "hooks.json"


def _codex_hooks_state_path() -> Path:
    """Where the hook-ownership state lives. Split out so tests can redirect it."""
    from sccs.integrations.codex_hooks import DEFAULT_CODEX_HOOKS_STATE_PATH

    return DEFAULT_CODEX_HOOKS_STATE_PATH
```

Then, after `codex_export_all` (around line 2700), add:

```python
@codex_group.command("export-hooks")
@click.option("-n", "--dry-run", is_flag=True, help="Preview changes without executing")
@click.pass_context
def codex_export_hooks(ctx: click.Context, dry_run: bool) -> None:
    """Export Claude hook entries into ~/.codex/hooks.json.

    Merges into the file rather than owning it: entries SCCS did not write are
    left alone. Deliberately NOT part of `export-all` — hooks execute code on
    every tool call, so they stay behind their own command.
    """
    from sccs.integrations.codex_hooks import (
        CodexHooksStateManager,
        build_hooks_plan,
        write_hooks_plan,
    )

    console = ctx.obj["console"]
    detector = _make_codex_detector()
    if not detector.is_installed():
        console.print_error("Codex is not installed (~/.codex/ not found)")
        sys.exit(1)

    settings_path, hooks_path = _codex_hooks_paths()
    state_manager = CodexHooksStateManager(state_path=_codex_hooks_state_path())

    plan, error = build_hooks_plan(settings_path, hooks_path, state_manager)
    if error is not None:
        console.print_error(error)
        sys.exit(1)

    if dry_run:
        console.print_info("Dry run — no files will be written\n")

    for label, names, colour in (
        ("Would add" if dry_run else "Added", plan.added, "green"),
        ("Would update" if dry_run else "Updated", plan.updated, "yellow"),
        ("Would remove" if dry_run else "Removed", plan.removed, "red"),
    ):
        for name in names:
            console.print(f"  [{colour}]{label}:[/{colour}] {name}")

    if plan.warnings:
        console.print(f"\n[yellow]Warnings ({len(plan.warnings)}):[/yellow]")
        for warning in plan.warnings:
            console.print(f"  [yellow]![/yellow] {warning}")

    if plan.unchanged:
        console.print_success("Hooks are already up to date in Codex")
        return

    write_hooks_plan(plan, hooks_path, state_manager, dry_run=dry_run)

    if not dry_run:
        console.print_success(f"\nWrote {hooks_path}")
        # Codex trusts hooks by hash, so a fresh export always needs review.
        console.print_info("Run /hooks in Codex to review and trust the new entries — until then they do not run")
```

- [ ] **Step 4: Add the hooks line to `codex status`**

In `codex_status`, after the three existing gap sections, add:

```python
    from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan

    settings_path, hooks_path = _codex_hooks_paths()
    plan, hooks_error = build_hooks_plan(
        settings_path, hooks_path, CodexHooksStateManager(state_path=_codex_hooks_state_path())
    )
    console.print("\n[bold]Hooks:[/bold]")
    if hooks_error is not None:
        console.print(f"  [red]{hooks_error}[/red]")
    elif plan.unchanged:
        console.print("  [dim]up to date[/dim]")
    else:
        console.print(
            f"  {len(plan.added)} to add · {len(plan.updated)} to update · {len(plan.removed)} to remove"
        )
```

- [ ] **Step 5: Mention the omission in `export-all`**

In `codex_export_all`'s docstring, replace the summary line with:

```python
    """Export skills, agents and commands to Codex in one run.

    Hooks are NOT included — they execute code on every tool call, so they need
    a deliberate `sccs integrations codex export-hooks`.
    """
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_codex_hooks_cli.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 7: Run the whole suite under both Python versions**

```bash
python -m pytest -q
uv run --python 3.10 --extra dev python -m pytest -q
```
Expected: both PASS, no regressions.

- [ ] **Step 8: Lint, format, type-check, commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/
git add sccs/cli.py tests/test_codex_hooks_cli.py
git commit -m "[ADD] cli: sccs integrations codex export-hooks"
```

---

### Task 5: Real-world fixture check

**Files:**
- Test: `tests/test_codex_hooks_convert.py` (append a class)

**Interfaces:**
- Consumes: `convert_hooks_block` from Task 1.
- Produces: nothing — this task only proves the spec's stated verdicts.

**Why this is its own task:** the spec makes concrete claims about a real settings.json. If they are wrong, the translation rules are wrong, and a reviewer should be able to reject exactly this without touching the rest.

- [ ] **Step 1: Write the tests**

Append to `tests/test_codex_hooks_convert.py`:

```python
class TestRealWorldSettings:
    """The verdicts the spec claims for a real ~/.claude/settings.json.

    Inlined rather than read from disk: a test that depends on the developer's
    own settings passes or fails for the wrong reasons, and would break in CI.
    """

    SETTINGS_HOOKS = {
        "PostToolUse": [
            {
                "matcher": "Edit|Write",
                "hooks": [{"type": "command", "command": 'python3 "$HOME/.claude/hooks/quality-gate.py"'}],
            }
        ],
        "PostToolUseFailure": [
            {
                "matcher": "Read|Write|Edit|Bash",
                "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/nono-hook.sh"}],
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Bash|Read|Grep|Glob",
                "hooks": [{"type": "command", "command": 'python3 "$HOME/.claude/hooks/suggest-compact.py"'}],
            }
        ],
        "SessionStart": [
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": 'python3 "$HOME/.claude/hooks/discover-skills.py"'}],
            },
            {"hooks": [{"type": "command", "command": '"/Users/picard/.claude/hooks/context-mode-cache-heal.mjs"'}]},
        ],
        "Stop": [
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": 'python3 "$HOME/.claude/hooks/cost-tracker.py"'}],
            }
        ],
    }

    def test_four_events_survive_one_is_dropped(self):
        converted, _ = convert_hooks_block(self.SETTINGS_HOOKS)
        assert sorted(converted) == ["PostToolUse", "PreToolUse", "SessionStart", "Stop"]
        assert "PostToolUseFailure" not in converted

    def test_the_dropped_event_is_named_in_a_warning(self):
        _, warnings = convert_hooks_block(self.SETTINGS_HOOKS)
        assert any("PostToolUseFailure" in w for w in warnings)

    def test_suggest_compact_gets_a_matcher_warning(self):
        _, warnings = convert_hooks_block(self.SETTINGS_HOOKS)
        matcher_warns = [w for w in warnings if "matcher names" in w]
        assert any("Read" in w and "Grep" in w and "Glob" in w for w in matcher_warns)

    def test_quality_gate_survives_without_a_warning_about_itself(self):
        converted, _ = convert_hooks_block(self.SETTINGS_HOOKS)
        group = converted["PostToolUse"][0]
        assert group["matcher"] == "Edit|Write"
        assert group["hooks"][0]["command"].endswith('quality-gate.py"')

    def test_both_session_start_groups_survive(self):
        converted, _ = convert_hooks_block(self.SETTINGS_HOOKS)
        assert len(converted["SessionStart"]) == 2

    def test_empty_matcher_is_not_emitted(self):
        # An empty matcher matches everything on both sides; omitting it keeps
        # the document smaller and the trust hash stable.
        converted, _ = convert_hooks_block(self.SETTINGS_HOOKS)
        assert "matcher" not in converted["Stop"][0]
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_codex_hooks_convert.py::TestRealWorldSettings -v`
Expected: PASS, 6 tests. If `test_four_events_survive_one_is_dropped` fails, the event allowlist in Task 1 is wrong — fix it there, not here.

- [ ] **Step 3: Commit**

```bash
git add tests/test_codex_hooks_convert.py
git commit -m "[ADD] tests: real-world hook fixtures for the Codex export"
```

---

### Task 6: Documentation, version bump and release

**Files:**
- Modify: `docs/usage/codex.md`, `usage/AGENT.md`, `README.md`, `CLAUDE.md`, `RELEASE_NOTES.md`, `.project-tips`
- Modify: `pyproject.toml`, `sccs/__init__.py`, then `uv lock`

**Interfaces:**
- Consumes: the finished feature from Tasks 1–5.
- Produces: a releasable 2.59.0.

- [ ] **Step 1: Document the feature in `docs/usage/codex.md` (DE + EN)**

Add a section before the collision section in BOTH language halves. German version:

```markdown
### Hooks exportieren

`sccs integrations codex export-hooks` überträgt die Hook-Einträge aus
`~/.claude/settings.json` nach `~/.codex/hooks.json`.

**Zehn Events sind übertragbar**: `PreToolUse`, `PostToolUse`,
`PermissionRequest`, `PreCompact`, `SessionStart`, `SessionEnd`,
`SubagentStart`, `SubagentStop`, `UserPromptSubmit`, `Stop`. Alles andere —
darunter `PostToolUseFailure`, `Notification`, `PostToolBatch` — kennt Codex
nicht und wird mit Warnung verworfen. Von Claudes Handler-Typen ist nur
`command` übertragbar; `http`, `prompt` und `agent` fallen weg.

**Skripte bleiben, wo sie sind.** Die Kommandos zeigen weiterhin auf
`~/.claude/hooks/` — ein Skript, eine Quelle der Wahrheit. Codex braucht dafür
ein vorhandenes `~/.claude/hooks/`.

**Matcher werden unverändert übernommen.** Codex feuert Tool-Events nur für
`Bash`, `apply_patch` (Aliase `Edit`/`Write`) und MCP-Namen — ein Matcher wie
`Bash|Read|Grep|Glob` greift dort nur bei `Bash`. Der Export warnt, schreibt den
Matcher aber nicht um: sobald Codex mehr Werkzeuge abdeckt, greift der Eintrag
von selbst.

**Deine eigenen Einträge bleiben unangetastet.** SCCS merkt sich in
`~/.config/sccs/.codex_hooks_state.yaml`, welche Einträge es geschrieben hat,
und fasst nur diese an. Ein in Claude gelöschter Hook verschwindet beim nächsten
Export auch hier.

**Nach dem Export: `/hooks` in Codex ausführen.** Codex vertraut Hooks über
einen Hash und führt neue oder geänderte Einträge erst nach einer Freigabe aus.

**Nicht Teil von `export-all`** — Hooks führen bei jedem Tool-Aufruf Code aus,
das gehört hinter eine bewusste Entscheidung.

> **Einschränkung:** Bearbeite exportierte Einträge nicht direkt in
> `hooks.json`. Der Besitz-Schlüssel enthält das Kommando; ein dort geänderter
> Eintrag gilt als fremd und der Export legt das Original erneut an. Ändere
> Hooks in Claude Code und exportiere neu.
```

The English half mirrors this text.

- [ ] **Step 2: Update `usage/AGENT.md`**

Add to the command table:

```markdown
| `sccs integrations codex export-hooks` | Merge Claude hook entries into ~/.codex/hooks.json. | -n/--dry-run |
```

And to the Codex recipe section:

```markdown
sccs integrations codex export-hooks --dry-run   # 10 shared events; others dropped with a warning
```

Plus one guardrail line: hooks are not in `export-all`; run `/hooks` in Codex afterwards to trust them; SCCS only touches entries it wrote.

- [ ] **Step 3: Update `README.md` (DE + EN) and `CLAUDE.md`**

`README.md` — one feature bullet per language half, in the style of the existing ones, mentioning: ten shared events, scripts stay in `~/.claude/hooks/`, non-destructive merge, `/hooks` trust review, not in `export-all`.

`CLAUDE.md` — a key-feature entry before the v2.58.4 one, recording the load-bearing details: the byte-stability requirement and why (trust hash), the `(event, matcher, command)` ownership key and its known limitation, and why hooks are excluded from `export-all`.

- [ ] **Step 4: Bump the version**

Set `2.59.0` in `pyproject.toml`, `sccs/__init__.py` (both the comment and `__version__`, date `25.08.2026`), `CLAUDE.md`, `README.md`, `usage/AGENT.md`, `.project-tips`.

Run: `uv lock`
Expected: `Updated sccs v2.58.4 -> v2.59.0`

- [ ] **Step 5: Write the release notes**

Prepend a `## Version 2.59.0 (25.08.2026)` section to `RELEASE_NOTES.md` under `### Added (Codex hooks export)`, covering: what transfers and what does not with counts; the trust-hash constraint and the byte-stability requirement it forces; the merge model and its known limitation; the deliberate exclusion from `export-all`; and the final test count.

- [ ] **Step 6: Full quality gate**

```bash
ruff format --check sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/
python -m pytest -q
uv run --python 3.10 --extra dev python -m pytest -q
rm -rf dist/ && uv build
```
Expected: all clean, both Python versions pass, wheel builds.

- [ ] **Step 7: Verify against the real Codex install**

```bash
python -m sccs integrations codex export-hooks --dry-run
```
Expected: reports `PostToolUseFailure` dropped, a matcher warning for the `Read|Grep|Glob` alternatives, and four events to add. Writes nothing.

Then run it for real, and confirm byte-stability:

```bash
python -m sccs integrations codex export-hooks
md5 ~/.codex/hooks.json
python -m sccs integrations codex export-hooks
md5 ~/.codex/hooks.json
```
Expected: identical checksums, and the second run reports "already up to date".

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "[ADD] integrations: export Claude hooks to Codex (v2.59.0)"
```

---

## Self-Review

**Spec coverage.** Target file and format → Tasks 1–2. Event coverage (10 shared, 9 dropped) → Task 1 + Task 5. Handler types → Task 1. Matcher warnings → Task 1. Trust flow → Task 4 (`/hooks` pointer) and Task 2 (byte-stability test). Decision 1 (scripts stay) → Task 1 rewrites no commands; documented in Task 6. Decision 2 (merge + state) → Tasks 2–3, ordering rule tested in Task 2. Decision 3 (strict + warn) → Task 1. Error-handling table → Task 3 readers. Serialization rules → Task 2. CLI incl. exclusion from `export-all` → Task 4. Testing section → Tasks 1–5. Documentation → Task 6. **No gaps.**

**Placeholder scan.** Every code step carries real code; every test step carries real assertions. The only prose-only steps are Task 6's documentation ones, which name the exact files, sections and required content.

**Type consistency.** `CodexHooksState.keys` is `set[HookKey]` throughout. `merge_hooks` returns a 3-tuple everywhere it appears. `build_hooks_plan` returns `(plan | None, error | None)` in Task 3 and is consumed that way in Task 4. `serialize_hooks_document` takes the full document (with the `hooks` wrapper) in both its definition and all call sites. `_codex_hooks_paths` returns `(settings, hooks)` in that order in the helper, the command, the status line and every test patch.
