import json
from pathlib import Path

from sccs.config.schema import RepositoryConfig, SccsConfig
from sccs.convert.frontmatter import parse_frontmatter_ex
from sccs.supervisor.wrappers import (
    AgentInfo,
    body_hash,
    detect_shape,
    find_model_token,
    find_model_token_in_file_text,
    scan_agents,
)
from tests.conftest import FIX, write_agent


def only(agents: list[AgentInfo], name: str) -> AgentInfo:
    found = [a for a in agents if a.name == name]
    assert len(found) == 1, [a.name for a in agents]
    return found[0]


def install_fake_plugin(home: Path, key: str, agents: list[str]) -> Path:
    install = home / ".claude" / "plugins" / "cache" / key.replace("@", "-")
    (install / "agents").mkdir(parents=True)
    for stem in agents:
        (install / "agents" / f"{stem}.md").write_text(f"---\nname: {stem}\n---\nBody\n", encoding="utf-8")
    index = home / ".claude" / "plugins" / "installed_plugins.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(index.read_text()) if index.exists() else {"version": 2, "plugins": {}}
    data["plugins"][key] = [{"scope": "user", "installPath": str(install), "version": "1"}]
    index.write_text(json.dumps(data), encoding="utf-8")
    return install


def config_with_excludes(opencode: list[str], pi: list[str], codex: list[str]) -> SccsConfig:
    cfg = SccsConfig(repository=RepositoryConfig(path="/nonexistent"))
    cfg.opencode.exclude = list(opencode)
    cfg.pi.exclude = list(pi)
    cfg.codex.exclude = list(codex)
    return cfg


def _body(name: str) -> str:
    return parse_frontmatter_ex(FIX(name)).body


def test_real_agy_wrapper_recognised():
    body = _body("antigravity-worker.md")
    assert detect_shape(body) == "agy"
    s, e = find_model_token(body, "agy")  # type: ignore[misc]
    assert body[s:e] == "gemini-4-argon-high"


def test_real_opencode_wrapper_recognised():
    body = _body("opencode-worker.md")
    assert detect_shape(body) == "opencode"
    s, e = find_model_token(body, "opencode")  # type: ignore[misc]
    assert body[s:e] == "openrouter/~moonshotai/kimi-latest"


def test_prose_mention_of_flash_model_is_not_the_token():
    body = _body("antigravity-worker.md")
    s, e = find_model_token(body, "agy")  # type: ignore[misc]
    assert "flash" not in body[s:e]


def test_detect_shape_codex_and_none():
    codex = 'x\n```bash\ntimeout 900 codex exec -s read-only --ephemeral -m gpt-5 "<P>"\n```\n'
    assert detect_shape(codex) == "codex"
    s, e = find_model_token(codex, "codex")  # type: ignore[misc]
    assert codex[s:e] == "gpt-5"
    assert detect_shape("just prose, agy -p mentioned\n") is None
    assert detect_shape("```bash\nagy -p x --mode accept-edits\n```\n") is None


def test_detect_shape_only_looks_in_first_bash_block():
    body = "```bash\necho hi\n```\n\n```bash\ncodex exec -s read-only -m x\n```\n"
    assert detect_shape(body) is None


def test_hash_ignores_model_but_not_other_edits():
    body = _body("opencode-worker.md")
    other_model = body.replace("kimi-latest", "kimi-k3", 1)
    assert body_hash(body, "opencode") == body_hash(other_model, "opencode")
    assert body_hash(body + "\nextra", "opencode") != body_hash(body, "opencode")


def test_crlf_and_bom(fake_home):
    lf = FIX("opencode-worker.md")
    crlf = lf.replace("\n", "\r\n")
    body = parse_frontmatter_ex(crlf).body
    assert detect_shape(body) == "opencode"
    assert body_hash(body, "opencode") == body_hash(parse_frontmatter_ex(lf).body, "opencode")
    s, e = find_model_token(body, "opencode")  # type: ignore[misc]
    assert body[s:e] == "openrouter/~moonshotai/kimi-latest"
    # through scan_agents, with BOM
    write_agent(fake_home, "bom-worker", "﻿" + crlf)
    a = only(scan_agents(fake_home, config_with_excludes([], [], [])), "bom-worker")
    assert a.template == "opencode"
    assert a.cli_model == "openrouter/~moonshotai/kimi-latest"
    assert a.managed == "no"


def test_missing_agents_dir(fake_home):
    assert [a for a in scan_agents(fake_home) if a.source == "user"] == []


def test_unrecognised_agent_listed_unmanaged(fake_home):
    write_agent(fake_home, "helper", "---\nname: helper\n---\nJust prose.\n")
    a = only(scan_agents(fake_home), "helper")
    assert a.template is None and a.managed == "no" and a.cli_model is None and a.hash_ok is None


def test_skips_underscore_dot_and_local(fake_home):
    for n in ("_draft", ".hidden", "x.local"):
        write_agent(fake_home, n, "---\nname: x\n---\nb\n")
    write_agent(fake_home, "keep", "---\nname: keep\n---\nb\n")
    assert [a.name for a in scan_agents(fake_home) if a.source == "user"] == ["keep"]


def test_unmanaged_recognised_wrapper(fake_home):
    write_agent(fake_home, "antigravity-worker", FIX("antigravity-worker.md"))
    a = only(scan_agents(fake_home), "antigravity-worker")
    assert (a.template, a.managed, a.cli_model, a.hash_ok) == ("agy", "no", "gemini-4-argon-high", None)


def _managed_text(body: str, template: str, hash_value: str, managed_kind: str = "new") -> str:
    sccs = f"sccs:\n  managed: true\n  template: {template}\n  hash: {hash_value}\n"
    if managed_kind == "adopted":
        sccs = f"sccs:\n  managed: true\n  template: adopted\n  shape: opencode\n  hash: {hash_value}\n"
    return f"---\nname: m\n{sccs}---\n{body}"


def test_managed_new_hash_ok_and_edited(fake_home):
    body = _body("opencode-worker.md")
    good = body_hash(body, "opencode")
    write_agent(fake_home, "m", _managed_text(body, "opencode", good))
    a = only(scan_agents(fake_home), "m")
    assert (a.template, a.managed, a.hash_ok) == ("opencode", "new", True)
    write_agent(fake_home, "m", _managed_text(body + "\nhand edit\n", "opencode", good))
    assert only(scan_agents(fake_home), "m").hash_ok is False


def test_managed_adopted(fake_home):
    body = _body("opencode-worker.md")
    write_agent(fake_home, "m", _managed_text(body, "opencode", body_hash(body, "opencode"), "adopted"))
    a = only(scan_agents(fake_home), "m")
    assert (a.template, a.managed, a.hash_ok) == ("opencode", "adopted", True)


def test_codex_plugin_agent_listed_readonly(fake_home, empty_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess spawned")

    monkeypatch.setattr("sccs.doctor.runner._run", boom)
    (fake_home / ".codex").mkdir()
    (fake_home / ".codex" / "config.toml").write_text('model = "gpt-9"\n', encoding="utf-8")
    install_fake_plugin(fake_home, "codex@openai-codex", agents=["codex-rescue"])
    install_fake_plugin(fake_home, "other@somewhere", agents=["nope"])
    agents = scan_agents(fake_home)
    a = only(agents, "codex:codex-rescue")
    assert (a.source, a.template, a.managed, a.path is not None, a.cli_model) == ("plugin", None, "no", True, "gpt-9")
    assert not [x for x in agents if "nope" in x.name]


def test_malformed_plugin_index(fake_home):
    idx = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    idx.parent.mkdir(parents=True)
    idx.write_text("{not json", encoding="utf-8")
    assert scan_agents(fake_home) == []


def test_excluded_needs_all_three_lists(fake_home):
    write_agent(fake_home, "w", "---\nname: w\n---\nx\n")
    assert only(scan_agents(fake_home, config_with_excludes(["w"], ["w"], ["w"])), "w").excluded is True
    assert only(scan_agents(fake_home, config_with_excludes(["w"], ["w"], [])), "w").excluded is False


def test_find_model_token_in_raw_crlf_file_text():
    for prefix in ("", "\ufeff"):
        text = prefix + FIX("opencode-worker.md").replace("\n", "\r\n")
        s, e = find_model_token_in_file_text(text, "opencode")  # type: ignore[misc]
        assert text[s:e] == "openrouter/~moonshotai/kimi-latest"
    lf = FIX("antigravity-worker.md")
    s, e = find_model_token_in_file_text(lf, "agy")  # type: ignore[misc]
    assert lf[s:e] == "gemini-4-argon-high"
    assert find_model_token_in_file_text("no frontmatter\n", "agy") is None


def test_codex_plugin_with_two_install_paths_yields_one_agent(tmp_path):
    import json

    for scope in ("a", "b"):
        (tmp_path / "plug" / scope / "agents").mkdir(parents=True)
        agent_file = tmp_path / "plug" / scope / "agents" / "codex-rescue.md"
        agent_file.write_text("---\nname: x\n---\nb\n", encoding="utf-8")
    index = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    index.parent.mkdir(parents=True)
    entries = [
        {"scope": "project", "installPath": str(tmp_path / "plug" / "a")},
        {"scope": "user", "installPath": str(tmp_path / "plug" / "b")},
    ]
    index.write_text(json.dumps({"plugins": {"codex@openai-codex": entries}}), encoding="utf-8")
    found = [a for a in scan_agents(tmp_path, None) if a.source == "plugin"]
    assert [a.name for a in found] == ["codex:codex-rescue"]
    assert found[0].path == tmp_path / "plug" / "b" / "agents" / "codex-rescue.md"


def test_mode_label_marks_edited_managed_agents():
    from sccs.supervisor.wrappers import AgentInfo, mode_label

    base = {"name": "w", "path": None, "source": "user", "template": "agy", "cli_model": "m", "excluded": False}
    assert mode_label(AgentInfo(managed="new", hash_ok=False, **base)) == "read-only (edited)"
    assert mode_label(AgentInfo(managed="new", hash_ok=True, **base)) == "read-only"
