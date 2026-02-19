# SCCS - SkillsCommandsConfigsSync

![SCCS Overview](sccs_gemini.jpg)

> **Language / Sprache**: [Deutsch](#deutsche-dokumentation) | [English](#english-documentation)

---

## Deutsche Dokumentation

### Projektübersicht

SCCS ist ein YAML-konfiguriertes bidirektionales Synchronisierungswerkzeug für Claude Code Dateien und optionale Shell-Konfigurationen. Es hält Skills, Commands, Hooks, Scripts und Shell-Configs zwischen einer lokalen Installation und einem Git-Repository synchron.

**Version:** 2.5.0 · **Lizenz:** AGPL-3.0 · **Python:** ≥3.10

### Funktionen

- **YAML-Konfiguration** — Zentrale `config.yaml` mit allen Sync-Kategorien
- **Flexible Kategorien** — Claude Skills, Commands, Hooks, Scripts, Fish-Shell u.v.m.
- **Bidirektionale Synchronisierung** — Zweiwege-Sync mit Konflikterkennung
- **Interaktive Konflikterkennung** — Menügesteuerte Konfliktauflösung mit `-i`
- **Automatische Backups** — Zeitgestempelte Sicherungen vor Überschreiben
- **Git-Integration** — Auto-Commit und Push nach Synchronisierung
- **Plattform-Filter** — Kategorien nur auf macOS, Linux oder beidem synchronisieren
- **Rich-Ausgabe** — Formatierte Terminal-Ausgabe mit Rich

### Installation

```bash
# Via PyPI
pip install sccs

# Mit UV (empfohlen)
uv pip install sccs
```

Für Entwicklung:

```bash
git clone https://github.com/equitania/sccs.git
cd sccs
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Workflows

#### Publisher (Änderungen teilen)

```bash
sccs sync --commit --push      # Synchronisieren, committen und pushen
sccs sync --dry-run             # Vorschau der Änderungen
sccs sync -c skills --push      # Nur Skills pushen
```

#### Subscriber (Änderungen empfangen)

```bash
sccs sync --pull                # Aktuelle Version ziehen und lokal synchronisieren
sccs sync --force repo          # Lokale Version mit Repo überschreiben
sccs sync -c skills --pull      # Nur Skills empfangen
```

### Schnellstart

```bash
# Konfiguration erstellen
sccs config init

# Status anzeigen
sccs status

# Änderungen prüfen
sccs sync --dry-run

# Alles synchronisieren
sccs sync

# Bestimmte Kategorie synchronisieren
sccs sync -c claude_skills
```

### Konfiguration

Konfigurationsdatei: `~/.config/sccs/config.yaml`

```yaml
# Repository-Einstellungen
repository:
  path: ~/gitbase/sccs-sync      # Lokaler Repository-Pfad
  remote: origin                  # Git Remote Name
  auto_commit: false              # Auto-Commit nach Sync
  auto_push: false                # Auto-Push nach Commit
  auto_pull: false                # Auto-Pull vor Sync
  commit_prefix: "[SYNC]"         # Prefix für Commit-Nachrichten

# Sync-Kategorien
sync_categories:
  claude_skills:
    enabled: true
    description: "Claude Code Skills"
    local_path: ~/.claude/skills
    repo_path: .claude/skills
    sync_mode: bidirectional       # bidirectional | local_to_repo | repo_to_local
    item_type: directory           # file | directory | mixed
    item_marker: SKILL.md          # Marker-Datei für Verzeichnisse
    include: ["*"]
    exclude: ["_archive/*"]

  fish_config:
    enabled: true
    platforms: ["macos"]           # Nur auf macOS synchronisieren
    local_path: ~/.config/fish
    repo_path: .config/fish
    item_type: mixed
    include: ["config.fish", "functions/*.fish"]
    exclude: ["fish_history", "fish_variables"]

# Globale Ausschlüsse
global_exclude:
  - ".DS_Store"
  - "*.tmp"
  - "__pycache__"
```

### Kategorien-Referenz

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|-------------|
| `enabled` | bool | Nein | Kategorie aktivieren (Standard: true) |
| `description` | string | Nein | Beschreibung |
| `local_path` | string | **Ja** | Lokaler Quellpfad (unterstützt `~`) |
| `repo_path` | string | **Ja** | Pfad im Repository |
| `sync_mode` | string | Nein | `bidirectional`, `local_to_repo`, `repo_to_local` |
| `item_type` | string | Nein | `file`, `directory`, `mixed` (Standard: file) |
| `item_marker` | string | Nein | Marker-Datei für Verzeichnisse (z.B. `SKILL.md`) |
| `item_pattern` | string | Nein | Glob-Pattern für Dateien (z.B. `*.md`) |
| `include` | list | Nein | Einschluss-Patterns (Standard: `["*"]`) |
| `exclude` | list | Nein | Ausschluss-Patterns (Standard: `[]`) |
| `platforms` | list | Nein | Plattform-Filter: `["macos"]`, `["linux"]`, `null` = alle |

### CLI-Befehle

```bash
# Synchronisierung
sccs sync                        # Alle aktivierten Kategorien
sccs sync -c skills              # Bestimmte Kategorie
sccs sync -n                     # Vorschau (Dry-Run)
sccs sync -i                     # Interaktive Konfliktauflösung
sccs sync --force local          # Lokale Version erzwingen
sccs sync --force repo           # Repo-Version erzwingen
sccs sync --commit --push        # Mit Git-Commit und Push
sccs sync --pull                 # Vorher Remote-Änderungen ziehen

# Status und Diff
sccs status                      # Sync-Status aller Kategorien
sccs diff                        # Alle Unterschiede anzeigen
sccs diff -c skills              # Diffs einer Kategorie
sccs log                         # Sync-Verlauf

# Konfiguration
sccs config show                 # Konfiguration anzeigen
sccs config init                 # Neue Konfiguration erstellen
sccs config edit                 # Im Editor öffnen
sccs config validate             # Konfiguration prüfen

# Kategorien
sccs categories list             # Aktivierte Kategorien
sccs categories list --all       # Alle (inkl. deaktivierte)
sccs categories enable fish      # Kategorie aktivieren
sccs categories disable fish     # Kategorie deaktivieren
```

### Standard-Kategorien

#### Claude Code (standardmäßig aktiv)

| Kategorie | Pfad | Beschreibung |
|-----------|------|-------------|
| `claude_framework` | `~/.claude/*.md` | SuperClaude Framework-Dateien |
| `claude_skills` | `~/.claude/skills/` | Skills (Verzeichnisse mit SKILL.md) |
| `claude_commands` | `~/.claude/commands/` | Commands (einzelne .md-Dateien) |
| `claude_hooks` | `~/.claude/hooks/` | Event-Handler-Skripte |
| `claude_scripts` | `~/.claude/scripts/` | Hilfsskripte |
| `claude_plugins` | `~/.claude/plugins/` | Plugin-Konfigurationen |
| `claude_mcp` | `~/.claude/mcp/` | MCP-Server-Konfigurationen |
| `claude_statusline` | `~/.claude/statusline.*` | Statusline-Skript |

#### Shell (standardmäßig aktiv)

| Kategorie | Pfad | Plattform | Beschreibung |
|-----------|------|-----------|-------------|
| `fish_config` | `~/.config/fish/` | alle | Fish-Shell-Konfiguration |
| `fish_config_macos` | `~/.config/fish/conf.d/*.macos.fish` | macOS | macOS-spezifische conf.d |
| `fish_functions` | `~/.config/fish/functions/` | alle | Fish-Funktionen |
| `fish_functions_macos` | `~/.config/fish/functions/macos/` | macOS | macOS-spezifische Funktionen |
| `starship_config` | `~/.config/starship.toml` | alle | Starship-Prompt |

### Konfliktauflösung

Bei Änderungen auf beiden Seiten bietet SCCS mehrere Auflösungsstrategien:

**Interaktiver Modus** (empfohlen):

```bash
sccs sync -i
```

Optionen im interaktiven Menü:
1. **Lokal behalten** — Lokale Version verwenden
2. **Repo behalten** — Repository-Version verwenden
3. **Diff anzeigen** — Unterschiede prüfen
4. **Interaktives Merge** — Hunk-für-Hunk-Zusammenführung
5. **Externer Editor** — In Editor öffnen
6. **Überspringen** — Dieses Element auslassen
7. **Abbrechen** — Sync komplett abbrechen

**Automatische Auflösung**:

```bash
sccs sync --force local          # Lokal gewinnt immer
sccs sync --force repo           # Repository gewinnt immer
```

### Automatische Backups

Vor jedem Überschreiben erstellt SCCS zeitgestempelte Sicherungen:

```
~/.config/sccs/backups/
├── claude_skills/
│   └── my-skill.20250123_143052.bak
└── fish_config/
    └── config.fish.20250123_143052.bak
```

### Plattform-Awareness

Kategorien können auf bestimmte Betriebssysteme beschränkt werden:

```yaml
fish_config_macos:
  enabled: true
  platforms: ["macos"]              # Nur auf macOS synchronisieren
  local_path: ~/.config/fish/conf.d
  repo_path: .config/fish/conf.d
  item_pattern: "*.macos.fish"
```

Erkennung: `Darwin` → `macos`, `Linux` → `linux`. Kategorien mit `platforms: null` synchronisieren auf allen Plattformen.

### Architektur

```
sccs/
├── cli.py                # Click CLI mit Befehlsgruppen
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
├── git/                  # Git-Operationen
│   └── operations.py     #   Commit, Push, Pull, Status
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

### Lizenz

AGPL-3.0 — Equitania Software GmbH

---

## English Documentation

### Project Overview

SCCS is a YAML-configured bidirectional synchronization tool for Claude Code files and optional shell configurations. It keeps skills, commands, hooks, scripts, and shell configs in sync between a local installation and a Git repository.

**Version:** 2.5.0 · **License:** AGPL-3.0 · **Python:** ≥3.10

### Features

- **YAML Configuration** — Single `config.yaml` with all sync categories
- **Flexible Categories** — Claude skills, commands, hooks, scripts, Fish shell, and more
- **Bidirectional Sync** — Full two-way synchronization with conflict detection
- **Interactive Conflict Resolution** — Menu-driven conflict handling with `-i` flag
- **Automatic Backups** — Timestamped backups before overwriting files
- **Git Integration** — Auto-commit and push after sync operations
- **Platform Filtering** — Sync categories only on macOS, Linux, or both
- **Rich Console Output** — Formatted terminal output with Rich

### Installation

```bash
# From PyPI
pip install sccs

# With UV (recommended)
uv pip install sccs
```

For development:

```bash
git clone https://github.com/equitania/sccs.git
cd sccs
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Workflows

#### Publisher (share your configs)

```bash
sccs sync --commit --push      # Sync, commit and push to remote
sccs sync --dry-run             # Preview what would change
sccs sync -c skills --push      # Push only skills category
```

#### Subscriber (receive shared configs)

```bash
sccs sync --pull                # Pull latest and sync to local
sccs sync --force repo          # Overwrite local with repo version
sccs sync -c skills --pull      # Pull only skills category
```

### Quick Start

```bash
# Initialize configuration
sccs config init

# Show sync status
sccs status

# Preview changes
sccs sync --dry-run

# Synchronize all enabled categories
sccs sync

# Sync specific category
sccs sync -c claude_skills
```

### Configuration

Config file: `~/.config/sccs/config.yaml`

```yaml
# Repository settings
repository:
  path: ~/gitbase/sccs-sync      # Local repository path
  remote: origin                  # Git remote name for push
  auto_commit: false              # Auto-commit after sync
  auto_push: false                # Auto-push after commit
  auto_pull: false                # Auto-pull before sync
  commit_prefix: "[SYNC]"         # Prefix for commit messages

# Sync categories
sync_categories:
  claude_skills:
    enabled: true
    description: "Claude Code Skills"
    local_path: ~/.claude/skills
    repo_path: .claude/skills
    sync_mode: bidirectional       # bidirectional | local_to_repo | repo_to_local
    item_type: directory           # file | directory | mixed
    item_marker: SKILL.md          # Marker file for directory items
    include: ["*"]
    exclude: ["_archive/*"]

  fish_config:
    enabled: true
    platforms: ["macos"]           # Only sync on macOS
    local_path: ~/.config/fish
    repo_path: .config/fish
    item_type: mixed
    include: ["config.fish", "functions/*.fish"]
    exclude: ["fish_history", "fish_variables"]

# Global excludes
global_exclude:
  - ".DS_Store"
  - "*.tmp"
  - "__pycache__"
```

### Category Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | bool | No | Enable/disable category (default: true) |
| `description` | string | No | Human-readable description |
| `local_path` | string | **Yes** | Local source path (supports `~`) |
| `repo_path` | string | **Yes** | Path in repository |
| `sync_mode` | string | No | `bidirectional`, `local_to_repo`, `repo_to_local` |
| `item_type` | string | No | `file`, `directory`, `mixed` (default: file) |
| `item_marker` | string | No | Marker file for directory items (e.g., `SKILL.md`) |
| `item_pattern` | string | No | Glob pattern for file items (e.g., `*.md`) |
| `include` | list | No | Patterns to include (default: `["*"]`) |
| `exclude` | list | No | Patterns to exclude (default: `[]`) |
| `platforms` | list | No | Platform filter: `["macos"]`, `["linux"]`, `null` = all |

### CLI Commands

```bash
# Synchronization
sccs sync                        # All enabled categories
sccs sync -c skills              # Specific category
sccs sync -n                     # Preview (dry-run)
sccs sync -i                     # Interactive conflict resolution
sccs sync --force local          # Force local version
sccs sync --force repo           # Force repo version
sccs sync --commit --push        # With git commit and push
sccs sync --pull                 # Pull remote changes first

# Status and diff
sccs status                      # Sync status of all categories
sccs diff                        # Show all differences
sccs diff -c skills              # Diffs for a category
sccs log                         # Sync history

# Configuration
sccs config show                 # Show configuration
sccs config init                 # Create new configuration
sccs config edit                 # Open in editor
sccs config validate             # Validate configuration

# Categories
sccs categories list             # List enabled categories
sccs categories list --all       # All (incl. disabled)
sccs categories enable fish      # Enable category
sccs categories disable fish     # Disable category
```

### Default Categories

#### Claude Code (enabled by default)

| Category | Path | Description |
|----------|------|-------------|
| `claude_framework` | `~/.claude/*.md` | SuperClaude Framework files |
| `claude_skills` | `~/.claude/skills/` | Skills (directories with SKILL.md) |
| `claude_commands` | `~/.claude/commands/` | Commands (single .md files) |
| `claude_hooks` | `~/.claude/hooks/` | Event handler scripts |
| `claude_scripts` | `~/.claude/scripts/` | Utility scripts |
| `claude_plugins` | `~/.claude/plugins/` | Plugin configurations |
| `claude_mcp` | `~/.claude/mcp/` | MCP server configs |
| `claude_statusline` | `~/.claude/statusline.*` | Statusline script |

#### Shell (enabled by default)

| Category | Path | Platform | Description |
|----------|------|----------|-------------|
| `fish_config` | `~/.config/fish/` | all | Fish shell configuration |
| `fish_config_macos` | `~/.config/fish/conf.d/*.macos.fish` | macOS | macOS-specific conf.d |
| `fish_functions` | `~/.config/fish/functions/` | all | Fish custom functions |
| `fish_functions_macos` | `~/.config/fish/functions/macos/` | macOS | macOS-specific functions |
| `starship_config` | `~/.config/starship.toml` | all | Starship prompt |

### Conflict Resolution

When both local and repo have changes, SCCS offers multiple resolution strategies:

**Interactive mode** (recommended):

```bash
sccs sync -i
```

Interactive menu options:
1. **Keep local** — Use local version
2. **Keep repo** — Use repository version
3. **Show diff** — View differences
4. **Interactive merge** — Hunk-by-hunk merge
5. **External editor** — Open in editor
6. **Skip** — Skip this item
7. **Abort** — Stop sync completely

**Automatic resolution**:

```bash
sccs sync --force local          # Local wins all conflicts
sccs sync --force repo           # Repository wins all conflicts
```

### Automatic Backups

Before overwriting any file, SCCS creates timestamped backups:

```
~/.config/sccs/backups/
├── claude_skills/
│   └── my-skill.20250123_143052.bak
└── fish_config/
    └── config.fish.20250123_143052.bak
```

### Platform Awareness

Categories can be restricted to specific operating systems:

```yaml
fish_config_macos:
  enabled: true
  platforms: ["macos"]              # Only sync on macOS
  local_path: ~/.config/fish/conf.d
  repo_path: .config/fish/conf.d
  item_pattern: "*.macos.fish"
```

Detection: `Darwin` → `macos`, `Linux` → `linux`. Categories with `platforms: null` sync on all platforms.

### Architecture

```
sccs/
├── cli.py                # Click CLI with command groups
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
├── git/                  # Git operations
│   └── operations.py     #   Commit, push, pull, status
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

### License

AGPL-3.0 — Equitania Software GmbH
