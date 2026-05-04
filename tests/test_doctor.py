# SCCS Doctor Tests
# Covers detection, install/update plan generation, argument-injection guards
# and the runner's no-shell / no-sudo policy.

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from sccs.doctor.defaults import (
    DEFAULT_CLAUDE_PLUGINS,
    DEFAULT_NPX_TOOLS,
    NODE_INSTALL,
    get_node_install_spec,
)
from sccs.doctor.detectors import (
    ClaudeCliDetector,
    ClaudePluginDetector,
    NodeDetector,
    NpxToolDetector,
)
from sccs.doctor.installer import (
    build_install_plan,
    build_update_plan,
    execute_plan,
)
from sccs.doctor.runner import DoctorError, _run, _validate_head, parse_node_major
from sccs.doctor.schema import DoctorConfig, NodeInstallSpec, NpxToolSpec, PluginSpec
from sccs.doctor.state import DoctorStateManager, _hash_invocation

# --------------------------------------------------------------------------- #
# Schema validation                                                           #
# --------------------------------------------------------------------------- #


class TestSchemaValidation:
    def test_plugin_spec_rejects_leading_dash(self):
        with pytest.raises(ValidationError):
            PluginSpec(name="--evil")

    def test_plugin_spec_rejects_shell_metacharacters(self):
        with pytest.raises(ValidationError):
            PluginSpec(name="evil; rm -rf /")

    def test_plugin_spec_accepts_scoped_npm_name(self):
        spec = PluginSpec(name="claude-mem", marketplace_source="thedotmack/claude-mem")
        assert spec.install_target == "claude-mem"

    def test_plugin_spec_install_target_with_marketplace(self):
        spec = PluginSpec(name="superpowers", marketplace="claude-plugins-official")
        assert spec.install_target == "superpowers@claude-plugins-official"

    def test_node_install_spec_rejects_sudo(self):
        with pytest.raises(ValidationError):
            NodeInstallSpec(runnable=True, cmd=["sudo", "apt-get", "install", "nodejs"])

    def test_npx_tool_spec_rejects_empty_invocation(self):
        with pytest.raises(ValidationError):
            NpxToolSpec(name="bad", invocation=[])


# --------------------------------------------------------------------------- #
# Runner — argument-injection guard                                           #
# --------------------------------------------------------------------------- #


class TestRunnerSecurity:
    def test_validate_head_rejects_option_prefix(self):
        with pytest.raises(DoctorError):
            _validate_head("--upload-pack=evil")

    def test_validate_head_rejects_metacharacters(self):
        with pytest.raises(DoctorError):
            _validate_head("foo;rm -rf /")

    def test_validate_head_rejects_sudo(self):
        with pytest.raises(DoctorError):
            _validate_head("sudo")

    def test_validate_head_accepts_known_safe_binaries(self):
        # The whitelist must allow standard binary names we ship in the
        # bundled defaults (brew, winget, npm, npx, node, claude).
        for binary in ("brew", "winget", "npm", "npx", "node", "claude"):
            _validate_head(binary)

    def test_validate_head_rejects_absolute_path(self):
        # Absolute paths are intentionally not allowed as argv heads — we
        # rely on PATH lookup for all bundled defaults.
        with pytest.raises(DoctorError):
            _validate_head("/usr/bin/node")

    def test_run_rejects_empty_cmd(self):
        with pytest.raises(DoctorError, match="Empty"):
            _run([])

    def test_run_propagates_filenotfound(self):
        # Missing binary surfaces as DoctorError, not FileNotFoundError
        with pytest.raises(DoctorError, match="Command not found"):
            _run(["this-binary-does-not-exist-xyz123"])


# --------------------------------------------------------------------------- #
# Node version parsing & detector                                             #
# --------------------------------------------------------------------------- #


class TestParseNodeMajor:
    def test_parses_v_prefixed_string(self):
        assert parse_node_major("20.10.0") == 20

    def test_handles_none(self):
        assert parse_node_major(None) is None

    def test_handles_garbage(self):
        assert parse_node_major("not-a-version") is None


class TestNodeDetector:
    def test_missing_node_returns_not_installed(self, monkeypatch):
        monkeypatch.setattr("sccs.doctor.detectors.run_node_version", lambda: None)
        status = NodeDetector(platform_name="macos").get_status(min_major=20)
        assert status.installed is False
        assert status.meets_minimum is False
        assert status.install_hint.cmd == ["brew", "install", "node"]

    def test_outdated_node_fails_minimum(self, monkeypatch):
        monkeypatch.setattr("sccs.doctor.detectors.run_node_version", lambda: "18.17.0")
        status = NodeDetector(platform_name="linux").get_status(min_major=20)
        assert status.installed is True
        assert status.major == 18
        assert status.meets_minimum is False
        # Linux must stay non-runnable so we never try to sudo
        assert status.install_hint.runnable is False

    def test_current_node_passes(self, monkeypatch):
        monkeypatch.setattr("sccs.doctor.detectors.run_node_version", lambda: "22.5.1")
        status = NodeDetector(platform_name="windows").get_status(min_major=20)
        assert status.installed is True
        assert status.meets_minimum is True
        assert status.install_hint.cmd == ["winget", "install", "OpenJS.NodeJS"]


# --------------------------------------------------------------------------- #
# Claude CLI / plugin / npx detectors                                         #
# --------------------------------------------------------------------------- #


class TestClaudeCliDetector:
    def test_missing_when_not_on_path(self, monkeypatch):
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
        status = ClaudeCliDetector().get_status()
        assert status.installed is False
        assert status.binary_path is None

    def test_present_when_on_path(self, monkeypatch):
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: "/usr/local/bin/claude")
        status = ClaudeCliDetector().get_status()
        assert status.installed is True
        assert status.binary_path == "/usr/local/bin/claude"


class TestClaudePluginDetector:
    SAMPLE_OUTPUT = """Installed plugins:

  ❯ claude-mem@thedotmack
    Version: 12.6.0

  ❯ context-mode@context-mode
    Version: 1.0.107

  ❯ skill-creator@claude-plugins-official
    Version: unknown
"""

    def test_marketplace_match_matches_full_target(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT)
        statuses = detector.get_statuses([PluginSpec(name="skill-creator", marketplace="claude-plugins-official")])
        assert statuses[0].installed is True

    def test_bare_name_match_when_marketplace_unspecified(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT)
        statuses = detector.get_statuses([PluginSpec(name="claude-mem")])
        assert statuses[0].installed is True

    def test_missing_plugin_detected(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT)
        statuses = detector.get_statuses([PluginSpec(name="superpowers", marketplace="claude-plugins-official")])
        assert statuses[0].installed is False

    def test_empty_output_means_all_missing(self):
        detector = ClaudePluginDetector(raw_output="")
        statuses = detector.get_statuses([PluginSpec(name="claude-mem"), PluginSpec(name="context-mode")])
        assert all(not s.installed for s in statuses)

    # --- New regex-based detection cases (v2.21.2 fix) --- #

    REAL_OUTPUT = """Installed plugins:

  ❯ claude-mem@thedotmack
    Version: 12.6.0
    Scope: user
    Status: ✔ enabled

  ❯ frontend-design@claude-code-plugins
    Version: 1.0.0

  ❯ frontend-design@claude-plugins-official
    Version: unknown

  ❯ skill-creator@claude-plugins-official
    Version: unknown

  ❯ superpowers-developing-for-claude-code@superpowers-marketplace
    Version: 0.3.1

  ❯ superpowers@superpowers-marketplace
    Version: 3.4.1
"""

    def test_alternative_marketplace_classified_as_installed(self):
        """superpowers@superpowers-marketplace must satisfy a request for
        superpowers@claude-plugins-official as 'alternative'."""
        detector = ClaudePluginDetector(raw_output=self.REAL_OUTPUT)
        statuses = detector.get_statuses([PluginSpec(name="superpowers", marketplace="claude-plugins-official")])
        st = statuses[0]
        assert st.installed is True
        assert st.detection_source == "alternative"
        assert st.found_marketplace == "superpowers-marketplace"

    def test_word_boundary_prevents_false_match_against_longer_name(self):
        """`superpowers@...` must not match the longer
        `superpowers-developing-for-claude-code@...` line."""
        # Output contains ONLY the longer plugin, not bare 'superpowers@...'
        output = (
            "Installed plugins:\n\n"
            "  ❯ superpowers-developing-for-claude-code@superpowers-marketplace\n"
            "    Version: 0.3.1\n"
        )
        detector = ClaudePluginDetector(raw_output=output)
        statuses = detector.get_statuses([PluginSpec(name="superpowers", marketplace="claude-plugins-official")])
        # The shorter name must NOT borrow the longer one's installation.
        assert statuses[0].installed is False
        assert statuses[0].detection_source == "missing"

    def test_exact_marketplace_match_preferred_over_alternative(self):
        """When BOTH the exact and an alternative marketplace are present,
        the result must be 'exact'."""
        detector = ClaudePluginDetector(raw_output=self.REAL_OUTPUT)
        statuses = detector.get_statuses([PluginSpec(name="frontend-design", marketplace="claude-plugins-official")])
        assert statuses[0].installed is True
        assert statuses[0].detection_source == "exact"
        assert statuses[0].found_marketplace == "claude-plugins-official"

    def test_no_marketplace_configured_treats_first_match_as_exact(self):
        """When the spec has no marketplace, any match is 'exact' for accounting."""
        detector = ClaudePluginDetector(raw_output=self.REAL_OUTPUT)
        statuses = detector.get_statuses([PluginSpec(name="claude-mem")])
        assert statuses[0].installed is True
        assert statuses[0].detection_source == "exact"
        assert statuses[0].found_marketplace == "thedotmack"


class TestNpxToolDetector:
    def test_present_when_binary_resolves(self, monkeypatch):
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: "/usr/local/bin/foo")
        statuses = NpxToolDetector().get_statuses([NpxToolSpec(name="foo", invocation=["npx", "foo"])])
        assert statuses[0].available is True
        assert statuses[0].binary_path == "/usr/local/bin/foo"

    def test_absent_when_binary_missing(self, monkeypatch):
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
        statuses = NpxToolDetector().get_statuses([NpxToolSpec(name="bar", invocation=["npx", "bar"])])
        assert statuses[0].available is False


# --------------------------------------------------------------------------- #
# DoctorConfig effective lists                                                #
# --------------------------------------------------------------------------- #


class TestDoctorConfig:
    def test_defaults_are_used_when_unspecified(self):
        cfg = DoctorConfig()
        assert [p.name for p in cfg.effective_plugins()] == [p.name for p in DEFAULT_CLAUDE_PLUGINS]
        assert [t.name for t in cfg.effective_npx_tools()] == [t.name for t in DEFAULT_NPX_TOOLS]

    def test_extra_plugins_are_appended(self):
        extra = [PluginSpec(name="custom-plugin", marketplace="my-marketplace")]
        cfg = DoctorConfig(extra_plugins=extra)
        names = [p.name for p in cfg.effective_plugins()]
        assert names[-1] == "custom-plugin"
        assert len(names) == len(DEFAULT_CLAUDE_PLUGINS) + 1

    def test_explicit_plugins_replace_defaults(self):
        cfg = DoctorConfig(plugins=[PluginSpec(name="only-this")])
        assert [p.name for p in cfg.effective_plugins()] == ["only-this"]


# --------------------------------------------------------------------------- #
# Install / update plan construction                                          #
# --------------------------------------------------------------------------- #


def _make_status_set(
    node_ok=True,
    cli_ok=True,
    plugins_present=None,
    tools_present=None,
    plugin_found_marketplace=None,
    plugin_detection_source=None,
):
    """Build the four detector results for plan tests.

    ``plugin_found_marketplace`` and ``plugin_detection_source`` accept
    ``{plugin_name: value}`` dicts so individual tests can simulate the
    alternative-marketplace and missing-marketplace cases.
    """
    from sccs.doctor.detectors import (
        ClaudeCliStatus,
        NodeStatus,
        NpxToolStatus,
        PluginStatus,
    )

    plugins_present = plugins_present if plugins_present is not None else {}
    tools_present = tools_present if tools_present is not None else {}
    plugin_found_marketplace = plugin_found_marketplace or {}
    plugin_detection_source = plugin_detection_source or {}

    plugin_statuses = [
        PluginStatus(
            spec=spec,
            installed=plugins_present.get(spec.name, False),
            update_available=None,
            detection_source=plugin_detection_source.get(
                spec.name, "exact" if plugins_present.get(spec.name, False) else "missing"
            ),
            found_marketplace=plugin_found_marketplace.get(spec.name),
        )
        for spec in DEFAULT_CLAUDE_PLUGINS
    ]
    tool_statuses = [
        NpxToolStatus(
            spec=spec,
            available=tools_present.get(spec.name, False),
            binary_path="/x" if tools_present.get(spec.name) else None,
        )
        for spec in DEFAULT_NPX_TOOLS
    ]

    node_status = NodeStatus(
        installed=node_ok,
        version="22.5.1" if node_ok else None,
        major=22 if node_ok else None,
        meets_minimum=node_ok,
        install_hint=get_node_install_spec("macos"),
        platform="macos",
    )
    return {
        "node": node_status,
        "claude_cli": ClaudeCliStatus(
            installed=cli_ok,
            binary_path="/usr/local/bin/claude" if cli_ok else None,
        ),
        "plugins": plugin_statuses,
        "npx_tools": tool_statuses,
    }


class TestBuildInstallPlan:
    def test_empty_plan_when_everything_present(self):
        cfg = DoctorConfig()
        all_plugins = {p.name: True for p in DEFAULT_CLAUDE_PLUGINS}
        all_tools = {t.name: True for t in DEFAULT_NPX_TOOLS}
        s = _make_status_set(plugins_present=all_plugins, tools_present=all_tools)
        plan = build_install_plan(cfg, **s)
        assert plan.is_empty()

    def test_install_plan_offers_node_via_brew_on_macos(self):
        cfg = DoctorConfig()
        s = _make_status_set(node_ok=False)
        plan = build_install_plan(cfg, **s)
        node_action = plan.actions[0]
        assert node_action.runnable is True
        assert node_action.cmd == ["brew", "install", "node"]

    def test_install_plan_uses_print_only_for_linux_node(self):
        cfg = DoctorConfig()
        s = _make_status_set(node_ok=False)
        s["node"].install_hint = NODE_INSTALL["linux"]
        plan = build_install_plan(cfg, **s)
        node_action = plan.actions[0]
        assert node_action.runnable is False
        assert node_action.cmd is None
        assert node_action.manual_block is not None
        assert "sudo" in node_action.manual_block

    def test_install_plan_registers_marketplace_then_plugin(self):
        cfg = DoctorConfig()
        s = _make_status_set()  # everything missing by default
        plan = build_install_plan(cfg, **s)
        # Find claude-mem related actions (it has marketplace_source)
        claude_mem_actions = [a for a in plan.actions if "claude-mem" in a.label]
        assert any("marketplace" in a.label for a in claude_mem_actions)
        # marketplace add must come BEFORE the install of the same plugin
        register_idx = next(i for i, a in enumerate(plan.actions) if "thedotmack/claude-mem" in a.label)
        install_idx = next(i for i, a in enumerate(plan.actions) if a.label == "install plugin claude-mem")
        assert register_idx < install_idx


class TestBuildUpdatePlan:
    def test_update_plan_includes_installed_plugins(self):
        cfg = DoctorConfig()
        s = _make_status_set(
            plugins_present={"claude-mem": True},
            plugin_found_marketplace={"claude-mem": "thedotmack"},
        )
        plan = build_update_plan(cfg, **s)
        labels = [a.label for a in plan.actions]
        assert any("update plugin claude-mem" in label for label in labels)

    def test_update_uses_found_marketplace_when_no_marketplace_configured(self):
        """v2.21.3 fix: PluginSpec without marketplace must update via the
        marketplace `claude plugin list` actually reports — `claude plugin
        update claude-mem` (bare) returns 'Plugin not found'."""
        cfg = DoctorConfig()
        s = _make_status_set(
            plugins_present={"claude-mem": True},
            plugin_found_marketplace={"claude-mem": "thedotmack"},
        )
        plan = build_update_plan(cfg, **s)
        actions = [a for a in plan.actions if a.component == "plugin:claude-mem"]
        assert actions, "expected an update action for claude-mem"
        assert actions[0].cmd == ["claude", "plugin", "update", "claude-mem@thedotmack"]
        assert actions[0].label == "update plugin claude-mem@thedotmack"

    def test_update_uses_alternative_marketplace_when_configured_marketplace_absent(self):
        """v2.21.3 fix: when superpowers is installed under
        `superpowers-marketplace` but the user configured
        `claude-plugins-official`, the update must hit the marketplace where
        the plugin actually lives — otherwise `claude plugin update` errors
        with 'Plugin "superpowers" is not installed'."""
        cfg = DoctorConfig()
        s = _make_status_set(
            plugins_present={"superpowers": True},
            plugin_found_marketplace={"superpowers": "superpowers-marketplace"},
            plugin_detection_source={"superpowers": "alternative"},
        )
        plan = build_update_plan(cfg, **s)
        actions = [a for a in plan.actions if a.component == "plugin:superpowers"]
        assert actions, "expected an update action for superpowers"
        # NOT spec.install_target ("superpowers@claude-plugins-official"),
        # which would fail at runtime — must be the actually-installed target.
        assert actions[0].cmd == [
            "claude",
            "plugin",
            "update",
            "superpowers@superpowers-marketplace",
        ]

    def test_update_falls_back_to_install_target_when_no_marketplace_known(self):
        """Defensive: if neither found_marketplace nor a configured marketplace
        is available, surface the bare name and let `claude plugin update`
        produce its own error message rather than silently dropping the action."""
        cfg = DoctorConfig()
        # claude-mem default has marketplace=None; simulate `claude plugin list`
        # output that contained no @marketplace token at all (bare-name match).
        s = _make_status_set(
            plugins_present={"claude-mem": True},
            plugin_found_marketplace={},
            plugin_detection_source={"claude-mem": "bare"},
        )
        plan = build_update_plan(cfg, **s)
        actions = [a for a in plan.actions if a.component == "plugin:claude-mem"]
        assert actions
        assert actions[0].cmd == ["claude", "plugin", "update", "claude-mem"]


# --------------------------------------------------------------------------- #
# execute_plan — confirm prompt / sudo / failure handling                     #
# --------------------------------------------------------------------------- #


class TestExecutePlan:
    def test_print_only_actions_are_never_executed(self):
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install Node.js via NodeSource",
                    cmd=None,
                    manual_block="sudo apt install nodejs",
                    runnable=False,
                    component="node",
                )
            ]
        )
        # If we mistakenly execute, _run would raise — patch and assert no call
        with patch("sccs.doctor.installer._run") as run_mock:
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        run_mock.assert_not_called()
        assert len(result.printed) == 1
        assert result.printed[0].status == "printed"

    def test_assume_yes_runs_confirmable_actions(self):
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install plugin foo",
                    cmd=["claude", "plugin", "install", "foo"],
                    runnable=True,
                    component="plugin:foo",
                )
            ]
        )
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with patch("sccs.doctor.installer._run", return_value=fake_proc) as run_mock:
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        run_mock.assert_called_once()
        assert len(result.executed) == 1

    def test_failed_action_recorded(self):
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install plugin bar",
                    cmd=["claude", "plugin", "install", "bar"],
                    runnable=True,
                )
            ]
        )
        with patch(
            "sccs.doctor.installer._run",
            side_effect=DoctorError("boom", returncode=2, stderr="upstream error"),
        ):
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        assert len(result.failed) == 1
        assert result.failed[0].detail == "upstream error"


# --------------------------------------------------------------------------- #
# SccsConfig integration: doctor block is optional & backwards compatible     #
# --------------------------------------------------------------------------- #


class TestSccsConfigBackwardsCompat:
    def test_legacy_config_without_doctor_block_loads(self):
        from sccs.config.schema import SccsConfig

        legacy = {
            "repository": {"path": "~/repo"},
            "sync_categories": {},
        }
        cfg = SccsConfig.model_validate(legacy)
        # doctor field defaulted to bundled DoctorConfig
        assert cfg.doctor.min_node_major == 20
        assert len(cfg.doctor.effective_plugins()) == len(DEFAULT_CLAUDE_PLUGINS)

    def test_user_can_override_min_node_major(self):
        from sccs.config.schema import SccsConfig

        data = {
            "repository": {"path": "~/repo"},
            "sync_categories": {},
            "doctor": {"min_node_major": 22},
        }
        cfg = SccsConfig.model_validate(data)
        assert cfg.doctor.min_node_major == 22


# --------------------------------------------------------------------------- #
# Doctor state — state-file fallback for npx tools without PATH binary        #
# --------------------------------------------------------------------------- #


class TestDoctorStateManager:
    def test_marks_and_recognises_run(self, tmp_path):
        state_path = tmp_path / ".doctor_state.yaml"
        mgr = DoctorStateManager(state_path=state_path)
        invocation = ["npx", "tool-x", "--global"]
        assert mgr.is_npx_tool_marked("tool-x", invocation) is False
        mgr.mark_npx_tool("tool-x", invocation)
        assert state_path.exists()
        assert mgr.is_npx_tool_marked("tool-x", invocation) is True

    def test_invocation_change_invalidates_state(self, tmp_path):
        mgr = DoctorStateManager(state_path=tmp_path / ".doctor_state.yaml")
        mgr.mark_npx_tool("tool-x", ["npx", "tool-x", "--v1"])
        # Same name, different invocation -> stale state, treat as missing
        assert mgr.is_npx_tool_marked("tool-x", ["npx", "tool-x", "--v2"]) is False

    def test_load_handles_missing_file(self, tmp_path):
        mgr = DoctorStateManager(state_path=tmp_path / "does-not-exist.yaml")
        state = mgr.load()
        assert state.npx_tools == {}

    def test_load_handles_corrupt_yaml(self, tmp_path):
        state_path = tmp_path / "broken.yaml"
        state_path.write_text(":\n:\n: not valid", encoding="utf-8")
        mgr = DoctorStateManager(state_path=state_path)
        state = mgr.load()  # must not raise
        assert state.npx_tools == {}

    def test_invocation_hash_is_deterministic(self):
        h1 = _hash_invocation(["npx", "tool", "--flag"])
        h2 = _hash_invocation(["npx", "tool", "--flag"])
        assert h1 == h2
        assert _hash_invocation(["npx", "tool", "--other"]) != h1


class TestNpxToolDetectorWithState:
    def test_state_fallback_marks_tool_available_when_path_missing(self, tmp_path, monkeypatch):
        """A state-tracked tool becomes available after a successful run is recorded."""
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
        state = DoctorStateManager(state_path=tmp_path / ".doctor_state.yaml")
        spec = NpxToolSpec(
            name="get-shit-done-cc",
            invocation=["npx", "get-shit-done-cc", "--global"],
            detect_via_state=True,
        )

        # Before the recorded run -> missing
        statuses = NpxToolDetector(state_manager=state).get_statuses([spec])
        assert statuses[0].available is False
        assert statuses[0].detection_source == "missing"

        # Record a successful run -> detector now reports available via state
        state.mark_npx_tool(spec.name, list(spec.invocation))
        statuses = NpxToolDetector(state_manager=state).get_statuses([spec])
        assert statuses[0].available is True
        assert statuses[0].detection_source == "state"
        assert statuses[0].binary_path is None

    def test_state_fallback_only_used_when_opted_in(self, tmp_path, monkeypatch):
        """Without detect_via_state=True the state cache must NOT shortcut detection."""
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
        state = DoctorStateManager(state_path=tmp_path / ".doctor_state.yaml")
        spec = NpxToolSpec(
            name="ordinary-tool",
            invocation=["npx", "ordinary-tool"],
            detect_via_state=False,
        )
        # Even with a state mark present, opt-out tools stay missing
        state.mark_npx_tool(spec.name, list(spec.invocation))
        statuses = NpxToolDetector(state_manager=state).get_statuses([spec])
        assert statuses[0].available is False
        assert statuses[0].detection_source == "missing"

    def test_path_lookup_wins_over_state(self, tmp_path, monkeypatch):
        """A real binary on PATH should be reported with detection_source='path'."""
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: "/usr/local/bin/x")
        state = DoctorStateManager(state_path=tmp_path / ".doctor_state.yaml")
        spec = NpxToolSpec(
            name="x",
            invocation=["npx", "x"],
            detect_via_state=True,
        )
        statuses = NpxToolDetector(state_manager=state).get_statuses([spec])
        assert statuses[0].available is True
        assert statuses[0].detection_source == "path"
        assert statuses[0].binary_path == "/usr/local/bin/x"


class TestExecutePlanRecordsState:
    def test_npx_tool_run_persists_state_marker(self, tmp_path):
        """A successful npx-tool action must write a state marker."""
        from sccs.doctor.installer import DoctorAction, InstallPlan

        state = DoctorStateManager(state_path=tmp_path / ".doctor_state.yaml")
        invocation = ["npx", "get-shit-done-cc", "--global"]
        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install npx tool get-shit-done-cc",
                    cmd=invocation,
                    runnable=True,
                    component="npx:get-shit-done-cc",
                    npx_tool_name="get-shit-done-cc",
                    npx_invocation=invocation,
                )
            ]
        )
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with patch("sccs.doctor.installer._run", return_value=fake_proc):
            execute_plan(
                plan,
                assume_yes=True,
                print_fn=lambda _: None,
                state_manager=state,
            )

        assert state.is_npx_tool_marked("get-shit-done-cc", invocation) is True

    def test_failed_action_does_not_record_state(self, tmp_path):
        """A failed npx-tool action must NOT write a state marker."""
        from sccs.doctor.installer import DoctorAction, InstallPlan

        state = DoctorStateManager(state_path=tmp_path / ".doctor_state.yaml")
        invocation = ["npx", "get-shit-done-cc", "--global"]
        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install npx tool get-shit-done-cc",
                    cmd=invocation,
                    runnable=True,
                    component="npx:get-shit-done-cc",
                    npx_tool_name="get-shit-done-cc",
                    npx_invocation=invocation,
                )
            ]
        )
        with patch(
            "sccs.doctor.installer._run",
            side_effect=DoctorError("boom", returncode=1),
        ):
            execute_plan(
                plan,
                assume_yes=True,
                print_fn=lambda _: None,
                state_manager=state,
            )

        assert state.is_npx_tool_marked("get-shit-done-cc", invocation) is False
