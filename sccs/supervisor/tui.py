"""Full-screen view for `sccs agents` (Textual).

The screen only calls the supervisor core. Tool detection, model lists and every
write run in thread workers so the first paint never waits on a subprocess.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Input, Label, MarkdownViewer, OptionList, Static
from textual.widgets.option_list import Option

from sccs.supervisor import (
    AgentInfo,
    SupervisorError,
    ToolInfo,
    adopt,
    detect_tools,
    list_models,
    mode_label,
    scan_agents,
    set_model,
)
from sccs.supervisor.models import model_warning
from sccs.supervisor.render import PI_REFUSAL, new_agent

_EXPLAIN: dict[str, str] = {
    "agy": "Read-only via --mode plan + allowlist · material inline",
    "opencode": (
        "Read-only via --agent claude-ro (inline config) · reads files itself"
        " · free opencode/* models: unclear data policy"
    ),
    "codex": "Read-only via codex exec -s read-only --ephemeral · reads files itself",
}
_NEW_TOOLS: tuple[tuple[str, str], ...] = (
    ("agy", "Antigravity (Gemini)"),
    ("opencode", "OpenCode"),
    ("codex", "Codex"),
    ("pi", "Pi (no template yet)"),
)
_PLUGIN_NOTICE = "Plugin agents are managed by their plugin; nothing is written."
_UNMANAGED_NOTICE = "Unmanaged agent: no wrapper template recognised; nothing is written."
_FREE_NOTICE = "No agent uses this tool. Press n to create one."


def _find_doc(name: str, repo_relative: tuple[str, ...]) -> Path | None:
    """Bundled `data/<name>` first, the repo's docs file as fallback."""
    package_dir = Path(__file__).resolve().parent.parent
    for candidate in (package_dir / "data" / name, package_dir.parent.joinpath(*repo_relative)):
        if candidate.is_file():
            return candidate
    return None


def find_help_doc() -> Path | None:
    """The usage guide: bundled `data/agents.md`, else `docs/usage/agents.md`."""
    return _find_doc("agents.md", ("docs", "usage", "agents.md"))


def find_approach_doc() -> Path | None:
    """The approach document: bundled `data/architecture.md`, else `docs/architecture.md`."""
    return _find_doc("architecture.md", ("docs", "architecture.md"))


def _read_doc(path: Path | None, missing: str) -> str:
    if path is None:
        return f"# Help not available\n\n{missing} was not found."
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return f"# Help not available\n\n{missing} could not be read."


def _tilde(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _clip(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1] + "…"


def _tool_id(agent: AgentInfo) -> str | None:
    return "codex" if agent.source == "plugin" else agent.template


class HelpScreen(Screen[None]):
    """Usage guide (bundled agents.md) and approach document (bundled architecture.md)."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("question_mark", "app.pop_screen", "Close"),
        Binding("tab", "switch", "Usage/Approach"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.texts = {
            "Usage": _read_doc(find_help_doc(), "agents.md"),
            "Approach": _read_doc(find_approach_doc(), "architecture.md"),
        }
        self.current = "Usage"
        self.text = self.texts[self.current]

    def compose(self) -> ComposeResult:
        yield Static(self._title(), id="help-title")
        yield MarkdownViewer(self.text, show_table_of_contents=False, id="help-viewer")
        yield Footer()

    def _title(self) -> str:
        other = "Approach" if self.current == "Usage" else "Usage"
        return f"[b]{self.current}[/b] · Tab: {other}"

    def action_switch(self) -> None:
        self.current = "Approach" if self.current == "Usage" else "Usage"
        self.text = self.texts[self.current]
        self.query_one("#help-title", Static).update(self._title())
        self.query_one("#help-viewer", MarkdownViewer).document.update(self.text)


class ToolsScreen(ModalScreen[None]):
    """All ToolInfo fields; install hint for missing tools."""

    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("w", "dismiss", "Close")]

    def __init__(self, tools: list[ToolInfo] | None, home: Path) -> None:
        super().__init__()
        self.tools = tools
        self.home = home

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Tools", id="dialog-title")
            table: DataTable[Any] = DataTable(id="tools-table", cursor_type="none")
            table.add_columns("Tool", "Installed", "Version", "Login", "Default model", "Config")
            for t in self.tools or []:
                table.add_row(
                    t.label,
                    "yes" if t.installed else "no",
                    t.version or "unknown",
                    t.login,
                    Text(t.default_model or "unknown"),
                    Text(_tilde(t.config_path, self.home) + ("" if t.config_present else " (absent)")),
                )
            yield table
            if self.tools is None:
                yield Static("Detecting tools…", id="tools-note")
            elif any(not t.installed for t in self.tools):
                yield Static("Missing tools — Install via: sccs doctor install", id="tools-note")
            yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()


class ModelScreen(ModalScreen["tuple[str, str] | None"]):
    """Model picker for one wrapper agent, with an adopt button when it is not adopted."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, agent: AgentInfo, tool: str, home: Path) -> None:
        super().__init__()
        self.agent = agent
        self.tool = tool
        self.home = home

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Model for {escape(self.agent.name)}  (now: {escape(self.agent.cli_model or 'unknown')})")
            yield Static("Loading models…", id="models-status")
            yield OptionList(id="models")
            yield Input(placeholder="model name", id="model-input")
            if self.agent.managed == "no":
                yield Static("Not adopted yet: adopt it before its model can change.", id="adopt-note")
                yield Button("Adopt", id="adopt", variant="warning")
            yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#model-input", Input).display = False
        self._load()

    @work(thread=True, exclusive=True, group="models", exit_on_error=False)
    def _load(self) -> None:
        result = list_models(self.tool, self.home)  # type: ignore[arg-type]
        try:
            self.app.call_from_thread(self._fill, result.models, result.readable)
        except RuntimeError:  # app already closed
            pass

    def _fill(self, models: tuple[str, ...], readable: bool) -> None:
        if not self.is_attached:  # picker was closed while the list was loading
            return
        options = self.query_one("#models", OptionList)
        options.add_options([Option(Text(m), id=m) for m in models])
        if readable:
            self.query_one("#models-status", Static).update(f"{len(models)} models")
        else:
            self.query_one("#models-status", Static).update("Model list could not be read; type a model name.")
            self.query_one("#model-input", Input).display = True
        (options if models else self.query_one("#model-input", Input)).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(("model", event.option.id or ""))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.dismiss(("model", event.value.strip()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(("adopt", "") if event.button.id == "adopt" else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class NewScreen(ModalScreen["tuple[str, str] | None"]):
    """Tool and name for a new wrapper agent; Pi is refused with the template message."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self.tool: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("New agent — choose a tool")
            yield OptionList(*[Option(label, id=tid) for tid, label in _NEW_TOOLS], id="tools")
            yield Static("", id="refusal")
            yield Input(placeholder="agent name, e.g. review-worker", id="name")
            yield Button("Create", id="create", variant="primary", disabled=True)
            yield Button("Cancel", id="cancel")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.tool = event.option.id
        refusal = self.query_one("#refusal", Static)
        refusal.update(PI_REFUSAL if self.tool == "pi" else "")
        self.query_one("#create", Button).disabled = self.tool in (None, "pi")
        self.query_one("#name", Input).focus()

    def _submit(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        if self.tool and self.tool != "pi" and name:
            self.dismiss((self.tool, name))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AgentsApp(App[None]):
    """Supervisor view: one row per agent, tools without an agent as dimmed `(free)` rows."""

    CSS = """
    #header-line { height: 1; padding: 0 1; background: $boost; }
    #agents { height: 1fr; }
    #explain { height: 2; padding: 0 1; color: $text-muted; }
    ModalScreen { align: center middle; }
    #dialog {
        width: 70%; max-width: 90; height: auto; max-height: 90%;
        padding: 1 2; border: round $accent; background: $surface;
    }
    #models { height: auto; max-height: 12; }
    #tools-table { height: auto; }
    #refusal { color: $error; }
    """
    BINDINGS = [
        Binding("m", "edit", "Model"),
        Binding("n", "new", "New agent"),
        Binding("w", "tools", "Tools"),
        Binding("question_mark", "help", "Help"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, home: Path | None = None) -> None:
        super().__init__()
        self.home = home if home is not None else Path.home()
        self.tools: list[ToolInfo] | None = None
        self.agents: list[AgentInfo] = []
        self.last_notice = ""

    # -- layout ---------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Static("", id="header-line")
        table: DataTable[Any] = DataTable(id="agents", cursor_type="row", zebra_stripes=False)
        table.add_columns("Agent", "Tool", "Model", "Mode")
        yield table
        yield Static("", id="explain")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()

    def on_resize(self) -> None:
        self._rebuild()

    # -- data -----------------------------------------------------------
    def action_refresh(self) -> None:
        self.agents = scan_agents(self.home)
        self._rebuild()
        self._detect()

    @work(thread=True, exclusive=True, group="detect", exit_on_error=False)
    def _detect(self) -> None:
        tools = detect_tools(self.home)
        self._thread_call(self._apply_tools, tools)

    def _thread_call(self, callback: Any, *args: Any) -> None:
        """call_from_thread that survives the app having closed meanwhile."""
        try:
            self.call_from_thread(callback, *args)
        except RuntimeError:
            pass

    def _apply_tools(self, tools: list[ToolInfo]) -> None:
        self.tools = tools
        self._rebuild()

    def _tool(self, tool_id: str | None) -> ToolInfo | None:
        return next((t for t in self.tools or [] if t.id == tool_id), None)

    def _tool_cell(self, tool_id: str | None) -> Text:
        if tool_id is None:
            return Text("-")
        if self.tools is None:
            return Text(f"{tool_id} …")
        tool = self._tool(tool_id)
        if tool is None:
            return Text(tool_id)
        if not tool.installed:
            return Text.assemble(f"{tool.id} ", ("missing", "red"))
        return Text.assemble(f"{tool.id} {tool.version or 'unknown'} ", ("✓", "green"))

    def _rebuild(self) -> None:
        try:
            table = self.query_one("#agents", DataTable)
            header = self.query_one("#header-line", Static)
        except Exception:  # noqa: BLE001 - not composed yet
            return
        model_w = 28 if self.size.width >= 100 else 18
        selected = self._selected_key()
        table.clear()
        for agent in self.agents:
            mode = mode_label(agent)
            table.add_row(
                Text(agent.name),
                self._tool_cell(_tool_id(agent)),
                Text(_clip(agent.cli_model or "unknown", model_w)),
                Text(mode),
                key=f"agent:{agent.name}",
            )
        used = {_tool_id(a) for a in self.agents}
        for tool in self.tools or []:
            if tool.id == "claude" or tool.id in used:
                continue
            table.add_row(
                Text("(free)", style="dim"),
                Text(self._tool_cell(tool.id).plain, style="dim"),
                Text("–", style="dim"),
                Text("–", style="dim"),
                key=f"free:{tool.id}",
            )
        if selected is not None:
            for index, row in enumerate(table.ordered_rows):
                if row.key.value == selected:
                    table.move_cursor(row=index)
                    break
        claude = self._tool("claude")
        if claude is None:
            state = "…"
        elif claude.installed:
            state = f"✓ {escape(claude.default_model or 'unknown')}"
        else:
            state = "[red]missing[/red]"
        agents_dir = escape(_tilde(self.home / ".claude" / "agents", self.home))
        header.update(f"[b]sccs agents[/b]   Supervisor: Claude Code {state} · {agents_dir}")
        self._explain()

    # -- selection ------------------------------------------------------
    def _selected_key(self) -> str | None:
        try:
            table = self.query_one("#agents", DataTable)
            if table.row_count == 0:
                return None
            return table.ordered_rows[table.cursor_row].key.value
        except Exception:  # noqa: BLE001
            return None

    def _selected(self) -> tuple[AgentInfo | None, str | None]:
        """(agent, None) for an agent row, (None, tool id) for a free row."""
        key = self._selected_key()
        if key is None:
            return None, None
        kind, _, value = key.partition(":")
        if kind == "free":
            return None, value
        return next((a for a in self.agents if a.name == value), None), None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._explain()

    def _explain(self) -> None:
        agent, free = self._selected()
        if agent is not None:
            if agent.source == "plugin":
                text = "Plugin agent: managed by the Codex plugin, never written here."
            elif agent.template is None:
                text = "Unmanaged: no wrapper template recognised; sccs never writes this file."
            else:
                text = _EXPLAIN[agent.template]
                if agent.managed == "no":
                    text += " · Not adopted: press enter to adopt"
                if agent.hash_ok is False:
                    text += " · Edited since sccs wrote it (unverified)"
            if agent.excluded:
                text += " · Export: off"
        elif free == "pi":
            text = PI_REFUSAL
        elif free:
            text = f"No agent uses {free}. Press n to create one."
        else:
            text = ""
        try:
            self.query_one("#explain", Static).update(Text(text))
        except Exception:  # noqa: BLE001
            pass

    # -- actions --------------------------------------------------------
    def notice(self, message: str, error: bool = False) -> None:
        self.last_notice = message
        self.notify(message, severity="error" if error else "information", markup=False)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_edit()

    def action_edit(self) -> None:
        agent, free = self._selected()
        if agent is None:
            if free:
                self.notice(_FREE_NOTICE)
            return
        if agent.source == "plugin":
            self.notice(_PLUGIN_NOTICE)
        elif agent.template is None:
            self.notice(_UNMANAGED_NOTICE)
        else:
            self.push_screen(ModelScreen(agent, agent.template, self.home), lambda r: self._edited(agent.name, r))

    def _edited(self, name: str, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        action, value = result
        self._write(action, name, value)

    @work(thread=True, group="write", exit_on_error=False)
    def _write(self, action: str, name: str, value: str) -> None:
        warning: str | None = None
        try:
            if action == "adopt":
                done = adopt(name, self.home)
                message = f"Adopted {name}." if done else f"{name} is already adopted."
            else:
                template = next((a.template for a in self.agents if a.name == name), None)
                check = set_model(name, value, self.home)
                warning = model_warning(template, value) if template else None
                message = f"{name}: model set to {value}" + (" (unverified)" if check.status == "unverified" else "")
        except SupervisorError as exc:
            self._thread_call(self.notice, str(exc), True)
            return
        self._thread_call(self.notice, message)
        if warning:
            self._thread_call(self.notice, warning, True)
        self._thread_call(self.action_refresh)

    def action_new(self) -> None:
        self.push_screen(NewScreen(), self._created)

    def _created(self, result: tuple[str, str] | None) -> None:
        if result is not None:
            self._create(*result)

    @work(thread=True, group="write", exit_on_error=False)
    def _create(self, tool: str, name: str) -> None:
        try:
            created = new_agent(tool, name, home=self.home)
        except SupervisorError as exc:
            self._thread_call(self.notice, str(exc), True)
            return
        self._thread_call(self.notice, f"Created {created.path.name} ({created.model_status} model).")
        self._thread_call(self.action_refresh)

    def action_tools(self) -> None:
        self.push_screen(ToolsScreen(self.tools, self.home))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


def run() -> None:
    """Open the full-screen view."""
    AgentsApp().run()
