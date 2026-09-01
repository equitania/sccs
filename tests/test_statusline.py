# Tests for sccs.doctor.statusline — selectable statuslines.
#
# Nothing here touches the network or the real home directory: every test
# builds its own ~/.claude/ under tmp_path, and the one test that exercises
# the installer stubs the subprocess runner.

import json
import re
from pathlib import Path

import pytest

from sccs.doctor.managed import get_doctor_managed_excludes
from sccs.doctor.schema import DoctorConfig
from sccs.doctor.statusline import (
    ALLOWED_INSTALL_HOSTS,
    DEFAULT_STATUSLINE_PRESETS,
    MAX_INSTALLER_BYTES,
    StatusLineConfig,
    StatusLineError,
    StatusLineManager,
    StatusLinePreset,
    install_command_hint,
    install_preset,
    resolve_statusline_presets,
    statusline_managed_paths,
    validate_preset_name,
)


@pytest.fixture
def claude_dir(tmp_path: Path) -> Path:
    root = tmp_path / "claude"
    root.mkdir()
    (root / "settings.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": "/hooks/gsd-statusline.js"}}, indent=2),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def manager(claude_dir: Path) -> StatusLineManager:
    return StatusLineManager(resolve_statusline_presets(None), claude_dir=claude_dir)


# --------------------------------------------------------------------- #
# Presets                                                                #
# --------------------------------------------------------------------- #


def test_bundled_presets():
    assert set(DEFAULT_STATUSLINE_PRESETS) == {"builtin", "claude-code-statusline"}
    ccs = DEFAULT_STATUSLINE_PRESETS["claude-code-statusline"]
    assert ccs.settings_block() == {"type": "command", "command": "~/.claude/statusline", "padding": 0}
    assert ccs.install_url and ccs.install_url.startswith("https://raw.githubusercontent.com/")


def test_builtin_preset_has_no_padding_key():
    """padding=None must be omitted, not written as null."""
    assert DEFAULT_STATUSLINE_PRESETS["builtin"].settings_block() == {
        "type": "command",
        "command": '"$HOME/.claude/statusline.sh"',
    }


def test_user_preset_overrides_bundled():
    resolved = resolve_statusline_presets({"builtin": StatusLinePreset(command="/my/own")})
    assert resolved["builtin"].command == "/my/own"
    assert "claude-code-statusline" in resolved


@pytest.mark.parametrize("bad", ["Bad", "-x", "a/b", "", "with space"])
def test_invalid_preset_names_rejected(bad):
    with pytest.raises(StatusLineError):
        validate_preset_name(bad)


# --------------------------------------------------------------------- #
# Install URL validation                                                 #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        "http://raw.githubusercontent.com/x/install.sh",  # not https
        "https://evil.example.com/install.sh",  # host not allowlisted
        "file:///etc/passwd",
        "https://raw.githubusercontent.com.evil.com/install.sh",
    ],
)
def test_install_url_rejected(url):
    with pytest.raises(ValueError):
        StatusLinePreset(command="x", install_url=url)


def test_install_url_accepted_for_allowlisted_hosts():
    for host in ALLOWED_INSTALL_HOSTS:
        preset = StatusLinePreset(command="x", install_url=f"https://{host}/o/r/install.sh")
        assert preset.install_url is not None


def test_managed_paths_must_be_bare_names():
    with pytest.raises(ValueError):
        StatusLinePreset(command="x", managed_paths=["../outside"])


# --------------------------------------------------------------------- #
# Sync excludes                                                          #
# --------------------------------------------------------------------- #


def test_statusline_binary_is_excluded_from_sync():
    """The binary is several MB — it must never reach the git repository."""
    excludes = get_doctor_managed_excludes(DoctorConfig())
    assert "statusline" in excludes
    assert "statusline.toml" in excludes
    # The user's own shell script is NOT managed and must keep syncing.
    assert "statusline.sh" not in excludes


def test_managed_paths_collected_from_all_presets_not_just_active():
    """Switching away from a statusline must not un-exclude its leftovers."""
    paths = statusline_managed_paths(resolve_statusline_presets(None))
    assert "statusline" in paths and "statusline.toml" in paths


def test_user_preset_contributes_its_managed_paths():
    presets = resolve_statusline_presets({"mine": StatusLinePreset(command="x", managed_paths=["mybar"])})
    cfg = StatusLineConfig(presets={"mine": presets["mine"]})
    assert "mybar" in get_doctor_managed_excludes(DoctorConfig(), cfg)


# --------------------------------------------------------------------- #
# Installed detection                                                    #
# --------------------------------------------------------------------- #


def test_is_installed_follows_the_marker(claude_dir: Path, manager: StatusLineManager):
    assert manager.status("claude-code-statusline").installed is False
    (claude_dir / "statusline").write_text("#!/bin/sh\n", encoding="utf-8")
    assert manager.status("claude-code-statusline").installed is True


def test_preset_without_marker_counts_as_installed():
    assert StatusLinePreset(command="x").is_installed() is True


# --------------------------------------------------------------------- #
# Reading and writing settings.json                                      #
# --------------------------------------------------------------------- #


def test_current_command_and_no_preset_match(manager: StatusLineManager):
    assert manager.current_command() == "/hooks/gsd-statusline.js"
    assert manager.match_current() is None  # gsd is owned by the profile, not a preset


def test_apply_writes_the_block_and_keeps_other_keys(claude_dir: Path, manager: StatusLineManager):
    data = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    data["theme"] = "dark"
    (claude_dir / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    block = manager.apply("claude-code-statusline")
    after = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert after["statusLine"] == block == {"type": "command", "command": "~/.claude/statusline", "padding": 0}
    assert after["theme"] == "dark"
    assert manager.match_current() == "claude-code-statusline"


def test_current_block_and_restore_round_trip(claude_dir: Path, manager: StatusLineManager):
    """Installers rewrite statusLine themselves — we must be able to undo that.

    claude-code-statusline's install.sh patches settings.json as its last
    step, so `sccs statusline install --no-use` has to capture the previous
    block and put it back, or the flag silently does the opposite of what
    it says.
    """
    before = manager.current_block()
    assert before == {"type": "command", "command": "/hooks/gsd-statusline.js"}

    manager.apply("claude-code-statusline")  # stand-in for what the installer does
    assert manager.current_block() != before

    manager.restore_block(before)
    assert manager.current_block() == before


def test_restore_none_removes_the_key(claude_dir: Path, manager: StatusLineManager):
    manager.restore_block(None)
    data = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert "statusLine" not in data


def test_apply_unknown_preset_raises(manager: StatusLineManager):
    with pytest.raises(StatusLineError, match="unknown statusline preset"):
        manager.apply("nope")


def test_apply_on_malformed_settings_raises(claude_dir: Path, manager: StatusLineManager):
    (claude_dir / "settings.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(StatusLineError, match="not valid JSON"):
        manager.apply("builtin")


def test_missing_settings_file_raises(tmp_path: Path):
    mgr = StatusLineManager(resolve_statusline_presets(None), claude_dir=tmp_path / "empty")
    assert mgr.current_command() is None
    with pytest.raises(StatusLineError, match="does not exist"):
        mgr.apply("builtin")


# --------------------------------------------------------------------- #
# Install                                                                #
# --------------------------------------------------------------------- #


# --------------------------------------------------------------------- #
# Version detection                                                      #
# --------------------------------------------------------------------- #


def test_version_arg_must_be_a_single_flag():
    for bad in ["version", "--version --extra", "/etc/passwd"]:
        with pytest.raises(ValueError):
            StatusLinePreset(command="x", version_arg=bad)


def test_detect_version_reads_the_first_line(tmp_path: Path):
    marker = tmp_path / "bar"
    marker.write_text("#!/bin/sh\necho 'bar 2.1.0'\necho 'second line'\n", encoding="utf-8")
    marker.chmod(0o755)
    preset = StatusLinePreset(command="x", marker_path="bar", version_arg="--version")
    assert preset.detect_version(tmp_path) == "bar 2.1.0"


def test_detect_version_is_none_without_version_arg(tmp_path: Path):
    (tmp_path / "bar").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (tmp_path / "bar").chmod(0o755)
    assert StatusLinePreset(command="x", marker_path="bar").detect_version(tmp_path) is None


def test_detect_version_degrades_when_not_executable(tmp_path: Path):
    (tmp_path / "bar").write_text("not a program", encoding="utf-8")
    preset = StatusLinePreset(command="x", marker_path="bar", version_arg="--version")
    assert preset.detect_version(tmp_path) is None


def test_detect_version_rejects_a_paragraph(tmp_path: Path):
    """A binary that answers with prose must not blow up the Version column."""
    marker = tmp_path / "bar"
    marker.write_text("#!/bin/sh\necho '" + "x" * 80 + "'\n", encoding="utf-8")
    marker.chmod(0o755)
    preset = StatusLinePreset(command="x", marker_path="bar", version_arg="--version")
    assert preset.detect_version(tmp_path) is None


def test_status_only_detects_version_when_asked(claude_dir: Path, manager: StatusLineManager):
    (claude_dir / "statusline").write_text("#!/bin/sh\necho 'sl 9.9'\n", encoding="utf-8")
    (claude_dir / "statusline").chmod(0o755)
    assert manager.status("claude-code-statusline").version is None
    assert manager.status("claude-code-statusline", detect_version=True).version == "sl 9.9"


# --------------------------------------------------------------------- #
# Doctor row                                                             #
# --------------------------------------------------------------------- #


def _row(**kw):
    from sccs.doctor.reporter import _statusline_preset_row
    from sccs.doctor.statusline import StatusLinePresetStatus

    defaults = dict(
        name="ccs",
        description="",
        command="~/.claude/statusline",
        installed=True,
        is_active=False,
        is_configured=True,
        installable=True,
        version=None,
    )
    defaults.update(kw)
    return _statusline_preset_row(StatusLinePresetStatus(**defaults))


def test_row_omitted_for_a_preset_that_is_neither_chosen_nor_live():
    """Listing every bundled preset would be a catalogue, not a status."""
    assert _row(is_configured=False, is_active=False) is None


def test_row_shown_when_installed_and_healthy():
    """Regression: an OK statusline used to print nothing at all.

    `doctor check` is a status report and every other component prints an
    OK row, so silence made "installed and fine" indistinguishable from
    "SCCS has no idea this exists".
    """
    row = _row(installed=True, is_active=True, version="statusline 1.0.0")
    assert row is not None
    component, status, version, detail = row
    assert "ccs" in component
    assert status == "OK"
    assert version == "statusline 1.0.0"
    assert "in use" in detail


def test_row_flags_configured_but_not_in_use():
    _, status, _, detail = _row(installed=True, is_active=False)
    assert status == "OK"
    assert "not in use" in detail
    assert "sccs statusline use ccs" in detail


def test_row_flags_missing_with_the_install_command():
    _, status, _, detail = _row(installed=False)
    assert "MISSING" in status
    assert "sccs statusline install ccs" in detail


def test_row_missing_without_installer_says_so():
    _, status, _, detail = _row(installed=False, installable=False)
    assert "MISSING" in status
    assert "no installer" in detail


def test_row_shown_for_a_live_preset_even_if_not_configured():
    row = _row(is_configured=False, is_active=True)
    assert row is not None and "in use" in row[3]


# --------------------------------------------------------------------- #
# Doctor install action                                                  #
# --------------------------------------------------------------------- #


def _install_actions(**kw):
    from sccs.doctor.installer import _statusline_preset_install_actions
    from sccs.doctor.statusline import StatusLinePresetStatus

    defaults = dict(
        name="claude-code-statusline",
        description="",
        command="~/.claude/statusline",
        installed=False,
        is_active=False,
        is_configured=True,
        installable=True,
        version=None,
    )
    defaults.update(kw)
    return _statusline_preset_install_actions([StatusLinePresetStatus(**defaults)])


def test_install_action_offered_for_the_configured_preset():
    actions = _install_actions()
    assert len(actions) == 1
    assert actions[0].component == "statusline-preset:claude-code-statusline"


def test_install_action_offered_for_a_live_preset_that_is_not_configured():
    """Regression (v2.58.2): `sccs profile off <name>` points settings.json at
    the profile's fallback preset without touching config.yaml. Gating the
    action on `statusline.active` alone made doctor print a MISSING row for a
    statusline it then refused to install — the row and the action must agree.
    """
    assert len(_install_actions(is_configured=False, is_active=True)) == 1


def test_no_install_action_for_a_preset_that_is_neither_chosen_nor_live():
    assert _install_actions(is_configured=False, is_active=False) == []


def test_no_install_action_when_already_installed():
    assert _install_actions(installed=True) == []


# --------------------------------------------------------------------- #
# CLI: choosing a preset records the choice                              #
# --------------------------------------------------------------------- #


def test_statusline_use_writes_settings_and_config(tmp_path: Path, monkeypatch, sample_config: dict):
    """`sccs statusline use` must touch BOTH files.

    settings.json alone is machine state: it does not survive a rebuild, and
    `doctor install` reads `statusline.active` to decide whether to offer the
    installer (v2.58.2).
    """
    import yaml
    from click.testing import CliRunner

    from sccs.cli import cli

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    monkeypatch.setattr("sccs.doctor.statusline.DEFAULT_CLAUDE_DIR", claude_dir)

    cfg_path = tmp_path / "config.yaml"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_config, f, default_flow_style=False)
    monkeypatch.setenv("SCCS_CONFIG", str(cfg_path))

    result = CliRunner().invoke(cli, ["statusline", "use", "claude-code-statusline", "--json"])
    assert result.exit_code == 0, result.output

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["statusLine"]["command"] == "~/.claude/statusline"
    assert settings["theme"] == "dark"  # untouched

    with open(cfg_path, encoding="utf-8") as f:
        assert yaml.safe_load(f)["statusline"]["active"] == "claude-code-statusline"


def test_statusline_use_survives_an_unwritable_config(tmp_path: Path, monkeypatch, sample_config: dict):
    """The statusline is already set by then — a failed preference write must
    warn, not fail the command."""
    from click.testing import CliRunner

    from sccs.cli import cli

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sccs.doctor.statusline.DEFAULT_CLAUDE_DIR", claude_dir)
    monkeypatch.setattr(
        "sccs.config.loader.save_statusline_active",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("read-only file system")),
    )

    result = CliRunner().invoke(cli, ["statusline", "use", "builtin"])
    assert result.exit_code == 0, result.output
    # Rich colours and hard-wraps the console output — strip both before
    # asserting (CI forces colour, a local pipe does not).
    plain = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert "read-only file system" in plain
    assert json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))["statusLine"]


def test_install_hint_is_the_documented_command():
    preset = DEFAULT_STATUSLINE_PRESETS["claude-code-statusline"]
    assert install_command_hint(preset) == f"curl -fsSL {preset.install_url} | bash"
    assert "scriptblock" in (install_command_hint(preset, windows=True) or "")


def test_install_without_url_raises():
    with pytest.raises(StatusLineError, match="no install_url"):
        install_preset(StatusLinePreset(command="x"))


def test_install_downloads_then_runs_bash_never_a_shell_pipe(monkeypatch, tmp_path: Path):
    """The installer must reach bash as a file argument, not via `curl | bash`."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[0] == "curl":
            Path(cmd[cmd.index("-o") + 1]).write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
        return None

    monkeypatch.setattr("sccs.doctor.runner._run", fake_run)
    monkeypatch.setattr("os.name", "posix")
    install_preset(DEFAULT_STATUSLINE_PRESETS["claude-code-statusline"])

    assert calls[0][0] == "curl"
    assert calls[1][0] == "bash"
    # No argument anywhere is a shell string containing a pipe.
    assert not any("|" in part for call in calls for part in call)


def test_install_refuses_an_oversized_download(monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd[0] == "curl":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"x" * (MAX_INSTALLER_BYTES + 1))
        return None

    monkeypatch.setattr("sccs.doctor.runner._run", fake_run)
    monkeypatch.setattr("os.name", "posix")
    with pytest.raises(StatusLineError, match="refusing to run"):
        install_preset(DEFAULT_STATUSLINE_PRESETS["claude-code-statusline"])


def test_install_refuses_an_empty_download(monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd[0] == "curl":
            Path(cmd[cmd.index("-o") + 1]).write_text("", encoding="utf-8")
        return None

    monkeypatch.setattr("sccs.doctor.runner._run", fake_run)
    monkeypatch.setattr("os.name", "posix")
    with pytest.raises(StatusLineError, match="empty"):
        install_preset(DEFAULT_STATUSLINE_PRESETS["claude-code-statusline"])


class TestStatuslineCategoryMatchesTheLiveScript:
    """The sync category must cover the file Claude Code actually runs.

    `statusline-command.sh` is the name Claude Code's own /statusline setup
    writes. It was covered by neither the include list nor the item_pattern
    (`statusline.*` is an fnmatch glob, where the dot is literal), so the one
    file that IS the statusline never reached the repository — while the
    stale `statusline.sh` next to it synced happily, and every other host
    kept running that.
    """

    def _category(self):
        from sccs.config.defaults import DEFAULT_CONFIG

        return DEFAULT_CONFIG["sync_categories"]["claude_statusline"]

    def _matches(self, name: str) -> bool:
        import fnmatch

        from sccs.utils.paths import matches_any_pattern

        cat = self._category()
        if not fnmatch.fnmatch(name, cat["item_pattern"]):
            return False
        if not matches_any_pattern(name, cat["include"]):
            return False
        return not matches_any_pattern(name, cat["exclude"])

    def test_live_statusline_script_is_synced(self):
        assert self._matches("statusline-command.sh")

    def test_legacy_scripts_still_sync(self):
        for name in ("statusline.sh", "statusline.ps1", "statusline.py", "statusline.fish"):
            assert self._matches(name), name

    def test_third_party_binary_and_config_never_sync(self):
        # Multi-megabyte binary plus machine-local taste.
        assert not self._matches("statusline")
        assert not self._matches("statusline.toml")

    def test_editor_and_backup_leftovers_never_sync(self):
        assert not self._matches("statusline-command.sh.bak")
        assert not self._matches("statusline.sh.orig")

    def test_settings_entry_points_at_the_live_script(self):
        entry = self._category()["settings_ensure"]["entries"]["statusLine"]
        assert entry["command"] == "bash ~/.claude/statusline-command.sh"

    def test_previous_release_commands_are_declared_superseded(self):
        """Otherwise a host that already ran an older SCCS keeps the old line."""
        from sccs.sync.settings import is_superseded

        patterns = self._category()["settings_ensure"]["superseded_patterns"]["statusLine"]
        assert is_superseded({"type": "command", "command": "~/.claude/statusline.sh"}, patterns)
        assert not is_superseded({"type": "command", "command": "~/bin/mine"}, patterns)
