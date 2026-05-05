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

Querverweise: [doctor.md](usage/doctor.md), [sync.md](usage/sync.md), [memory-bridge.md](usage/memory-bridge.md)

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

See also: [doctor.md](usage/doctor.md), [sync.md](usage/sync.md), [memory-bridge.md](usage/memory-bridge.md)
