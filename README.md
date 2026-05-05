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

### Sync-Workflow

Publisher/Subscriber-Workflow, Schnellstart, Konfigurations-Beispiel, Konfliktauflösung und automatische Backups: [docs/usage/sync.md](docs/usage/sync.md).

### Export/Import (Kundendeployment)

ZIP-basierter Export/Import einzelner Kategorien für gezielte Kundendeployments. Vollständige Beispiele und Use-Cases siehe [docs/usage/transfer.md](docs/usage/transfer.md).

### Memory Bridge

File-basierter Brückenschlag zwischen Claude Code (Terminal) und Claude.ai (Web). Konzept, Item-Format, Konfiguration, Setup, CLI-Befehle, Konfliktauflösung, Export-Workflows und Sicherheitshinweise siehe [docs/usage/memory-bridge.md](docs/usage/memory-bridge.md).

### Kategorien-Referenz

Feld-Referenz, Liste aller Standard-Kategorien und Plattform-Filter siehe [docs/usage/categories.md](docs/usage/categories.md).

### CLI-Befehle

Vollständige Referenz aller `sccs`-Subcommands in [docs/usage/cli-reference.md](docs/usage/cli-reference.md).

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

### Sync workflow

Publisher/subscriber workflow, quick start, configuration example, conflict resolution and automatic backups: [docs/usage/sync.md](docs/usage/sync.md).

### Export/Import (Customer Deployment)

ZIP-based export/import of individual categories for targeted customer deployments. Full command reference and use cases live in [docs/usage/transfer.md](docs/usage/transfer.md).

### Memory Bridge

File-based bridge between Claude Code (terminal) and Claude.ai (web). Concept, item format, configuration, setup, CLI commands, conflict resolution, export workflows and security notes live in [docs/usage/memory-bridge.md](docs/usage/memory-bridge.md).

### Category Field Reference

Field reference, list of all default categories and platform filter syntax live in [docs/usage/categories.md](docs/usage/categories.md).

### CLI Commands

Full reference of all `sccs` subcommands in [docs/usage/cli-reference.md](docs/usage/cli-reference.md).

### Platform Awareness

Platform filter (`platforms: ["macos"]` etc.), detection logic and skip notices live in [docs/usage/categories.md](docs/usage/categories.md#platform-awareness).

### Windows / PowerShell Support

The PowerShell profile category and the Fish-to-PowerShell conversion workflow live in [docs/usage/platforms.md](docs/usage/platforms.md).

### Architecture & Development

Module layout, test setup and the quality gate live in [docs/architecture.md](docs/architecture.md).

### License

AGPL-3.0 — Equitania Software GmbH
