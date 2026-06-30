# Sync — Synchronisierung / Synchronization

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

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

Komplette Feld-Referenz für `SyncCategory`: siehe [categories.md](categories.md).

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

Querverweise: [categories.md](categories.md), [doctor.md](doctor.md), [transfer.md](transfer.md), [memory-bridge.md](memory-bridge.md), [cli-reference.md](cli-reference.md)

---

## English

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

Full `SyncCategory` field reference: see [categories.md](categories.md).

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

### Adopting new default categories (opt-in)

When SCCS ships new default sync categories (e.g. the `opencode_*` or Pi integrations), `sccs sync`
does **not** offer them automatically — those integrations aren't for everyone, so a plain `sync`
stays silent (no prompt, no notice, CI-friendly).

To adopt newly available categories, choose one of:

```bash
sccs config upgrade    # dedicated interactive flow (also re-offers previously declined ones)
sccs sync --migrate    # opt-in: offer new categories as part of a sync run
```

`--no-migrate` remains valid as the (default) no-op. Categories you decline are remembered and not
re-offered by `sccs sync --migrate`; use `sccs config upgrade` to revisit them.

See also: [categories.md](categories.md), [doctor.md](doctor.md), [transfer.md](transfer.md), [memory-bridge.md](memory-bridge.md), [cli-reference.md](cli-reference.md)
