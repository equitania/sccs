# SCCS Doctor Tests
# Covers detection, install/update plan generation, argument-injection guards
# and the runner's no-shell / no-sudo policy.

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from sccs.doctor.defaults import (
    DEFAULT_CLAUDE_PLUGINS,
    DEFAULT_IGNORED_MCP_PATTERNS,
    DEFAULT_NPX_TOOLS,
    NODE_INSTALL,
    get_node_install_spec,
)
from sccs.doctor.detectors import (
    ClaudeCliDetector,
    ClaudePluginDetector,
    ForeignMCPServerStatus,
    ForeignPluginStatus,
    MCPServerDetector,
    NodeDetector,
    NpxToolDetector,
    SettingsHookDetector,
    SettingsHookViolation,
)
from sccs.doctor.installer import (
    _settings_hook_cleanup_actions,
    build_install_plan,
    build_optimize_plan,
    build_update_plan,
    execute_plan,
)
from sccs.doctor.runner import DoctorError, _run, _validate_head, parse_node_major
from sccs.doctor.schema import DoctorConfig, MCPServerSpec, NodeInstallSpec, NpxToolSpec, PluginSpec
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

    def test_npx_tool_spec_accepts_scoped_npm_name(self):
        # Scoped npm packages (leading '@') must be valid npx-tool names so
        # GSD's `@opengsd/get-shit-done-redux` can be a default tool. '@' is
        # not an option-injection vector — only a leading '-' is.
        spec = NpxToolSpec(name="@opengsd/get-shit-done-redux", invocation=["npx", "@opengsd/get-shit-done-redux"])
        assert spec.name == "@opengsd/get-shit-done-redux"

    def test_npx_tool_spec_still_rejects_leading_dash_name(self):
        # The option-injection guard must survive the leading-'@' allowance.
        with pytest.raises(ValidationError):
            NpxToolSpec(name="--evil", invocation=["npx", "x"])


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
        spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "@opengsd/get-shit-done-redux")
        assert spec.invocation[0] == "npx"
        assert spec.invocation[1] == "-y"

    def test_default_playwright_cli_uses_npm_install_global(self):
        # Playwright-CLI ships a real binary on PATH (unlike @opengsd/get-shit-done-redux)
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
    specs=None,
):
    """Build the four detector results for plan tests.

    ``plugin_found_marketplace`` and ``plugin_detection_source`` accept
    ``{plugin_name: value}`` dicts so individual tests can simulate the
    alternative-marketplace and missing-marketplace cases.

    ``specs`` overrides the plugin specs the status set is built from
    (defaults to DEFAULT_CLAUDE_PLUGINS). Tests needing a plugin shape no
    longer present in the defaults (e.g. a bare marketplace=None plugin)
    pass their own list.
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
    specs = specs if specs is not None else DEFAULT_CLAUDE_PLUGINS

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
        for spec in specs
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
        # claude-mem shape (marketplace=None + marketplace_source) is no longer
        # a default; inject it so this test still exercises the register-then-
        # install ordering for source-based plugins.
        claude_mem = PluginSpec(name="claude-mem", marketplace=None, marketplace_source="thedotmack/claude-mem")
        s = _make_status_set(specs=[claude_mem])  # everything missing by default
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
        claude_mem = PluginSpec(name="claude-mem", marketplace=None, marketplace_source="thedotmack/claude-mem")
        s = _make_status_set(
            specs=[claude_mem],
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
        claude_mem = PluginSpec(name="claude-mem", marketplace=None, marketplace_source="thedotmack/claude-mem")
        s = _make_status_set(
            specs=[claude_mem],
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
        # A marketplace=None plugin; simulate `claude plugin list` output that
        # contained no @marketplace token at all (bare-name match).
        claude_mem = PluginSpec(name="claude-mem", marketplace=None, marketplace_source="thedotmack/claude-mem")
        s = _make_status_set(
            specs=[claude_mem],
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

    def test_auto_confirm_runs_without_prompt(self):
        """auto_confirm=True bypasses questionary even when assume_yes=False."""
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="update plugin foo",
                    cmd=["claude", "plugin", "update", "foo"],
                    runnable=True,
                    component="plugin:foo",
                    auto_confirm=True,
                )
            ]
        )
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with (
            patch("sccs.doctor.installer._run", return_value=fake_proc) as run_mock,
            patch("sccs.doctor.installer.questionary") as q_mock,
        ):
            result = execute_plan(plan, assume_yes=False, print_fn=lambda _: None)
        run_mock.assert_called_once()
        q_mock.confirm.assert_not_called()  # never prompted
        assert len(result.executed) == 1

    def test_destructive_action_still_prompts_when_not_auto(self):
        """auto_confirm=False (e.g. uninstall) keeps the confirm gate; declining skips it."""
        from sccs.doctor.installer import DoctorAction, InstallPlan

        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="update plugin foo",
                    cmd=["claude", "plugin", "update", "foo"],
                    runnable=True,
                    component="plugin:foo",
                    auto_confirm=True,
                ),
                DoctorAction(
                    label="REMOVE foreign plugin bar@baz",
                    cmd=["claude", "plugin", "uninstall", "bar@baz"],
                    runnable=True,
                    component="plugin:bar",
                    auto_confirm=False,
                ),
            ]
        )
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        # questionary.confirm(...).ask() → False: the user declines the uninstall.
        with (
            patch("sccs.doctor.installer._run", return_value=fake_proc) as run_mock,
            patch("sccs.doctor.installer.questionary") as q_mock,
        ):
            q_mock.confirm.return_value.ask.return_value = False
            result = execute_plan(plan, assume_yes=False, print_fn=lambda _: None)
        # Only the auto_confirm update ran; the uninstall was prompted and declined.
        run_mock.assert_called_once()
        q_mock.confirm.assert_called_once()
        assert len(result.executed) == 1
        assert len(result.skipped) == 1
        assert result.skipped[0].detail == "user declined"


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
            name="@opengsd/get-shit-done-redux",
            invocation=["npx", "@opengsd/get-shit-done-redux", "--global"],
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
        invocation = ["npx", "@opengsd/get-shit-done-redux", "--global"]
        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install npx tool @opengsd/get-shit-done-redux",
                    cmd=invocation,
                    runnable=True,
                    component="npx:@opengsd/get-shit-done-redux",
                    npx_tool_name="@opengsd/get-shit-done-redux",
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

        assert state.is_npx_tool_marked("@opengsd/get-shit-done-redux", invocation) is True

    def test_failed_action_does_not_record_state(self, tmp_path):
        """A failed npx-tool action must NOT write a state marker."""
        from sccs.doctor.installer import DoctorAction, InstallPlan

        state = DoctorStateManager(state_path=tmp_path / ".doctor_state.yaml")
        invocation = ["npx", "@opengsd/get-shit-done-redux", "--global"]
        plan = InstallPlan(
            actions=[
                DoctorAction(
                    label="install npx tool @opengsd/get-shit-done-redux",
                    cmd=invocation,
                    runnable=True,
                    component="npx:@opengsd/get-shit-done-redux",
                    npx_tool_name="@opengsd/get-shit-done-redux",
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

        assert state.is_npx_tool_marked("@opengsd/get-shit-done-redux", invocation) is False


# --------------------------------------------------------------------------- #
# Doctor-managed excludes — files installed by doctor tools must NOT sync     #
# --------------------------------------------------------------------------- #


class TestDoctorManagedExcludes:
    """v2.22.0: files installed by `sccs doctor install` (e.g. gsd-* via
    npx @opengsd/get-shit-done-redux) are reproducible from the doctor manifest, so
    `sccs sync` skips them to avoid cross-machine conflicts."""

    def test_default_npx_tools_contribute_gsd_pattern(self):
        from sccs.doctor.managed import get_doctor_managed_excludes

        cfg = DoctorConfig()  # default tools incl. @opengsd/get-shit-done-redux
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
        # v2.33.2: also monkeypatch Path.home() to tmp_path so the resolved
        # path lies *under* $HOME — the new fix_command safety guard returns
        # None for paths outside $HOME (system prefixes like /usr) where
        # chown is unsafe AND incomplete. tmp_path on macOS resolves to
        # /private/var/folders/... which is OUTSIDE $HOME, so without this
        # patch the chown branch never fires.
        from pathlib import Path

        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        (tmp_path / "child.txt").write_text("hi", encoding="utf-8")
        monkeypatch.setattr("sccs.doctor.detectors.os.getuid", lambda: 999999)
        monkeypatch.setattr("sccs.doctor.detectors.os.getgid", lambda: 999999)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

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

        # v2.33.2: fix_command returns None outside $HOME (system-prefix guard).
        # The chown branch only fires for in-$HOME paths, so spoof Path.home().
        from pathlib import Path

        (tmp_path / "x").write_text("hi", encoding="utf-8")
        monkeypatch.setattr("sccs.doctor.detectors.os.getuid", lambda: 999999)
        monkeypatch.setattr("sccs.doctor.detectors.os.getgid", lambda: 999999)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

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
        # @opengsd/get-shit-done-redux has no bundled_skill → must not appear in the
        # status list at all. Otherwise the reporter would print empty rows.
        from sccs.doctor.detectors import BundledSkillDetector
        from sccs.doctor.schema import NpxToolSpec

        plain = NpxToolSpec(name="@opengsd/get-shit-done-redux", invocation=["npx", "@opengsd/get-shit-done-redux"])
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

        plain = NpxToolSpec(name="@opengsd/get-shit-done-redux", invocation=["npx", "@opengsd/get-shit-done-redux"])
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

    def test_home_owned_npm_root_triggers_manual_block_with_two_options(self, monkeypatch, tmp_path):
        # Root-owned npm root UNDER the user's home (e.g. ~/.npm-global chowned
        # to root by a stray `sudo npm`). Here `sudo chown` IS safe and complete
        # (the sibling bin dir is also under home), so BOTH options must show.
        import sccs.doctor.installer as installer_mod
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        home_root = str(Path.home() / ".npm-global" / "lib" / "node_modules")
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
            resolved_path=home_root,
            offending_paths=[home_root + "/some-pkg"],
        )
        actions = installer_mod._permission_actions([bad_status])
        assert len(actions) == 1
        block = actions[0].manual_block or ""
        # Both fix options must be present for a home-relative path
        assert "npm config set prefix ~/.npm-global" in block
        assert f"sudo chown -R 1000:1000 {home_root}" in block
        # PATH advice for both bash/zsh and fish must be present
        assert 'export PATH="$HOME/.npm-global/bin:$PATH"' in block
        assert "set -gx PATH $HOME/.npm-global/bin $PATH" in block
        # mkdir for lib/ + bin/ — guards against the ENOENT-on-first-npx
        # quirk we hit on Debian 13 right after `npm config set prefix`.
        assert "mkdir -p ~/.npm-global/lib ~/.npm-global/bin" in block
        assert actions[0].runnable is False  # manual only — never run by SCCS

    def test_system_npm_root_suppresses_chown_option(self):
        # System path (/usr/lib/node_modules, NOT under $HOME): `sudo chown` of
        # the lib dir alone is the TRAP — it leaves the sibling bin dir
        # (/usr/bin) root-owned and `npm install -g` still fails on the binary
        # symlink. Option B must be suppressed; only the user-local prefix
        # (Option A) is offered, with an explicit system-dir warning.
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
        block = actions[0].manual_block or ""
        assert "npm config set prefix ~/.npm-global" in block  # Option A present
        # The actual chown COMMAND must be gone (the prose may mention sudo chown
        # to explain *why* it's unsafe).
        assert "sudo chown -R" not in block
        assert "system director" in block.lower()  # explanatory warning

    def test_literal_path_keeps_simple_chown_block(self, tmp_path, monkeypatch):
        # Regression: literal paths (e.g. ~/.npm) must keep their old single-
        # option chown manual block — only npm-root-global gets the two-option
        # treatment. Otherwise we'd flood every permission issue with npm
        # advice that doesn't apply.
        # v2.33.2: fix_command returns None outside $HOME. We simulate
        # `/home/picard/.npm` on a Linux uid 1000 box — patch Path.home() so
        # the resolved_path lies under the spoofed home and chown is offered.
        from pathlib import Path

        import sccs.doctor.installer as installer_mod
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        monkeypatch.setattr(Path, "home", lambda: Path("/home/picard"))

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
# v2.32.1 — npm global BIN dir writability (Linux system-npm symlink EACCES)  #
# --------------------------------------------------------------------------- #


class TestNpmBinGlobalPermission:
    """Catches the gap behind the Linux system-npm incident: `npm install -g`
    also symlinks the CLI binary into `<prefix>/bin` (e.g. /usr/bin). Chowning
    only `npm root -g` (/usr/lib/node_modules) passes the old check but the
    install still dies with EACCES on the /usr/bin symlink. A dedicated
    `npm-bin-global` permission check closes that gap.
    """

    def test_default_includes_npm_bin_global_check(self):
        # v2.33.2 renamed the label from "npm bin -g" → "npm prefix bin"
        # because npm 9+ removed the `npm bin` subcommand (a user copying the
        # old label would hit "Unknown command 'bin'"). The path_kind contract
        # is what wires the dynamic resolver — the path string is display only.
        from sccs.doctor.defaults import DEFAULT_PERMISSION_CHECKS

        bin_specs = [c for c in DEFAULT_PERMISSION_CHECKS if c.path_kind == "npm-bin-global"]
        assert len(bin_specs) == 1
        assert bin_specs[0].path == "npm prefix bin"

    def test_skipped_when_npm_missing(self, monkeypatch):
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        monkeypatch.setattr("sccs.doctor.detectors._resolve_npm_prefix_bin", lambda: None)
        spec = PermissionCheckSpec(path="npm bin -g", path_kind="npm-bin-global", label="npm bin", purpose="...")
        statuses = PermissionDetector().get_statuses([spec])
        assert statuses[0].ok is True
        assert statuses[0].skipped_reason is not None
        assert "npm not on PATH" in statuses[0].skipped_reason

    def test_unwritable_npm_bin_is_not_ok(self, monkeypatch, tmp_path):
        # Simulate /usr/bin: exists but not writable by current uid.
        import sccs.doctor.detectors as det_mod
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        bin_dir = tmp_path / "usr-bin"
        bin_dir.mkdir()
        monkeypatch.setattr(det_mod, "_resolve_npm_prefix_bin", lambda: str(bin_dir))
        monkeypatch.setattr(det_mod.os, "access", lambda p, mode: False)
        spec = PermissionCheckSpec(path="npm bin -g", path_kind="npm-bin-global", label="npm bin", purpose="...")
        statuses = PermissionDetector().get_statuses([spec])
        assert statuses[0].ok is False
        assert statuses[0].resolved_path == str(bin_dir)

    def test_writable_npm_bin_is_ok(self, monkeypatch, tmp_path):
        import sccs.doctor.detectors as det_mod
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        bin_dir = tmp_path / "home-bin"
        bin_dir.mkdir()
        monkeypatch.setattr(det_mod, "_resolve_npm_prefix_bin", lambda: str(bin_dir))
        spec = PermissionCheckSpec(path="npm bin -g", path_kind="npm-bin-global", label="npm bin", purpose="...")
        statuses = PermissionDetector().get_statuses([spec])
        assert statuses[0].ok is True

    def test_nonexistent_npm_bin_is_ok(self, monkeypatch, tmp_path):
        # User-local prefix not created yet — npm creates the bin dir on first
        # install, so a missing dir must NOT be flagged.
        import sccs.doctor.detectors as det_mod
        from sccs.doctor.detectors import PermissionDetector
        from sccs.doctor.schema import PermissionCheckSpec

        missing = tmp_path / "not-yet" / "bin"
        monkeypatch.setattr(det_mod, "_resolve_npm_prefix_bin", lambda: str(missing))
        spec = PermissionCheckSpec(path="npm bin -g", path_kind="npm-bin-global", label="npm bin", purpose="...")
        statuses = PermissionDetector().get_statuses([spec])
        assert statuses[0].ok is True

    def test_bin_global_block_recommends_user_prefix_only_for_system_path(self):
        # /usr/bin is a system path → user-local prefix advice, no chown.
        import sccs.doctor.installer as installer_mod
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        spec = PermissionCheckSpec(
            path="npm bin -g", path_kind="npm-bin-global", label="npm global bin dir", purpose="..."
        )
        bad = PermissionStatus(
            spec=spec,
            exists=True,
            is_user_owned=True,
            is_writable=False,
            expected_uid=1000,
            expected_gid=1000,
            resolved_path="/usr/bin",
        )
        actions = installer_mod._permission_actions([bad])
        assert len(actions) == 1
        block = actions[0].manual_block or ""
        assert "npm config set prefix ~/.npm-global" in block
        assert "sudo chown -R" not in block

    def test_failing_npm_bin_gates_npx_install(self):
        # The bin-writability failure must gate the npx install (install_deps),
        # not just post_install — otherwise `npm install -g` runs and dies.
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.installer import _blocking_components
        from sccs.doctor.schema import PermissionCheckSpec

        # v2.33.2: spec label is now "npm prefix bin" (npm 9+ removed `npm bin`).
        spec = PermissionCheckSpec(path="npm prefix bin", path_kind="npm-bin-global", label="npm bin", purpose="...")
        bad = PermissionStatus(
            spec=spec,
            exists=True,
            is_user_owned=True,
            is_writable=False,
            expected_uid=1000,
            expected_gid=1000,
            resolved_path="/usr/bin",
        )
        install_deps, use_deps = _blocking_components([bad], None)
        # Component name mirrors PermissionCheckSpec.path (see installer.py:311).
        assert "perm:npm prefix bin" in install_deps
        assert "perm:npm prefix bin" in use_deps


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
        actions = _plugin_install_actions([PluginStatus(spec=spec, installed=False, update_available=None)])
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

        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="/home/u/.npm-global\n", stderr="")
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

        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="/home/u/.npm-global\n", stderr="")
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
        market_missing = MarketplaceStatus(name="claude-plugins-official", registered=False, suggested_source=None)
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
        plugin_statuses = [PluginStatus(spec=s, installed=False, update_available=None) for s in plugin_specs]
        market_missing = [MarketplaceStatus(name="claude-plugins-official", registered=False, suggested_source=None)]
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
        from sccs.doctor.installer import _npm_global_fix_block
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
        block = "\n".join(_npm_global_fix_block(st))
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
        # Single-admin AND home-relative npm root: chown is safe + complete here
        # (the sibling bin dir is also under home), so both options stay.
        # NOTE: for a SYSTEM root (/usr/...) Option B is now suppressed even for
        # a single admin — see test_system_npm_root_suppresses_chown_option.
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.installer import _npm_global_fix_block
        from sccs.doctor.schema import PermissionCheckSpec

        home_root = str(Path.home() / ".npm-global" / "lib" / "node_modules")
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
            resolved_path=home_root,
            offending_paths=[home_root + "/foo"],
            foreign_uids={0},  # root only — single admin host
        )
        block = "\n".join(_npm_global_fix_block(st))
        assert "Option A" in block
        assert "Option B" in block


# ---------------------------------------------------------------------------
# v2.29.0 — StatusLine Detector
# ---------------------------------------------------------------------------
# Triggered by the 2026-05-11 incident: Homebrew bumped Node 25.x → 26.0.0 and
# pruned the old Cellar directory, leaving a hardcoded
# `/opt/homebrew/Cellar/node/25.9.0_3/bin/node` in the user's settings.json.
# Statusline silently disappeared; doctor was all-green because nothing
# inspected settings.json.


def _write_settings(tmp_path, statusline=None, extra=None):
    """Helper: write a synthetic settings.json and return its Path."""
    import json as _json

    data: dict = {}
    if statusline is not None:
        data["statusLine"] = statusline
    if extra:
        data.update(extra)
    sf = tmp_path / "settings.json"
    sf.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    return sf


class TestStatusLineDetector:
    """Parse ~/.claude/settings.json statusLine.command and classify into
    one of: ok / missing / missing_binary / missing_script / stale_cellar /
    opaque / no_settings_file."""

    def test_no_settings_file_state(self, tmp_path):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        spec = StatusLineCheckSpec(
            identifier="t",
            settings_path=str(tmp_path / "absent.json"),
            required_mode="smart",
        )
        statuses = StatusLineDetector().get_statuses([spec])
        assert statuses[0].state == "no_settings_file"
        assert statuses[0].ok is True  # not a fault

    def test_missing_key_with_required_never_is_ok(self, tmp_path):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = _write_settings(tmp_path, statusline=None, extra={"foo": "bar"})
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        statuses = StatusLineDetector(smart_required=True).get_statuses([spec])
        assert statuses[0].state == "ok"
        assert "opt-in" in statuses[0].detail

    def test_missing_key_with_required_always_fails(self, tmp_path):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = _write_settings(tmp_path, statusline=None)
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="always")
        statuses = StatusLineDetector().get_statuses([spec])
        assert statuses[0].state == "missing"
        assert statuses[0].ok is False

    def test_smart_mode_requires_sync_and_script(self, tmp_path):
        """smart-detect: required iff sync_enabled AND a script file exists in
        the settings.json's parent directory."""
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = _write_settings(tmp_path, statusline=None)
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="smart")

        # sync disabled → not required → ok
        statuses = StatusLineDetector(smart_required=False).get_statuses([spec])
        assert statuses[0].state == "ok"

        # sync enabled but no script → still not required → ok
        statuses = StatusLineDetector(smart_required=True).get_statuses([spec])
        assert statuses[0].state == "ok"

        # sync enabled + script present → required → missing
        (tmp_path / "statusline.sh").write_text("#!/usr/bin/env bash\necho hi\n")
        statuses = StatusLineDetector(smart_required=True).get_statuses([spec])
        assert statuses[0].state == "missing"

    def test_ok_binary_resolves_via_path(self, tmp_path, monkeypatch):
        """`bash script.sh` — binary on PATH, script exists → ok."""
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        script = tmp_path / "s.sh"
        script.write_text("#!/usr/bin/env bash\n")
        sf = _write_settings(tmp_path, statusline={"type": "command", "command": f"bash {script}"})
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda b: f"/usr/bin/{b}")
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        st = StatusLineDetector().get_statuses([spec])[0]
        assert st.state == "ok", st.detail
        assert st.binary == "bash"
        assert st.script == str(script)

    def test_missing_binary_state(self, tmp_path, monkeypatch):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = _write_settings(tmp_path, statusline={"type": "command", "command": "nope-xyz"})
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        st = StatusLineDetector().get_statuses([spec])[0]
        assert st.state == "missing_binary"
        assert "nope-xyz" in st.detail

    def test_missing_script_state(self, tmp_path, monkeypatch):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = _write_settings(
            tmp_path,
            statusline={"type": "command", "command": "/usr/bin/node /tmp/definitely-not-here.js"},
        )
        # Pretend the binary path resolves; the script path does not exist.
        monkeypatch.setattr(
            "pathlib.Path.is_file",
            lambda self: self.name == "node",
        )
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        st = StatusLineDetector().get_statuses([spec])[0]
        # The settings.json file itself is also is_file()=False per the
        # monkeypatch — but evaluate() reads it before walking the rest, so
        # we hit no_settings_file instead. Use a narrower stub:
        # Restore and try again with a real script-absence:
        import pathlib as _pl

        monkeypatch.undo()
        # Use a real, existing binary path (settings_path tmp file works);
        # we'll use the python binary which always exists.
        import sys as _sys

        real_bin = _sys.executable
        sf2 = _write_settings(
            tmp_path,
            statusline={"type": "command", "command": f"{real_bin} /tmp/nonexistent-{tmp_path.name}.js"},
        )
        spec2 = StatusLineCheckSpec(identifier="t", settings_path=str(sf2), required_mode="never")
        st2 = StatusLineDetector().get_statuses([spec2])[0]
        assert st2.state == "missing_script", f"got {st2.state}: {st2.detail}"
        # Silence unused-variable lint:
        _ = (st, _pl)

    def test_stale_cellar_state(self, tmp_path):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        # Cellar version 99.99.99 will (essentially) never exist on disk.
        sf = _write_settings(
            tmp_path,
            statusline={
                "type": "command",
                "command": '"/opt/homebrew/Cellar/node/99.99.99/bin/node" "/tmp/s.js"',
            },
        )
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        st = StatusLineDetector().get_statuses([spec])[0]
        assert st.state == "stale_cellar"
        assert st.cellar_pkg == "node"
        assert st.cellar_version == "99.99.99"
        assert st.ok is False

    def test_opaque_pipeline_command(self, tmp_path):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = _write_settings(
            tmp_path,
            statusline={"type": "command", "command": "echo hi | rev"},
        )
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        st = StatusLineDetector().get_statuses([spec])[0]
        assert st.state == "opaque"
        assert st.ok is True  # informational, not a fault

    def test_opaque_env_prefix(self, tmp_path):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = _write_settings(
            tmp_path,
            statusline={"type": "command", "command": "FOO=bar node /tmp/s.js"},
        )
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        st = StatusLineDetector().get_statuses([spec])[0]
        assert st.state == "opaque"


class TestStatusLineAutoFix:
    """`_status_line_actions` returns an in-process auto-fix for stale_cellar
    and manual blocks for the unfixable states. The auto-fix must back up
    settings.json, rewrite the Cellar path to /opt/homebrew/bin/X, and
    preserve every other key in the JSON document."""

    def test_auto_fix_rewrites_cellar_and_backs_up(self, tmp_path):
        import json as _json

        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.installer import _status_line_actions
        from sccs.doctor.schema import StatusLineCheckSpec

        original = {
            "statusLine": {
                "type": "command",
                "command": '"/opt/homebrew/Cellar/node/99.99.99/bin/node" "/tmp/s.js"',
            },
            "preserved": {"key": [1, 2, 3]},
        }
        sf = tmp_path / "settings.json"
        sf.write_text(_json.dumps(original, indent=2), encoding="utf-8")
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        statuses = StatusLineDetector().get_statuses([spec])
        actions = _status_line_actions(statuses)
        assert len(actions) == 1
        action = actions[0]
        assert action.python_callable is not None
        assert action.blocks_downstream is False

        action.python_callable()
        after = _json.loads(sf.read_text())
        assert after["statusLine"]["command"] == '"/opt/homebrew/bin/node" "/tmp/s.js"'
        assert after["preserved"] == {"key": [1, 2, 3]}
        backups = list(tmp_path.glob("settings.json.bak-*"))
        assert len(backups) == 1
        assert _json.loads(backups[0].read_text()) == original

    def test_auto_fix_idempotent_for_cellar(self, tmp_path):
        """Running the fix twice produces a single rewrite; the second pass
        is a no-op because the Cellar marker is already gone."""
        import json as _json

        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.installer import _status_line_actions
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = tmp_path / "settings.json"
        sf.write_text(
            _json.dumps(
                {
                    "statusLine": {
                        "type": "command",
                        "command": '"/opt/homebrew/Cellar/node/99.99.99/bin/node"',
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")

        # First pass: stale_cellar → fix.
        first = _status_line_actions(StatusLineDetector().get_statuses([spec]))
        assert len(first) == 1
        first[0].python_callable()

        # Second pass: the stale_cellar auto-fix (an in-process python_callable
        # action) must NOT be re-triggered — that is the idempotency guarantee.
        # We assert on the absence of an auto-fix rather than `== []` because
        # the rewrite target (/opt/homebrew/bin/node) only exists on macOS
        # Homebrew hosts; on Linux CI it surfaces as a `missing_binary` manual
        # block, which is a correct, different finding — not a re-applied fix.
        second = _status_line_actions(StatusLineDetector().get_statuses([spec]))
        assert all(a.python_callable is None for a in second)  # no auto-fix re-triggered

    def test_missing_binary_emits_manual_block(self, tmp_path, monkeypatch):
        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.installer import _status_line_actions
        from sccs.doctor.schema import StatusLineCheckSpec

        sf = _write_settings(tmp_path, statusline={"type": "command", "command": "nope-xyz"})
        monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        actions = _status_line_actions(StatusLineDetector().get_statuses([spec]))
        assert len(actions) == 1
        assert actions[0].runnable is False
        assert actions[0].python_callable is None
        assert "binary not found" in actions[0].manual_block.lower() or (
            "not on path" in actions[0].manual_block.lower()
        )

    def test_auto_fix_rewrites_gsd_script_and_backs_up(self, tmp_path):
        """missing_script for the GSD rename hooks/statusline.js →
        hooks/gsd-statusline.js auto-fixes when the new script exists, backs up
        settings.json, and preserves every other key."""
        import json as _json
        import sys as _sys

        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.installer import _status_line_actions
        from sccs.doctor.schema import StatusLineCheckSpec

        hooks = tmp_path / "hooks"
        hooks.mkdir()
        (hooks / "gsd-statusline.js").write_text("// stub", encoding="utf-8")  # new script exists
        # Old script (hooks/statusline.js) is intentionally absent → missing_script.

        real_bin = _sys.executable
        original = {
            "statusLine": {"type": "command", "command": f'"{real_bin}" "{hooks}/statusline.js"'},
            "preserved": {"key": [1, 2, 3]},
        }
        sf = tmp_path / "settings.json"
        sf.write_text(_json.dumps(original, indent=2), encoding="utf-8")
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        statuses = StatusLineDetector().get_statuses([spec])
        assert statuses[0].state == "missing_script"

        actions = _status_line_actions(statuses)
        assert len(actions) == 1
        action = actions[0]
        assert action.python_callable is not None
        assert action.blocks_downstream is False

        action.python_callable()
        after = _json.loads(sf.read_text())
        assert after["statusLine"]["command"] == f'"{real_bin}" "{hooks}/gsd-statusline.js"'
        assert after["preserved"] == {"key": [1, 2, 3]}
        backups = list(tmp_path.glob("settings.json.bak-*"))
        assert len(backups) == 1
        assert _json.loads(backups[0].read_text()) == original

    def test_no_auto_fix_when_new_gsd_script_absent(self, tmp_path):
        """If hooks/gsd-statusline.js does not exist, the GSD rename is NOT
        auto-fixed — it falls through to a manual block."""
        import json as _json
        import sys as _sys

        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.installer import _status_line_actions
        from sccs.doctor.schema import StatusLineCheckSpec

        hooks = tmp_path / "hooks"
        hooks.mkdir()
        # Neither old nor new script exists → missing_script, but no safe target.
        real_bin = _sys.executable
        sf = tmp_path / "settings.json"
        sf.write_text(
            _json.dumps({"statusLine": {"type": "command", "command": f'"{real_bin}" "{hooks}/statusline.js"'}}),
            encoding="utf-8",
        )
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        actions = _status_line_actions(StatusLineDetector().get_statuses([spec]))
        assert len(actions) == 1
        assert actions[0].python_callable is None  # manual block, not auto-fix
        assert actions[0].runnable is False

    def test_foreign_missing_script_stays_manual(self, tmp_path):
        """A non-GSD missing script (not hooks/statusline.js) must never be
        auto-rewritten — scope guard."""
        import json as _json
        import sys as _sys

        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.installer import _status_line_actions
        from sccs.doctor.schema import StatusLineCheckSpec

        real_bin = _sys.executable
        sf = tmp_path / "settings.json"
        sf.write_text(
            _json.dumps(
                {"statusLine": {"type": "command", "command": f'"{real_bin}" "{tmp_path}/custom-statusline.js"'}}
            ),
            encoding="utf-8",
        )
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")
        actions = _status_line_actions(StatusLineDetector().get_statuses([spec]))
        assert len(actions) == 1
        assert actions[0].python_callable is None  # manual block — no rewrite target
        assert actions[0].runnable is False

    def test_auto_fix_gsd_script_idempotent(self, tmp_path):
        """After the rewrite the command points at the existing
        gsd-statusline.js, so a second pass detects 'ok' and produces no
        further auto-fix."""
        import json as _json
        import sys as _sys

        from sccs.doctor.detectors import StatusLineDetector
        from sccs.doctor.installer import _status_line_actions
        from sccs.doctor.schema import StatusLineCheckSpec

        hooks = tmp_path / "hooks"
        hooks.mkdir()
        (hooks / "gsd-statusline.js").write_text("// stub", encoding="utf-8")

        real_bin = _sys.executable
        sf = tmp_path / "settings.json"
        sf.write_text(
            _json.dumps({"statusLine": {"type": "command", "command": f'"{real_bin}" "{hooks}/statusline.js"'}}),
            encoding="utf-8",
        )
        spec = StatusLineCheckSpec(identifier="t", settings_path=str(sf), required_mode="never")

        first = _status_line_actions(StatusLineDetector().get_statuses([spec]))
        assert len(first) == 1
        first[0].python_callable()

        second = _status_line_actions(StatusLineDetector().get_statuses([spec]))
        assert all(a.python_callable is None for a in second)  # no auto-fix re-triggered


# v2.30.0: foreign-plugin detection + doctor optimize sub-command.


class TestForeignPluginDetection:
    """ClaudePluginDetector.get_foreign_plugins() — plugins installed locally
    but NOT in the user's spec.
    """

    SAMPLE = """Installed plugins:

  ❯ claude-mem@thedotmack
    Version: 13.3.0
    Scope: user

  ❯ context-mode@context-mode
    Version: 1.0.131
    Scope: user

  ❯ frontend-design@claude-code-plugins
    Version: 1.0.0
    Scope: user

  ❯ frontend-design@claude-plugins-official
    Version: unknown
    Scope: user

  ❯ gopls-lsp@claude-plugins-official
    Version: 1.0.0
    Scope: user
"""

    def test_empty_spec_means_everything_is_foreign(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE)
        foreign = detector.get_foreign_plugins([])
        names = {(f.name, f.marketplace) for f in foreign}
        assert names == {
            ("claude-mem", "thedotmack"),
            ("context-mode", "context-mode"),
            ("frontend-design", "claude-code-plugins"),
            ("frontend-design", "claude-plugins-official"),
            ("gopls-lsp", "claude-plugins-official"),
        }

    def test_exact_match_excludes_from_foreign(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE)
        foreign = detector.get_foreign_plugins([PluginSpec(name="context-mode", marketplace="context-mode")])
        assert ("context-mode", "context-mode") not in {(f.name, f.marketplace) for f in foreign}

    def test_marketplace_mismatch_still_counts_as_foreign(self):
        """frontend-design@A in spec must NOT excuse frontend-design@B."""
        detector = ClaudePluginDetector(raw_output=self.SAMPLE)
        foreign = detector.get_foreign_plugins(
            [PluginSpec(name="frontend-design", marketplace="claude-plugins-official")]
        )
        names = {(f.name, f.marketplace) for f in foreign}
        assert ("frontend-design", "claude-code-plugins") in names
        assert ("frontend-design", "claude-plugins-official") not in names

    def test_bare_spec_marketplace_none_covers_all_marketplaces(self):
        """A spec without marketplace excuses every installed copy under any source."""
        detector = ClaudePluginDetector(raw_output=self.SAMPLE)
        foreign = detector.get_foreign_plugins([PluginSpec(name="frontend-design")])
        names = {(f.name, f.marketplace) for f in foreign}
        assert ("frontend-design", "claude-code-plugins") not in names
        assert ("frontend-design", "claude-plugins-official") not in names

    # Real host snapshot (2026-05-25): all 11 managed plugins, claude-mem gone.
    HOST_SAMPLE = """Installed plugins:

  ❯ context-mode@context-mode
  ❯ frontend-design@claude-code-plugins
  ❯ frontend-design@claude-plugins-official
  ❯ gopls-lsp@claude-plugins-official
  ❯ pyright-lsp@claude-plugins-official
  ❯ rust-analyzer-lsp@claude-plugins-official
  ❯ skill-creator@claude-plugins-official
  ❯ superpowers-developing-for-claude-code@superpowers-marketplace
  ❯ superpowers@claude-plugins-official
  ❯ swift-lsp@claude-plugins-official
  ❯ typescript-lsp@claude-plugins-official
"""

    def test_default_plugins_flag_nothing_foreign_on_real_host(self):
        """The canonical DEFAULT_CLAUDE_PLUGINS allowlist must cover this host."""
        detector = ClaudePluginDetector(raw_output=self.HOST_SAMPLE)
        foreign = detector.get_foreign_plugins(list(DEFAULT_CLAUDE_PLUGINS))
        assert foreign == []

    def test_claude_mem_is_foreign_against_defaults(self):
        """claude-mem was dropped from defaults — a stray install must be flagged."""
        sample = self.HOST_SAMPLE + "  ❯ claude-mem@thedotmack\n"
        detector = ClaudePluginDetector(raw_output=sample)
        foreign = detector.get_foreign_plugins(list(DEFAULT_CLAUDE_PLUGINS))
        assert {(f.name, f.marketplace) for f in foreign} == {("claude-mem", "thedotmack")}

    def test_scope_is_extracted(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE)
        foreign = detector.get_foreign_plugins([])
        scopes = {f.name: f.scope for f in foreign}
        assert scopes["claude-mem"] == "user"
        assert scopes["gopls-lsp"] == "user"

    def test_empty_output_means_no_foreign(self):
        detector = ClaudePluginDetector(raw_output="")
        assert detector.get_foreign_plugins([]) == []


class TestMCPServerDetector:
    """MCPServerDetector — parses `claude mcp list` and classifies servers."""

    SAMPLE = """Checking MCP server health…

claude.ai Gmail: https://gmailmcp.googleapis.com/mcp/v1 - ! Needs authentication
claude.ai Google Calendar: https://calendarmcp.googleapis.com/mcp/v1 - ! Needs authentication
plugin:context-mode:context-mode: node /tmp/start.mjs - ✓ Connected
my-custom-server: docker mcp gateway run - ✓ Connected
MCP_DOCKER: docker mcp gateway run - ✓ Connected
"""

    def test_parser_handles_colons_in_names(self):
        """Names like `plugin:context-mode:context-mode` must survive intact."""
        names = MCPServerDetector._parse_server_names(self.SAMPLE)
        assert "plugin:context-mode:context-mode" in names

    def test_parser_handles_spaces_in_names(self):
        """`claude.ai Gmail` has a space — must split on `: ` not first `:`."""
        names = MCPServerDetector._parse_server_names(self.SAMPLE)
        assert "claude.ai Gmail" in names
        assert "claude.ai Google Calendar" in names

    def test_parser_skips_banner(self):
        """The `Checking MCP server health…` banner must not leak in."""
        names = MCPServerDetector._parse_server_names(self.SAMPLE)
        assert all(not n.startswith("Checking") for n in names)

    def test_default_ignored_patterns_skip_oauth_and_plugin(self):
        detector = MCPServerDetector(raw_output=self.SAMPLE)
        foreign = detector.get_foreign_servers([], DEFAULT_IGNORED_MCP_PATTERNS)
        names = {f.name for f in foreign}
        assert names == {"my-custom-server", "MCP_DOCKER"}

    def test_spec_match_excludes_from_foreign(self):
        detector = MCPServerDetector(raw_output=self.SAMPLE)
        foreign = detector.get_foreign_servers(
            [MCPServerSpec(name="my-custom-server")],
            DEFAULT_IGNORED_MCP_PATTERNS,
        )
        assert {f.name for f in foreign} == {"MCP_DOCKER"}

    def test_empty_ignored_patterns_flags_everything(self):
        """Setting ignored_mcp_patterns: [] lets the user audit ALL drift."""
        detector = MCPServerDetector(raw_output=self.SAMPLE)
        foreign = detector.get_foreign_servers([], [])
        assert "claude.ai Gmail" in {f.name for f in foreign}
        assert "plugin:context-mode:context-mode" in {f.name for f in foreign}

    def test_spec_status_marks_missing(self):
        detector = MCPServerDetector(raw_output=self.SAMPLE)
        statuses = detector.get_statuses([MCPServerSpec(name="my-custom-server"), MCPServerSpec(name="not-installed")])
        installed = {s.spec.name: s.installed for s in statuses}
        assert installed == {"my-custom-server": True, "not-installed": False}

    def test_empty_output(self):
        assert MCPServerDetector(raw_output="").get_foreign_servers([], []) == []


class TestMCPServerSpecValidation:
    def test_name_rejects_unsafe_chars(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            MCPServerSpec(name="bad; rm -rf /")

    def test_name_accepts_colons_and_dots(self):
        # Real `claude mcp list` names use both.
        MCPServerSpec(name="plugin:context-mode:context-mode")
        MCPServerSpec(name="claude.ai Gmail")

    def test_scope_rejects_unknown_value(self):
        with pytest.raises(ValueError, match="user/project/local"):
            MCPServerSpec(name="x", scope="managed")


class TestBuildOptimizePlan:
    """Smoke-tests for build_optimize_plan — does it queue what we expect?"""

    @staticmethod
    def _minimal_kwargs(**overrides):
        """Build a complete kwarg set so plan-builders don't crash."""
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus

        defaults = {
            "node": NodeStatus(
                installed=True,
                version="20.0.0",
                major=20,
                meets_minimum=True,
                install_hint=get_node_install_spec("macos"),
                platform="macos",
            ),
            "claude_cli": ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
            "plugins": [],
            "foreign_plugins": [],
            "mcp_servers": [],
            "foreign_mcp_servers": [],
            "npx_tools": [],
            "permissions": [],
            "path_prefixes": [],
            "marketplaces": [],
            "status_lines": [],
        }
        defaults.update(overrides)
        return defaults

    def test_non_strict_emits_warning_block_for_foreign_plugins(self):
        plan = build_optimize_plan(
            DoctorConfig(),
            **self._minimal_kwargs(
                foreign_plugins=[ForeignPluginStatus(name="claude-mem", marketplace="thedotmack", scope="user")],
            ),
            strict=False,
        )
        # Should be a manual_block, NOT a runnable uninstall.
        warning_actions = [a for a in plan.actions if a.component == "foreign-plugins:summary"]
        assert len(warning_actions) == 1
        assert warning_actions[0].runnable is False
        assert "claude-mem@thedotmack" in warning_actions[0].manual_block

    def test_strict_queues_uninstall_action(self):
        plan = build_optimize_plan(
            DoctorConfig(),
            **self._minimal_kwargs(
                foreign_plugins=[ForeignPluginStatus(name="claude-mem", marketplace="thedotmack", scope="user")],
            ),
            strict=True,
        )
        uninstall = [a for a in plan.actions if a.component == "foreign-plugin:claude-mem"]
        assert len(uninstall) == 1
        assert uninstall[0].runnable is True
        assert uninstall[0].cmd[:3] == ["claude", "plugin", "uninstall"]
        assert "claude-mem@thedotmack" in uninstall[0].cmd
        assert "--scope" in uninstall[0].cmd

    def test_strict_queues_mcp_remove_action(self):
        plan = build_optimize_plan(
            DoctorConfig(),
            **self._minimal_kwargs(
                foreign_mcp_servers=[ForeignMCPServerStatus(name="MCP_DOCKER")],
            ),
            strict=True,
        )
        remove = [a for a in plan.actions if a.component == "foreign-mcp:MCP_DOCKER"]
        assert len(remove) == 1
        assert remove[0].runnable is True
        assert remove[0].cmd == ["claude", "mcp", "remove", "MCP_DOCKER", "-s", "user"]

    def test_non_strict_emits_warning_block_for_foreign_mcp(self):
        plan = build_optimize_plan(
            DoctorConfig(),
            **self._minimal_kwargs(
                foreign_mcp_servers=[ForeignMCPServerStatus(name="MCP_DOCKER")],
            ),
            strict=False,
        )
        summary = [a for a in plan.actions if a.component == "foreign-mcp:summary"]
        assert len(summary) == 1
        assert summary[0].runnable is False

    def test_empty_state_produces_empty_plan(self):
        plan = build_optimize_plan(DoctorConfig(), **self._minimal_kwargs(), strict=False)
        assert plan.is_empty() or all(not a.runnable for a in plan.actions)


class TestDoctorConfigLoaderPreservesMCPOverride:
    """Loader regression: doctor.mcp_servers and ignored_mcp_patterns must
    survive _merge_with_defaults — same bug class as v2.29.1's doctor.plugins.
    """

    def test_mcp_servers_override_loads(self, tmp_path):
        import yaml

        from sccs.config.loader import load_config

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "repository": {"path": str(tmp_path)},
                    "sync_categories": {},
                    "doctor": {
                        "mcp_servers": [{"name": "my-server", "scope": "user"}],
                        "ignored_mcp_patterns": ["custom:*"],
                    },
                }
            )
        )

        cfg = load_config(config_path)
        assert cfg.doctor.mcp_servers is not None
        assert len(cfg.doctor.mcp_servers) == 1
        assert cfg.doctor.mcp_servers[0].name == "my-server"
        assert cfg.doctor.ignored_mcp_patterns == ["custom:*"]


# v2.31.0: settings.json hook sanitisation after doctor runs.


class TestSettingsHookDetector:
    """SettingsHookDetector — parse settings.json + flag disallowed hooks."""

    SAMPLE_SETTINGS = {
        "permissions": {"allow": []},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [
                        {"type": "command", "command": "node /home/u/.claude/hooks/gsd-read-guard.js"},
                    ],
                },
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "bash /home/u/.claude/hooks/lint.sh"},
                    ],
                },
            ],
            "PostToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {"type": "command", "command": "python3 /home/u/.claude/hooks/quality-gate.py"},
                        {"type": "command", "command": "node /home/u/.claude/hooks/gsd-context-monitor.js"},
                    ],
                },
            ],
        },
    }

    def test_finds_match_in_nested_hook(self, tmp_path: Path):
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps(self.SAMPLE_SETTINGS))
        det = SettingsHookDetector(sp)
        violations = det.get_violations(["gsd-read-guard.js"])
        assert len(violations) == 1
        v = violations[0]
        assert v.event == "PreToolUse"
        assert v.matcher == "Write|Edit"
        assert "gsd-read-guard.js" in v.command
        assert v.matched_pattern == "gsd-read-guard.js"

    def test_finds_match_in_multi_hook_entry(self, tmp_path: Path):
        """Two hooks in the same `hooks:` array — the matching one must surface."""
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps(self.SAMPLE_SETTINGS))
        det = SettingsHookDetector(sp)
        violations = det.get_violations(["gsd-context-monitor.js"])
        assert len(violations) == 1
        assert violations[0].event == "PostToolUse"

    def test_empty_disallowed_returns_empty(self, tmp_path: Path):
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps(self.SAMPLE_SETTINGS))
        det = SettingsHookDetector(sp)
        assert det.get_violations([]) == []

    def test_no_settings_file_returns_empty(self, tmp_path: Path):
        det = SettingsHookDetector(tmp_path / "missing.json")
        assert det.get_violations(["foo"]) == []

    def test_malformed_json_returns_empty(self, tmp_path: Path):
        sp = tmp_path / "settings.json"
        sp.write_text("{ not json")
        det = SettingsHookDetector(sp)
        assert det.get_violations(["foo"]) == []

    def test_no_hooks_block_returns_empty(self, tmp_path: Path):
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps({"permissions": {"allow": []}}))
        det = SettingsHookDetector(sp)
        assert det.get_violations(["anything"]) == []

    def test_multiple_patterns_only_first_match_reported(self, tmp_path: Path):
        """If two patterns match the same command, only the first is reported."""
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps(self.SAMPLE_SETTINGS))
        det = SettingsHookDetector(sp)
        violations = det.get_violations(["gsd-read-guard.js", "read-guard"])
        # Both patterns match the SAME command — break-after-first means 1.
        assert len(violations) == 1

    def test_protected_hook_is_never_reported(self, tmp_path: Path):
        """A GSD hook matched by disallowed must be skipped when protected matches."""
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps(self.SAMPLE_SETTINGS))
        det = SettingsHookDetector(sp)
        violations = det.get_violations(["gsd-read-guard.js"], protected=["gsd-"])
        assert violations == []

    def test_protection_is_selective(self, tmp_path: Path):
        """Protection skips only protected commands; others still surface."""
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps(self.SAMPLE_SETTINGS))
        det = SettingsHookDetector(sp)
        # gsd-read-guard.js is protected; lint.sh is not.
        violations = det.get_violations(["gsd-read-guard.js", "lint.sh"], protected=["gsd-"])
        assert len(violations) == 1
        assert "lint.sh" in violations[0].command

    def test_without_protection_gsd_hook_is_reported(self, tmp_path: Path):
        """Counter-check: no protection list → GSD hook is a violation."""
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps(self.SAMPLE_SETTINGS))
        det = SettingsHookDetector(sp)
        assert len(det.get_violations(["gsd-read-guard.js"])) == 1


class TestSettingsHookCleanupAction:
    """_settings_hook_cleanup_actions — build action; run python_callable."""

    def test_no_violations_means_no_action(self, tmp_path: Path):
        actions = _settings_hook_cleanup_actions([], settings_path=tmp_path / "settings.json")
        assert actions == []

    def test_action_removes_matching_hook_entry(self, tmp_path: Path):
        sp = tmp_path / "settings.json"
        sp.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Write|Edit",
                                "hooks": [
                                    {"command": "node /a/gsd-read-guard.js"},
                                    {"command": "node /a/keep-me.js"},
                                ],
                            }
                        ],
                    }
                }
            )
        )
        violation = SettingsHookViolation(
            event="PreToolUse",
            matcher="Write|Edit",
            command="node /a/gsd-read-guard.js",
            matched_pattern="gsd-read-guard.js",
        )
        actions = _settings_hook_cleanup_actions([violation], settings_path=sp)
        assert len(actions) == 1
        assert actions[0].runnable is True
        assert actions[0].python_callable is not None

        actions[0].python_callable()
        result = json.loads(sp.read_text())
        commands = [h["command"] for h in result["hooks"]["PreToolUse"][0]["hooks"]]
        assert commands == ["node /a/keep-me.js"]  # other hook survives

    def test_action_drops_empty_outer_entry(self, tmp_path: Path):
        """If removal empties the inner `hooks:` list, the outer entry goes too."""
        sp = tmp_path / "settings.json"
        sp.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"matcher": "X", "hooks": [{"command": "node /a/bad.js"}]},
                            {"matcher": "Y", "hooks": [{"command": "node /a/good.js"}]},
                        ]
                    }
                }
            )
        )
        v = SettingsHookViolation(event="PreToolUse", matcher="X", command="node /a/bad.js", matched_pattern="bad.js")
        actions = _settings_hook_cleanup_actions([v], settings_path=sp)
        actions[0].python_callable()
        result = json.loads(sp.read_text())
        entries = result["hooks"]["PreToolUse"]
        assert len(entries) == 1
        assert entries[0]["matcher"] == "Y"

    def test_action_drops_empty_event_key(self, tmp_path: Path):
        """If removal empties the event entirely, the event key is dropped."""
        sp = tmp_path / "settings.json"
        sp.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"matcher": "X", "hooks": [{"command": "node /a/bad.js"}]},
                        ],
                        "PostToolUse": [
                            {"matcher": "Z", "hooks": [{"command": "node /a/keep.js"}]},
                        ],
                    }
                }
            )
        )
        v = SettingsHookViolation(event="PreToolUse", matcher="X", command="node /a/bad.js", matched_pattern="bad.js")
        actions = _settings_hook_cleanup_actions([v], settings_path=sp)
        actions[0].python_callable()
        result = json.loads(sp.read_text())
        assert "PreToolUse" not in result["hooks"]
        assert "PostToolUse" in result["hooks"]

    def test_action_writes_backup(self, tmp_path: Path):
        sp = tmp_path / "settings.json"
        original = json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command": "/a/bad"}]}]}})
        sp.write_text(original)
        v = SettingsHookViolation(event="PreToolUse", matcher=None, command="/a/bad", matched_pattern="bad")
        actions = _settings_hook_cleanup_actions([v], settings_path=sp)
        actions[0].python_callable()
        # Find the bak-* sibling.
        backups = list(tmp_path.glob("settings.json.bak-*"))
        assert len(backups) == 1
        assert backups[0].read_text() == original

    def test_action_is_idempotent(self, tmp_path: Path):
        """Running the python_callable twice yields the same end state."""
        sp = tmp_path / "settings.json"
        sp.write_text(
            json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command": "/a/bad"}, {"command": "/a/keep"}]}]}})
        )
        v = SettingsHookViolation(event="PreToolUse", matcher=None, command="/a/bad", matched_pattern="bad")
        actions = _settings_hook_cleanup_actions([v], settings_path=sp)
        actions[0].python_callable()
        first_state = sp.read_text()
        actions[0].python_callable()
        second_state = sp.read_text()
        assert first_state == second_state

    def test_action_writes_settings_atomically(self, tmp_path: Path):
        """Rewrite goes through atomic_write: no .tmp leftovers, and on POSIX
        the file ends up 0600 (settings.json may hold MCP tokens). Regression
        guard against reverting to a plain p.write_text()."""
        import os

        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command": "/a/bad"}]}]}}))
        v = SettingsHookViolation(event="PreToolUse", matcher=None, command="/a/bad", matched_pattern="bad")
        actions = _settings_hook_cleanup_actions([v], settings_path=sp)
        actions[0].python_callable()
        # mkstemp + os.replace leaves no temp turds in the target directory.
        assert not list(tmp_path.glob(".settings.json.*.tmp"))
        # mkstemp creates the temp file 0600; os.replace preserves it. Not on Windows.
        if os.name == "posix":
            assert sp.stat().st_mode & 0o077 == 0


class TestDoctorConfigDisallowedHooks:
    """Loader regression: doctor.disallowed_hooks must survive merge."""

    def test_override_loads(self, tmp_path: Path):
        import yaml as _yaml

        from sccs.config.loader import load_config

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            _yaml.dump(
                {
                    "repository": {"path": str(tmp_path)},
                    "sync_categories": {},
                    "doctor": {"disallowed_hooks": ["gsd-read-guard.js"]},
                }
            )
        )
        cfg = load_config(config_path)
        assert cfg.doctor.effective_disallowed_hooks() == ["gsd-read-guard.js"]

    def test_default_is_empty(self):
        from sccs.doctor.schema import DoctorConfig

        assert DoctorConfig().effective_disallowed_hooks() == []


class TestDoctorConfigProtectedHooks:
    """protected_hooks default + override — GSD hooks must be guarded."""

    def test_default_protects_gsd(self):
        from sccs.doctor.schema import DoctorConfig

        assert DoctorConfig().effective_protected_hooks() == ["gsd-"]

    def test_explicit_empty_disables_protection(self):
        from sccs.doctor.schema import DoctorConfig

        assert DoctorConfig(protected_hooks=[]).effective_protected_hooks() == []

    def test_override_loads(self, tmp_path: Path):
        import yaml as _yaml

        from sccs.config.loader import load_config

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            _yaml.dump(
                {
                    "repository": {"path": str(tmp_path)},
                    "sync_categories": {},
                    "doctor": {"protected_hooks": ["gsd-", "my-hook.js"]},
                }
            )
        )
        cfg = load_config(config_path)
        assert cfg.doctor.effective_protected_hooks() == ["gsd-", "my-hook.js"]


class TestPluginSpecAllowlistOnly:
    """allowlist_only field on PluginSpec."""

    def test_default_is_false(self):
        assert PluginSpec(name="foo").allowlist_only is False

    def test_accepts_true(self):
        assert PluginSpec(name="foo", marketplace="bar", allowlist_only=True).allowlist_only is True

    def test_override_loads(self, tmp_path: Path):
        import yaml as _yaml

        from sccs.config.loader import load_config

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            _yaml.dump(
                {
                    "repository": {"path": str(tmp_path)},
                    "sync_categories": {},
                    "doctor": {
                        "plugins": [
                            {"name": "core", "marketplace": "m1"},
                            {"name": "extra", "marketplace": "m2", "allowlist_only": True},
                        ]
                    },
                }
            )
        )
        cfg = load_config(config_path)
        assert [p.allowlist_only for p in cfg.doctor.effective_plugins()] == [False, True]


class TestCheckablePlugins:
    """checkable_plugins() excludes allowlist_only; effective_plugins() keeps them."""

    def test_checkable_excludes_allowlist_only(self):
        cfg = DoctorConfig(
            plugins=[
                PluginSpec(name="core", marketplace="m1"),
                PluginSpec(name="al", marketplace="m2", allowlist_only=True),
            ]
        )
        assert [p.name for p in cfg.checkable_plugins()] == ["core"]

    def test_effective_keeps_allowlist_only(self):
        cfg = DoctorConfig(
            plugins=[
                PluginSpec(name="core", marketplace="m1"),
                PluginSpec(name="al", marketplace="m2", allowlist_only=True),
            ]
        )
        assert [p.name for p in cfg.effective_plugins()] == ["core", "al"]

    def test_default_lsps_and_second_frontend_design_not_checkable(self):
        checkable = {p.install_target for p in DoctorConfig().checkable_plugins()}
        for entry in (
            "gopls-lsp@claude-plugins-official",
            "pyright-lsp@claude-plugins-official",
            "rust-analyzer-lsp@claude-plugins-official",
            "swift-lsp@claude-plugins-official",
            "typescript-lsp@claude-plugins-official",
            "frontend-design@claude-code-plugins",
        ):
            assert entry not in checkable
        # The primary frontend-design copy stays a real install target.
        assert "frontend-design@claude-plugins-official" in checkable


class TestAllowlistOnlyNotForeign:
    """Regression: an installed allowlist_only plugin is never flagged foreign."""

    def test_lsp_and_second_frontend_design_not_foreign(self):
        raw = (
            "❯ typescript-lsp@claude-plugins-official\n"
            "  Scope: user\n"
            "❯ frontend-design@claude-code-plugins\n"
            "  Scope: user\n"
        )
        detector = ClaudePluginDetector(raw_output=raw)
        foreign_names = {f.name for f in detector.get_foreign_plugins(DoctorConfig().effective_plugins())}
        assert "typescript-lsp" not in foreign_names
        assert "frontend-design" not in foreign_names


class TestAllowlistOnlyNoMarketplaceBlock:
    """A marketplace referenced only by an allowlist_only entry (claude-code-plugins)
    is not derived from checkable_plugins(), so it produces no registration block."""

    def test_claude_code_plugins_absent_from_marketplace_statuses(self):
        from sccs.doctor.detectors import ClaudeMarketplaceDetector

        detector = ClaudeMarketplaceDetector(raw_output="❯ claude-plugins-official\n  Source: x/y\n")
        names = {s.name for s in detector.get_statuses(DoctorConfig().checkable_plugins())}
        assert "claude-code-plugins" not in names
        assert "claude-plugins-official" in names


class TestAlternativeReportedAsInfo:
    """alternative detection -> INFO, not OUTDATED (it never converges and is installed)."""

    def test_plugin_row_alternative_is_info(self):
        from sccs.doctor.detectors import PluginStatus
        from sccs.doctor.reporter import _INFO, _OUTDATED, _plugin_row

        status = PluginStatus(
            spec=PluginSpec(name="frontend-design", marketplace="claude-code-plugins"),
            installed=True,
            update_available=None,
            detection_source="alternative",
            found_marketplace="claude-plugins-official",
            scope="user",
        )
        _, label, detail = _plugin_row(status)
        assert label == _INFO
        assert label != _OUTDATED
        assert "installed via claude-plugins-official" in detail


# --------------------------------------------------------------------------- #
# v2.33.2 — Safe fix_command + reporter delegation for system / multi-user    #
# npm prefixes. Real-session bug: `sccs doctor check` on a Linux uid 1000     #
# user with system npm (/usr) printed `sudo chown -R 1000:1000 /usr/bin` in   #
# the "Permission issues" block, which would brick the system. The installer  #
# already had the correct safe block (`_npm_global_fix_block`) but the        #
# reporter rendered `p.fix_command` directly and bypassed the guard.          #
# --------------------------------------------------------------------------- #


class TestFixCommandSafetyGuards:
    """`PermissionStatus.fix_command` must return None when chown is unsafe
    or incomplete. Callers (reporter / installer) handle None by delegating
    to the richer `_npm_global_fix_block`."""

    @staticmethod
    def _bad_status(resolved_path: str, foreign_uids=None):
        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        spec = PermissionCheckSpec(
            path="npm prefix bin",
            path_kind="npm-bin-global",
            label="npm global bin dir",
            purpose="...",
        )
        return PermissionStatus(
            spec=spec,
            exists=True,
            is_user_owned=True,
            is_writable=False,
            expected_uid=1000,
            expected_gid=1000,
            resolved_path=resolved_path,
            foreign_uids=foreign_uids or set(),
        )

    def test_fix_command_none_for_system_prefix(self):
        # /usr/bin is outside $HOME → chown is unsafe AND incomplete.
        st = self._bad_status("/usr/bin")
        assert st.fix_command is None

    def test_fix_command_none_for_multi_user_dir(self):
        # ≥2 distinct non-root owners → chown would destroy other users' installs.
        # Use a $HOME path so the multi-user guard, not the system-path guard, fires.
        from pathlib import Path

        home_path = str(Path.home() / ".npm-global" / "bin")
        st = self._bad_status(home_path, foreign_uids={1001, 1002})
        assert st.is_multi_user is True
        assert st.fix_command is None

    def test_fix_command_present_for_in_home_single_user(self, tmp_path, monkeypatch):
        # A user-owned ~/.npm-global chowned by stray `sudo npm` → chown IS the fix.
        from pathlib import Path

        from sccs.doctor.detectors import PermissionStatus
        from sccs.doctor.schema import PermissionCheckSpec

        # Force `Path.home()` to tmp_path so the resolved_path appears in-home.
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        in_home = tmp_path / ".npm-global" / "bin"
        in_home.mkdir(parents=True)
        spec = PermissionCheckSpec(
            path="npm prefix bin",
            path_kind="npm-bin-global",
            label="npm global bin dir",
            purpose="...",
        )
        st = PermissionStatus(
            spec=spec,
            exists=True,
            is_user_owned=True,
            is_writable=False,
            expected_uid=1000,
            expected_gid=1000,
            resolved_path=str(in_home),
        )
        assert st.fix_command is not None
        assert "sudo chown -R 1000:1000" in st.fix_command


class TestReporterSafeFixForSystemPrefix:
    """The reporter's "Permission issues" block must never recommend
    `sudo chown /usr/bin`. It must delegate to `_npm_global_fix_block`
    when `fix_command is None` for an npm-root/bin-global status.
    """

    def _capture_report(self, statuses):
        # Capture the reporter output via a buffered rich.Console. The reporter
        # only calls `console.print(...)`, so a lightweight rich Console is a
        # drop-in replacement for the sccs Console facade in this context.
        from io import StringIO

        from rich.console import Console as RichConsole

        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.reporter import render_doctor_report

        buf = StringIO()
        console = RichConsole(file=buf, width=200, force_terminal=False, color_system=None)
        render_doctor_report(
            console,
            node=NodeStatus(
                installed=True,
                version="20.20.2",
                major=20,
                meets_minimum=True,
                install_hint=None,
                platform="linux",
            ),
            claude_cli=ClaudeCliStatus(installed=True, binary_path="/usr/bin/claude"),
            min_node_major=20,
            plugins=[],
            npx_tools=[],
            permissions=statuses,
            path_prefixes=[],
            marketplaces=[],
            bundled_skills=[],
            browser_bundles=[],
            status_lines=[],
        )
        return buf.getvalue()

    def test_reporter_does_not_suggest_sudo_chown_usr_bin(self):
        st = TestFixCommandSafetyGuards._bad_status("/usr/bin")
        out = self._capture_report([st])
        # The dangerous suggestion must never appear.
        assert "sudo chown -R 1000:1000 /usr/bin" not in out
        # The safe Option-A guidance must appear instead.
        assert "WARNING" in out
        assert "npm config set prefix ~/.npm-global" in out

    def test_reporter_emits_reload_hint(self):
        st = TestFixCommandSafetyGuards._bad_status("/usr/bin")
        out = self._capture_report([st])
        assert "restart your shell" in out.lower() or "exec $SHELL" in out

    def test_reporter_safe_fix_for_multi_user_npm_dir(self):
        from pathlib import Path

        home_bin = str(Path.home() / ".npm-global" / "bin")
        st = TestFixCommandSafetyGuards._bad_status(home_bin, foreign_uids={1001, 1002})
        out = self._capture_report([st])
        # No actionable chown COMMAND (the multi-user warning prose may mention
        # `sudo chown -R` to explain *why* it's unsafe — that's fine; what must
        # never appear is a chown command targeting our UID:GID:path).
        assert "sudo chown -R 1000:1000" not in out
        assert "multi-user" in out.lower() or "DESTROY" in out


class TestNpmBinLabelRename:
    """v2.33.2: the spec label was renamed from `npm bin -g` to
    `npm prefix bin` because npm 9+ removed the `npm bin` subcommand.
    A user copying the label would otherwise hit "Unknown command 'bin'"."""

    def test_default_spec_uses_npm_prefix_bin_label(self):
        from sccs.doctor.defaults import DEFAULT_PERMISSION_CHECKS

        bin_specs = [s for s in DEFAULT_PERMISSION_CHECKS if s.path_kind == "npm-bin-global"]
        assert len(bin_specs) == 1
        assert bin_specs[0].path == "npm prefix bin"
        assert bin_specs[0].path != "npm bin -g"
