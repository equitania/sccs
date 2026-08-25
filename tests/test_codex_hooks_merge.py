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

MANAGED = {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "quality-gate.py"}]}]}

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
