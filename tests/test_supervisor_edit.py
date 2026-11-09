import re

import pytest

from sccs.config.schema import RepositoryConfig, SccsConfig
from sccs.convert.frontmatter import parse_frontmatter_ex
from sccs.supervisor import SupervisorError
from sccs.supervisor.edit import adopt, set_model
from sccs.supervisor.render import new_agent
from sccs.supervisor.wrappers import AgentInfo, body_hash, scan_agents
from tests.conftest import FIX, write_agent

OLD = "openrouter/~moonshotai/kimi-latest"
NEW = "openrouter/~moonshotai/kimi-k3"
CFG_BEFORE = "repository:\n  path: ~/x\n"


def only(agents: list[AgentInfo], name: str) -> AgentInfo:
    found = [a for a in agents if a.name == name]
    assert len(found) == 1, [a.name for a in agents]
    return found[0]


def scan(home, name):
    return only(scan_agents(home, SccsConfig(repository=RepositoryConfig(path="~/x"))), name)


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CFG_BEFORE)
    return path


@pytest.fixture
def opencode_models_readable(fake_bin):
    fake_bin("opencode", stdout=f"{OLD}\n{NEW}\n")


def adopted(home, cfg, text=None):
    p = write_agent(home, "opencode-worker", FIX("opencode-worker.md") if text is None else text)
    assert adopt("opencode-worker", home, cfg) is True
    return p


def stored_hash(text):
    return re.search(r"^  hash: (\S+)\r?$", text, re.MULTILINE).group(1)


def test_adopt_keeps_body_and_frontmatter_bytes(fake_home, cfg):
    p = write_agent(fake_home, "opencode-worker", FIX("opencode-worker.md"))
    before = p.read_bytes()
    assert adopt("opencode-worker", fake_home, cfg) is True
    after = p.read_bytes()
    marker = (
        b"sccs:\n  managed: true\n  template: adopted\n  shape: opencode\n  template_version: 1\n  hash: "
        + stored_hash(after.decode()).encode()
        + b"\n"
    )
    assert after.replace(marker, b"", 1) == before
    info = scan(fake_home, "opencode-worker")
    assert info.managed == "adopted" and info.template == "opencode" and info.hash_ok is True
    assert "opencode-worker" in cfg.read_text()


def test_adopt_twice_is_noop(fake_home, cfg):
    p = adopted(fake_home, cfg)
    once = p.read_bytes()
    assert adopt("opencode-worker", fake_home, cfg) is False
    assert p.read_bytes() == once


def test_adopt_refuses_unmanageable(fake_home, cfg):
    write_agent(fake_home, "plain", "---\nname: plain\n---\nJust text.\n")
    write_agent(fake_home, "nofm", "No frontmatter\n")
    with pytest.raises(SupervisorError):
        adopt("plain", fake_home, cfg)
    with pytest.raises(SupervisorError):
        adopt("nofm", fake_home, cfg)
    with pytest.raises(SupervisorError):
        adopt("missing", fake_home, cfg)
    assert cfg.read_text() == CFG_BEFORE


def test_adopt_noop_for_new_agent(fake_home, cfg, opencode_models_readable):
    new_agent("opencode", "fresh", OLD, fake_home, cfg)
    assert adopt("fresh", fake_home, cfg) is False


def test_set_model_surgical(fake_home, cfg, opencode_models_readable):
    p = adopted(fake_home, cfg)
    before = p.read_text()
    check = set_model("opencode-worker", NEW, fake_home)
    assert check.status == "verified"
    after = p.read_text()
    body = parse_frontmatter_ex(after).body
    new_hash = body_hash(body, "opencode")
    expected = before.replace(OLD, NEW, 1).replace(stored_hash(before), new_hash)
    assert after == expected
    info = scan(fake_home, "opencode-worker")
    assert info.hash_ok is True and info.cli_model == NEW


def test_set_model_on_new_agent(fake_home, cfg, opencode_models_readable):
    new_agent("opencode", "fresh", OLD, fake_home, cfg)
    set_model("fresh", NEW, fake_home)
    info = scan(fake_home, "fresh")
    assert info.managed == "new" and info.cli_model == NEW and info.hash_ok is True


def test_set_model_after_hand_edit_keeps_mismatch(fake_home, cfg, opencode_models_readable):
    p = adopted(fake_home, cfg)
    p.write_text(p.read_text() + "\nMy note.\n")
    old_hash = stored_hash(p.read_text())
    set_model("opencode-worker", NEW, fake_home)
    info = scan(fake_home, "opencode-worker")
    assert info.cli_model == NEW and info.hash_ok is False
    assert "My note." in p.read_text() and stored_hash(p.read_text()) == old_hash


def test_set_model_unverified_is_allowed(fake_home, cfg, empty_path):
    p = adopted(fake_home, cfg)
    check = set_model("opencode-worker", NEW, fake_home)
    assert check.ok and check.status == "unverified"
    assert NEW in p.read_text()


def test_set_model_rejected_changes_nothing(fake_home, cfg, opencode_models_readable):
    p = adopted(fake_home, cfg)
    before = p.read_bytes()
    with pytest.raises(SupervisorError, match="not offered"):
        set_model("opencode-worker", "openrouter/other", fake_home)
    assert p.read_bytes() == before


def test_set_model_refuses_plugin_and_unmanaged(fake_home, cfg, empty_path):
    write_agent(fake_home, "opencode-worker", FIX("opencode-worker.md"))
    with pytest.raises(SupervisorError):
        set_model("opencode-worker", NEW, fake_home)
    with pytest.raises(SupervisorError):
        set_model("codex:rescue", NEW, fake_home)
    with pytest.raises(SupervisorError):
        set_model("nothing", NEW, fake_home)


def test_set_model_refuses_claude_model_on_agy(fake_home, cfg, empty_path):
    p = write_agent(fake_home, "antigravity-worker", FIX("antigravity-worker.md"))
    assert adopt("antigravity-worker", fake_home, cfg) is True
    before = p.read_bytes()
    with pytest.raises(SupervisorError, match="gemini-"):
        set_model("antigravity-worker", "claude-opus-5", fake_home)
    assert p.read_bytes() == before


@pytest.mark.parametrize("bom", ["", "﻿"])
def test_crlf_bom_preserved(fake_home, cfg, opencode_models_readable, bom):
    text = bom + FIX("opencode-worker.md").replace("\r\n", "\n").replace("\n", "\r\n")
    p = write_agent(fake_home, "opencode-worker", text)
    before = p.read_bytes()
    assert adopt("opencode-worker", fake_home, cfg) is True
    mid = p.read_bytes()
    assert mid.startswith(before[:3] if bom else b"---")
    assert b"\r\n" in mid and re.search(rb"(?<!\r)\n", mid) is None
    assert scan(fake_home, "opencode-worker").hash_ok is True
    set_model("opencode-worker", NEW, fake_home)
    after = p.read_bytes()
    assert after.startswith(before[:3] if bom else b"---")
    assert re.search(rb"(?<!\r)\n", after) is None
    info = scan(fake_home, "opencode-worker")
    assert info.cli_model == NEW and info.hash_ok is True
    assert after.count(NEW.encode()) == 1  # only the command's token changed


def test_adopt_with_malformed_config_leaves_file_byte_identical(fake_home, tmp_path):
    write_agent(fake_home, "ocw", FIX("opencode-worker.md"))
    path = fake_home / ".claude" / "agents" / "ocw.md"
    before = path.read_bytes()
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed\n")
    with pytest.raises(SupervisorError):
        adopt("ocw", fake_home, bad)
    assert path.read_bytes() == before


def test_adopt_restores_file_when_exclude_write_fails(fake_home, cfg, monkeypatch):
    from sccs.config.loader import ConfigWriteError

    write_agent(fake_home, "ocw", FIX("opencode-worker.md"))
    path = fake_home / ".claude" / "agents" / "ocw.md"
    before = path.read_bytes()

    def boom(*_a, **_k):
        raise ConfigWriteError("disk full")

    monkeypatch.setattr("sccs.supervisor.render.add_supervisor_excludes", boom)
    with pytest.raises(SupervisorError, match="disk full"):
        adopt("ocw", fake_home, cfg)
    assert path.read_bytes() == before
