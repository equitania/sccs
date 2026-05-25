# SCCS — SkillsCommandsConfigsSync

![SCCS Overview](sccs-openai.png)

> **Language / Sprache**: [Deutsch](#deutsche-dokumentation) | [English](#english-documentation)

**Version:** 2.32.0 · **Lizenz / License:** AGPL-3.0 · **Python:** ≥ 3.10

---

## Deutsche Dokumentation

### Was ist SCCS?

SCCS ist ein YAML-konfiguriertes, bidirektionales Synchronisierungswerkzeug für Claude Code Dateien (Skills, Commands, Hooks, Agents, Scripts) und optionale Shell-Konfigurationen (Fish, Starship, PowerShell). Es hält deine `~/.claude/`-Installation und ein Git-Repository deckungsgleich — über mehrere Maschinen, mehrere Plattformen, mehrere Identitäten hinweg.

### Was kann SCCS?

- 🔄 **Bidirektionale Synchronisierung** zwischen `~/.claude/` und Git-Repository, mit interaktiver Konfliktauflösung und automatischen Backups → [docs/usage/sync.md](docs/usage/sync.md)
- 🩺 **System & Plugin Health-Check** (`sccs doctor`) für Node.js, `claude` CLI, Claude-Plugins, npm-Helper-Tools, Browser-Bundles und Filesystem-Permissions — mit gezielten Reparatur-Plänen → [docs/usage/doctor.md](docs/usage/doctor.md)
- 🧹 **`sccs doctor optimize`** *(v2.30.0)* — Ein-Schuss-Optimierungslauf: install + update + Drift-Warnung für Plugins/MCP-Server außerhalb der Spec. Mit `--strict` werden Uninstall-Actions per Confirm gequeut.
- 🔧 **`doctor.disallowed_hooks`** *(v2.31.0)* — Substring-Patterns entfernen unerwünschte Hooks aus `~/.claude/settings.json` nach jedem doctor-Pass (z.B. Hooks die von npx-Tools re-injiziert werden). Mit Backup, idempotent.
- 🛡️ **`doctor.protected_hooks`** *(v2.32.0)* — harter Schutzwall (Default `gsd-`): geschützte Hooks werden NIE entfernt, auch wenn ein `disallowed_hooks`-Pattern matcht (*protection wins*). GSD-Hooks überleben jeden doctor-Pass.
- ⚡ **Auto-Update sicherer Wartung** *(v2.32.0)* — `sccs doctor update`/`optimize` führt Plugin-Install/Update, npx-Refresh (inkl. GSD), Marketplace- und Bundled-Skill-Schritte ohne Nachfrage aus; destruktive Actions (Uninstall, Hook-Removal) bleiben confirm-pflichtig.
- 📦 **Selektiver Export/Import** als ZIP-Archiv (Checkbox-Auswahl) für Kundendeployments → [docs/usage/transfer.md](docs/usage/transfer.md)
- 🧠 **Memory Bridge** — file-basierter persistenter Kontext zwischen Claude Code (Terminal) und Claude.ai (Web), inklusive `sccs memory` CRUD-CLI → [docs/usage/memory-bridge.md](docs/usage/memory-bridge.md)
- 🪟 **Plattformübergreifend** macOS, Linux, Windows mit nativer PowerShell-7-Unterstützung und Fish→PowerShell-Konvertierung → [docs/usage/platforms.md](docs/usage/platforms.md)
- 🗂️ **Mehr als 30 vordefinierte Kategorien** mit Plattform-Filtern, anpassbaren Include/Exclude-Patterns und Sync-Modi → [docs/usage/categories.md](docs/usage/categories.md)

### Voraussetzungen

[UV](https://docs.astral.sh/uv/) muss installiert sein:

| Betriebssystem | Befehl |
|----------------|--------|
| macOS | `brew install uv` |
| Linux / WSL | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Windows | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |

### Installation

```bash
# Als CLI-Tool installieren (empfohlen)
uv tool install sccs

# Aktualisieren
uv tool upgrade sccs
```

**Für Entwickler:**

```bash
git clone https://github.com/equitania/sccs.git
cd sccs
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -e ".[dev]"
sccs --help
```

### Quick Start

```bash
sccs config init                 # Konfiguration erstellen
sccs status                      # Status anzeigen
sccs sync --dry-run              # Vorschau der Änderungen
sccs sync                        # Synchronisieren
sccs doctor check                # System & Plugin Health prüfen
```

### Dokumentation

| Datei | Inhalt |
|-------|--------|
| [docs/usage/sync.md](docs/usage/sync.md) | Sync-Workflow, Schnellstart, Konfiguration, Konfliktauflösung, Backups |
| [docs/usage/doctor.md](docs/usage/doctor.md) | `sccs doctor` — System & Plugin Health, Bundled Skills, Browser-Bundles, Permission-Checks |
| [docs/usage/transfer.md](docs/usage/transfer.md) | Export/Import als ZIP-Archive (Customer Deployment) |
| [docs/usage/memory-bridge.md](docs/usage/memory-bridge.md) | Memory Bridge: persistenter Kontext zwischen Claude Code und Claude.ai |
| [docs/usage/categories.md](docs/usage/categories.md) | Kategorien-Referenz, Standard-Kategorien, Plattform-Filter |
| [docs/usage/platforms.md](docs/usage/platforms.md) | Windows/PowerShell-Support, Fish→PowerShell-Konvertierung |
| [docs/usage/cli-reference.md](docs/usage/cli-reference.md) | Vollständige CLI-Befehlsreferenz |
| [docs/architecture.md](docs/architecture.md) | Modul-Layout, Test-Setup, Quality-Gate |
| [RELEASE_NOTES.md](RELEASE_NOTES.md) | Versions-Historie und Changelog |

### Lizenz

AGPL-3.0 — Equitania Software GmbH

---

## English Documentation

### What is SCCS?

SCCS is a YAML-configured, bidirectional synchronization tool for Claude Code files (skills, commands, hooks, agents, scripts) and optional shell configurations (Fish, Starship, PowerShell). It keeps your `~/.claude/` installation and a Git repository in lockstep — across multiple machines, multiple platforms, multiple identities.

### What can SCCS do?

- 🔄 **Bidirectional sync** between `~/.claude/` and a Git repository, with interactive conflict resolution and automatic backups → [docs/usage/sync.md](docs/usage/sync.md)
- 🩺 **System & plugin health check** (`sccs doctor`) for Node.js, the `claude` CLI, Claude plugins, npm helper tools, browser bundles and filesystem permissions — with surgical repair plans → [docs/usage/doctor.md](docs/usage/doctor.md)
- 🧹 **`sccs doctor optimize`** *(v2.30.0)* — one-shot optimisation pass: install + update + drift warning for plugins/MCP servers outside the spec. With `--strict`, uninstall actions are queued per confirm.
- 🔧 **`doctor.disallowed_hooks`** *(v2.31.0)* — substring patterns strip unwanted hooks from `~/.claude/settings.json` after every doctor pass (e.g. hooks re-injected by npx tools). Backup-aware, idempotent.
- 🛡️ **`doctor.protected_hooks`** *(v2.32.0)* — hard guard (default `gsd-`): protected hooks are NEVER stripped, even when a `disallowed_hooks` pattern matches (*protection wins*). GSD hooks survive every doctor pass.
- ⚡ **Auto-update for safe maintenance** *(v2.32.0)* — `sccs doctor update`/`optimize` runs plugin install/update, npx refresh (incl. GSD), marketplace and bundled-skill steps without prompts; destructive actions (uninstall, hook removal) keep their confirm gate.
- 📦 **Selective export/import** as ZIP archives (checkbox selection) for customer deployments → [docs/usage/transfer.md](docs/usage/transfer.md)
- 🧠 **Memory Bridge** — file-based persistent context between Claude Code (terminal) and Claude.ai (web), including a full `sccs memory` CRUD CLI → [docs/usage/memory-bridge.md](docs/usage/memory-bridge.md)
- 🪟 **Cross-platform** macOS, Linux, Windows with native PowerShell 7 support and Fish→PowerShell conversion → [docs/usage/platforms.md](docs/usage/platforms.md)
- 🗂️ **Over 30 predefined categories** with platform filters, customizable include/exclude patterns and sync modes → [docs/usage/categories.md](docs/usage/categories.md)

### Prerequisites

[UV](https://docs.astral.sh/uv/) must be installed:

| OS | Command |
|----|---------|
| macOS | `brew install uv` |
| Linux / WSL | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Windows | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |

### Installation

```bash
# Install as CLI tool (recommended)
uv tool install sccs

# Update
uv tool upgrade sccs
```

**For developers:**

```bash
git clone https://github.com/equitania/sccs.git
cd sccs
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -e ".[dev]"
sccs --help
```

### Quick Start

```bash
sccs config init                 # Initialize configuration
sccs status                      # Show sync status
sccs sync --dry-run              # Preview changes
sccs sync                        # Synchronize
sccs doctor check                # System & plugin health check
```

### Documentation

| File | Content |
|------|---------|
| [docs/usage/sync.md](docs/usage/sync.md) | Sync workflow, quick start, configuration, conflict resolution, backups |
| [docs/usage/doctor.md](docs/usage/doctor.md) | `sccs doctor` — system & plugin health, bundled skills, browser bundles, permission checks |
| [docs/usage/transfer.md](docs/usage/transfer.md) | Export/Import as ZIP archives (customer deployment) |
| [docs/usage/memory-bridge.md](docs/usage/memory-bridge.md) | Memory Bridge: persistent context between Claude Code and Claude.ai |
| [docs/usage/categories.md](docs/usage/categories.md) | Category reference, default categories, platform filters |
| [docs/usage/platforms.md](docs/usage/platforms.md) | Windows/PowerShell support, Fish→PowerShell conversion |
| [docs/usage/cli-reference.md](docs/usage/cli-reference.md) | Full CLI command reference |
| [docs/architecture.md](docs/architecture.md) | Module layout, test setup, quality gate |
| [RELEASE_NOTES.md](RELEASE_NOTES.md) | Version history and changelog |

### License

AGPL-3.0 — Equitania Software GmbH
