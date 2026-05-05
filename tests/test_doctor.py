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

    def test_run_passes_stdin_devnull(self):
        # Defensive hardening: any doctor subprocess that asks for stdin
        # should fail fast instead of hanging the parent for `timeout` seconds.
        # Regression guard for the Debian 13 hang where npx asked
        # "Ok to proceed? (y)" and waited on stdin forever.
        fake = subprocess.CompletedProcess(args=["echo"], returncode=0, stdout="ok", stderr="")
        with patch("sccs.doctor.runner.subprocess.run", return_value=fake) as run_mock:
            _run(["echo", "x"])
        kwargs = run_mock.call_args.kwargs
        assert kwargs["stdin"] is subprocess.DEVNULL

    def test_default_npx_get_shit_done_uses_dash_y(self):
        # Without `-y`, npx prompts on stdout for "Need to install... Ok to
        # proceed?" on Linux/fresh systems — and capture_output=True hides
        # that prompt from the user. Regression guard for the v2.22.x Debian hang.
        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "get-shit-done-cc")
        assert spec.invocation[0] == "npx"
        assert spec.invocation[1] == "-y"

    def test_default_playwright_cli_uses_npm_install_global(self):
        # Playwright-CLI ships a real binary on PATH (unlike get-shit-done-cc)
        # and is invoked many times per session, so `npm install -g …@latest`
        # is preferred over a one-shot `npx -y`. Regression guard against a
        # future refactor that switches to npx and silently breaks the cached
        # binary lookup.
        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        assert spec.invocation == ["npm", "install", "-g", "@playwright/cli@latest"]
        assert spec.detect_command == "playwright-cli"
        assert spec.detect_via_state is False


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

    def test_playwright_cli_present_when_binary_on_path(self, monkeypatch):
        # End-to-end check that the new playwright-cli default flows through
        # the detector with detect_via_state=False (PATH-only lookup).
        monkeypatch.setattr(
            "sccs.doctor.detectors.which",
            lambda name: "/opt/homebrew/bin/playwright-cli" if name == "playwright-cli" else None,
        )
        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        statuses = NpxToolDetector().get_statuses([spec])
        assert statuses[0].available is True
        assert statuses[0].binary_path == "/opt/homebrew/bin/playwright-cli"

    def test_playwright_cli_missing_when_binary_absent(self, monkeypatch):
        # Without state-file fallback (detect_via_state=False), missing binary
        # must surface as not-installed so install_plan picks up the action.
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        statuses = NpxToolDetector().get_statuses([spec])
        assert statuses[0].available is False
        assert statuses[0].binary_path is None


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


# --------------------------------------------------------------------------- #
# Doctor-managed excludes — files installed by doctor tools must NOT sync     #
# --------------------------------------------------------------------------- #


class TestDoctorManagedExcludes:
    """v2.22.0: files installed by `sccs doctor install` (e.g. gsd-* via
    npx get-shit-done-cc) are reproducible from the doctor manifest, so
    `sccs sync` skips them to avoid cross-machine conflicts."""

    def test_default_npx_tools_contribute_gsd_pattern(self):
        from sccs.doctor.managed import get_doctor_managed_excludes

        cfg = DoctorConfig()  # default tools incl. get-shit-done-cc
        assert "gsd-*" in get_doctor_managed_excludes(cfg)

    def test_user_managed_excludes_are_appended(self):
        from sccs.doctor.managed import get_doctor_managed_excludes

        cfg = DoctorConfig(managed_excludes=["custom-*", "another-*"])
        excludes = get_doctor_managed_excludes(cfg)
        assert "custom-*" in excludes
        assert "another-*" in excludes
        assert "gsd-*" in excludes  # bundled default still present

    def test_excludes_are_deduplicated(self):
        from sccs.doctor.managed import get_doctor_managed_excludes

        cfg = DoctorConfig(managed_excludes=["gsd-*"])  # duplicate of bundled
        excludes = get_doctor_managed_excludes(cfg)
        assert excludes.count("gsd-*") == 1

    def test_npx_tool_removed_drops_its_pattern(self):
        from sccs.doctor.managed import get_doctor_managed_excludes

        # User explicitly clears the npx tool list — gsd-* must drop out.
        cfg = DoctorConfig(npx_tools=[])
        assert get_doctor_managed_excludes(cfg) == []

    def test_sync_engine_merges_doctor_excludes_into_global_exclude(self, tmp_path):
        """Verify the SyncEngine actually picks up the patterns and pushes
        them through to CategoryHandler.global_exclude (which is what the
        scan code reads). This is the integration that makes the bug fix
        observable end-to-end."""
        from sccs.config.schema import SccsConfig
        from sccs.sync.engine import SyncEngine

        repo = tmp_path / "repo"
        repo.mkdir()
        config = SccsConfig.model_validate(
            {
                "repository": {"path": str(repo)},
                "sync_categories": {
                    "claude_skills": {
                        "enabled": True,
                        "local_path": str(tmp_path / "skills"),
                        "repo_path": ".claude/skills",
                        "item_type": "directory",
                        "item_marker": "SKILL.md",
                    }
                },
                "global_exclude": [".DS_Store"],
            }
        )

        engine = SyncEngine(config)
        # gsd-* must be merged in via the doctor block, alongside the
        # explicit .DS_Store from global_exclude.
        assert ".DS_Store" in engine.effective_global_exclude
        assert "gsd-*" in engine.effective_global_exclude

    def test_managed_pattern_filters_real_directory_scan(self, tmp_path, monkeypatch):
        """End-to-end: a `gsd-foo/SKILL.md` directory is silently skipped
        by find_directories when the doctor exclude pattern is active."""
        from sccs.utils.paths import find_directories

        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "user-skill").mkdir()
        (skills / "user-skill" / "SKILL.md").write_text("...", encoding="utf-8")
        (skills / "gsd-managed").mkdir()
        (skills / "gsd-managed" / "SKILL.md").write_text("...", encoding="utf-8")

        # Without the exclude both are found
        all_dirs = find_directories(skills, marker="SKILL.md")
        assert {d.name for d in all_dirs} == {"user-skill", "gsd-managed"}

        # With gsd-* exclude only the user-owned one survives
        filtered = find_directories(skills, marker="SKILL.md", exclude=["gsd-*"])
        assert {d.name for d in filtered} == {"user-skill"}


# --------------------------------------------------------------------------- #
# Permission detector — guard against EACCES on ~/.npm and friends            #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not hasattr(__import__("os"), "getuid"), reason="POSIX-only")
class TestPermissionDetector:
    def test_nonexistent_path_is_ok(self, tmp_path):
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        spec = PermissionCheckSpec(
            path=str(tmp_path / "does-not-exist"),
            label="missing dir",
            purpose="test",
        )
        [status] = PermissionDetector().get_statuses([spec])
        assert status.exists is False
        assert status.ok is True
        assert status.fix_command is None

    def test_user_owned_path_is_ok(self, tmp_path):
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        # tmp_path is owned by the current user — perfect baseline.
        (tmp_path / "child.txt").write_text("hi", encoding="utf-8")
        spec = PermissionCheckSpec(
            path=str(tmp_path),
            label="user dir",
            purpose="test",
        )
        [status] = PermissionDetector().get_statuses([spec])
        assert status.exists is True
        assert status.is_user_owned is True
        assert status.is_writable is True
        assert status.ok is True
        assert status.offending_paths == []
        assert status.fix_command is None

    def test_foreign_owned_root_flagged(self, tmp_path, monkeypatch):
        # Simulate the Debian 13 case: tmp_path itself reports a different
        # owner than the current process. We patch os.getuid to return a uid
        # that nobody on the box uses — every stat() will then look "foreign".
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        (tmp_path / "child.txt").write_text("hi", encoding="utf-8")
        monkeypatch.setattr("sccs.doctor.detectors.os.getuid", lambda: 999999)
        monkeypatch.setattr("sccs.doctor.detectors.os.getgid", lambda: 999999)

        spec = PermissionCheckSpec(
            path=str(tmp_path),
            label="foreign-owned",
            purpose="test",
        )
        [status] = PermissionDetector().get_statuses([spec])
        assert status.exists is True
        assert status.is_user_owned is False
        assert status.ok is False
        # Both the root and the child should show up as foreign.
        assert str(tmp_path) in status.offending_paths
        assert any(p.endswith("child.txt") for p in status.offending_paths)
        # Fix command must contain the resolved path and the expected uid.
        assert status.fix_command is not None
        assert "sudo chown -R 999999:999999" in status.fix_command
        assert str(tmp_path) in status.fix_command

    def test_offenders_are_capped(self, tmp_path, monkeypatch):
        # Even with thousands of files we should not blow up — the detector
        # caps both the scan budget and the offender list. The user only
        # needs a few examples in the report.
        from sccs.doctor.detectors import (
            _MAX_OFFENDERS_REPORTED,
            PermissionDetector,
        )
        from sccs.doctor.schema import PermissionCheckSpec

        for i in range(20):
            (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
        monkeypatch.setattr("sccs.doctor.detectors.os.getuid", lambda: 999999)
        monkeypatch.setattr("sccs.doctor.detectors.os.getgid", lambda: 999999)

        spec = PermissionCheckSpec(path=str(tmp_path), label="big", purpose="test")
        [status] = PermissionDetector().get_statuses([spec])
        assert len(status.offending_paths) <= _MAX_OFFENDERS_REPORTED

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        # Specs may use ~ — the detector must expand it before stat()ing.
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "marker").write_text("ok", encoding="utf-8")

        spec = PermissionCheckSpec(path="~/marker", label="home file", purpose="test")
        [status] = PermissionDetector().get_statuses([spec])
        assert status.resolved_path == str(tmp_path / "marker")
        assert status.exists is True
        assert status.ok is True


class TestPermissionInstallPlan:
    def test_permission_issue_creates_manual_block_at_front(self, tmp_path, monkeypatch):
        # End-to-end: a foreign-owned ~/.npm-style path should produce a
        # runnable=False action that prints the chown fix BEFORE any other
        # action runs.
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.installer import build_install_plan
        from sccs.doctor.schema import DoctorConfig, PermissionCheckSpec

        if not hasattr(__import__("os"), "getuid"):
            pytest.skip("POSIX-only")

        (tmp_path / "x").write_text("hi", encoding="utf-8")
        monkeypatch.setattr("sccs.doctor.detectors.os.getuid", lambda: 999999)
        monkeypatch.setattr("sccs.doctor.detectors.os.getgid", lambda: 999999)

        spec = PermissionCheckSpec(path=str(tmp_path), label="cache", purpose="test cache")
        [perm_status] = PermissionDetector().get_statuses([spec])

        cfg = DoctorConfig()
        all_plugins = {p.name: True for p in DEFAULT_CLAUDE_PLUGINS}
        all_tools = {t.name: True for t in DEFAULT_NPX_TOOLS}
        s = _make_status_set(plugins_present=all_plugins, tools_present=all_tools)
        plan = build_install_plan(cfg, **s, permissions=[perm_status])

        # Plan should now contain exactly one action — the manual permission block.
        assert len(plan.actions) == 1
        action = plan.actions[0]
        assert action.runnable is False
        assert action.cmd is None
        assert "fix permissions" in action.label
        assert "sudo chown -R 999999:999999" in (action.manual_block or "")

    def test_default_permission_checks_cover_npm_and_claude(self):
        # Regression guard: the bundled defaults must include ~/.npm so the
        # Debian incident doesn't silently fall off the radar in a refactor.
        from sccs.doctor.defaults import DEFAULT_PERMISSION_CHECKS

        paths = [c.path for c in DEFAULT_PERMISSION_CHECKS]
        assert "~/.npm" in paths
        assert "~/.claude" in paths
        assert "~/.config/sccs" in paths


# --------------------------------------------------------------------------- #
# Playwright-CLI: post_install + bundled_skill                                #
# --------------------------------------------------------------------------- #


class TestPlaywrightCliBundling:
    """Covers the post_install (browser bundles) and bundled_skill (SKILL.md
    sync from the npm package) features added for `playwright-cli`.

    The same generic mechanism backs any future npm-tool spec that wants to
    run follow-up commands or ship a Claude skill — the tests intentionally
    use the playwright-cli default to lock in the real-world contract.
    """

    def test_default_playwright_cli_has_browser_post_install(self):
        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        assert ["playwright-cli", "install-browser", "chromium"] in spec.post_install
        assert ["playwright-cli", "install-browser", "firefox"] in spec.post_install

    def test_default_playwright_cli_has_bundled_skill(self):
        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        assert spec.bundled_skill is not None
        assert spec.bundled_skill.package_subpath == "@playwright/cli/skills/playwright-cli"
        assert spec.bundled_skill.target == "~/.claude/skills/playwright-cli"

    def test_playwright_cli_managed_pattern_excludes_skill_from_sync(self):
        # `~/.claude/skills/playwright-cli/` must be auto-excluded so two
        # machines that both run `sccs doctor` don't fight over the tree.
        from sccs.doctor.managed import get_doctor_managed_excludes

        cfg = DoctorConfig()  # bundled defaults
        patterns = get_doctor_managed_excludes(cfg)
        assert "playwright-cli" in patterns

    def test_install_plan_appends_post_install_for_missing_tool(self):
        """Missing playwright-cli → install + 2 browsers + skill-sync."""
        from sccs.doctor.detectors import NpxToolStatus
        from sccs.doctor.installer import _npx_install_actions

        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        status = NpxToolStatus(spec=spec, available=False, binary_path=None, detection_source="missing")
        actions = _npx_install_actions([status])
        labels = [a.label for a in actions]
        # Order must be: main install → browser:chromium → browser:firefox → skill-sync
        assert labels[0] == "install npx tool playwright-cli"
        assert "install-browser chromium" in labels[1]
        assert "install-browser firefox" in labels[2]
        assert labels[3].startswith("sync bundled skill playwright-cli")
        # The skill action is python_callable, not subprocess.
        assert actions[3].cmd is None
        assert actions[3].python_callable is not None

    def test_update_plan_always_re_runs_post_install_and_skill(self):
        """Update path must re-run browser fetch + skill sync even when the
        main tool is already on PATH — that's how doctor catches new browser
        bundles and refreshed SKILL.md content shipping in npm updates."""
        from sccs.doctor.detectors import NpxToolStatus
        from sccs.doctor.installer import _npx_update_actions

        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        status = NpxToolStatus(
            spec=spec,
            available=True,
            binary_path="/opt/homebrew/bin/playwright-cli",
            detection_source="path",
        )
        actions = _npx_update_actions([status])
        labels = [a.label for a in actions]
        assert any("install-browser chromium" in lab for lab in labels)
        assert any("install-browser firefox" in lab for lab in labels)
        assert any(lab.startswith("sync bundled skill playwright-cli") for lab in labels)

    def test_sync_bundled_skill_copies_directory_into_target(self, tmp_path, monkeypatch):
        """End-to-end: fake `npm root -g` → fake source tree → expect copy."""
        from sccs.doctor.installer import _sync_bundled_skill
        from sccs.doctor.schema import BundledSkillSpec

        # Fake npm global root with a skill payload
        fake_npm_root = tmp_path / "npm_global"
        skill_src = fake_npm_root / "@vendor/cli/skills/my-skill"
        (skill_src / "references").mkdir(parents=True)
        (skill_src / "SKILL.md").write_text("# my skill\n", encoding="utf-8")
        (skill_src / "references" / "ref.md").write_text("ref\n", encoding="utf-8")

        target = tmp_path / "claude_home" / "skills" / "my-skill"
        bs = BundledSkillSpec(package_subpath="@vendor/cli/skills/my-skill", target=str(target))

        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=f"{fake_npm_root}\n", stderr="")
        with patch("sccs.doctor.installer._run", return_value=fake_proc):
            _sync_bundled_skill(bs)

        assert (target / "SKILL.md").read_text(encoding="utf-8") == "# my skill\n"
        assert (target / "references" / "ref.md").read_text(encoding="utf-8") == "ref\n"

    def test_sync_bundled_skill_overwrites_existing_target(self, tmp_path):
        """A second run replaces the directory — npm package is the source of truth."""
        from sccs.doctor.installer import _sync_bundled_skill
        from sccs.doctor.schema import BundledSkillSpec

        fake_npm_root = tmp_path / "npm_global"
        skill_src = fake_npm_root / "p/skills/s"
        skill_src.mkdir(parents=True)
        (skill_src / "SKILL.md").write_text("v2\n", encoding="utf-8")

        target = tmp_path / "skills" / "s"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("v1-stale\n", encoding="utf-8")
        (target / "stray.md").write_text("should be removed\n", encoding="utf-8")

        bs = BundledSkillSpec(package_subpath="p/skills/s", target=str(target))
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=f"{fake_npm_root}\n", stderr="")
        with patch("sccs.doctor.installer._run", return_value=fake_proc):
            _sync_bundled_skill(bs)

        assert (target / "SKILL.md").read_text(encoding="utf-8") == "v2\n"
        assert not (target / "stray.md").exists()  # full replace, not merge

    def test_sync_bundled_skill_raises_on_missing_source(self, tmp_path):
        from sccs.doctor.installer import _sync_bundled_skill
        from sccs.doctor.runner import DoctorError
        from sccs.doctor.schema import BundledSkillSpec

        bs = BundledSkillSpec(package_subpath="does/not/exist", target=str(tmp_path / "s"))
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=f"{tmp_path}\n", stderr="")
        with (
            patch("sccs.doctor.installer._run", return_value=fake_proc),
            pytest.raises(DoctorError, match="bundled skill source not found"),
        ):
            _sync_bundled_skill(bs)

    def test_execute_plan_runs_python_callable(self, tmp_path):
        """python_callable actions execute in-process and report success."""
        from sccs.doctor.installer import DoctorAction, InstallPlan

        marker = tmp_path / "marker"

        def _do() -> None:
            marker.write_text("done", encoding="utf-8")

        plan = InstallPlan(actions=[DoctorAction(label="custom", runnable=True, python_callable=_do)])
        result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        assert marker.exists()
        assert result.executed[0].label == "custom"

    def test_post_install_spec_validation_rejects_dash_head(self):
        # Same security guard as `invocation`: argv[0] must not start with '-'
        with pytest.raises(ValidationError):
            NpxToolSpec(
                name="x",
                invocation=["npx", "x"],
                post_install=[["--rm-rf-flag"]],
            )
