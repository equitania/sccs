"""Tests for the `sccs agents` CLI group (uses fake HOME and fake binaries)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest
from click.testing import CliRunner

from sccs.cli import cli
from tests.conftest import FIX, write_agent

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.fixture(autouse=True)
def _isolated(fake_home, monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("SCCS_CONFIG", str(cfg / "config.yaml"))
    return fake_home


def _run(*args: str):
    return CliRunner().invoke(cli, ["agents", *args])


def test_list_json_shape(fake_home, fake_bin):
    fake_bin("claude", "2.1.0")
    result = _run("list", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data) == {"supervisor", "tools", "agents"}
    assert data["supervisor"]["tool"] == "claude"
    assert data["supervisor"]["agents_dir"] == str(fake_home / ".claude" / "agents")
    pi = next(t for t in data["tools"] if t["id"] == "pi")
    assert pi["installed"] is False


def test_list_json_contains_agents(fake_home):
    write_agent(fake_home, "opencode-worker", FIX("opencode-worker.md"))
    data = json.loads(_run("list", "--json").output)
    assert [a["name"] for a in data["agents"]] == ["opencode-worker"]


def test_list_table_columns(fake_home):
    write_agent(fake_home, "opencode-worker", FIX("opencode-worker.md"))
    result = _run("list")
    assert result.exit_code == 0, result.output
    out = _plain(result.output)
    for word in ("Agent", "Tool", "Model", "Mode", "opencode-worker", "read-only", "adopted)"):
        assert word in out


def test_tools_json(fake_home):
    data = json.loads(_run("tools", "--json").output)
    assert {t["id"] for t in data["tools"]} == {"claude", "codex", "opencode", "agy", "pi"}


def test_models_json_unreadable(fake_home, empty_path):
    data = json.loads(_run("models", "opencode", "--json").output)
    assert data["tool"] == "opencode"
    assert data["readable"] is False
    assert data["models"] == []


def test_models_unknown_tool(fake_home):
    result = _run("models", "nope")
    assert result.exit_code != 0


def test_new_pi_refused(fake_home):
    result = _run("new", "pi", "p")
    assert result.exit_code == 1
    assert "Pi has no tested wrapper template yet." in _plain(result.output)


def test_new_bad_model_json(fake_home):
    result = _run("new", "opencode", "x-worker", "--model", "a;b", "--json")
    assert result.exit_code == 1
    assert "error" in json.loads(result.output)
    assert not (fake_home / ".claude" / "agents" / "x-worker.md").exists()


def test_new_creates_agent(fake_home, empty_path):
    result = _run("new", "opencode", "x-worker", "--model", "openrouter/foo", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["model_status"] == "unverified"
    assert (fake_home / ".claude" / "agents" / "x-worker.md").is_file()


def test_new_unverified_warning(fake_home, empty_path):
    result = _run("new", "opencode", "x-worker", "--model", "openrouter/foo")
    assert result.exit_code == 0, result.output
    assert "Model not verified: the tool's model list could not be read." in _plain(result.output)


def test_set_model_unknown_agent(fake_home):
    result = _run("set-model", "ghost", "m", "--json")
    assert result.exit_code == 1
    assert "error" in json.loads(result.output)


def test_set_model_roundtrip(fake_home, empty_path):
    _run("new", "opencode", "x-worker", "--model", "openrouter/foo")
    result = _run("set-model", "x-worker", "openrouter/bar", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "unverified"
    assert "openrouter/bar" in (fake_home / ".claude" / "agents" / "x-worker.md").read_text(encoding="utf-8")


def test_adopt_json_without_yes_refuses(fake_home):
    path = write_agent(fake_home, "opencode-worker", FIX("opencode-worker.md"))
    before = path.read_bytes()
    result = _run("adopt", "opencode-worker", "--json")
    assert result.exit_code == 1
    assert "error" in json.loads(result.output)
    assert path.read_bytes() == before


def test_adopt_declined(fake_home):
    path = write_agent(fake_home, "opencode-worker", FIX("opencode-worker.md"))
    before = path.read_bytes()
    result = CliRunner().invoke(cli, ["agents", "adopt", "opencode-worker"], input="n\n")
    assert result.exit_code == 1
    assert path.read_bytes() == before


def test_adopt_yes(fake_home):
    path = write_agent(fake_home, "opencode-worker", FIX("opencode-worker.md"))
    result = _run("adopt", "opencode-worker", "--yes", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["adopted"] is True
    assert "adopted" in path.read_text(encoding="utf-8")


def test_bare_group_non_tty_prints_list_and_hint(fake_home):
    result = _run()
    assert result.exit_code == 0, result.output
    out = _plain(result.output)
    assert "Agent" in out
    assert "Run in a terminal for the full-screen view." in out


def test_no_textual_import(fake_home):
    code = (
        "import sys; from click.testing import CliRunner; from sccs.cli import cli; "
        "CliRunner().invoke(cli, ['agents','list','--json']); assert 'textual' not in sys.modules"
    )
    env = dict(os.environ, HOME=str(fake_home), USERPROFILE=str(fake_home))
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_new_with_malformed_config_json_error_envelope(fake_home, empty_path, tmp_path, monkeypatch):
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed\n")
    monkeypatch.setenv("SCCS_CONFIG", str(bad))
    result = _run("new", "agy", "w", "--model", "gemini-x", "--json")
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["success"] is False
    assert not (fake_home / ".claude" / "agents" / "w.md").exists()


def test_new_opencode_free_model_warns(fake_home, empty_path):
    result = _run("new", "opencode", "w", "--model", "opencode/big-free", "--json")
    assert result.exit_code == 0, result.output
    assert "unclear data policy" in json.loads(result.output)["warning"]
    plain = _run("new", "opencode", "w2", "--model", "opencode/big-free")
    assert "unclear data policy" in _plain(plain.output)


def test_set_model_free_opencode_model_warns(fake_home, empty_path):
    write_agent(fake_home, "ocw", FIX("opencode-worker.md"))
    assert _run("adopt", "ocw", "--yes").exit_code == 0
    result = _run("set-model", "ocw", "opencode/big-free", "--json")
    assert result.exit_code == 0, result.output
    assert "unclear data policy" in json.loads(result.output)["warning"]


def test_tools_table_escapes_markup(fake_home, fake_bin):
    fake_bin("agy", "[bold]9.9[/bold]")
    out = _plain(_run("tools").output)
    assert "[bold]9.9[/bold]" in out
