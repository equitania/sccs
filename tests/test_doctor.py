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


# --------------------------------------------------------------------------- #
# Plugin scope detection + scope-aware update                                 #
# --------------------------------------------------------------------------- #


class TestPluginScopeDetection:
    """Real-world bug from Debian 13: `claude plugin list` reports
    `superpowers@claude-plugins-official` as installed (Scope: project),
    but `claude plugin update superpowers@claude-plugins-official` defaults
    to scope=user and dies with "Plugin … is not installed at scope user".

    Detection now reads the Scope: line; update forwards `--scope <value>`.
    """

    SAMPLE_OUTPUT_USER = """Installed plugins:

  ❯ skill-creator@claude-plugins-official
    Version: 1.2.3
    Scope: user
    Status: ✔ enabled
"""

    SAMPLE_OUTPUT_PROJECT = """Installed plugins:

  ❯ superpowers@claude-plugins-official
    Version: 3.4.1
    Scope: project
    Status: ✔ enabled
"""

    SAMPLE_OUTPUT_NO_SCOPE_LINE = """Installed plugins:

  ❯ legacy-plugin@some-marketplace
    Version: 0.1.0
"""

    SAMPLE_OUTPUT_TWO_PLUGINS = """Installed plugins:

  ❯ first-plugin@market-a
    Version: 1.0.0
    Scope: user
    Status: ✔ enabled

  ❯ second-plugin@market-b
    Version: 2.0.0
    Scope: project
    Status: ✔ enabled
"""

    def test_user_scope_extracted(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT_USER)
        statuses = detector.get_statuses([PluginSpec(name="skill-creator", marketplace="claude-plugins-official")])
        assert statuses[0].installed is True
        assert statuses[0].scope == "user"

    def test_project_scope_extracted(self):
        # The Debian 13 case: scope reported correctly so update doesn't
        # default to scope=user.
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT_PROJECT)
        statuses = detector.get_statuses([PluginSpec(name="superpowers", marketplace="claude-plugins-official")])
        assert statuses[0].installed is True
        assert statuses[0].scope == "project"

    def test_missing_scope_line_is_none(self):
        # Older CLI / odd outputs may omit the line entirely. None is fine —
        # update will fall through to its own default behaviour.
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT_NO_SCOPE_LINE)
        statuses = detector.get_statuses([PluginSpec(name="legacy-plugin")])
        assert statuses[0].installed is True
        assert statuses[0].scope is None

    def test_scope_does_not_bleed_across_neighbours(self):
        # Regression: the slice that follows the matched header must stop at
        # the next plugin block, otherwise we'd attribute neighbour scopes.
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT_TWO_PLUGINS)
        statuses = detector.get_statuses(
            [
                PluginSpec(name="first-plugin", marketplace="market-a"),
                PluginSpec(name="second-plugin", marketplace="market-b"),
            ]
        )
        assert statuses[0].scope == "user"
        assert statuses[1].scope == "project"


class TestPluginUpdateActionScopeForwarding:
    @staticmethod
    def _status_with_scope(name: str, marketplace: str, scope: str | None):
        from sccs.doctor.detectors import PluginStatus

        return PluginStatus(
            spec=PluginSpec(name=name, marketplace=marketplace),
            installed=True,
            update_available=None,
            detection_source="exact",
            found_marketplace=marketplace,
            scope=scope,
        )

    def test_update_action_appends_scope_flag_when_known(self):
        from sccs.doctor.installer import _plugin_update_actions

        st = self._status_with_scope("superpowers", "claude-plugins-official", "project")
        actions = _plugin_update_actions([st])
        assert actions[0].cmd == [
            "claude",
            "plugin",
            "update",
            "superpowers@claude-plugins-official",
            "--scope",
            "project",
        ]
        assert "scope: project" in actions[0].label

    def test_update_action_omits_scope_when_unknown(self):
        # Scope=None preserves prior behaviour: no flag, claude defaults to user.
        from sccs.doctor.installer import _plugin_update_actions

        st = self._status_with_scope("foo", "bar", None)
        actions = _plugin_update_actions([st])
        assert actions[0].cmd == ["claude", "plugin", "update", "foo@bar"]

    def test_update_action_drops_unknown_scope_value(self):
        # Defensive: only the four documented scope values get forwarded.
        # A future Claude CLI release that introduces a new scope is therefore
        # caught at our argv boundary instead of being passed through blindly.
        from sccs.doctor.installer import _plugin_update_actions

        st = self._status_with_scope("foo", "bar", "weirdscope")
        actions = _plugin_update_actions([st])
        assert actions[0].cmd == ["claude", "plugin", "update", "foo@bar"]


class TestPluginUpdateScopeMismatchSoftFail:
    """When `claude plugin update` reports the plugin as not installed at the
    chosen scope but our detection said it WAS installed, that's a list/update
    mismatch — not a real failure. Doctor classifies the action as `skipped`
    (not `failed`) so the overall report stays green for users whose plugins
    are installed under an unusual scope.
    """

    def test_not_installed_at_scope_user_is_skipped_not_failed(self):
        from sccs.doctor.installer import DoctorAction, InstallPlan
        from sccs.doctor.runner import DoctorError

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="update plugin superpowers@claude-plugins-official",
                    cmd=["claude", "plugin", "update", "superpowers@claude-plugins-official"],
                    runnable=True,
                    component="plugin:superpowers",
                )
            ]
        )
        err = DoctorError(
            "Command failed: claude plugin update superpowers@claude-plugins-official",
            returncode=1,
            stderr=(
                '✘ Failed to update plugin "superpowers@claude-plugins-official": '
                'Plugin "superpowers" is not installed at scope user'
            ),
        )
        with patch("sccs.doctor.installer._run", side_effect=err):
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)

        assert len(result.failed) == 0
        assert len(result.skipped) == 1
        assert "scope mismatch" in result.skipped[0].detail.lower()

    def test_other_plugin_failures_remain_failed(self):
        # Soft-fail is targeted: any other update error keeps its FAILED status.
        from sccs.doctor.installer import DoctorAction, InstallPlan
        from sccs.doctor.runner import DoctorError

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="update plugin foo@bar",
                    cmd=["claude", "plugin", "update", "foo@bar"],
                    runnable=True,
                    component="plugin:foo",
                )
            ]
        )
        err = DoctorError(
            "Command failed: claude plugin update foo@bar",
            returncode=2,
            stderr="network unreachable",
        )
        with patch("sccs.doctor.installer._run", side_effect=err):
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)

        assert len(result.failed) == 1
        assert len(result.skipped) == 0


# --------------------------------------------------------------------------- #
# Bundled-skill + browser-bundle detectors (v2.26.0)                          #
# --------------------------------------------------------------------------- #


class TestBundledSkillDetector:
    """Closes the v2.25.x gap: `sccs doctor check` was claiming OK whenever
    the npm tool's binary was on PATH, even if the bundled skill directory
    had been deleted. The detector now verifies the SKILL.md target exists.
    """

    def _spec_with_skill(self, target: str):
        from sccs.doctor.schema import BundledSkillSpec, NpxToolSpec

        return NpxToolSpec(
            name="playwright-cli",
            invocation=["npm", "install", "-g", "@playwright/cli@latest"],
            bundled_skill=BundledSkillSpec(
                package_subpath="@playwright/cli/skills/playwright-cli",
                target=target,
            ),
        )

    def test_skill_md_present_reports_ok(self, tmp_path):
        from sccs.doctor.detectors import BundledSkillDetector

        target = tmp_path / "skills" / "playwright-cli"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("# stub\n", encoding="utf-8")

        statuses = BundledSkillDetector().get_statuses([self._spec_with_skill(str(target))])
        assert statuses[0].skill_md_present is True
        assert statuses[0].target_path == str(target)

    def test_missing_skill_md_reports_missing(self, tmp_path):
        from sccs.doctor.detectors import BundledSkillDetector

        target = tmp_path / "skills" / "playwright-cli"
        # No mkdir — directory doesn't exist at all
        statuses = BundledSkillDetector().get_statuses([self._spec_with_skill(str(target))])
        assert statuses[0].skill_md_present is False

    def test_specs_without_bundled_skill_are_skipped(self):
        # get-shit-done-cc has no bundled_skill → must not appear in the
        # status list at all. Otherwise the reporter would print empty rows.
        from sccs.doctor.detectors import BundledSkillDetector
        from sccs.doctor.schema import NpxToolSpec

        plain = NpxToolSpec(name="get-shit-done-cc", invocation=["npx", "get-shit-done-cc"])
        statuses = BundledSkillDetector().get_statuses([plain])
        assert statuses == []


class TestBrowserBundleDetector:
    """Mirrors the `playwright install-browser` cache layout: bundles land
    under `<cache>/<name>-<version>/`, so we glob `<name>-*` per declared
    bundle and report missing ones.
    """

    def _spec_with_browsers(self, browsers: list[str]):
        from sccs.doctor.schema import NpxToolSpec

        return NpxToolSpec(
            name="playwright-cli",
            invocation=["npm", "install", "-g", "@playwright/cli@latest"],
            browser_bundles=browsers,
        )

    def test_all_bundles_present(self, tmp_path):
        from sccs.doctor.detectors import BrowserBundleDetector

        (tmp_path / "chromium-1234").mkdir()
        (tmp_path / "firefox-1515").mkdir()

        spec = self._spec_with_browsers(["chromium", "firefox"])
        statuses = BrowserBundleDetector(cache_dir=tmp_path).get_statuses([spec])
        assert statuses[0].present == {"chromium": True, "firefox": True}
        assert statuses[0].all_present is True
        assert statuses[0].cache_dir_exists is True

    def test_partial_bundles_present(self, tmp_path):
        from sccs.doctor.detectors import BrowserBundleDetector

        (tmp_path / "chromium-1234").mkdir()
        # firefox-* missing on purpose
        spec = self._spec_with_browsers(["chromium", "firefox"])
        statuses = BrowserBundleDetector(cache_dir=tmp_path).get_statuses([spec])
        assert statuses[0].present == {"chromium": True, "firefox": False}
        assert statuses[0].all_present is False

    def test_cache_dir_missing_marks_all_absent(self, tmp_path):
        from sccs.doctor.detectors import BrowserBundleDetector

        absent = tmp_path / "no-such-cache"
        spec = self._spec_with_browsers(["chromium", "firefox"])
        statuses = BrowserBundleDetector(cache_dir=absent).get_statuses([spec])
        assert statuses[0].cache_dir_exists is False
        assert all(v is False for v in statuses[0].present.values())
        assert statuses[0].all_present is False

    def test_env_override_takes_precedence(self, tmp_path, monkeypatch):
        # PLAYWRIGHT_BROWSERS_PATH must override the platform default. Without
        # this, users who relocate their cache (e.g. into an XDG-violating
        # custom path or a Docker volume) get false MISSING reports.
        from sccs.doctor.detectors import _resolve_playwright_cache

        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "custom"))
        resolved = _resolve_playwright_cache()
        assert str(resolved) == str(tmp_path / "custom")

    def test_macos_default_cache_path(self, monkeypatch):
        # Regression guard: macOS uses `~/Library/Caches/`, not `~/.cache/`.
        from sccs.doctor.detectors import _resolve_playwright_cache

        monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        monkeypatch.setattr("sccs.doctor.detectors.sys.platform", "darwin")
        resolved = _resolve_playwright_cache()
        assert str(resolved).endswith("/Library/Caches/ms-playwright")

    def test_specs_without_browser_bundles_are_skipped(self):
        from sccs.doctor.detectors import BrowserBundleDetector
        from sccs.doctor.schema import NpxToolSpec

        plain = NpxToolSpec(name="get-shit-done-cc", invocation=["npx", "get-shit-done-cc"])
        statuses = BrowserBundleDetector().get_statuses([plain])
        assert statuses == []


class TestBundledSkillReporter:
    def test_row_present(self, tmp_path):
        from sccs.doctor.detectors import BundledSkillStatus
        from sccs.doctor.reporter import _bundled_skill_row
        from sccs.doctor.schema import BundledSkillSpec, NpxToolSpec

        st = BundledSkillStatus(
            spec=NpxToolSpec(
                name="playwright-cli",
                invocation=["npm", "install", "-g", "@playwright/cli@latest"],
                bundled_skill=BundledSkillSpec(
                    package_subpath="@playwright/cli/skills/playwright-cli",
                    target=str(tmp_path),
                ),
            ),
            target_path=str(tmp_path),
            skill_md_present=True,
        )
        label, status, detail = _bundled_skill_row(st)
        assert label == "skill: playwright-cli"
        assert "OK" in status
        assert "SKILL.md" in detail

    def test_row_missing(self, tmp_path):
        from sccs.doctor.detectors import BundledSkillStatus
        from sccs.doctor.reporter import _bundled_skill_row
        from sccs.doctor.schema import BundledSkillSpec, NpxToolSpec

        st = BundledSkillStatus(
            spec=NpxToolSpec(
                name="playwright-cli",
                invocation=["npm", "install", "-g", "@playwright/cli@latest"],
                bundled_skill=BundledSkillSpec(
                    package_subpath="@playwright/cli/skills/playwright-cli",
                    target=str(tmp_path),
                ),
            ),
            target_path=str(tmp_path),
            skill_md_present=False,
        )
        _, status, detail = _bundled_skill_row(st)
        assert "MISSING" in status
        assert str(tmp_path) in detail


class TestBrowserBundleReporter:
    def test_row_all_present(self):
        from sccs.doctor.detectors import BrowserBundleStatus
        from sccs.doctor.reporter import _browser_bundle_row
        from sccs.doctor.schema import NpxToolSpec

        st = BrowserBundleStatus(
            spec=NpxToolSpec(
                name="playwright-cli",
                invocation=["npm", "install", "-g", "@playwright/cli@latest"],
                browser_bundles=["chromium", "firefox"],
            ),
            cache_dir="/tmp/cache",
            cache_dir_exists=True,
            present={"chromium": True, "firefox": True},
            all_present=True,
        )
        label, status, detail = _browser_bundle_row(st)
        assert label == "browsers: playwright-cli"
        assert "OK" in status
        assert "chromium, firefox" in detail

    def test_row_partial_present(self):
        from sccs.doctor.detectors import BrowserBundleStatus
        from sccs.doctor.reporter import _browser_bundle_row
        from sccs.doctor.schema import NpxToolSpec

        st = BrowserBundleStatus(
            spec=NpxToolSpec(
                name="playwright-cli",
                invocation=["npm", "install", "-g", "@playwright/cli@latest"],
                browser_bundles=["chromium", "firefox"],
            ),
            cache_dir="/tmp/cache",
            cache_dir_exists=True,
            present={"chromium": True, "firefox": False},
            all_present=False,
        )
        _, status, detail = _browser_bundle_row(st)
        assert "MISSING" in status
        assert "firefox" in detail
        assert "chromium" not in detail  # only missing bundles listed

    def test_row_cache_dir_missing(self):
        from sccs.doctor.detectors import BrowserBundleStatus
        from sccs.doctor.reporter import _browser_bundle_row
        from sccs.doctor.schema import NpxToolSpec

        st = BrowserBundleStatus(
            spec=NpxToolSpec(
                name="playwright-cli",
                invocation=["npm", "install", "-g", "@playwright/cli@latest"],
                browser_bundles=["chromium", "firefox"],
            ),
            cache_dir="/tmp/no-such-cache",
            cache_dir_exists=False,
            present={"chromium": False, "firefox": False},
            all_present=False,
        )
        _, status, detail = _browser_bundle_row(st)
        assert "MISSING" in status
        assert "cache dir not found" in detail


class TestBuildInstallPlanWithBundles:
    """When the npm tool itself is on PATH but the skill or browser bundles
    are missing, build_install_plan must queue targeted repair actions —
    rather than relying on the user to run `sccs doctor update`.
    """

    def _make_status_set_with_npx_present(self):
        # Helper: minimal happy-path status set so build_install_plan only
        # surfaces the bundle-repair actions we are asserting on.
        from sccs.doctor.defaults import DEFAULT_NPX_TOOLS

        s = _make_status_set(plugins_present={p.name: True for p in DEFAULT_CLAUDE_PLUGINS})
        # Override npx_tools so playwright-cli is reported AVAILABLE.
        from sccs.doctor.detectors import NpxToolStatus

        s["npx_tools"] = [
            NpxToolStatus(spec=spec, available=True, binary_path="/usr/bin/" + spec.name, detection_source="path")
            for spec in DEFAULT_NPX_TOOLS
        ]
        return s

    def test_missing_skill_appends_repair_action(self, tmp_path):
        from sccs.doctor.defaults import DEFAULT_NPX_TOOLS
        from sccs.doctor.detectors import BundledSkillStatus
        from sccs.doctor.installer import build_install_plan

        playwright_spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        skill_status = BundledSkillStatus(
            spec=playwright_spec,
            target_path=str(tmp_path / "skill"),
            skill_md_present=False,
        )

        cfg = DoctorConfig()
        s = self._make_status_set_with_npx_present()
        plan = build_install_plan(cfg, **s, bundled_skills=[skill_status])
        labels = [a.label for a in plan.actions]
        assert any("sync bundled skill playwright-cli" in lab for lab in labels)

    def test_missing_browser_appends_install_browser_action(self):
        from sccs.doctor.defaults import DEFAULT_NPX_TOOLS
        from sccs.doctor.detectors import BrowserBundleStatus
        from sccs.doctor.installer import build_install_plan

        playwright_spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        browser_status = BrowserBundleStatus(
            spec=playwright_spec,
            cache_dir="/tmp/cache",
            cache_dir_exists=True,
            present={"chromium": True, "firefox": False},
            all_present=False,
        )

        cfg = DoctorConfig()
        s = self._make_status_set_with_npx_present()
        plan = build_install_plan(cfg, **s, browser_bundles=[browser_status])
        commands = [a.cmd for a in plan.actions if a.cmd]
        assert ["playwright-cli", "install-browser", "firefox"] in commands
        # chromium was already there → no redundant action queued
        assert ["playwright-cli", "install-browser", "chromium"] not in commands

    def test_no_repair_when_tool_itself_missing(self, tmp_path):
        # When the npm tool isn't installed, the regular install action
        # already pulls everything (npm install → post_install → bundled_skill).
        # Adding repair actions on top would duplicate the work.
        from sccs.doctor.defaults import DEFAULT_NPX_TOOLS
        from sccs.doctor.detectors import BundledSkillStatus
        from sccs.doctor.installer import build_install_plan

        playwright_spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
        skill_status = BundledSkillStatus(
            spec=playwright_spec,
            target_path=str(tmp_path / "skill"),
            skill_md_present=False,
        )

        cfg = DoctorConfig()
        # Default _make_status_set: npx_tools all unavailable.
        s = _make_status_set(plugins_present={p.name: True for p in DEFAULT_CLAUDE_PLUGINS})
        plan = build_install_plan(cfg, **s, bundled_skills=[skill_status])
        # Skill-sync action is already in the plan via _npx_install_actions
        # (because the tool is missing). Count occurrences — must be exactly 1.
        skill_actions = [a for a in plan.actions if "sync bundled skill" in a.label]
        assert len(skill_actions) == 1


class TestHasProblemsWithBundles:
    def test_missing_skill_marks_problems(self):
        from sccs.doctor.detectors import BundledSkillStatus
        from sccs.doctor.reporter import has_problems

        all_plugins = {p.name: True for p in DEFAULT_CLAUDE_PLUGINS}
        all_tools = {t.name: True for t in DEFAULT_NPX_TOOLS}
        s = _make_status_set(plugins_present=all_plugins, tools_present=all_tools)
        skill = BundledSkillStatus(
            spec=DEFAULT_NPX_TOOLS[0],
            target_path="/missing",
            skill_md_present=False,
        )
        assert has_problems(**s, bundled_skills=[skill]) is True

    def test_missing_browser_marks_problems(self):
        from sccs.doctor.detectors import BrowserBundleStatus
        from sccs.doctor.reporter import has_problems

        all_plugins = {p.name: True for p in DEFAULT_CLAUDE_PLUGINS}
        all_tools = {t.name: True for t in DEFAULT_NPX_TOOLS}
        s = _make_status_set(plugins_present=all_plugins, tools_present=all_tools)
        browser = BrowserBundleStatus(
            spec=DEFAULT_NPX_TOOLS[0],
            cache_dir="/tmp",
            cache_dir_exists=False,
            present={"chromium": False},
            all_present=False,
        )
        assert has_problems(**s, browser_bundles=[browser]) is True

    def test_all_bundles_ok_does_not_mark_problems(self):
        from sccs.doctor.detectors import BrowserBundleStatus, BundledSkillStatus
        from sccs.doctor.reporter import has_problems

        all_plugins = {p.name: True for p in DEFAULT_CLAUDE_PLUGINS}
        all_tools = {t.name: True for t in DEFAULT_NPX_TOOLS}
        s = _make_status_set(plugins_present=all_plugins, tools_present=all_tools)
        skill = BundledSkillStatus(spec=DEFAULT_NPX_TOOLS[0], target_path="/ok", skill_md_present=True)
        browser = BrowserBundleStatus(
            spec=DEFAULT_NPX_TOOLS[0],
            cache_dir="/tmp",
            cache_dir_exists=True,
            present={"chromium": True, "firefox": True},
            all_present=True,
        )
        assert has_problems(**s, bundled_skills=[skill], browser_bundles=[browser]) is False


# --------------------------------------------------------------------------- #
# `npm root -g` permission check (v2.27.0)                                    #
# --------------------------------------------------------------------------- #


class TestNpmRootGlobalPermission:
    """Catches the second Debian-13 failure mode: system-wide npm install
    has its global root at /usr/lib/node_modules/, which is root-owned.
    `npm install -g @playwright/cli@latest` then dies with EACCES — and
    the previous SCCS would just report the failure post-hoc instead of
    surfacing the bad permission *before* attempting the install.
    """

    def test_default_includes_npm_root_global_check(self):
        from sccs.doctor.defaults import DEFAULT_PERMISSION_CHECKS

        npm_root_specs = [c for c in DEFAULT_PERMISSION_CHECKS if c.path_kind == "npm-root-global"]
        assert len(npm_root_specs) == 1
        assert npm_root_specs[0].path == "npm root -g"

    def test_skipped_when_npm_missing(self, monkeypatch):
        # `_resolve_npm_root_global` returning None must produce a skipped
        # PermissionStatus, not crash. Realistic on hosts where Node has not
        # been installed yet — doctor should still finish cleanly.
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        monkeypatch.setattr("sccs.doctor.detectors._resolve_npm_root_global", lambda: None)
        spec = PermissionCheckSpec(
            path="npm root -g",
            path_kind="npm-root-global",
            label="npm root",
            purpose="...",
        )
        statuses = PermissionDetector().get_statuses([spec])
        assert statuses[0].ok is True  # ok because skipped_reason is set
        assert statuses[0].skipped_reason is not None
        assert "npm not on PATH" in statuses[0].skipped_reason

    def test_user_writable_npm_root_is_ok(self, monkeypatch, tmp_path):
        # Happy path: `npm root -g` resolves to a directory owned by current
        # user. PermissionDetector treats it like any other literal path.
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        monkeypatch.setattr("sccs.doctor.detectors._resolve_npm_root_global", lambda: str(tmp_path))
        spec = PermissionCheckSpec(
            path="npm root -g",
            path_kind="npm-root-global",
            label="npm root",
            purpose="...",
        )
        statuses = PermissionDetector().get_statuses([spec])
        assert statuses[0].ok is True
        assert statuses[0].resolved_path == str(tmp_path)

    def test_root_owned_npm_root_triggers_manual_block_with_two_options(self, monkeypatch, tmp_path):
        # Simulate root ownership by stubbing PermissionStatus to look bad.
        # The manual block must contain BOTH fix options (npm prefix +
        # sudo chown) so the user can pick whichever fits their setup.
        import sccs.doctor.installer as installer_mod
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        spec = PermissionCheckSpec(
            path="npm root -g",
            path_kind="npm-root-global",
            label="npm global install dir",
            purpose="`npm install -g` writes here",
        )
        bad_status = PermissionStatus(
            spec=spec,
            exists=True,
            is_user_owned=False,
            is_writable=False,
            expected_uid=1000,
            expected_gid=1000,
            resolved_path="/usr/lib/node_modules",
            offending_paths=["/usr/lib/node_modules/some-pkg"],
        )
        actions = installer_mod._permission_actions([bad_status])
        assert len(actions) == 1
        block = actions[0].manual_block or ""
        # Both fix options must be present
        assert "npm config set prefix ~/.npm-global" in block
        assert "sudo chown -R 1000:1000 /usr/lib/node_modules" in block
        # PATH advice for both bash/zsh and fish must be present
        assert 'export PATH="$HOME/.npm-global/bin:$PATH"' in block
        assert "set -gx PATH $HOME/.npm-global/bin $PATH" in block
        # mkdir for lib/ + bin/ — guards against the ENOENT-on-first-npx
        # quirk we hit on Debian 13 right after `npm config set prefix`.
        assert "mkdir -p ~/.npm-global/lib ~/.npm-global/bin" in block
        assert actions[0].runnable is False  # manual only — never run by SCCS

    def test_literal_path_keeps_simple_chown_block(self, tmp_path):
        # Regression: literal paths (e.g. ~/.npm) must keep their old single-
        # option chown manual block — only npm-root-global gets the two-option
        # treatment. Otherwise we'd flood every permission issue with npm
        # advice that doesn't apply.
        import sccs.doctor.installer as installer_mod
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        spec = PermissionCheckSpec(
            path="~/.npm",
            label="npm cache",
            purpose="npx writes here",
        )
        bad_status = PermissionStatus(
            spec=spec,
            exists=True,
            is_user_owned=False,
            is_writable=False,
            expected_uid=1000,
            expected_gid=1000,
            resolved_path="/home/picard/.npm",
            offending_paths=["/home/picard/.npm/_cacache/foo"],
        )
        actions = installer_mod._permission_actions([bad_status])
        block = actions[0].manual_block or ""
        assert "sudo chown -R 1000:1000 /home/picard/.npm" in block
        assert "npm config set prefix" not in block  # npm advice stays scoped


class TestResolveNpmRootGlobal:
    def test_returns_none_when_npm_missing(self, monkeypatch):
        from sccs.doctor.detectors import _resolve_npm_root_global
        from sccs.doctor.runner import DoctorError

        def _raise(*_args, **_kwargs):
            raise DoctorError("Command not found: npm")

        monkeypatch.setattr("sccs.doctor.detectors._run", _raise)
        assert _resolve_npm_root_global() is None

    def test_returns_first_line_when_npm_succeeds(self, monkeypatch):
        from sccs.doctor.detectors import _resolve_npm_root_global

        fake_proc = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="/usr/lib/node_modules\n",
            stderr="",
        )
        monkeypatch.setattr("sccs.doctor.detectors._run", lambda *a, **kw: fake_proc)
        assert _resolve_npm_root_global() == "/usr/lib/node_modules"

    def test_returns_none_when_output_empty(self, monkeypatch):
        from sccs.doctor.detectors import _resolve_npm_root_global

        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="\n", stderr="")
        monkeypatch.setattr("sccs.doctor.detectors._run", lambda *a, **kw: fake_proc)
        assert _resolve_npm_root_global() is None


# --------------------------------------------------------------------------- #
# v2.28.0 — Cascade-Resilience & Marketplace Auto-Update                      #
# --------------------------------------------------------------------------- #


class TestCascadeSkip:
    """An action listing a failed component in `depends_on_components` is
    reported as `skipped` (not `failed`) and never spawns a subprocess.

    Real failure mode this guards against: `npm install -g @playwright/cli`
    dies with EACCES, then `playwright-cli install-browser chromium` runs
    anyway and fails with a redundant `Command not found`. v2.28.0 marks the
    second action as cascade-skipped instead of executing it blind.
    """

    def test_skipped_when_dependency_failed(self):
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install npx tool playwright-cli",
                    cmd=["npm", "install", "-g", "@playwright/cli@latest"],
                    runnable=True,
                    component="npx:playwright-cli",
                ),
                DoctorAction(
                    label="playwright-cli: install-browser chromium",
                    cmd=["playwright-cli", "install-browser", "chromium"],
                    runnable=True,
                    component="npx:playwright-cli:post:0",
                    depends_on_components=("npx:playwright-cli",),
                ),
            ]
        )
        with patch(
            "sccs.doctor.installer._run",
            side_effect=DoctorError("EACCES", returncode=13, stderr="EACCES on node_modules"),
        ) as run_mock:
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        # First action ran (and failed). Second was skipped — exactly one
        # subprocess call total.
        assert run_mock.call_count == 1
        assert len(result.failed) == 1
        assert len(result.skipped) == 1
        assert result.skipped[0].label.startswith("playwright-cli: install-browser")
        assert "depends on npx:playwright-cli" in result.skipped[0].detail

    def test_runs_normally_when_dependency_succeeded(self):
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install npx tool playwright-cli",
                    cmd=["npm", "install", "-g", "@playwright/cli@latest"],
                    runnable=True,
                    component="npx:playwright-cli",
                ),
                DoctorAction(
                    label="playwright-cli: install-browser chromium",
                    cmd=["playwright-cli", "install-browser", "chromium"],
                    runnable=True,
                    component="npx:playwright-cli:post:0",
                    depends_on_components=("npx:playwright-cli",),
                ),
            ]
        )
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with patch("sccs.doctor.installer._run", return_value=ok):
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        assert len(result.executed) == 2
        assert not result.skipped
        assert not result.failed


class TestManualBlockBlocksDownstream:
    """A `manual_block` action with `blocks_downstream=True` fences off any
    subsequent action that lists the same component in
    `depends_on_components` — even when `--yes` would otherwise green-light
    the next subprocess.

    Real failure mode: doctor printed the npm-root-global remediation block,
    then `--yes` ran the npm install anyway, which died with EACCES because
    the block hadn't been actioned. v2.28.0 reports the install as `skipped`
    with the manual block as the reason.
    """

    def test_manual_block_marks_component_blocked_for_downstream(self):
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="fix permissions: npm root -g",
                    cmd=None,
                    manual_block="npm config set prefix ~/.npm-global",
                    runnable=False,
                    component="perm:npm root -g",
                    blocks_downstream=True,
                ),
                DoctorAction(
                    label="install npx tool playwright-cli",
                    cmd=["npm", "install", "-g", "@playwright/cli@latest"],
                    runnable=True,
                    component="npx:playwright-cli",
                    depends_on_components=("perm:npm root -g",),
                ),
            ]
        )
        with patch("sccs.doctor.installer._run") as run_mock:
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        # Manual block printed, npm install never spawned.
        run_mock.assert_not_called()
        assert len(result.printed) == 1
        assert len(result.skipped) == 1
        assert result.skipped[0].label.startswith("install npx tool")
        assert "depends on perm:npm root -g" in result.skipped[0].detail

    def test_runnable_manual_block_without_flag_does_not_block(self):
        """A manual block WITHOUT `blocks_downstream=True` (legacy behaviour)
        still prints, but downstream actions are not auto-skipped.
        """
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="manual note",
                    cmd=None,
                    manual_block="just a note",
                    runnable=False,
                    component="note:foo",
                    blocks_downstream=False,
                ),
                DoctorAction(
                    label="run something",
                    cmd=["echo", "hi"],
                    runnable=True,
                    component="run:hi",
                    depends_on_components=("note:foo",),
                ),
            ]
        )
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="hi\n", stderr="")
        with patch("sccs.doctor.installer._run", return_value=ok) as run_mock:
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        run_mock.assert_called_once()
        assert len(result.executed) == 1


class TestNpxInstallCascade:
    """`_npx_install_actions()` wires `post_install` and `bundled_skill`
    actions to depend on the install component, so a failed install
    cascades cleanly into `skipped` rows for everything downstream.
    """

    def test_post_install_and_skill_depend_on_install(self):
        from sccs.doctor.detectors import NpxToolStatus
        from sccs.doctor.installer import _npx_install_actions
        from sccs.doctor.schema import BundledSkillSpec

        spec = NpxToolSpec(
            name="playwright-cli",
            invocation=["npm", "install", "-g", "@playwright/cli@latest"],
            detect_command="playwright-cli",
            post_install=[
                ["playwright-cli", "install-browser", "chromium"],
                ["playwright-cli", "install-browser", "firefox"],
            ],
            bundled_skill=BundledSkillSpec(
                package_subpath="@playwright/cli/skills/playwright-cli",
                target="~/.claude/skills/playwright-cli",
            ),
        )
        status = NpxToolStatus(spec=spec, available=False, binary_path=None)
        actions = _npx_install_actions([status])
        # 1 install + 2 post + 1 skill
        assert len(actions) == 4
        install, post0, post1, skill = actions
        assert install.component == "npx:playwright-cli"
        assert install.depends_on_components == ()
        assert "npx:playwright-cli" in post0.depends_on_components
        assert "npx:playwright-cli" in post1.depends_on_components
        assert "npx:playwright-cli" in skill.depends_on_components

    def test_install_failure_skips_post_install_and_skill(self):
        from sccs.doctor.detectors import NpxToolStatus
        from sccs.doctor.installer import InstallPlan, _npx_install_actions
        from sccs.doctor.schema import BundledSkillSpec

        spec = NpxToolSpec(
            name="playwright-cli",
            invocation=["npm", "install", "-g", "@playwright/cli@latest"],
            detect_command="playwright-cli",
            post_install=[["playwright-cli", "install-browser", "chromium"]],
            bundled_skill=BundledSkillSpec(
                package_subpath="@playwright/cli/skills/playwright-cli",
                target="~/.claude/skills/playwright-cli",
            ),
        )
        status = NpxToolStatus(spec=spec, available=False, binary_path=None)
        plan = InstallPlan(actions=_npx_install_actions([status]))
        with patch(
            "sccs.doctor.installer._run",
            side_effect=DoctorError("EACCES", returncode=13, stderr="EACCES"),
        ) as run_mock:
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        # Only the install was attempted; post_install and skill were skipped.
        assert run_mock.call_count == 1
        assert len(result.failed) == 1
        assert len(result.skipped) == 2  # post_install + bundled_skill


class TestMarketplaceUpdateBeforePluginInstall:
    """For PluginSpecs with `marketplace` but no `marketplace_source`, the
    install plan inserts a single `claude plugin marketplace update <name>`
    step per marketplace, marked `soft_fail=True`. Real failure mode:
    `claude plugin install skill-creator@claude-plugins-official` died with
    "Plugin not found in marketplace" because the local cache was stale.
    """

    def test_one_update_step_per_marketplace_before_first_install(self):
        from sccs.doctor.detectors import PluginStatus
        from sccs.doctor.installer import _plugin_install_actions

        spec_a = PluginSpec(name="skill-creator", marketplace="claude-plugins-official")
        spec_b = PluginSpec(name="superpowers", marketplace="claude-plugins-official")
        spec_c = PluginSpec(name="other", marketplace="other-market")

        statuses = [
            PluginStatus(spec=spec_a, installed=False, update_available=None),
            PluginStatus(spec=spec_b, installed=False, update_available=None),
            PluginStatus(spec=spec_c, installed=False, update_available=None),
        ]
        actions = _plugin_install_actions(statuses)
        # Expected order: update(claude-plugins-official), install(skill-creator),
        # install(superpowers), update(other-market), install(other).
        labels = [a.label for a in actions]
        assert labels == [
            "sync plugin marketplace: claude-plugins-official",
            "install plugin skill-creator@claude-plugins-official",
            "install plugin superpowers@claude-plugins-official",
            "sync plugin marketplace: other-market",
            "install plugin other@other-market",
        ]
        # Only the marketplace-update steps are soft-fail.
        soft = [a.label for a in actions if a.soft_fail]
        assert soft == [
            "sync plugin marketplace: claude-plugins-official",
            "sync plugin marketplace: other-market",
        ]

    def test_marketplace_source_skips_auto_update(self):
        """Plugins with an explicit `marketplace_source` already register the
        marketplace via `marketplace add` — no separate update step."""
        from sccs.doctor.detectors import PluginStatus
        from sccs.doctor.installer import _plugin_install_actions

        spec = PluginSpec(
            name="context-mode",
            marketplace="context-mode",
            marketplace_source="mksglu/context-mode",
        )
        actions = _plugin_install_actions(
            [PluginStatus(spec=spec, installed=False, update_available=None)]
        )
        labels = [a.label for a in actions]
        # No "sync plugin marketplace" step — the `marketplace add` covers it.
        assert "sync plugin marketplace: context-mode" not in labels
        assert any(lbl.startswith("register marketplace") for lbl in labels)
        assert any(lbl.startswith("install plugin") for lbl in labels)

    def test_soft_fail_marketplace_update_records_warned_status(self):
        """When the auto-update step itself fails, the install still runs and
        the user sees a `warned` row instead of red FAILED."""
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="sync plugin marketplace: claude-plugins-official",
                    cmd=["claude", "plugin", "marketplace", "update", "claude-plugins-official"],
                    runnable=True,
                    component="plugin-marketplace:claude-plugins-official:update",
                    soft_fail=True,
                ),
                DoctorAction(
                    label="install plugin skill-creator@claude-plugins-official",
                    cmd=["claude", "plugin", "install", "skill-creator@claude-plugins-official"],
                    runnable=True,
                    component="plugin:skill-creator",
                ),
            ]
        )
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="installed\n", stderr="")

        def _fake_run(cmd, *args, **kwargs):
            if "marketplace" in cmd:
                raise DoctorError("network error", returncode=1, stderr="ECONNRESET")
            return ok

        with patch("sccs.doctor.installer._run", side_effect=_fake_run):
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        # Update step warned, install still ran.
        assert len(result.warned) == 1
        assert "ECONNRESET" in result.warned[0].detail
        assert len(result.executed) == 1
        assert not result.failed


class TestNpmPrefixInPathDetection:
    """`PathPrefixDetector` resolves `<npm config get prefix>/bin` and
    verifies it is on $PATH. Triggered by the Debian 13 follow-up incident:
    user runs `npm config set prefix ~/.npm-global` to fix the EACCES
    block, but `~/.npm-global/bin` isn't yet in $PATH for the current shell,
    so every subsequent `playwright-cli install-browser …` step dies with
    "Command not found".
    """

    def test_in_path_returns_ok(self, monkeypatch):
        from sccs.doctor.detectors import PathPrefixDetector
        from sccs.doctor.schema import PathPrefixCheckSpec

        fake_proc = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="/home/u/.npm-global\n", stderr=""
        )
        monkeypatch.setattr("sccs.doctor.detectors._run", lambda *a, **kw: fake_proc)
        # Build env with the expected bin on PATH (use realpath to mirror
        # the detector's normalization).
        import os

        expected = os.path.realpath("/home/u/.npm-global/bin")
        env = {"PATH": f"{expected}:/usr/bin"}
        spec = PathPrefixCheckSpec(
            identifier="npm-prefix-bin",
            label="npm global bin in PATH",
            purpose="test",
        )
        statuses = PathPrefixDetector(env=env).get_statuses([spec])
        assert len(statuses) == 1
        assert statuses[0].in_path is True
        assert statuses[0].ok is True

    def test_missing_from_path_reports_not_ok(self, monkeypatch):
        from sccs.doctor.detectors import PathPrefixDetector
        from sccs.doctor.schema import PathPrefixCheckSpec

        fake_proc = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="/home/u/.npm-global\n", stderr=""
        )
        monkeypatch.setattr("sccs.doctor.detectors._run", lambda *a, **kw: fake_proc)
        env = {"PATH": "/usr/bin:/bin"}
        spec = PathPrefixCheckSpec(
            identifier="npm-prefix-bin",
            label="npm global bin in PATH",
            purpose="test",
        )
        statuses = PathPrefixDetector(env=env).get_statuses([spec])
        assert statuses[0].in_path is False
        assert statuses[0].ok is False
        assert statuses[0].expected_path.endswith(".npm-global/bin")

    def test_npm_missing_results_in_skipped_ok(self, monkeypatch):
        from sccs.doctor.detectors import PathPrefixDetector
        from sccs.doctor.schema import PathPrefixCheckSpec

        def _raise(*_args, **_kwargs):
            raise DoctorError("Command not found: npm")

        monkeypatch.setattr("sccs.doctor.detectors._run", _raise)
        spec = PathPrefixCheckSpec(
            identifier="npm-prefix-bin",
            label="npm global bin in PATH",
            purpose="test",
        )
        statuses = PathPrefixDetector(env={"PATH": ""}).get_statuses([spec])
        # Skipped → treated as OK so doctor doesn't loop on a missing-npm host.
        assert statuses[0].ok is True
        assert statuses[0].skipped_reason

    def test_install_plan_renders_manual_block_and_skips_post_install(self, monkeypatch):
        """End-to-end: PATH mismatch → manual block printed → npx
        post_install actions are reported as `skipped` instead of failing
        with `command not found`."""
        from sccs.doctor.detectors import (
            ClaudeCliStatus,
            NodeStatus,
            NpxToolStatus,
            PathPrefixStatus,
        )
        from sccs.doctor.installer import build_install_plan, execute_plan
        from sccs.doctor.schema import (
            BundledSkillSpec,
            DoctorConfig,
            NodeInstallSpec,
            PathPrefixCheckSpec,
        )

        spec = NpxToolSpec(
            name="playwright-cli",
            invocation=["npm", "install", "-g", "@playwright/cli@latest"],
            detect_command="playwright-cli",
            post_install=[["playwright-cli", "install-browser", "chromium"]],
            bundled_skill=BundledSkillSpec(
                package_subpath="@playwright/cli/skills/playwright-cli",
                target="~/.claude/skills/playwright-cli",
            ),
        )
        path_st = PathPrefixStatus(
            spec=PathPrefixCheckSpec(
                identifier="npm-prefix-bin",
                label="npm global bin in PATH",
                purpose="test",
            ),
            expected_path="/home/u/.npm-global/bin",
            in_path=False,
        )
        plan = build_install_plan(
            DoctorConfig(),
            node=NodeStatus(
                installed=True,
                version="20.10.0",
                major=20,
                meets_minimum=True,
                install_hint=NodeInstallSpec(runnable=False, label="x"),
                platform="linux",
            ),
            claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
            plugins=[],
            npx_tools=[NpxToolStatus(spec=spec, available=False, binary_path=None)],
            permissions=None,
            path_prefixes=[path_st],
        )
        labels = [a.label for a in plan.actions]
        assert any("add to PATH" in lbl for lbl in labels)

        # Execute: the install itself is allowed (writable npm root assumed),
        # but `playwright-cli install-browser chromium` should be skipped
        # because path:npm-prefix-bin is fenced off by the manual block.
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with patch("sccs.doctor.installer._run", return_value=ok) as run_mock:
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        # 1 install attempted; post_install (browser) skipped because PATH
        # check fenced the use_deps.
        ran_cmds = [str(call.args[0]) for call in run_mock.call_args_list]
        assert any("npm" in c and "install" in c for c in ran_cmds)
        assert not any("install-browser" in c for c in ran_cmds)
        skipped_labels = [o.label for o in result.skipped]
        assert any("install-browser chromium" in lbl for lbl in skipped_labels)


class TestDiagnoseHint:
    """`_diagnose_hint()` returns one-line user guidance for known stderr
    patterns. Verified to map the three failure modes from the Debian 13
    session (Plugin not found, EACCES on node_modules, command not found)
    to actionable next steps.
    """

    def test_plugin_not_found_hint(self):
        from sccs.doctor.installer import _diagnose_hint

        hint = _diagnose_hint("Plugin not found in marketplace 'claude-plugins-official'")
        assert hint is not None
        assert "marketplace update" in hint.lower()

    def test_eacces_node_modules_hint(self):
        from sccs.doctor.installer import _diagnose_hint

        hint = _diagnose_hint(
            "npm ERR! Error: EACCES: permission denied, mkdir '/usr/local/lib/node_modules/@playwright'"
        )
        assert hint is not None
        assert "manual block" in hint.lower()

    def test_command_not_found_hint(self):
        from sccs.doctor.installer import _diagnose_hint

        hint = _diagnose_hint("Command not found: playwright-cli")
        assert hint is not None
        assert "path" in hint.lower()

    def test_unknown_error_returns_none(self):
        from sccs.doctor.installer import _diagnose_hint

        assert _diagnose_hint("some unrelated error message") is None


# --------------------------------------------------------------------------- #
# v2.28.1 — Marketplace-Existenz + Multi-User                                 #
# --------------------------------------------------------------------------- #


class TestClaudeMarketplaceDetector:
    """Parses `claude plugin marketplace list` and reports per-marketplace
    registered/missing status. Real failure mode: `claude-plugins-official`
    was never registered on a Debian terminal server, so every plugin
    install for that marketplace died with "Plugin not found in marketplace".
    """

    def test_registered_marketplace_detected(self):
        from sccs.doctor.detectors import ClaudeMarketplaceDetector

        raw = (
            "❯ claude-plugins-official\n"
            "  Source: anthropics/claude-plugins-official\n"
            "  Plugins: 12\n"
            "❯ context-mode\n"
            "  Source: mksglu/context-mode\n"
        )
        det = ClaudeMarketplaceDetector(raw_output=raw)
        specs = [
            PluginSpec(name="skill-creator", marketplace="claude-plugins-official"),
            PluginSpec(
                name="context-mode",
                marketplace="context-mode",
                marketplace_source="mksglu/context-mode",
            ),
        ]
        statuses = {st.name: st for st in det.get_statuses(specs)}
        assert statuses["claude-plugins-official"].registered is True
        assert statuses["claude-plugins-official"].ok is True
        assert statuses["context-mode"].registered is True
        # `suggested_source` carried through from PluginSpec.marketplace_source.
        assert statuses["context-mode"].suggested_source == "mksglu/context-mode"

    def test_missing_marketplace_reported(self):
        from sccs.doctor.detectors import ClaudeMarketplaceDetector

        # Only `context-mode` is registered.
        raw = "❯ context-mode\n  Source: mksglu/context-mode\n"
        det = ClaudeMarketplaceDetector(raw_output=raw)
        specs = [
            PluginSpec(name="skill-creator", marketplace="claude-plugins-official"),
            PluginSpec(
                name="context-mode",
                marketplace="context-mode",
                marketplace_source="mksglu/context-mode",
            ),
        ]
        statuses = {st.name: st for st in det.get_statuses(specs)}
        assert statuses["claude-plugins-official"].registered is False
        assert statuses["claude-plugins-official"].ok is False
        assert statuses["claude-plugins-official"].suggested_source is None

    def test_skipped_when_claude_cli_missing(self):
        from sccs.doctor.detectors import ClaudeMarketplaceDetector

        det = ClaudeMarketplaceDetector(raw_output="")  # would otherwise be empty=missing
        specs = [PluginSpec(name="skill-creator", marketplace="claude-plugins-official")]
        statuses = det.get_statuses(specs, claude_cli_installed=False)
        assert statuses[0].skipped_reason == "claude CLI not installed"
        # `ok` is True so doctor doesn't double-count the missing CLI as a
        # marketplace failure (the missing CLI is reported elsewhere).
        assert statuses[0].ok is True

    def test_no_marketplace_in_specs_returns_empty(self):
        from sccs.doctor.detectors import ClaudeMarketplaceDetector

        det = ClaudeMarketplaceDetector(raw_output="")
        specs = [PluginSpec(name="claude-mem", marketplace=None, marketplace_source="thedotmack/claude-mem")]
        assert det.get_statuses(specs) == []


class TestPluginInstallSkipsWhenMarketplaceMissing:
    """When the configured marketplace is not registered, the matching
    `claude plugin install <name>@<marketplace>` step gains a dependency
    on `plugin-marketplace:<name>:exists`. The companion
    `_marketplace_missing_actions` provides a manual_block with the
    `marketplace add` command and `blocks_downstream=True`, so the cascade
    engine skips the install rather than queuing a guaranteed-failed
    subprocess.
    """

    def test_install_depends_on_marketplace_exists_when_missing(self):
        from sccs.doctor.detectors import MarketplaceStatus, PluginStatus
        from sccs.doctor.installer import _plugin_install_actions

        spec = PluginSpec(name="skill-creator", marketplace="claude-plugins-official")
        plugin_status = PluginStatus(spec=spec, installed=False, update_available=None)
        market_missing = MarketplaceStatus(
            name="claude-plugins-official", registered=False, suggested_source=None
        )
        actions = _plugin_install_actions([plugin_status], marketplaces=[market_missing])
        # No marketplace UPDATE step (cannot update a non-existent marketplace).
        assert not any(a.label.startswith("sync plugin marketplace") for a in actions)
        install = next(a for a in actions if a.label.startswith("install plugin"))
        assert "plugin-marketplace:claude-plugins-official:exists" in install.depends_on_components

    def test_install_has_no_marketplace_dep_when_registered(self):
        from sccs.doctor.detectors import MarketplaceStatus, PluginStatus
        from sccs.doctor.installer import _plugin_install_actions

        spec = PluginSpec(name="skill-creator", marketplace="claude-plugins-official")
        plugin_status = PluginStatus(spec=spec, installed=False, update_available=None)
        market_ok = MarketplaceStatus(name="claude-plugins-official", registered=True)
        actions = _plugin_install_actions([plugin_status], marketplaces=[market_ok])
        install = next(a for a in actions if a.label.startswith("install plugin"))
        assert install.depends_on_components == ()
        # Marketplace update IS queued (registered marketplace, stale-cache safety).
        assert any(a.label.startswith("sync plugin marketplace") for a in actions)

    def test_marketplace_missing_actions_emits_manual_block_with_source_hint(self):
        from sccs.doctor.detectors import MarketplaceStatus
        from sccs.doctor.installer import _marketplace_missing_actions

        statuses = [
            MarketplaceStatus(
                name="claude-plugins-official",
                registered=False,
                suggested_source="anthropics/claude-plugins-official",
            ),
        ]
        actions = _marketplace_missing_actions(statuses)
        assert len(actions) == 1
        action = actions[0]
        assert action.runnable is False
        assert action.blocks_downstream is True
        assert action.component == "plugin-marketplace:claude-plugins-official:exists"
        assert "claude plugin marketplace add anthropics/claude-plugins-official" in (action.manual_block or "")

    def test_marketplace_missing_block_without_source_hints_at_config(self):
        from sccs.doctor.detectors import MarketplaceStatus
        from sccs.doctor.installer import _marketplace_missing_actions

        statuses = [
            MarketplaceStatus(name="claude-plugins-official", registered=False, suggested_source=None),
        ]
        actions = _marketplace_missing_actions(statuses)
        block = actions[0].manual_block or ""
        assert "marketplace_source" in block
        assert "config.yaml" in block

    def test_end_to_end_install_skipped_when_marketplace_missing(self):
        """Exact reproduction of the Debian-13 multi-user incident:
        `claude-plugins-official` not registered → 3 plugin installs for it
        end up `skipped`, NOT failed."""
        from sccs.doctor.detectors import (
            ClaudeCliStatus,
            MarketplaceStatus,
            NodeStatus,
            PluginStatus,
        )
        from sccs.doctor.installer import build_install_plan, execute_plan
        from sccs.doctor.schema import DoctorConfig, NodeInstallSpec

        plugin_specs = [
            PluginSpec(name="skill-creator", marketplace="claude-plugins-official"),
            PluginSpec(name="superpowers", marketplace="claude-plugins-official"),
            PluginSpec(name="frontend-design", marketplace="claude-plugins-official"),
        ]
        plugin_statuses = [
            PluginStatus(spec=s, installed=False, update_available=None) for s in plugin_specs
        ]
        market_missing = [
            MarketplaceStatus(name="claude-plugins-official", registered=False, suggested_source=None)
        ]
        plan = build_install_plan(
            DoctorConfig(),
            node=NodeStatus(
                installed=True,
                version="20.10.0",
                major=20,
                meets_minimum=True,
                install_hint=NodeInstallSpec(runnable=False, label="x"),
                platform="linux",
            ),
            claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
            plugins=plugin_statuses,
            npx_tools=[],
            marketplaces=market_missing,
        )
        with patch("sccs.doctor.installer._run") as run_mock:
            result = execute_plan(plan, assume_yes=True, print_fn=lambda _: None)
        # Manual block printed once for the marketplace; three install
        # actions all reported as skipped; ZERO `claude plugin install`
        # subprocesses spawned.
        run_mock.assert_not_called()
        assert len(result.printed) == 1
        assert len(result.skipped) == 3
        assert all("plugin-marketplace:claude-plugins-official:exists" in o.detail for o in result.skipped)
        assert not result.failed


class TestMultiUserPermission:
    """`PermissionStatus.is_multi_user` and the `_npm_root_global_fix_block`
    that suppresses Option B on terminal-server boxes.

    Real failure mode: `/usr/local/lib/node_modules/` on a multi-user
    Debian terminal server held packages from several non-root users.
    Recommending `sudo chown -R <me>:<me>` would have silently destroyed
    those installs.
    """

    def test_is_multi_user_when_two_distinct_non_root_uids(self):
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        st = PermissionStatus(
            spec=PermissionCheckSpec(path="x", label="x", purpose="x"),
            exists=True,
            is_user_owned=False,
            is_writable=False,
            expected_uid=1009,
            expected_gid=1011,
            resolved_path="/usr/local/lib/node_modules",
            offending_paths=["/usr/local/lib/node_modules/bun"],
            foreign_uids={1001, 1002},  # two non-root uids ≠ self
        )
        assert st.is_multi_user is True

    def test_root_only_ownership_is_not_multi_user(self):
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        st = PermissionStatus(
            spec=PermissionCheckSpec(path="x", label="x", purpose="x"),
            exists=True,
            is_user_owned=False,
            is_writable=False,
            expected_uid=1009,
            expected_gid=1011,
            resolved_path="/usr/lib/node_modules",
            offending_paths=["/usr/lib/node_modules/foo"],
            foreign_uids={0},  # root only
        )
        assert st.is_multi_user is False

    def test_single_foreign_user_is_not_multi_user(self):
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        st = PermissionStatus(
            spec=PermissionCheckSpec(path="x", label="x", purpose="x"),
            exists=True,
            is_user_owned=False,
            is_writable=False,
            expected_uid=1009,
            expected_gid=1011,
            resolved_path="/usr/local/lib/node_modules",
            offending_paths=["/usr/local/lib/node_modules/foo"],
            foreign_uids={0, 1001},  # root + one user
        )
        assert st.is_multi_user is False

    def test_multi_user_block_suppresses_option_b(self):
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.installer import _npm_root_global_fix_block
        from sccs.doctor.schema import PermissionCheckSpec

        st = PermissionStatus(
            spec=PermissionCheckSpec(
                path="npm root -g",
                path_kind="npm-root-global",
                label="npm global install dir",
                purpose="x",
            ),
            exists=True,
            is_user_owned=False,
            is_writable=False,
            expected_uid=1009,
            expected_gid=1011,
            resolved_path="/usr/local/lib/node_modules",
            offending_paths=["/usr/local/lib/node_modules/bun"],
            foreign_uids={1001, 1002},
        )
        block = "\n".join(_npm_root_global_fix_block(st))
        # Option B suppressed; warning + uid list visible; Option A still there.
        assert "DO NOT" in block.upper() or "do not" in block.lower()
        assert "1001" in block and "1002" in block
        # The ACTUAL chown command (with uid:gid) must not be present, but
        # the prose warning *can* mention `sudo chown` to explain why.
        assert f"sudo chown -R 1009:1011 {st.resolved_path}" not in block
        assert "npm config set prefix ~/.npm-global" in block
        # The "Option B" *header* line must be gone — the warning doesn't
        # need to use the literal label. We check absence of the runnable
        # block by ensuring no chown command remains.
        for line in block.splitlines():
            assert not line.startswith("sudo chown -R"), f"runnable chown leaked: {line}"

    def test_single_admin_block_keeps_both_options(self):
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.installer import _npm_root_global_fix_block
        from sccs.doctor.schema import PermissionCheckSpec

        st = PermissionStatus(
            spec=PermissionCheckSpec(
                path="npm root -g",
                path_kind="npm-root-global",
                label="npm global install dir",
                purpose="x",
            ),
            exists=True,
            is_user_owned=False,
            is_writable=False,
            expected_uid=1009,
            expected_gid=1011,
            resolved_path="/usr/lib/node_modules",
            offending_paths=["/usr/lib/node_modules/foo"],
            foreign_uids={0},  # root only — single admin host
        )
        block = "\n".join(_npm_root_global_fix_block(st))
        assert "Option A" in block
        assert "Option B" in block
        assert "sudo chown" in block
