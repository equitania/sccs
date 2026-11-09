"""Tests for sccs.supervisor.tools (agent CLI detection)."""

from sccs.supervisor import ToolInfo, detect_tools


def _by_id(home):
    return {t.id: t for t in detect_tools(home)}


def test_fixed_order(fake_home, empty_path):
    assert [t.id for t in detect_tools(fake_home)] == ["claude", "codex", "opencode", "agy", "pi"]
    assert all(isinstance(t, ToolInfo) for t in detect_tools(fake_home))


def test_missing_binary_is_not_installed(fake_home, empty_path):
    pi = _by_id(fake_home)["pi"]
    assert pi.installed is False and pi.version is None


def test_config_present_without_binary(fake_home, empty_path):
    (fake_home / ".pi/agent").mkdir(parents=True)
    pi = _by_id(fake_home)["pi"]
    assert pi.installed is False and pi.config_present is True


def test_version_from_fake_binary(fake_home, fake_bin):
    fake_bin("agy", stdout="1.5.3\n")
    agy = _by_id(fake_home)["agy"]
    assert agy.installed and agy.version == "1.5.3"


def test_version_failure_is_unknown(fake_home, fake_bin):
    fake_bin("codex", stdout="", exit_code=3)
    codex = _by_id(fake_home)["codex"]
    assert codex.installed and codex.version is None


def test_codex_default_model_from_config_toml(fake_home, empty_path):
    (fake_home / ".codex").mkdir()
    (fake_home / ".codex/config.toml").write_text('model = "gpt-6.1-terra"\n')
    assert _by_id(fake_home)["codex"].default_model == "gpt-6.1-terra"


def test_claude_and_pi_default_model(fake_home, empty_path):
    (fake_home / ".claude").mkdir()
    (fake_home / ".claude/settings.json").write_text('{"model": "opus"}')
    (fake_home / ".pi/agent").mkdir(parents=True)
    (fake_home / ".pi/agent/settings.json").write_text('{"defaultModel": "p-1"}')
    tools = _by_id(fake_home)
    assert tools["claude"].default_model == "opus"
    assert tools["pi"].default_model == "p-1"


def test_broken_config_gives_no_model(fake_home, empty_path):
    (fake_home / ".codex").mkdir()
    (fake_home / ".codex/config.toml").write_text("not [valid")
    (fake_home / ".claude").mkdir()
    (fake_home / ".claude/settings.json").write_text("{nope")
    tools = _by_id(fake_home)
    assert tools["codex"].default_model is None
    assert tools["claude"].default_model is None


def test_login_presence_only(fake_home, empty_path):
    (fake_home / ".codex").mkdir()
    (fake_home / ".codex/auth.json").write_text('{"secret":"x"}')
    tools = _by_id(fake_home)
    assert tools["codex"].login == "yes" and "secret" not in repr(tools["codex"])
    assert tools["pi"].login == "unknown"
    assert tools["claude"].login == "unknown" and tools["agy"].login == "unknown"
