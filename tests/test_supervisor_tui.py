"""Pilot tests for the `sccs agents` full-screen view (Textual run_test)."""

from __future__ import annotations

import asyncio
import functools
import json

import pytest
from textual.widgets import DataTable, MarkdownViewer, OptionList, Static

from sccs.supervisor.render import PI_REFUSAL
from sccs.supervisor.tui import AgentsApp, HelpScreen, ModelScreen, NewScreen
from sccs.supervisor.wrappers import mode_label, scan_agents
from tests.conftest import FIX, write_agent


def arun(fn):
    """Run an async pilot test without a pytest-asyncio dependency."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        asyncio.run(fn(*args, **kwargs))

    return wrapper


@pytest.fixture(autouse=True)
def _env(fake_home, empty_path, monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("SCCS_CONFIG", str(cfg / "config.yaml"))
    write_agent(fake_home, "antigravity-worker", FIX("antigravity-worker.md"))
    write_agent(fake_home, "opencode-worker", FIX("opencode-worker.md"))
    plugin = fake_home / "plugins" / "codex"
    (plugin / "agents").mkdir(parents=True)
    (plugin / "agents" / "codex-rescue.md").write_text("---\nname: codex-rescue\n---\nbody\n", encoding="utf-8")
    index = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"plugins": {"codex@openai-codex": [{"installPath": str(plugin)}]}}), encoding="utf-8")
    return fake_home


def _names(app: AgentsApp) -> list[str]:
    table = app.query_one("#agents", DataTable)
    return [str(table.get_row_at(i)[0]) for i in range(table.row_count)]


def _select(app: AgentsApp, key: str) -> None:
    table = app.query_one("#agents", DataTable)
    table.move_cursor(row=[r.key.value for r in table.ordered_rows].index(key))


async def _ready(app: AgentsApp, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


@arun
async def test_rows_and_free_row(fake_home):
    app = AgentsApp(home=fake_home)
    async with app.run_test(size=(120, 30)) as pilot:
        await _ready(app, pilot)
        assert _names(app) == ["antigravity-worker", "opencode-worker", "codex:codex-rescue", "(free)"]
        table = app.query_one("#agents", DataTable)
        assert "pi" in str(table.get_row_at(3)[1]) and "missing" in str(table.get_row_at(3)[1])
        assert "€" in str(table.get_row_at(1)[3])


@arun
async def test_edit_key_on_plugin_row_notifies_and_writes_nothing(fake_home):
    before = {p: p.read_bytes() for p in (fake_home / ".claude" / "agents").glob("*.md")}
    app = AgentsApp(home=fake_home)
    async with app.run_test(size=(120, 30)) as pilot:
        await _ready(app, pilot)
        _select(app, "agent:codex:codex-rescue")
        await pilot.press("m")
        await pilot.pause()
        assert "Plugin agents" in app.last_notice
        assert not isinstance(app.screen, ModelScreen)
    assert before == {p: p.read_bytes() for p in (fake_home / ".claude" / "agents").glob("*.md")}


@arun
async def test_new_agent_pi_shows_refusal(fake_home):
    app = AgentsApp(home=fake_home)
    async with app.run_test(size=(120, 30)) as pilot:
        await _ready(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, NewScreen)
        tools = app.screen.query_one("#tools", OptionList)
        tools.highlighted = 3
        tools.action_select()
        await pilot.pause()
        assert PI_REFUSAL in str(app.screen.query_one("#refusal", Static).render())


@arun
async def test_help_shows_agents_md_heading(fake_home):
    app = AgentsApp(home=fake_home)
    async with app.run_test(size=(120, 30)) as pilot:
        await _ready(app, pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert app.screen.text.startswith("# sccs agents")
        assert app.screen.query_one(MarkdownViewer)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


@arun
async def test_quit_key_exits(fake_home):
    app = AgentsApp(home=fake_home)
    async with app.run_test(size=(120, 30)) as pilot:
        await _ready(app, pilot)
        await pilot.press("q")
        await pilot.pause()
    assert not app.is_running


@arun
async def test_adopt_via_edit_modal(fake_home):
    app = AgentsApp(home=fake_home)
    async with app.run_test(size=(120, 30)) as pilot:
        await _ready(app, pilot)
        _select(app, "agent:opencode-worker")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ModelScreen)
        await app.workers.wait_for_complete()
        await pilot.click("#adopt")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
    agent = next(a for a in scan_agents(fake_home) if a.name == "opencode-worker")
    assert agent.managed == "adopted"
    assert mode_label(agent) == "read-only €"


@arun
async def test_set_model_free_text_when_list_unreadable(fake_home):
    app = AgentsApp(home=fake_home)
    async with app.run_test(size=(120, 30)) as pilot:
        await _ready(app, pilot)
        _select(app, "agent:opencode-worker")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#adopt")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("m")
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ModelScreen)
        screen.query_one("#model-input").value = "openrouter/some-model"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
    agent = next(a for a in scan_agents(fake_home) if a.name == "opencode-worker")
    assert agent.cli_model == "openrouter/some-model"


def test_mode_label_values(fake_home):
    labels = {a.name: mode_label(a) for a in scan_agents(fake_home)}
    assert labels["codex:codex-rescue"] == "plugin"
    assert labels["opencode-worker"] == "read-only (not adopted) €"
    assert labels["antigravity-worker"] == "read-only (not adopted)"


@arun
async def test_closing_picker_while_models_load_does_not_crash(fake_home, monkeypatch):
    import time

    import sccs.supervisor.tui as tui

    real = tui.list_models

    def slow(*args, **kwargs):
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(tui, "list_models", slow)
    before = {p: p.read_bytes() for p in (fake_home / ".claude" / "agents").glob("*.md")}
    app = AgentsApp(home=fake_home)
    async with app.run_test(size=(120, 30)) as pilot:
        await _ready(app, pilot)
        _select(app, "agent:opencode-worker")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ModelScreen)
        await pilot.press("escape")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await asyncio.sleep(0.5)
        await pilot.pause()
        assert app.is_running
        assert not isinstance(app.screen, ModelScreen)
    assert before == {p: p.read_bytes() for p in (fake_home / ".claude" / "agents").glob("*.md")}
