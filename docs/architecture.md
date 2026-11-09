# Architektur & Entwicklung / Architecture & Development

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../README.md)

---

## Deutsch

### Architektur

```
sccs/
├── cli.py                # Click CLI mit Befehlsgruppen
├── cli_memory.py         # Memory Command Group
├── config/               # Konfigurationsmanagement
│   ├── schema.py         #   Pydantic-Modelle
│   ├── loader.py         #   YAML-Laden/Speichern
│   └── defaults.py       #   Standard-Konfiguration
├── sync/                 # Synchronisierungs-Engine
│   ├── engine.py         #   Hauptorchestrator
│   ├── category.py       #   Kategorie-Handler
│   ├── item.py           #   SyncItem, Scan-Funktionen
│   ├── actions.py        #   Aktionstypen und -ausführung
│   ├── state.py          #   State-Persistenz
│   └── settings.py       #   JSON-Settings-Ensure
├── doctor/               # System & Plugin Health
│   ├── schema.py         #   Pydantic-Modelle (PluginSpec, NpxToolSpec, …)
│   ├── defaults.py       #   Bundled-Plugin-/Tool-/Permission-Defaults
│   ├── detectors.py      #   Read-only Inspection (Node, CLI, Plugins, npx, …)
│   ├── installer.py      #   Plan-Builder + Action-Execution
│   ├── reporter.py       #   Rich-Tabelle + Inline-Summary
│   ├── runner.py         #   Subprocess-Wrapper (no shell, no sudo)
│   ├── managed.py        #   Doctor-managed Files (vom Sync ausgenommen)
│   └── state.py          #   Doctor-State-Persistenz
├── supervisor/           # Agent-Wrapper: Erkennung, Vorlagen, Modelländerung, Vollbild-Ansicht
├── transfer/             # Export/Import-Modul
│   ├── manifest.py       #   ZIP-Manifest (Pydantic)
│   ├── exporter.py       #   Scan + ZIP-Erstellung
│   ├── importer.py       #   ZIP-Extraktion + Platzierung
│   └── ui.py             #   questionary Checkbox-Helpers
├── git/                  # Git-Operationen
│   └── operations.py     #   Commit, Push, Pull, Status
├── memory/               # Memory Bridge Modul
│   ├── __init__.py       #   Modul-Exports
│   ├── item.py           #   MemoryItem (Frontmatter + Markdown)
│   ├── manager.py        #   CRUD-Layer für ~/.claude/memory/
│   ├── filter.py         #   Filter und Sortierung
│   ├── bridge.py         #   Import/Export Claude.ai
│   └── api.py            #   Optionaler Anthropic Files API Layer
├── output/               # Terminal-Ausgabe
│   ├── console.py        #   Rich-Console
│   ├── diff.py           #   Diff-Anzeige
│   └── merge.py          #   Interaktives Merge
└── utils/                # Hilfsfunktionen
    ├── paths.py          #   Pfad-Utilities, atomares Schreiben
    ├── hashing.py        #   SHA256-Hashing
    └── platform.py       #   Plattformerkennung
```

### Supervisor und Wrapper-Agenten

Hintergrund zu [`sccs agents`](usage/agents.md). Die Arbeitsweise: **Claude Code ist der Supervisor**. Er gibt Reviews und zweite Meinungen an andere KI-CLIs ab (Codex, Antigravity/Gemini, OpenCode/Kimi) und prüft jeden zurückgekommenen Befund selbst am Code.

- **Warum Claude Supervisor ist.** Dort läuft die Sitzung mit dem Projektkontext, den Regeln und den Werkzeugen. Eine zweite Orchestrierungsschicht daneben müsste all das nachbauen. Ein Befund eines anderen Modells ist eine Behauptung; erst der Abgleich mit dem Code macht daraus einen Fehler oder eben nicht. Deshalb wird jeder Befund ausdrücklich als ungeprüft gekennzeichnet und vom Supervisor einzeln geprüft.
- **Warum dünne Haiku-Wrapper mit nur `Bash` und `Read`.** Ein Wrapper soll einen CLI-Aufruf weiterreichen und die Antwort zurückgeben, nicht selbst urteilen. Das kleinste Modell reicht dafür, und ohne Schreibwerkzeuge kann der Wrapper selbst nichts verändern. Der Befehl steht fest in der Wrapper-Datei; sccs ändert daran nur das Modell, und der Modellname wird vorher streng geprüft (Zeichenmuster, kein führendes `-`), weil der Wrapper den Befehl wörtlich über Bash ausführt.
- **Warum nicht CAO.** Ein eigener Orchestrator mit Sitzungsverwaltung, Provider-Patches und Handoff-Protokoll ist für „drei Prüfer parallel, einer wertet aus“ mehr Maschinerie als nötig. Claude Code kann Unteragenten im Hintergrund starten, wird benachrichtigt und besitzt bereits den Kontext. Was bleibt, ist reine Konfiguration, und die ist Sache von sccs.
- **Warum Prüfer nur lesen.** Ein Prüfer, der den Code verändern darf, verändert das, was er prüfen soll. Jedes Werkzeug erzwingt Read-only auf seine Weise: Antigravity mit `--mode plan` und einer Erlaubnisliste lesender Befehle, OpenCode mit einem eingebetteten Agenten `claude-ro` (keine Schreibwerkzeuge, Shell nur für lesende Befehle, keine Web-Abrufe, keine Unteragenten), Codex mit `codex exec -s read-only --ephemeral`. Nie `--dangerously-skip-permissions`, nie OpenCode `--auto`, nie `--mode accept-edits`. Eine schreibfähige Variante gibt es bewusst nicht.
- **Warum ein Gemini-Prüfer nie auf ein Claude-Modell ausweicht.** Antigravity verkauft neben Gemini auch Claude- und GPT-Modelle weiter und rechnet Gemini getrennt ab. Fällt der Gemini-Prüfer auf ein Claude-Modell zurück, prüft Anthropic sich selbst: Das ist Selbstreview mit Umweg, nicht die zweite Modellfamilie, um die es geht. Darum verlangt die Vorlage für Antigravity ein Modell mit dem Präfix `gemini-`, und der Wrapper bricht ab, statt auszuweichen. Dieselbe Regel steht hinter `sccs capacity`: Ist Gemini knapp, springt der Prüfer zu Codex, nie zu Antigravity auf einem Claude-Modell.
- **Aufbau im Code.** `sccs/supervisor/` hält Erkennung und Wrapper-Modell (ohne Textual-Import, damit `--json` überall läuft); `sccs agents …` in der CLI ruft nur diesen Kern; die Vollbild-Ansicht (Textual) ruft ebenfalls nur den Kern.

### Entwicklung

```bash
# Tests
pytest                            # Alle Tests
pytest --cov=sccs                 # Mit Coverage (Minimum: 60%)

# Code-Qualität
ruff check sccs/ tests/           # Linting
ruff format sccs/ tests/          # Formatierung
mypy sccs/                        # Typenprüfung
bandit -r sccs/                   # Security-Scan
```

Querverweise: [agents.md](usage/agents.md), [doctor.md](usage/doctor.md), [sync.md](usage/sync.md), [memory-bridge.md](usage/memory-bridge.md)

---

## English

### Architecture

```
sccs/
├── cli.py                # Click CLI with command groups
├── cli_memory.py         # Memory command group
├── config/               # Configuration management
│   ├── schema.py         #   Pydantic models
│   ├── loader.py         #   YAML loading/saving
│   └── defaults.py       #   Default configuration
├── sync/                 # Synchronization engine
│   ├── engine.py         #   Main orchestrator
│   ├── category.py       #   Category handler
│   ├── item.py           #   SyncItem, scan functions
│   ├── actions.py        #   Action types and execution
│   ├── state.py          #   State persistence
│   └── settings.py       #   JSON settings ensure
├── doctor/               # System & plugin health
│   ├── schema.py         #   Pydantic models (PluginSpec, NpxToolSpec, …)
│   ├── defaults.py       #   Bundled plugin / tool / permission defaults
│   ├── detectors.py      #   Read-only inspection (Node, CLI, plugins, npx, …)
│   ├── installer.py      #   Plan builder + action execution
│   ├── reporter.py       #   Rich table + inline summary
│   ├── runner.py         #   Subprocess wrapper (no shell, no sudo)
│   ├── managed.py        #   Doctor-managed files (excluded from sync)
│   └── state.py          #   Doctor state persistence
├── supervisor/           # Agent wrappers: detection, templates, model change, full-screen view
├── transfer/             # Export/Import module
│   ├── manifest.py       #   ZIP manifest (Pydantic)
│   ├── exporter.py       #   Scan + ZIP creation
│   ├── importer.py       #   ZIP extraction + placement
│   └── ui.py             #   questionary checkbox helpers
├── git/                  # Git operations
│   └── operations.py     #   Commit, push, pull, status
├── memory/               # Memory Bridge module
│   ├── __init__.py       #   Module exports
│   ├── item.py           #   MemoryItem (frontmatter + Markdown)
│   ├── manager.py        #   CRUD layer for ~/.claude/memory/
│   ├── filter.py         #   Filtering and sorting
│   ├── bridge.py         #   Claude.ai import/export
│   └── api.py            #   Optional Anthropic Files API layer
├── output/               # Terminal output
│   ├── console.py        #   Rich console
│   ├── diff.py           #   Diff display
│   └── merge.py          #   Interactive merge
└── utils/                # Utilities
    ├── paths.py          #   Path utilities, atomic writes
    ├── hashing.py        #   SHA256 hashing
    └── platform.py       #   Platform detection
```

### Supervisor and wrapper agents

Background to [`sccs agents`](usage/agents.md). The working model: **Claude Code is the supervisor**. It hands reviews and second opinions to other AI CLIs (Codex, Antigravity/Gemini, OpenCode/Kimi) and checks every returned finding against the code itself.

- **Why Claude is the supervisor.** That is where the session with the project context, the rules and the tools lives. A second orchestration layer next to it would have to rebuild all of that. Another model's finding is a claim; only the comparison with the code turns it into a bug or not. So every finding is explicitly marked unverified and checked one by one by the supervisor.
- **Why thin Haiku wrappers with only `Bash` and `Read`.** A wrapper forwards one CLI call and returns the answer; it does not judge. The smallest model is enough for that, and without write tools the wrapper cannot change anything itself. The command is fixed in the wrapper file; sccs changes only the model in it, and the model name is validated strictly beforehand (character pattern, no leading `-`) because the wrapper runs the command verbatim through Bash.
- **Why not CAO.** A separate orchestrator with session management, provider patches and a handoff protocol is more machinery than „three reviewers in parallel, one evaluates“ needs. Claude Code can start subagents in the background, gets notified and already owns the context. What remains is plain configuration, which is sccs' job.
- **Why reviewers are read-only.** A reviewer allowed to change the code changes what it is supposed to review. Each tool enforces read-only its own way: Antigravity with `--mode plan` and an allowlist of reading commands, OpenCode with an inline agent `claude-ro` (no write tools, shell for reading commands only, no web fetches, no sub-agents), Codex with `codex exec -s read-only --ephemeral`. Never `--dangerously-skip-permissions`, never OpenCode `--auto`, never `--mode accept-edits`. A write-capable variant is left out on purpose.
- **Why a Gemini reviewer never falls back to a Claude model.** Besides Gemini, Antigravity resells Claude and GPT models and bills Gemini separately. If the Gemini reviewer fell back to a Claude model, Anthropic would review itself: self-review by detour, not the second model family the setup is for. So the Antigravity template requires a model with the `gemini-` prefix and the wrapper stops instead of switching. The same rule stands behind `sccs capacity`: when Gemini is tight, the reviewer moves to Codex, never to Antigravity on a Claude model.
- **How it is built.** `sccs/supervisor/` holds detection and the wrapper model (it never imports Textual, so `--json` works everywhere); `sccs agents …` in the CLI only calls that core; the full-screen view (Textual) also calls only the core.

### Development

```bash
# Tests
pytest                            # All tests
pytest --cov=sccs                 # With coverage (minimum: 60%)

# Code quality
ruff check sccs/ tests/           # Linting
ruff format sccs/ tests/          # Formatting
mypy sccs/                        # Type checking
bandit -r sccs/                   # Security scan
```

See also: [agents.md](usage/agents.md), [doctor.md](usage/doctor.md), [sync.md](usage/sync.md), [memory-bridge.md](usage/memory-bridge.md)
