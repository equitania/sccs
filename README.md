# SCCS - SkillsCommandsConfigsSync

![SCCS Overview](sccs-openai.png)

> **Language / Sprache**: [Deutsch](#deutsche-dokumentation) | [English](#english-documentation)

---

## Deutsche Dokumentation

### Projektübersicht

SCCS ist ein YAML-konfiguriertes bidirektionales Synchronisierungswerkzeug für Claude Code Dateien und optionale Shell-Konfigurationen. Es hält Skills, Commands, Hooks, Scripts und Shell-Configs zwischen einer lokalen Installation und einem Git-Repository synchron.

**Version:** 2.23.0 · **Lizenz:** AGPL-3.0 · **Python:** ≥3.10

### Funktionen

- **YAML-Konfiguration** — Zentrale `config.yaml` mit allen Sync-Kategorien
- **Flexible Kategorien** — Claude Skills, Commands, Hooks, Scripts, Fish-Shell u.v.m.
- **Bidirektionale Synchronisierung** — Zweiwege-Sync mit Konflikterkennung
- **Interaktive Konflikterkennung** — Menügesteuerte Konfliktauflösung mit `-i`
- **Interaktive Divergenz-Auflösung** — Menü (Rebase / Merge / Force-Push / Abort) wenn Branch von Remote abgewichen ist; CI-freundlich (auto-Abort ohne TTY)
- **Automatische Backups** — Zeitgestempelte Sicherungen vor Überschreiben
- **Git-Integration** — Auto-Commit und Push nach Synchronisierung
- **Plattform-Filter** — Kategorien nur auf macOS, Linux oder beidem synchronisieren
- **Smart Conflict Resolution** — `--force newer` löst Konflikte per Dateizeit (mtime)
- **Project Memories Sync** — Claude's persistente Projekt-Memories synchronisieren
- **Selektiver Export/Import** — ZIP-Archive mit Checkbox-Auswahl fuer Kundendeployments
- **Rich-Ausgabe** — Formatierte Terminal-Ausgabe mit Rich
- **Memory Bridge** — Persistenter Kontext zwischen Claude Code und Claude.ai via Git-Sync
- **Memory-CLI** — Vollständige CRUD-Verwaltung mit `sccs memory`
- **Auto-Expire** — Zeitgesteuerte Archivierung abgelaufener Memory-Items
- **Antigravity-Integration** — Skills zu Antigravity IDE Prompts migrieren
- **Claude Desktop-Integration** — Repository als Trusted Folder registrieren
- **`sccs doctor`** — System & Plugin Health-Check für Node.js, `claude` CLI, Claude-Plugins, npx-Helper-Tools (`get-shit-done-cc`, `playwright-cli` inklusive Chromium/Firefox-Bundles und npm-Skill-Sync nach `~/.claude/skills/`) und Filesystem-Permissions (`~/.npm`, `~/.claude`, `~/.config/sccs`). `check` validiert nicht nur das Binary auf PATH, sondern auch ob die `SKILL.md` im Skill-Verzeichnis existiert und ob der Browser-Cache (`$PLAYWRIGHT_BROWSERS_PATH` bzw. plattformspezifischer Default) die deklarierten Bundles enthält — fehlende Komponenten werden gezielt durch `install`/`update` repariert. Plattformspezifisch (`brew` / `winget` / NodeSource-Manual). Doctor-installierte Dateien (z.B. `gsd-*` Skills/Hooks/Agents, `playwright-cli`-Skill) werden automatisch vom Sync ausgeschlossen, damit sie keine Konflikte zwischen Maschinen erzeugen. Bei kaputten Verzeichnis-Rechten (z.B. root-owned `~/.npm/_cacache/`) zeigt der Doctor die exakte `sudo chown`-Fix-Command an — SCCS selbst ruft niemals sudo auf.

### Voraussetzungen

[UV](https://docs.astral.sh/uv/) muss installiert sein:

| Betriebssystem | Befehl |
|----------------|--------|
| macOS | `brew install uv` |
| Linux / WSL | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Windows | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |

### Installation

**Als CLI-Tool (empfohlen):**

```bash
uv tool install sccs
```

**Aktualisierung:**

```bash
uv tool upgrade sccs
```

**UV aktualisieren:**

```bash
# macOS
brew upgrade uv

# Linux / Windows
uv self update
```

### Für Entwickler

```bash
git clone https://github.com/equitania/sccs.git
cd sccs
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -e ".[dev]"
sccs --help
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

### Export/Import (Kundendeployment)

ZIP-basierter Export/Import einzelner Kategorien für gezielte Kundendeployments. Vollständige Beispiele und Use-Cases siehe [docs/usage/transfer.md](docs/usage/transfer.md).

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

### Memory Bridge

File-basierter Brückenschlag zwischen Claude Code (Terminal) und Claude.ai (Web). Konzept, Item-Format, Konfiguration, Setup, CLI-Befehle, Konfliktauflösung, Export-Workflows und Sicherheitshinweise siehe [docs/usage/memory-bridge.md](docs/usage/memory-bridge.md).

### Kategorien-Referenz

Feld-Referenz, Liste aller Standard-Kategorien und Plattform-Filter siehe [docs/usage/categories.md](docs/usage/categories.md).

### CLI-Befehle

Vollständige Referenz aller `sccs`-Subcommands in [docs/usage/cli-reference.md](docs/usage/cli-reference.md).

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
sccs sync --force newer          # Neuere Datei gewinnt (per mtime)
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

Plattform-Filter (`platforms: ["macos"]` etc.), Erkennungslogik und Skip-Hinweise siehe [docs/usage/categories.md](docs/usage/categories.md#plattform-awareness).

### Windows / PowerShell-Support

PowerShell-Profile-Kategorie und der Fish-zu-PowerShell-Konvertierungs-Workflow sind in [docs/usage/platforms.md](docs/usage/platforms.md) dokumentiert.

### Architektur & Entwicklung

Modul-Layout, Test-Setup und Quality-Gate sind in [docs/architecture.md](docs/architecture.md) dokumentiert.

### Lizenz

AGPL-3.0 — Equitania Software GmbH

---

## English Documentation

### Project Overview

SCCS is a YAML-configured bidirectional synchronization tool for Claude Code files and optional shell configurations. It keeps skills, commands, hooks, scripts, and shell configs in sync between a local installation and a Git repository.

**Version:** 2.23.0 · **License:** AGPL-3.0 · **Python:** ≥3.10

### Features

- **YAML Configuration** — Single `config.yaml` with all sync categories
- **Flexible Categories** — Claude skills, commands, hooks, scripts, Fish shell, and more
- **Bidirectional Sync** — Full two-way synchronization with conflict detection
- **Interactive Conflict Resolution** — Menu-driven conflict handling with `-i` flag
- **Interactive Divergence Resolution** — Menu (Rebase / Merge / Force-Push / Abort) when the branch has diverged from its remote; CI-friendly (auto-Abort without TTY)
- **Automatic Backups** — Timestamped backups before overwriting files
- **Git Integration** — Auto-commit and push after sync operations
- **Platform Filtering** — Sync categories only on macOS, Linux, or both
- **Smart Conflict Resolution** — `--force newer` resolves conflicts by file modification time
- **Project Memories Sync** — Sync Claude's persistent project memories across machines
- **Selective Export/Import** — ZIP archives with checkbox selection for customer deployments
- **Rich Console Output** — Formatted terminal output with Rich
- **Memory Bridge** — Persistent context between Claude Code and Claude.ai via Git sync
- **Memory CLI** — Full CRUD management with `sccs memory`
- **Auto-Expire** — Time-based archiving of expired memory items
- **Antigravity Integration** — Migrate skills to Antigravity IDE prompts
- **Claude Desktop Integration** — Register repository as trusted folder
- **`sccs doctor`** — System & plugin health checks for Node.js, the `claude` CLI, configured Claude plugins, npx helper tools (`get-shit-done-cc`, `playwright-cli` including its Chromium/Firefox browser bundles and npm-shipped skill copied into `~/.claude/skills/`) and filesystem permissions (`~/.npm`, `~/.claude`, `~/.config/sccs`). `check` does more than verify the binary on PATH: it also validates that the bundled skill's `SKILL.md` exists in the target directory and that the browser cache (`$PLAYWRIGHT_BROWSERS_PATH` or the platform default) actually contains the declared bundles — missing components are surgically repaired by `install`/`update`. Platform-aware (`brew` / `winget` / NodeSource manual). Files installed by the doctor (e.g. `gsd-*` skills/hooks/agents, `playwright-cli` skill) are automatically excluded from sync so they never produce cross-machine conflicts. When directory ownership is broken (e.g. root-owned `~/.npm/_cacache/`), the doctor surfaces the exact `sudo chown` fix command — SCCS itself never invokes sudo.

### Prerequisites

[UV](https://docs.astral.sh/uv/) must be installed:

| OS | Command |
|----|---------|
| macOS | `brew install uv` |
| Linux / WSL | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Windows | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |

### Installation

**As CLI tool (recommended):**

```bash
uv tool install sccs
```

**Update:**

```bash
uv tool upgrade sccs
```

**Update UV itself:**

```bash
# macOS
brew upgrade uv

# Linux / Windows
uv self update
```

### For Developers

```bash
git clone https://github.com/equitania/sccs.git
cd sccs
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -e ".[dev]"
sccs --help
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

### Export/Import (Customer Deployment)

ZIP-based export/import of individual categories for targeted customer deployments. Full command reference and use cases live in [docs/usage/transfer.md](docs/usage/transfer.md).

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

### Memory Bridge

File-based bridge between Claude Code (terminal) and Claude.ai (web). Concept, item format, configuration, setup, CLI commands, conflict resolution, export workflows and security notes live in [docs/usage/memory-bridge.md](docs/usage/memory-bridge.md).

### Category Field Reference

Field reference, list of all default categories and platform filter syntax live in [docs/usage/categories.md](docs/usage/categories.md).

### CLI Commands

Full reference of all `sccs` subcommands in [docs/usage/cli-reference.md](docs/usage/cli-reference.md).

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
sccs sync --force newer          # Newer file wins (by mtime)
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

Platform filter (`platforms: ["macos"]` etc.), detection logic and skip notices live in [docs/usage/categories.md](docs/usage/categories.md#platform-awareness).

### Windows / PowerShell Support

The PowerShell profile category and the Fish-to-PowerShell conversion workflow live in [docs/usage/platforms.md](docs/usage/platforms.md).

### Architecture & Development

Module layout, test setup and the quality gate live in [docs/architecture.md](docs/architecture.md).

### License

AGPL-3.0 — Equitania Software GmbH
