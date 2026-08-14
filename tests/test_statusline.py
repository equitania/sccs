# Tests for sccs.doctor.statusline — selectable statuslines.
#
# Nothing here touches the network or the real home directory: every test
# builds its own ~/.claude/ under tmp_path, and the one test that exercises
# the installer stubs the subprocess runner.

import json
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
