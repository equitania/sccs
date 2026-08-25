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

    def test_hand_extended_group_does_not_duplicate_the_owned_handler(self):
        # Regression: state owns backup.sh alone. The user hand-adds a second
        # handler to that same group inside Codex, which makes the group read
        # as foreign (mixed ownership). The managed copy of backup.sh must not
        # be re-appended as a second group, or it fires twice on every run.
        managed = {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "backup.sh"}]}]}
        state = CodexHooksState(keys={("PostToolUse", "Bash", "backup.sh")})
        hand_extended = {
            "matcher": "Bash",
            "hooks": [
                {"type": "command", "command": "backup.sh"},
                {"type": "command", "command": "user-added.sh"},
            ],
        }
        existing = {"hooks": {"PostToolUse": [hand_extended]}}

        document, _, warnings = merge_hooks(existing, managed, state)
        groups = document["hooks"]["PostToolUse"]

        commands = [handler["command"] for group in groups for handler in group["hooks"]]
        assert commands.count("backup.sh") == 1
        assert commands.count("user-added.sh") == 1
        assert groups == [hand_extended]  # the user's group survives untouched
        assert any("backup.sh" in w for w in warnings)
        assert not any("no longer found" in w for w in warnings)

    def test_stray_non_dict_element_prevents_replacement(self):
        """Finding 1b: group_keys() silently skips a non-dict element when

        computing keys, which used to let _is_managed treat a group as fully
        owned even though it holds something SCCS never wrote (a bare string
        hand-appended to a group it wrote outright). Replacing such a group
        would discard that element with no warning — Finding 1's failure
        mode one level down. It must now be classified as foreign instead.
        """
        state = CodexHooksState(keys={("PostToolUse", "Edit|Write", "quality-gate.py")})
        mixed = {
            "matcher": "Edit|Write",
            "hooks": [
                {"type": "command", "command": "quality-gate.py"},
                "user-added-string",
            ],
        }
        existing = {"hooks": {"PostToolUse": [mixed]}}

        document, _, warnings = merge_hooks(existing, MANAGED, state)
        groups = document["hooks"]["PostToolUse"]

        assert groups == [mixed]  # untouched, stray element included verbatim
        assert "user-added-string" in groups[0]["hooks"]
        assert any("quality-gate.py" in w for w in warnings)

    def test_group_with_only_non_dict_elements_stays_foreign(self):
        # No regression: group_keys() already returned [] for a group with no
        # dict handlers at all, so it was foreign before this fix too — must
        # keep behaving exactly the same.
        odd = {"matcher": "Bash", "hooks": ["not-a-dict", 5, None]}
        existing = {"hooks": {"PreToolUse": [odd]}}
        document, _, _ = merge_hooks(existing, {}, CodexHooksState())
        assert document["hooks"]["PreToolUse"] == [odd]


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

    def test_event_value_that_is_an_object_instead_of_a_list_is_refused(self, tmp_path):
        """Finding 1 (CRITICAL): a dict where a list belongs used to be silently

        dropped by merge_hooks (`.get(event, []) or []` folds the truthy dict
        to `[]`), erasing the user's entry on the next write with no warning.
        The reader must refuse instead.
        """
        from sccs.integrations.codex_hooks import read_codex_hooks

        path = tmp_path / "hooks.json"
        path.write_text(
            json.dumps({"hooks": {"PreToolUse": {"matcher": "Bash", "hooks": []}}}),
            encoding="utf-8",
        )
        document, error = read_codex_hooks(path)
        assert document == {}
        assert error is not None and "PreToolUse" in error

    def test_event_list_containing_a_non_object_element_is_refused(self, tmp_path):
        """A bare string inside an event's list would silently vanish too —

        merge_hooks' `if not isinstance(group, dict): continue` never
        re-appends it to the preserved foreign groups.
        """
        from sccs.integrations.codex_hooks import read_codex_hooks

        path = tmp_path / "hooks.json"
        path.write_text(json.dumps({"hooks": {"PreToolUse": ["not-a-group"]}}), encoding="utf-8")
        document, error = read_codex_hooks(path)
        assert document == {}
        assert error is not None and "PreToolUse[0]" in error


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

    def test_malformed_event_shape_aborts_the_plan_and_writes_nothing(self, tmp_path):
        """Finding 1 end-to-end: the exact reproduction from the review.

        `{"PreToolUse": {"matcher": "Bash", "hooks": []}}` used to pass the
        reader, get folded away by merge_hooks, and vanish from the file on
        the next write with `plan.warnings == []`. Now the plan must abort and
        the target file must be byte-for-byte untouched.
        """
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan

        settings = self._settings(tmp_path, MANAGED)
        hooks_path = tmp_path / "hooks.json"
        original_bytes = json.dumps({"hooks": {"PreToolUse": {"matcher": "Bash", "hooks": []}}}).encode("utf-8")
        hooks_path.write_bytes(original_bytes)
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        plan, error = build_hooks_plan(settings, hooks_path, manager)
        assert plan is None
        assert error is not None and "PreToolUse" in error

        # There is no plan to hand write_hooks_plan in this case — the CLI
        # never calls it when build_hooks_plan errors (see codex_export_hooks).
        # The invariant under test is that the abort happened before any write,
        # so the file on disk is exactly what it was.
        assert hooks_path.read_bytes() == original_bytes


class TestWriteErrors:
    """Finding 2: the write path must never leak a raw traceback."""

    def _settings(self, tmp_path, hooks):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
        return path

    def test_unwritable_hooks_parent_returns_a_clean_error(self, tmp_path):
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan, write_hooks_plan

        settings = self._settings(tmp_path, MANAGED)
        # A regular file sitting where the hooks.json parent directory needs
        # to be: mkdir(parents=True) raises FileExistsError (an OSError
        # subclass), the same failure class a read-only ~/.codex/ produces.
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        hooks_path = blocker / "hooks.json"
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        plan, error = build_hooks_plan(settings, hooks_path, manager)
        assert error is None
        assert plan is not None

        write_error = write_hooks_plan(plan, hooks_path, manager)
        assert write_error is not None
        assert "hooks.json" in write_error
        assert not hooks_path.exists()

    def test_state_save_failure_still_reports_an_error(self, tmp_path):
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan, write_hooks_plan

        settings = self._settings(tmp_path, MANAGED)
        hooks_path = tmp_path / "hooks.json"
        # Same trick for the state path's parent: the hooks file write
        # succeeds first, then the state save hits the blocked parent.
        blocker = tmp_path / "state_blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        manager = CodexHooksStateManager(state_path=blocker / "state.yaml")

        plan, error = build_hooks_plan(settings, hooks_path, manager)
        assert error is None

        write_error = write_hooks_plan(plan, hooks_path, manager)
        assert write_error is not None
        assert "ownership state" in write_error
        # The hooks file itself was written successfully before the failure.
        assert hooks_path.exists()
        assert json.loads(hooks_path.read_text())["hooks"] == MANAGED


class TestNoOpGuard:
    """Finding 3: a genuine no-op must not write a file or claim success falsely."""

    def _settings(self, tmp_path, hooks):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
        return path

    def test_zero_hooks_and_no_target_file_is_a_true_no_op(self, tmp_path):
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan, write_hooks_plan

        settings = self._settings(tmp_path, {})
        hooks_path = tmp_path / "hooks.json"
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        plan, error = build_hooks_plan(settings, hooks_path, manager)
        assert error is None
        assert plan.unchanged is True

        write_error = write_hooks_plan(plan, hooks_path, manager)
        assert write_error is None
        assert not hooks_path.exists()

    def test_removing_every_claude_hook_still_rewrites_an_existing_target(self, tmp_path):
        """The self-correcting case must keep working: once a target file

        exists with SCCS-managed content, removing every hook on the Claude
        side must still strip that content out on the next export.
        """
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan, write_hooks_plan

        hooks_path = tmp_path / "hooks.json"
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        settings = self._settings(tmp_path, MANAGED)
        plan, _ = build_hooks_plan(settings, hooks_path, manager)
        write_hooks_plan(plan, hooks_path, manager)
        assert hooks_path.exists()

        settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        plan2, _ = build_hooks_plan(settings, hooks_path, manager)
        assert plan2.unchanged is False
        assert plan2.removed == ["PostToolUse / quality-gate.py"]

        write_hooks_plan(plan2, hooks_path, manager)
        assert json.loads(hooks_path.read_text())["hooks"] == {}


class TestPartialAccounting:
    """Finding 1b end-to-end: a group SCCS owns must not be replaced — and

    its stray content discarded — just because group_keys() silently skipped
    an element it could not turn into a key.
    """

    def _settings(self, tmp_path, hooks):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
        return path

    def test_hand_added_stray_element_survives_a_full_export_cycle(self, tmp_path):
        """The re-reviewer's exact repro: export, hand-append a bare string

        into the managed group's `hooks` list, re-export with Claude
        unchanged. The string must still be present in the written file.
        """
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan, write_hooks_plan

        settings = self._settings(tmp_path, MANAGED)
        hooks_path = tmp_path / "hooks.json"
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        plan, _ = build_hooks_plan(settings, hooks_path, manager)
        write_hooks_plan(plan, hooks_path, manager)

        doc = json.loads(hooks_path.read_text())
        doc["hooks"]["PostToolUse"][0]["hooks"].append("user-added-string")
        hooks_path.write_text(json.dumps(doc), encoding="utf-8")

        plan2, error = build_hooks_plan(settings, hooks_path, manager)
        assert error is None
        assert any("quality-gate.py" in w for w in plan2.warnings)

        write_error = write_hooks_plan(plan2, hooks_path, manager)
        assert write_error is None

        written = json.loads(hooks_path.read_text())
        handlers = written["hooks"]["PostToolUse"][0]["hooks"]
        assert "user-added-string" in handlers
        assert {"type": "command", "command": "quality-gate.py"} in handlers

    def test_group_with_only_non_dict_elements_stays_foreign(self, tmp_path):
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan, write_hooks_plan

        settings = self._settings(tmp_path, {})
        hooks_path = tmp_path / "hooks.json"
        odd_group = {"matcher": "Bash", "hooks": ["not-a-dict"]}
        hooks_path.write_text(json.dumps({"hooks": {"PreToolUse": [odd_group]}}), encoding="utf-8")
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        plan, error = build_hooks_plan(settings, hooks_path, manager)
        assert error is None
        assert plan.document["hooks"]["PreToolUse"] == [odd_group]

        write_error = write_hooks_plan(plan, hooks_path, manager)
        assert write_error is None
        written = json.loads(hooks_path.read_text())
        assert written["hooks"]["PreToolUse"] == [odd_group]

    def test_ordinary_managed_group_is_still_replaced(self, tmp_path):
        """The common path must not regress: a fully-accountable managed

        group that state already owns is still replaced on re-export (e.g.
        after a timeout value changes), not frozen in place forever.
        """
        from sccs.integrations.codex_hooks import CodexHooksStateManager, build_hooks_plan, write_hooks_plan

        settings = self._settings(tmp_path, MANAGED)
        hooks_path = tmp_path / "hooks.json"
        manager = CodexHooksStateManager(state_path=tmp_path / "state.yaml")

        plan, _ = build_hooks_plan(settings, hooks_path, manager)
        write_hooks_plan(plan, hooks_path, manager)

        updated_managed = {
            "PostToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [{"type": "command", "command": "quality-gate.py", "timeout": 30}],
                }
            ]
        }
        settings.write_text(json.dumps({"hooks": updated_managed}), encoding="utf-8")

        plan2, error = build_hooks_plan(settings, hooks_path, manager)
        assert error is None
        assert plan2.unchanged is False

        write_error = write_hooks_plan(plan2, hooks_path, manager)
        assert write_error is None

        written = json.loads(hooks_path.read_text())
        assert written["hooks"]["PostToolUse"][0]["hooks"][0]["timeout"] == 30
