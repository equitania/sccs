# Agent Supervisor Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sccs agents` — a Textual full-screen UI plus `--json` CLI that shows the five AI CLIs, Claude Code's supervisor role and every delegating wrapper agent, and lets the user change a wrapper's CLI model, create read-only wrappers from bundled templates and adopt the two hand-written ones.

**Architecture:** A new core package `sccs/supervisor/` (detection, model lists, wrapper parsing, rendering, edits) that never imports Textual. A `sccs agents` click group in `sccs/cli.py` exposes it, Core-First with `--json`. `sccs/supervisor/tui.py` is a thin Textual app (layout variant C) on top of the same core functions, imported lazily.

**Tech Stack:** Python ≥3.11, click, rich, PyYAML, pydantic, **Textual (new)**, pytest, hatchling, uv.

**Spec:** `docs/superpowers/specs/2026-11-09-agent-supervisor-setup-design.md`

## Global Constraints

- Release **2.73.0**: bump `pyproject.toml`, `sccs/__init__.py`, `CLAUDE.md` (`**Version**:`), then `uv lock`.
- Configuration only: nothing here starts, dispatches or monitors agent work.
- Every subprocess goes through `sccs/doctor/runner.py` `_run` (`shell=False`, `stdin=DEVNULL`, validated head, a timeout).
- Model pattern, exactly: `^[A-Za-z0-9._:/~][A-Za-z0-9._:/~-]*$`. The Gemini (`agy`) template additionally requires the prefix `gemini-`.
- Agent names for `new`: `^[a-z0-9][a-z0-9-]*$`, no `/`, no `.md` suffix.
- Templates are read-only only: agy `--mode plan --settings "$AGY_RO"`; OpenCode `--agent claude-ro` with the inline `OPENCODE_CONFIG_CONTENT`; Codex `codex exec -s read-only --ephemeral`. Never `--dangerously-skip-permissions`, never OpenCode `--auto`, never `--mode accept-edits`.
- Wrapper frontmatter `model: haiku`, `tools: Bash, Read` — fixed, never offered for editing.
- No Pi template. `sccs agents new pi …` exits non-zero with: `Pi has no tested wrapper template yet.`
- Unmanaged agents that match no template shape and all plugin agents are never written.
- Auth files are checked for existence only; their contents are never read into output.
- A value that cannot be determined is shown as `unknown` (or `unverified` for models), never guessed.
- UI and CLI text in English (like all sccs output). User docs bilingual DE/EN in one file; every snippet a user types is **fish syntax**.
- `sccs agents list --json` and every other non-TUI command must work without importing `textual` (test enforces it).
- Tests must pass on Linux CI: fake binaries on a temporary `PATH`, `HOME` redirected to `tmp_path`, no macOS paths assumed; CLI assertions strip ANSI.
- Commits only when the Captain has authorised commits for this execution. Prefixes `[ADD]`/`[CHG]`/`[FIX]`; trailer lines as given in the session. Before each commit run `python3 ~/.claude/scripts/public_repo_guard.py` on the staged diff (the repo pushes to GitHub).

## Review Focus

1. **Agent files with CRLF line endings or a UTF-8 BOM** (synced from Windows) — must be recognised, model-edited and adopted without converting the rest of the file. Test in Task 3 and Task 5.
2. **Missing `~/.claude/agents` or a tool whose `--version` hangs or exits non-zero** (fresh host, broken install) — the screen still renders, the tool shows version `unknown`. Test in Task 1 and Task 3.
3. **`new` with a name that already exists, or a path-like name (`../x`, `a/b`, `x.md`)** — refuse, write nothing, touch no config. Test in Task 4.
4. **`config.yaml` without an `opencode:`/`pi:`/`codex:` block, or with the name already excluded** — block created, entry added once, backup written, nothing else in the file changes. Test in Task 4.
5. **`set-model` on a managed file that was hand-edited since** — surgical edit still happens, but the stored hash is *not* refreshed, so the re-render protection keeps seeing the edit. Test in Task 5.

---

## File Structure

| File | Responsibility |
|---|---|
| `sccs/supervisor/__init__.py` | Re-exports the public core API |
| `sccs/supervisor/tools.py` | Detect the five tools: binary, version, login presence, default model, config path |
| `sccs/supervisor/models.py` | Per-tool model lists and model validation |
| `sccs/supervisor/wrappers.py` | Scan agent files and plugin agents, recognise template shapes, extract the CLI model, compute the hash |
| `sccs/supervisor/templates/{agy,opencode,codex}.md` | Bundled wrapper templates with `{{NAME}}`, `{{MODEL}}` placeholders |
| `sccs/supervisor/render.py` | Render a template into a new agent file; `new_agent()` |
| `sccs/supervisor/edit.py` | `set_model()`, `adopt()` — textual, surgical edits |
| `sccs/supervisor/tui.py` | Textual app (variant C), help screen |
| `sccs/config/loader.py` | + `add_supervisor_excludes()` |
| `sccs/doctor/runner.py` | + `run_tool_version()`, `run_agy_models()` |
| `sccs/cli.py` | + `agents` group |
| `docs/usage/agents.md` | Usage guide (bilingual), bundled into the wheel as `sccs/data/agents.md` |
| `docs/architecture.md` | + section "Supervisor and wrapper agents" (DE and EN halves) |
| `tests/test_supervisor_*.py` | One test file per core module, plus `test_supervisor_cli.py`, `test_supervisor_tui.py` |

---

### Task 1: Tool detection

**Files:**
- Create: `sccs/supervisor/__init__.py`, `sccs/supervisor/tools.py`
- Modify: `sccs/doctor/runner.py` (append after `run_opencode_models`)
- Test: `tests/test_supervisor_tools.py`

**Interfaces:**
- Produces:
  - `runner.run_tool_version(binary: str) -> str | None` — `_run([binary, "--version"], timeout=10, check=False)`; first non-empty stdout line, `None` on `DoctorError` or non-zero exit.
  - `ToolId = Literal["claude", "codex", "opencode", "agy", "pi"]`
  - `@dataclass(frozen=True) class ToolInfo: id: ToolId; label: str; binary: str; installed: bool; version: str | None; login: Literal["yes", "no", "unknown"]; default_model: str | None; config_path: Path; config_present: bool`
  - `detect_tools(home: Path | None = None) -> list[ToolInfo]` — fixed order claude, codex, opencode, agy, pi.

Values to pin (labels / binary / config path / default model source / login presence file):
- `claude` "Claude Code" / `claude` / `~/.claude` / `"model"` in `~/.claude/settings.json` / `unknown` (keychain)
- `codex` "Codex" / `codex` / `~/.codex` / `model` in `~/.codex/config.toml` (stdlib `tomllib`) / `~/.codex/auth.json`
- `opencode` "OpenCode" / `opencode` / `~/.config/opencode` / `None` / `~/.local/share/opencode/auth.json`
- `agy` "Antigravity" / `agy` / `~/.gemini/antigravity` / `None` / `unknown`
- `pi` "Pi" / `pi` / `~/.pi/agent` / `defaultModel` in `~/.pi/agent/settings.json` if present / `~/.pi/agent/auth.json`

Login: presence file exists → `yes`, missing → `no`, no presence file defined → `unknown`. The builder may refine the heuristics; it must never read the file's content.

- [ ] **Step 1: Write the failing tests**

```python
def test_missing_binary_is_not_installed(fake_home, empty_path):
    pi = {t.id: t for t in detect_tools(fake_home)}["pi"]
    assert pi.installed is False and pi.version is None

def test_config_present_without_binary(fake_home, empty_path):
    (fake_home / ".pi/agent").mkdir(parents=True)
    pi = {t.id: t for t in detect_tools(fake_home)}["pi"]
    assert pi.installed is False and pi.config_present is True

def test_version_from_fake_binary(fake_home, fake_bin):
    fake_bin("agy", stdout="1.5.3\n")
    agy = {t.id: t for t in detect_tools(fake_home)}["agy"]
    assert agy.installed and agy.version == "1.5.3"

def test_version_failure_is_unknown(fake_home, fake_bin):          # Review Focus 2
    fake_bin("codex", stdout="", exit_code=3)
    assert {t.id: t for t in detect_tools(fake_home)}["codex"].version is None

def test_codex_default_model_from_config_toml(fake_home, empty_path):
    (fake_home / ".codex").mkdir(); (fake_home / ".codex/config.toml").write_text('model = "gpt-6.1-terra"\n')
    assert {t.id: t for t in detect_tools(fake_home)}["codex"].default_model == "gpt-6.1-terra"

def test_login_presence_only(fake_home, empty_path):
    (fake_home / ".codex").mkdir(); (fake_home / ".codex/auth.json").write_text('{"secret":"x"}')
    codex = {t.id: t for t in detect_tools(fake_home)}["codex"]
    assert codex.login == "yes" and "secret" not in repr(codex)
```

Fixtures `fake_home` (tmp dir, `HOME` monkeypatched), `empty_path` (`PATH` = empty tmp dir) and `fake_bin(name, stdout, exit_code=0)` (writes an executable `#!/bin/sh` script into a tmp dir prepended to `PATH`) go into `tests/conftest.py` — reused by later tasks.

- [ ] **Step 2: Run** `pytest tests/test_supervisor_tools.py -q` — Expected: FAIL (`ModuleNotFoundError: sccs.supervisor`).
- [ ] **Step 3: Implement** `run_tool_version`, `ToolInfo`, `detect_tools` as specified.
- [ ] **Step 4: Run** `pytest tests/test_supervisor_tools.py -q` — Expected: all pass.
- [ ] **Step 5: Commit** `[ADD] supervisor: detect the five agent CLIs`

---

### Task 2: Model lists and validation

**Files:**
- Create: `sccs/supervisor/models.py`
- Modify: `sccs/doctor/runner.py` (+ `run_agy_models`)
- Test: `tests/test_supervisor_models.py`

**Interfaces:**
- Consumes: `ToolId`, `runner.run_opencode_models()`.
- Produces:
  - `runner.run_agy_models() -> str` — `_run(["agy", "models"], timeout=30, check=False)` stdout, `""` on failure.
  - `@dataclass(frozen=True) class ModelList: tool: ToolId; models: tuple[str, ...]; readable: bool`
  - `list_models(tool: ToolId, home: Path | None = None) -> ModelList` — `agy`: `run_agy_models()` lines; `opencode`: `run_opencode_models()` lines; `claude`: `("haiku","sonnet","opus","fable")`, readable; `codex`: the config.toml model if any, `readable=False`; `pi`: model ids from `~/.pi/agent/models.json` if parseable, else `readable=False`. Lines are stripped; blank and ANSI-only lines dropped.
  - `MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/~][A-Za-z0-9._:/~-]*$")`
  - `@dataclass(frozen=True) class ModelCheck: ok: bool; status: Literal["verified", "unverified", "rejected"]; reason: str | None`
  - `check_model(template: str, model: str, available: ModelList) -> ModelCheck` — `template` is `"agy" | "opencode" | "codex"`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("bad", ["x; rm -rf ~", "$(id)", "a b", "`id`", "-m", "--help", "", "a|b", "a\nb"])
def test_pattern_rejects(bad):
    assert check_model("opencode", bad, ModelList("opencode", (bad,), True)).status == "rejected"

def test_gemini_template_rejects_non_gemini():
    ml = ModelList("agy", ("gemini-4-argon-high", "claude-opus-5-5-high"), True)
    assert check_model("agy", "claude-opus-5-5-high", ml).status == "rejected"
    assert check_model("agy", "gemini-4-argon-high", ml).status == "verified"

def test_absent_from_readable_list_is_rejected():
    ml = ModelList("opencode", ("openrouter/~moonshotai/kimi-latest",), True)
    assert check_model("opencode", "openrouter/other", ml).status == "rejected"

def test_unreadable_list_gives_unverified():
    ml = ModelList("opencode", (), False)
    c = check_model("opencode", "openrouter/~moonshotai/kimi-latest", ml)
    assert c.ok and c.status == "unverified"

def test_agy_list_from_fake_binary(fake_home, fake_bin):
    fake_bin("agy", stdout="gemini-4-argon-high\ngemini-3.8-flash-medium\n")
    assert list_models("agy", fake_home).models == ("gemini-4-argon-high", "gemini-3.8-flash-medium")

def test_codex_list_is_not_readable(fake_home, empty_path):
    assert list_models("codex", fake_home).readable is False
```

- [ ] **Step 2: Run** `pytest tests/test_supervisor_models.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** — Expected: all pass.
- [ ] **Step 5: Commit** `[ADD] supervisor: per-tool model lists and model validation`

---

### Task 3: Scan agents and recognise wrapper shapes

**Files:**
- Create: `sccs/supervisor/wrappers.py`
- Create fixtures: `tests/fixtures/supervisor/antigravity-worker.md`, `tests/fixtures/supervisor/opencode-worker.md` — **byte-exact copies** of `~/.claude/agents/antigravity-worker.md` and `~/.claude/agents/opencode-worker.md` as of 09.11.2026 (they contain no personal data; the guard must stay clean).
- Test: `tests/test_supervisor_wrappers.py`

**Interfaces:**
- Consumes: `parse_frontmatter_ex` from `sccs/convert/frontmatter.py` (read only — the file is rewritten textually in Task 5, never via `render_frontmatter`).
- Produces:
  - `TemplateId = Literal["agy", "opencode", "codex"]`
  - `@dataclass(frozen=True) class AgentInfo: name: str; path: Path | None; source: Literal["user", "plugin"]; template: TemplateId | None; managed: Literal["new", "adopted", "no"]; cli_model: str | None; hash_ok: bool | None; excluded: bool`
  - `detect_shape(body: str) -> TemplateId | None` — looks only inside the **first** ```` ```bash ```` fenced block: `agy` if it contains `agy -p`, `--mode plan` and `--settings "$AGY_RO"`; `opencode` if `opencode run --agent claude-ro`; `codex` if `codex exec -s read-only`.
  - `find_model_token(body: str, template: TemplateId) -> tuple[int, int] | None` — span of the model value in the first bash block: agy after `--model `, opencode and codex after `-m `; the value runs to the next whitespace.
  - `body_hash(body: str, template: TemplateId) -> str` — sha256 hex of the body with the model span replaced by `{{MODEL}}`, line endings normalised to `\n` before hashing.
  - `scan_agents(home: Path | None = None, config: SccsConfig | None = None) -> list[AgentInfo]` — user agents from `~/.claude/agents/*.md` (skip names starting with `_` or `.`, and `*.local.md`), then plugin agents. `managed` from frontmatter `sccs.managed` + `sccs.template`; `excluded` is True when the name is in all three of `config.opencode.exclude`, `config.pi.exclude`, `config.codex.exclude`.
  - Plugin agents: read `~/.claude/plugins/installed_plugins.json`; for the plugin key `codex@openai-codex`, each `<installPath>/agents/*.md` becomes `AgentInfo(name="codex:<stem>", source="plugin", template=None, managed="no", cli_model=<codex default model from detect_tools>, …)`. Other plugins are ignored. A missing or malformed JSON yields no plugin agents.

- [ ] **Step 1: Write the failing tests**

```python
def test_real_agy_wrapper_recognised():
    body = parse_frontmatter_ex(FIX("antigravity-worker.md")).body
    assert detect_shape(body) == "agy"
    s, e = find_model_token(body, "agy"); assert body[s:e] == "gemini-4-argon-high"

def test_real_opencode_wrapper_recognised():
    body = parse_frontmatter_ex(FIX("opencode-worker.md")).body
    assert detect_shape(body) == "opencode"
    s, e = find_model_token(body, "opencode"); assert body[s:e] == "openrouter/~moonshotai/kimi-latest"

def test_prose_mention_of_flash_model_is_not_the_token():
    body = parse_frontmatter_ex(FIX("antigravity-worker.md")).body
    s, e = find_model_token(body, "agy"); assert "flash" not in body[s:e]

def test_hash_ignores_model_but_not_other_edits():
    body = parse_frontmatter_ex(FIX("opencode-worker.md")).body
    other_model = body.replace("kimi-latest", "kimi-k3", 1)
    assert body_hash(body, "opencode") == body_hash(other_model, "opencode")
    assert body_hash(body + "\nextra", "opencode") != body_hash(body, "opencode")

def test_crlf_and_bom(tmp_path):                                    # Review Focus 1
    text = "﻿" + FIX("opencode-worker.md").replace("\n", "\r\n")
    body = parse_frontmatter_ex(text.lstrip("﻿")).body
    assert detect_shape(body) == "opencode"
    assert body_hash(body, "opencode") == body_hash(parse_frontmatter_ex(FIX("opencode-worker.md")).body, "opencode")

def test_missing_agents_dir(fake_home):                             # Review Focus 2
    assert [a for a in scan_agents(fake_home) if a.source == "user"] == []

def test_unrecognised_agent_listed_unmanaged(fake_home):
    write_agent(fake_home, "helper", "---\nname: helper\n---\nJust prose.\n")
    a = only(scan_agents(fake_home), "helper"); assert a.template is None and a.managed == "no"

def test_codex_plugin_agent_listed_readonly(fake_home):
    install_fake_plugin(fake_home, "codex@openai-codex", agents=["codex-rescue"])
    a = only(scan_agents(fake_home), "codex:codex-rescue"); assert a.source == "plugin"

def test_excluded_needs_all_three_lists(fake_home, config_with_excludes):
    ...  # name in opencode+pi+codex → True; missing from codex → False
```

`FIX(name)` reads the fixture with `newline=""` so CRLF tests are real. If the BOM case needs BOM stripping, do it in `scan_agents` (read with `encoding="utf-8-sig"`), and remember in `AgentInfo`-independent form for Task 5 that writes must restore it.

- [ ] **Step 2: Run** `pytest tests/test_supervisor_wrappers.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** — Expected: all pass.
- [ ] **Step 5: Commit** `[ADD] supervisor: recognise wrapper agents and their CLI model`

---

### Task 4: Templates, `new_agent` and export excludes

**Files:**
- Create: `sccs/supervisor/templates/agy.md`, `opencode.md`, `codex.md`, `sccs/supervisor/render.py`
- Modify: `sccs/config/loader.py` (+ `add_supervisor_excludes`, modelled on `save_opencode_model_map`: raw YAML, backup, only the three `exclude` keys touched)
- Test: `tests/test_supervisor_render.py`

**Interfaces:**
- Consumes: `check_model`, `list_models`, `body_hash`, `detect_shape`, `find_model_token`.
- Produces:
  - `add_supervisor_excludes(name: str, config_path: Path | None = None) -> bool` — True when something was added; appends `name` to `opencode.exclude`, `pi.exclude`, `codex.exclude`, creating blocks/lists as needed; no write and no backup when all three already contain it.
  - `render_template(template: TemplateId, name: str, model: str, description: str | None = None) -> str`
  - `@dataclass(frozen=True) class NewResult: path: Path; model_status: Literal["verified", "unverified"]; excludes_added: bool`
  - `new_agent(template: str, name: str, model: str | None = None, home: Path | None = None, config_path: Path | None = None) -> NewResult` — raises `SupervisorError(message)` (defined in `sccs/supervisor/__init__.py`) on: `template == "pi"` (exact message from Global Constraints), unknown template, invalid name, existing file, rejected model. Default model when `None`: agy `gemini-4-argon-high`, opencode `openrouter/~moonshotai/kimi-latest`, codex the `default_model` from `detect_tools`, else error `"No default Codex model in ~/.codex/config.toml; pass --model."`.

Templates:
- `agy.md` and `opencode.md` are the Task 3 fixtures with name and default model replaced by `{{NAME}}` / `{{MODEL}}`, and the frontmatter gaining the marker block. Description keeps the original wording, with the agent name substituted.
- `codex.md` follows the same structure ("You are a thin forwarding wrapper …", "How to call", "The prompt you build", "What you return"). Its command block, exactly:

```bash
OUT=$(mktemp -t codex-worker)
timeout 900 codex exec -s read-only --ephemeral -m {{MODEL}} -o "$OUT" "<PROMPT>" </dev/null >/dev/null 2>&1
echo "exit $?"; cat "$OUT"
```

  Failure mapping: EPERM on `/tmp/xcrun_db…` is Codex' own read-only sandbox (skip, not nono); exit 124 → timeout, split the task; auth error → user runs `codex login`.
- Marker block written into each rendered frontmatter:

```yaml
sccs:
  managed: true
  template: <agy|opencode|codex>
  template_version: 1
  hash: <body_hash of the rendered body>
```

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("t", ["agy", "opencode", "codex"])
def test_rendered_template_round_trips(t):
    text = render_template(t, "x-worker", MODEL[t])
    meta, body = parse_frontmatter_ex(text)[:2]
    assert detect_shape(body) == t and meta["model"] == "haiku" and meta["tools"] == "Bash, Read"
    s, e = find_model_token(body, t); assert body[s:e] == MODEL[t]
    assert meta["sccs"]["hash"] == body_hash(body, t)

def test_rendered_agy_matches_fixture_shape():
    # golden: rendering agy with the real name and model reproduces the fixture body byte-for-byte
    body = parse_frontmatter_ex(render_template("agy", "antigravity-worker", "gemini-4-argon-high")).body
    assert body == parse_frontmatter_ex(FIX("antigravity-worker.md")).body

def test_no_template_contains_forbidden_flags():
    for t in ("agy", "opencode", "codex"):
        txt = render_template(t, "x", MODEL[t])
        for flag in ("--dangerously-skip-permissions", "--auto", "accept-edits"):
            assert flag not in command_block(txt)

def test_new_pi_refused(fake_home):
    with pytest.raises(SupervisorError, match="Pi has no tested wrapper template yet."): new_agent("pi", "p", home=fake_home)

@pytest.mark.parametrize("bad", ["../x", "a/b", "x.md", "X", "-x", ""])  # Review Focus 3
def test_bad_names_write_nothing(fake_home, cfg, bad):
    with pytest.raises(SupervisorError): new_agent("opencode", bad, home=fake_home, config_path=cfg)
    assert not any((fake_home / ".claude/agents").glob("*")) and cfg.read_text() == CFG_BEFORE

def test_existing_name_refused(fake_home, cfg): ...

def test_excludes_created_and_idempotent(tmp_path):                 # Review Focus 4
    cfg = tmp_path / "config.yaml"; cfg.write_text("repository:\n  path: ~/x\n")
    assert add_supervisor_excludes("w", cfg) is True
    assert add_supervisor_excludes("w", cfg) is False
    raw = yaml.safe_load(cfg.read_text())
    assert raw["opencode"]["exclude"] == ["w"] == raw["pi"]["exclude"] == raw["codex"]["exclude"]
    assert raw["repository"] == {"path": "~/x"}
```

- [ ] **Step 2: Run** `pytest tests/test_supervisor_render.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** templates, `render_template`, `new_agent`, `add_supervisor_excludes`. Templates load via `importlib.resources.files("sccs.supervisor") / "templates"`.
- [ ] **Step 4: Run** — Expected: all pass. Then `uv build` and check that the wheel contains `sccs/supervisor/templates/*.md` (`unzip -l dist/*.whl | grep templates`).
- [ ] **Step 5: Manual end-to-end check of the Codex template** (spec: proven once before it counts). Render it into a scratch dir as `codex-worker.md`, run its command block by hand from the repo root with the prompt `Name one function in sccs/doctor/runner.py. Modify nothing.`; expected: `exit 0` and a function name. Record the result in the task report. If it fails, stop and report — do not adjust flags beyond the read-only set.
- [ ] **Step 6: Commit** `[ADD] supervisor: wrapper templates for agy, OpenCode and Codex`

---

### Task 5: `set_model` and `adopt`

**Files:**
- Create: `sccs/supervisor/edit.py`
- Test: `tests/test_supervisor_edit.py`

**Interfaces:**
- Consumes: `scan_agents`, `find_model_token`, `body_hash`, `detect_shape`, `check_model`, `list_models`, `add_supervisor_excludes`.
- Produces:
  - `set_model(name: str, model: str, home: Path | None = None) -> ModelCheck` — refuses (`SupervisorError`) plugin agents, unmanaged agents, rejected models. Replaces only the model span; if the stored hash matched the body *before* the edit, writes the new hash; otherwise leaves the stored hash unchanged. Writes via `atomic_write`, keeping BOM and line endings.
  - `adopt(name: str, home: Path | None = None, config_path: Path | None = None) -> bool` — only for `source == "user"`, `managed == "no"`, `template` not None; inserts the marker block (`template: adopted`, plus `shape: <agy|opencode|codex>` so later edits know the token rule) as text lines directly before the closing `---` fence; the body and every existing frontmatter line stay byte-identical; then `add_supervisor_excludes(name)`. Returns False when already managed.
  - For adopted files, `scan_agents` uses `sccs.shape` as `template`.

- [ ] **Step 1: Write the failing tests**

```python
def test_adopt_keeps_body_and_frontmatter_bytes(fake_home, cfg):
    p = install_fixture(fake_home, "opencode-worker.md"); before = p.read_bytes()
    assert adopt("opencode-worker", fake_home, cfg) is True
    after = p.read_bytes()
    assert after.replace(MARKER_BYTES(after), b"") == before       # only the marker lines were inserted
    assert only(scan_agents(fake_home), "opencode-worker").managed == "adopted"

def test_adopt_twice_is_noop(fake_home, cfg): ...

def test_set_model_surgical(fake_home, cfg, opencode_models_readable):
    p = adopted(fake_home, "opencode-worker"); before = p.read_text()
    set_model("opencode-worker", "openrouter/~moonshotai/kimi-k3", fake_home)
    assert p.read_text() == before.replace("openrouter/~moonshotai/kimi-latest", "openrouter/~moonshotai/kimi-k3", 1).replace(OLD_HASH, NEW_HASH)
    assert only(scan_agents(fake_home), "opencode-worker").hash_ok is True

def test_set_model_after_hand_edit_keeps_mismatch(fake_home, cfg):  # Review Focus 5
    p = adopted(fake_home, "opencode-worker"); p.write_text(p.read_text() + "\nMy note.\n")
    set_model("opencode-worker", "openrouter/~moonshotai/kimi-k3", fake_home)
    a = only(scan_agents(fake_home), "opencode-worker")
    assert a.cli_model == "openrouter/~moonshotai/kimi-k3" and a.hash_ok is False and "My note." in p.read_text()

def test_set_model_refuses_plugin_and_unmanaged(fake_home): ...
def test_set_model_refuses_claude_model_on_agy(fake_home): ...
def test_set_model_crlf_bom_preserved(fake_home): ...              # Review Focus 1
```

- [ ] **Step 2: Run** `pytest tests/test_supervisor_edit.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** — Expected: all pass.
- [ ] **Step 5: Commit** `[ADD] supervisor: change a wrapper's model, adopt hand-written wrappers`

---

### Task 6: `sccs agents` CLI group

**Files:**
- Modify: `sccs/cli.py` (new group after the `capacity` command; imports from `sccs.supervisor` inside the command functions, like `capacity` does)
- Test: `tests/test_supervisor_cli.py`

**Interfaces:**
- Consumes: everything above; `emit_json`, `emit_json_error`.
- Produces (click, `invoke_without_command=True`; bare `sccs agents` calls `sccs.supervisor.tui.run()` when stdout is a TTY, else prints `list` and the hint `Run in a terminal for the full-screen view.`):
  - `sccs agents list [--json]` → JSON `{"supervisor": {"tool": "claude", "model": …, "agents_dir": …}, "tools": [ToolInfo…], "agents": [AgentInfo…]}`
  - `sccs agents tools [--json]` → `{"tools": [...]}`
  - `sccs agents models TOOL [--json]` → `{"tool":…, "readable":…, "models":[…]}`
  - `sccs agents set-model NAME MODEL [--json]`
  - `sccs agents new TOOL NAME [--model M] [--json]`
  - `sccs agents adopt NAME [--yes] [--json]` — without `--yes` asks (`click.confirm`); with `--json` and without `--yes` it refuses with an error instead of prompting.
  - `SupervisorError` → exit 1, message on stderr, or `emit_json_error` with `--json`.
  - Rich table for `list` mirrors the main-screen columns: Agent, Tool (version + ✓/missing), Model, Mode (`read-only`, `plugin`, `unmanaged`), plus `€` for the opencode template.

- [ ] **Step 1: Write the failing tests** — `CliRunner` with `fake_home`/`fake_bin`:
  - `list --json` parses with `json.loads`, has the three top-level keys, Pi shows `installed: false`.
  - `new pi p` → exit code 1, output contains `Pi has no tested wrapper template yet.`
  - `new opencode x-worker --model 'a;b' --json` → exit 1, JSON has `"error"`.
  - `adopt opencode-worker --json` (no `--yes`) → exit 1, file unchanged.
  - **No Textual import:** run `python -c "import sys; from click.testing import CliRunner; from sccs.cli import cli; CliRunner().invoke(cli, ['agents','list','--json']); assert 'textual' not in sys.modules"` via `subprocess` with `fake_home` env → exit 0.
  - ANSI stripped before asserting on the table output.
- [ ] **Step 2: Run** `pytest tests/test_supervisor_cli.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the group. Update the `--help` docstrings; add `agents` to `docs/usage/cli-reference.md` (both languages).
- [ ] **Step 4: Run** `pytest tests/test_supervisor_cli.py tests/test_cli.py -q` — Expected: all pass.
- [ ] **Step 5: Commit** `[ADD] sccs agents: list, models, set-model, new, adopt (--json)`

---

### Task 7: Textual full-screen UI (variant C)

**Files:**
- Modify: `pyproject.toml` — add `textual` to `dependencies` with the range `>=<version uv resolves today>,<next major>`; run `uv lock`; `pip-audit` (or the CI audit step locally) must report nothing.
- Modify: `pyproject.toml` force-include: `"docs/usage/agents.md" = "sccs/data/agents.md"` (the file is created in Task 8; create a stub now so the build works).
- Create: `sccs/supervisor/tui.py`
- Test: `tests/test_supervisor_tui.py` (Textual `App.run_test()` pilot)

**Interfaces:**
- Consumes: `detect_tools`, `scan_agents`, `list_models`, `set_model`, `new_agent`, `adopt`.
- Produces: `run() -> None` and `class AgentsApp(App)`.

Layout, from the approved mockup (English text):
- Header line: `sccs agents   Supervisor: Claude Code ✓ <model> · ~/.claude/agents`
- `DataTable` columns `Agent | Tool | Model | Mode`; one row per agent from `scan_agents`; one dimmed `(free)` row per installed-or-missing tool that has no agent (Pi shows `pi missing`); `€` suffix for opencode-template rows; `unverified`/`edited` markers when `hash_ok is False`.
- Footer explanation line for the selected row (how read-only is enforced; `Export: off` when `excluded`).
- Keys: `enter` edit (opens a modal with model picker + adopt button when applicable), `m` model picker (`OptionList` from `list_models`, with a free-text input when `readable` is False), `n` new agent (tool select + name input; Pi disabled with the refusal text), `w` tools view (all `ToolInfo` fields; for missing tools the hint `Install via: sccs doctor install`), `?` help (renders the bundled `agents.md` with `MarkdownViewer`), `r` refresh, `q` quit.
- Plugin and unmanaged rows: edit keys show a notice instead of a modal.
- Tool detection and model lists run in Textual workers so the screen appears before slow subprocesses finish.

- [ ] **Step 1: Write the failing pilot tests:** app starts with `fake_home` containing the two fixtures and a codex plugin → table has rows `antigravity-worker`, `opencode-worker`, `codex:codex-rescue`, `(free)`; pressing `m` on the plugin row shows the notice and writes nothing; pressing `n`, choosing Pi, shows the refusal text; `?` opens a screen containing the heading of `agents.md`; `q` exits.
- [ ] **Step 2: Run** `pytest tests/test_supervisor_tui.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `AgentsApp`.
- [ ] **Step 4: Run** the pilot tests and the full suite `pytest -q` — Expected: all pass. Then a manual look: `sccs agents` in a real terminal at 100 columns and at 80 columns — the table must stay readable (truncate the Model column, never wrap rows).
- [ ] **Step 5: Commit** `[ADD] sccs agents: full-screen view (Textual)`

---

### Task 8: Documentation and release 2.73.0

**Files:**
- Create: `docs/usage/agents.md` (bilingual, structure like `docs/usage/codex.md`: language links, back link, `## Deutsch`, `## English`)
- Modify: `docs/architecture.md` (section "Supervisor und Wrapper-Agenten" in the DE half, "Supervisor and wrapper agents" in the EN half), `README.md` (feature bullet *(v2.73.0)* like the capacity one), `RELEASE_NOTES.md` (`## Version 2.73.0 (<date from the environment>)`), `docs/development/maintainer-notes.md` (new section "Supervisor wrappers" with the rules below), project `CLAUDE.md` (one maintainer-note bullet + version), `pyproject.toml`, `sccs/__init__.py`, `uv.lock`
- Test: `tests/test_docs.py` already checks doc links — extend if it enumerates usage docs.

`agents.md` content (spec, section "Documentation"):
1. Configure: `sccs agents`, keys, adopting the existing wrappers, new wrapper, model change, why `Export: off`.
2. Work: open a Herdr window, `cd` into the project, `claude`; after creating a new agent restart Claude Code. Example tasks, quoted as the user types them: „Lass den Diff von Codex, Gemini und Kimi prüfen und gleiche die Befunde am Code ab“, „Hol eine zweite Meinung von Gemini zu diesem Entwurf“. What the supervisor does: runs workers in the background, gets notified, marks findings as unverified claims, checks each against the code, reports which held.
3. Running / done / stuck: background notification; 900 s outer timeout; exit 124 → task too large, split.
4. Traps: Codex' own sandbox EPERM is not nono; Gemini needs the material inline (`jetski: no output produced`); OpenCode costs OpenRouter credit; free `opencode/*` models not for customer data; a new agent needs a restart.
5. All user snippets in fish syntax.

Architecture section (the approach): Claude as supervisor; thin Haiku wrappers with only Bash+Read; why not CAO; reviewers read-only and how each tool enforces it; a Gemini reviewer never falls back to a Claude model (otherwise Anthropic reviews itself — same rule as `sccs capacity`); the supervisor verifies every finding.

Maintainer-notes rules: model pattern and Gemini prefix; templates read-only only, forbidden flags; adoption inserts marker lines textually, never re-dumps frontmatter; `set-model` refreshes the hash only when it matched; plugin and unrecognised agents never written; auth files presence-only; core never imports Textual.

- [ ] **Step 1:** Write the docs and release files as listed.
- [ ] **Step 2:** Version 2.73.0 in the three places, then `uv lock`.
- [ ] **Step 3: Verify:** `ruff check sccs/ tests/`, `ruff format --check sccs/ tests/`, `mypy sccs/`, `pytest -q` — Expected: clean, all pass. `uv build` and `unzip -l dist/*.whl | grep -E "sccs/data/agents.md|supervisor/templates"` — Expected: four files.
- [ ] **Step 4:** `python3 ~/.claude/scripts/public_repo_guard.py` on the staged diff — Expected: clean.
- [ ] **Step 5: Commit** `[ADD] sccs agents: usage guide, approach, release 2.73.0`
