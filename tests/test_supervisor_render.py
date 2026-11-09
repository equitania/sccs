import re

import pytest
import yaml

from sccs.config.loader import add_supervisor_excludes
from sccs.convert.frontmatter import parse_frontmatter_ex
from sccs.supervisor import SupervisorError
from sccs.supervisor.render import new_agent, render_template
from sccs.supervisor.wrappers import body_hash, detect_shape, find_model_token
from tests.conftest import FIX, write_agent

MODEL = {"agy": "gemini-4-argon-high", "opencode": "openrouter/~moonshotai/kimi-latest", "codex": "gpt-5.5"}
CFG_BEFORE = "repository:\n  path: ~/x\n"


def command_block(text: str) -> str:
    match = re.search(r"```bash[ \t]*\n(.*?)\n[ \t]*```", text, re.DOTALL)
    assert match
    return match.group(1)


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CFG_BEFORE)
    return path


@pytest.mark.parametrize("t", ["agy", "opencode", "codex"])
def test_rendered_template_round_trips(t):
    text = render_template(t, "x-worker", MODEL[t])
    parsed = parse_frontmatter_ex(text)
    meta, body = parsed.metadata, parsed.body
    assert detect_shape(body) == t and meta["model"] == "haiku" and meta["tools"] == "Bash, Read"
    assert meta["name"] == "x-worker"
    version = 2 if t == "codex" else 1
    assert meta["sccs"] == {"managed": True, "template": t, "template_version": version, "hash": body_hash(body, t)}
    s, e = find_model_token(body, t)
    assert body[s:e] == MODEL[t]
    assert "{{" not in text


def test_rendered_agy_matches_fixture_body():
    body = parse_frontmatter_ex(render_template("agy", "antigravity-worker", "gemini-4-argon-high")).body
    assert body == parse_frontmatter_ex(FIX("antigravity-worker.md")).body


def test_rendered_opencode_matches_fixture_body():
    body = parse_frontmatter_ex(render_template("opencode", "opencode-worker", MODEL["opencode"])).body
    assert body == parse_frontmatter_ex(FIX("opencode-worker.md")).body


def test_description_override_is_valid_yaml():
    text = render_template("codex", "c", "m", description='Has: a colon and "quotes"')
    assert parse_frontmatter_ex(text).metadata["description"] == 'Has: a colon and "quotes"'


def test_codex_command_block_exact():
    assert command_block(render_template("codex", "c", "gpt-5.5")) == (
        'OUT=$(mktemp "${TMPDIR:-/tmp}/codex-worker.XXXXXX")\n'
        "timeout 900 codex exec -s read-only --ephemeral -m gpt-5.5 "
        '-o "$OUT" "<PROMPT>" </dev/null >/dev/null 2>"$OUT.err"\n'
        'echo "exit $?"; cat "$OUT"; tail -n 20 "$OUT.err"'
    )


def test_no_template_contains_forbidden_flags():
    for t in ("agy", "opencode", "codex"):
        block = command_block(render_template(t, "x", MODEL[t]))
        for flag in ("--dangerously-skip-permissions", "--auto", "accept-edits"):
            assert flag not in block


def test_new_pi_refused(fake_home):
    with pytest.raises(SupervisorError, match=re.escape("Pi has no tested wrapper template yet.")):
        new_agent("pi", "p", home=fake_home)


def test_unknown_template_refused(fake_home):
    with pytest.raises(SupervisorError):
        new_agent("nope", "p", home=fake_home)


@pytest.mark.parametrize("bad", ["../x", "a/b", "x.md", "X", "-x", ""])
def test_bad_names_write_nothing(fake_home, empty_path, cfg, bad):
    with pytest.raises(SupervisorError):
        new_agent("opencode", bad, home=fake_home, config_path=cfg)
    assert not (fake_home / ".claude").exists() and cfg.read_text() == CFG_BEFORE


def test_existing_name_refused(fake_home, empty_path, cfg):
    path = write_agent(fake_home, "w", "mine\n")
    with pytest.raises(SupervisorError, match="already exists"):
        new_agent("opencode", "w", home=fake_home, config_path=cfg)
    assert path.read_text() == "mine\n" and cfg.read_text() == CFG_BEFORE


def test_rejected_model_writes_nothing(fake_home, empty_path, cfg):
    with pytest.raises(SupervisorError):
        new_agent("agy", "g", model="claude-opus", home=fake_home, config_path=cfg)
    with pytest.raises(SupervisorError):
        new_agent("opencode", "o", model="bad model;rm", home=fake_home, config_path=cfg)
    assert not (fake_home / ".claude").exists() and cfg.read_text() == CFG_BEFORE


def test_new_agent_writes_file_and_excludes(fake_home, empty_path, cfg):
    result = new_agent("opencode", "kimi-w", home=fake_home, config_path=cfg)
    assert result.path == fake_home / ".claude/agents/kimi-w.md"
    assert result.model_status == "unverified" and result.excludes_added is True
    assert result.path.read_text() == render_template("opencode", "kimi-w", MODEL["opencode"])
    raw = yaml.safe_load(cfg.read_text())
    assert raw["codex"]["exclude"] == ["kimi-w"]


def test_new_codex_default_model_from_config(fake_home, empty_path, cfg):
    with pytest.raises(SupervisorError, match="No default Codex model"):
        new_agent("codex", "c", home=fake_home, config_path=cfg)
    assert cfg.read_text() == CFG_BEFORE
    (fake_home / ".codex").mkdir()
    (fake_home / ".codex/config.toml").write_text('model = "gpt-5.5"\n')
    result = new_agent("codex", "c", home=fake_home, config_path=cfg)
    assert "-m gpt-5.5 " in result.path.read_text()


def test_excludes_created_and_idempotent(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CFG_BEFORE)
    assert add_supervisor_excludes("w", cfg) is True
    assert add_supervisor_excludes("w", cfg) is False
    raw = yaml.safe_load(cfg.read_text())
    assert raw["opencode"]["exclude"] == ["w"] == raw["pi"]["exclude"] == raw["codex"]["exclude"]
    assert raw["repository"] == {"path": "~/x"}


def test_excludes_keep_other_keys_and_write_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / "config.yaml"
    cfg.write_text("opencode:\n  model_map: {a: b}\n  exclude: [old]\ncodex:\n  exclude: [w]\n")
    assert add_supervisor_excludes("w", cfg) is True
    raw = yaml.safe_load(cfg.read_text())
    assert raw["opencode"] == {"model_map": {"a": "b"}, "exclude": ["old", "w"]}
    assert raw["codex"]["exclude"] == ["w"] and raw["pi"]["exclude"] == ["w"]


def test_new_with_malformed_config_raises_and_writes_no_agent(fake_home, empty_path, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed\n")
    with pytest.raises(SupervisorError):
        new_agent("agy", "w", model="gemini-x", home=fake_home, config_path=bad)
    assert not (fake_home / ".claude" / "agents" / "w.md").exists()


def test_new_rolls_back_agent_file_when_exclude_write_fails(fake_home, empty_path, cfg, monkeypatch):
    from sccs.config.loader import ConfigWriteError

    def boom(*_a, **_k):
        raise ConfigWriteError("disk full")

    monkeypatch.setattr("sccs.supervisor.render.add_supervisor_excludes", boom)
    with pytest.raises(SupervisorError, match="disk full"):
        new_agent("agy", "w", model="gemini-x", home=fake_home, config_path=cfg)
    assert not (fake_home / ".claude" / "agents" / "w.md").exists()
