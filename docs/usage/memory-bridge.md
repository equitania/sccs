# Memory Bridge

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

### Konzept

Claude Code (Terminal) und Claude.ai (Web) teilen keinen gemeinsamen Speicher. Der Memory Bridge löst dies file-basiert:

```
local: ~/.claude/memory/<slug>/MEMORY.md
↕ SCCS-Sync (bidirektional, via Git)
repo: .claude/memory/<slug>/MEMORY.md
→ Claude.ai:    sccs memory export  →  als <memory>...</memory> Block einfügen
→ Claude Code:  SessionStart-Hook lädt Memory automatisch als Context
```

### Memory Item Format

Jedes Memory Item ist eine Datei `MEMORY.md` mit YAML-Frontmatter und Markdown-Body:

```markdown
---
id: "project-odoo18-arch"
title: "Odoo 18 Architecture Decisions"
category: decision   # project|decision|learning|pattern|preference|reference|context
project: v18
tags: [odoo, architecture]
priority: 4          # 1 (niedrig) – 5 (kritisch)
created: "2026-02-23T10:00:00"
updated: "2026-02-23T14:30:00"
expires: null        # ISO datetime oder null
version: 1
---

# Odoo 18 Architecture Decisions

Inhalt in Markdown.
```

### Konfiguration

Zwei neue Blöcke in `~/.config/sccs/config.yaml`:

```yaml
# 1. Memory-Kategorie (standardmäßig deaktiviert)
sync_categories:
  claude_memory:
    enabled: false           # Explizit aktivieren: sccs categories enable claude_memory
    description: "Claude Code <-> Claude.ai Memory Bridge"
    local_path: ~/.claude/memory
    repo_path: .claude/memory
    sync_mode: bidirectional
    item_type: directory
    item_marker: MEMORY.md
    conflict_resolution: newest   # Neuestes updated-Timestamp gewinnt
    exclude: ["_archive/*", "*.tmp"]

# 2. Memory-Einstellungen
memory_config:
  auto_expire: false           # Abgelaufene Items bei sccs sync archivieren
  max_context_chars: 8000      # Maximale Zeichen für SessionStart-Hook
  min_priority: 1              # Mindest-Priorität für Hook-Export
  max_age_days: null           # Maximales Alter (Tage), null = unbegrenzt
```

### Lokale Einrichtung

```bash
# 1. Kategorie aktivieren
sccs categories enable claude_memory

# 2. Hook installieren (wird mit sccs sync -c claude_hooks synchronisiert)
#    Alternativ: hook direkt unter ~/.claude/hooks/load-memory.py ablegen

# 3. Hook in ~/.claude/settings.json eintragen (manuell!)
```

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/load-memory.py"}]
      }
    ]
  }
}
```

```bash
# 4. Optional: Anthropic API für Cloud-Sync (Files API)
uv pip install "sccs[memory]"
export ANTHROPIC_API_KEY="..."

# 5. Ersten Sync durchführen
sccs sync -c claude_memory
```

> **Wichtig**: Das private Repository für Memory-Sync verwenden, da Memory-Items persönliche Entscheidungen und Kontextinformationen enthalten können.

### Memory CLI-Befehle

```bash
# Memory-Items verwalten
sccs memory add "Titel" [--content "..."] [--from-stdin] [--from-file pfad] \
                        [--tag TAG] [--project P] [--priority 1-5] [--expires DATUM]
sccs memory list        [--project P] [--tag T] [--expired] [--min-priority N]
sccs memory show <slug> [--raw]
sccs memory edit <slug>
sccs memory update <slug> [--extend "..."] [--tag T] [--priority N] [--bump-version]
sccs memory delete <slug> [--force]   # Soft-Delete: verschiebt nach _archive/

# Suche und Export
sccs memory search "query" [--project P]
sccs memory export  [--format claude_block|markdown|json] \
                    [--project P] [--tag T] [--out DATEI] [--api]
sccs memory import conversation.json [--preview]

# Verwaltung
sccs memory expire        # Abgelaufene Items archivieren
sccs memory stats         # Statistiken anzeigen
```

### Sync-Richtung und Konfliktauflösung

| Aspekt | Verhalten |
|--------|-----------|
| Sync-Modus | `bidirectional`: lokal ↔ Repository (Standard) |
| Konfliktauflösung | `conflict_resolution: newest`: Das Item mit dem neueren `updated`-Timestamp gewinnt automatisch |
| Soft-Delete | `sccs memory delete` verschiebt nach `_archive/<slug>/` — kein Datenverlust |
| Auto-Expire | Items mit vergangener `expires`-Zeit werden bei `sccs sync` archiviert wenn `auto_expire: true` |
| Prioritätsfilter | SessionStart-Hook respektiert `min_priority` aus `memory_config` |
| Zeichenlimit | Hook kürzt Context bei `max_context_chars` (Standard: 8000) |

### Export-Workflows für Claude.ai

```bash
# Als <memory>...</memory> Block für System-Prompt in Claude.ai
sccs memory export
sccs memory export --project v18 --format claude_block

# Als JSON (strukturiert)
sccs memory export --format json --out ~/Desktop/memory.json

# Über Anthropic Files API hochladen (erfordert sccs[memory] + ANTHROPIC_API_KEY)
sccs memory export --api

# Claude.ai Konversations-Export importieren
sccs memory import ~/Downloads/conversation.json
sccs memory import ~/Downloads/conversation.json --preview  # Vorschau ohne Speichern
```

### Sicherheitshinweise

- **Privates Repository**: `claude_memory` nur mit privatem Git-Repo nutzen
- **API-Key**: `ANTHROPIC_API_KEY` ausschließlich als Umgebungsvariable, nie in Dateien
- **Globale Ausschlüsse**: Bestehende `global_exclude`-Pattern schützen automatisch vor versehentlichem Sync sensibler Dateinamen (`*token*`, `*secret*`, `*credential*`)
- **`--api` ist immer explizit**: Anthropic Files API-Upload niemals automatisch

Querverweise: [sync.md](sync.md), [categories.md](categories.md), [transfer.md](transfer.md), [cli-reference.md](cli-reference.md)

---

## English

### Concept

Claude Code (terminal) and Claude.ai (web) share no common memory. The Memory Bridge solves this file-based:

```
local: ~/.claude/memory/<slug>/MEMORY.md
↕ SCCS sync (bidirectional, via Git)
repo: .claude/memory/<slug>/MEMORY.md
→ Claude.ai:    sccs memory export  →  paste as <memory>...</memory> block
→ Claude Code:  SessionStart hook loads memory automatically as context
```

### Memory Item Format

Each memory item is a `MEMORY.md` file with YAML frontmatter and Markdown body:

```markdown
---
id: "project-odoo18-arch"
title: "Odoo 18 Architecture Decisions"
category: decision   # project|decision|learning|pattern|preference|reference|context
project: v18
tags: [odoo, architecture]
priority: 4          # 1 (low) – 5 (critical)
created: "2026-02-23T10:00:00"
updated: "2026-02-23T14:30:00"
expires: null        # ISO datetime or null
version: 1
---

# Odoo 18 Architecture Decisions

Content in Markdown.
```

### Configuration

Two new blocks in `~/.config/sccs/config.yaml`:

```yaml
# 1. Memory category (disabled by default)
sync_categories:
  claude_memory:
    enabled: false           # Enable explicitly: sccs categories enable claude_memory
    description: "Claude Code <-> Claude.ai Memory Bridge"
    local_path: ~/.claude/memory
    repo_path: .claude/memory
    sync_mode: bidirectional
    item_type: directory
    item_marker: MEMORY.md
    conflict_resolution: newest   # Item with newer updated timestamp wins
    exclude: ["_archive/*", "*.tmp"]

# 2. Memory settings
memory_config:
  auto_expire: false           # Archive expired items on sccs sync
  max_context_chars: 8000      # Maximum characters for SessionStart hook
  min_priority: 1              # Minimum priority for hook export
  max_age_days: null           # Maximum age (days), null = unlimited
```

### Local Setup

```bash
# 1. Enable the category
sccs categories enable claude_memory

# 2. Install the hook (synced via sccs sync -c claude_hooks)
#    Alternative: place hook directly at ~/.claude/hooks/load-memory.py

# 3. Register hook in ~/.claude/settings.json (manual step!)
```

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/load-memory.py"}]
      }
    ]
  }
}
```

```bash
# 4. Optional: Anthropic API for cloud sync (Files API)
uv pip install "sccs[memory]"
export ANTHROPIC_API_KEY="..."

# 5. Run first sync
sccs sync -c claude_memory
```

> **Important**: Use a private repository for memory sync, as memory items may contain personal decisions and context information.

### Memory CLI Commands

```bash
# Manage memory items
sccs memory add "Title" [--content "..."] [--from-stdin] [--from-file path] \
                        [--tag TAG] [--project P] [--priority 1-5] [--expires DATE]
sccs memory list        [--project P] [--tag T] [--expired] [--min-priority N]
sccs memory show <slug> [--raw]
sccs memory edit <slug>
sccs memory update <slug> [--extend "..."] [--tag T] [--priority N] [--bump-version]
sccs memory delete <slug> [--force]   # Soft-delete: moves to _archive/

# Search and export
sccs memory search "query" [--project P]
sccs memory export  [--format claude_block|markdown|json] \
                    [--project P] [--tag T] [--out FILE] [--api]
sccs memory import conversation.json [--preview]

# Management
sccs memory expire        # Archive expired items
sccs memory stats         # Show statistics
```

### Sync Direction and Conflict Resolution

| Aspect | Behavior |
|--------|----------|
| Sync mode | `bidirectional`: local ↔ repository (default) |
| Conflict resolution | `conflict_resolution: newest`: item with newer `updated` timestamp wins automatically |
| Soft-delete | `sccs memory delete` moves to `_archive/<slug>/` — no data loss |
| Auto-expire | Items with a past `expires` time are archived on `sccs sync` when `auto_expire: true` |
| Priority filter | SessionStart hook respects `min_priority` from `memory_config` |
| Character limit | Hook truncates context at `max_context_chars` (default: 8000) |

### Export Workflows for Claude.ai

```bash
# As <memory>...</memory> block for system prompt in Claude.ai
sccs memory export
sccs memory export --project v18 --format claude_block

# As JSON (structured)
sccs memory export --format json --out ~/Desktop/memory.json

# Upload via Anthropic Files API (requires sccs[memory] + ANTHROPIC_API_KEY)
sccs memory export --api

# Import Claude.ai conversation export
sccs memory import ~/Downloads/conversation.json
sccs memory import ~/Downloads/conversation.json --preview  # Preview without saving
```

### Security Notes

- **Private repository**: Only use `claude_memory` with a private Git repo
- **API key**: Store `ANTHROPIC_API_KEY` as environment variable only, never in files
- **Global excludes**: Existing `global_exclude` patterns automatically protect against accidental sync of sensitive filenames (`*token*`, `*secret*`, `*credential*`)
- **`--api` is always explicit**: Anthropic Files API upload is never automatic

See also: [sync.md](sync.md), [categories.md](categories.md), [transfer.md](transfer.md), [cli-reference.md](cli-reference.md)
