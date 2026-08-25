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
        assert {
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
        } == CODEX_HOOK_EVENTS

    def test_claude_only_event_is_dropped_with_a_named_warning(self):
        block = {"PostToolUseFailure": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "x.sh"}]}]}
        converted, warnings = convert_hooks_block(block)
        assert converted == {}
        assert any("PostToolUseFailure" in w for w in warnings)
        assert any("Codex" in w for w in warnings)

    def test_shared_event_survives(self):
        block = {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "q.py"}]}]}
        converted, warnings = convert_hooks_block(block)
        assert converted == {
            "PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "q.py"}]}]
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
