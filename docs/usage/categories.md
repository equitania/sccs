# Kategorien-Referenz / Category Reference

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

### Feld-Referenz

Alle Felder, die ein `SyncCategory` in `config.yaml` aufnehmen kann:

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
| `settings_ensure` | dict | Nein | Einträge, die nach dem Sync in einer JSON-Datei stehen müssen (siehe unten) |

`settings_ensure` selbst:

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `target_file` | string | Zieldatei, z.B. `~/.claude/settings.json` |
| `entries` | dict | Schlüssel, die vorhanden sein müssen. Fehlende werden ergänzt, vorhandene **nicht** überschrieben |
| `platform_overrides` | dict | Pro Plattform (`macos`/`linux`/`windows`). Überschreiben auch vorhandene Werte — eine ausdrückliche Wahl je Betriebssystem |
| `superseded_patterns` | dict | Je Schlüssel die Werte, die SCCS selbst in einer früheren Version geschrieben hat. Nur ein Treffer wird durch den aktuellen `entries`-Wert ersetzt; alles andere gilt als eigene Wahl und bleibt. Ein Muster trifft, wenn jeder von ihm genannte Schlüssel im Zielwert gleich ist — zusätzliche Schlüssel im Ziel stören nicht. Ein leeres Muster wird beim Laden abgelehnt, es würde jeden Wert treffen |
| `create_if_missing` | bool | Zieldatei anlegen, wenn sie fehlt (Standard: true) |
| `backup_before_modify` | bool | Sicherung vor jeder Änderung (Standard: true) |

### Standard-Kategorien

#### Claude Code (standardmäßig aktiv)

| Kategorie | Pfad | Beschreibung |
|-----------|------|-------------|
| `claude_framework` | `~/.claude/*.md` | SuperClaude Framework-Dateien |
| `claude_skills` | `~/.claude/skills/` | Skills (Verzeichnisse mit SKILL.md) |
| `claude_commands` | `~/.claude/commands/` | Commands (einzelne .md-Dateien) |
| `claude_hooks` | `~/.claude/hooks/` | Event-Handler-Skripte |
| `claude_agents` | `~/.claude/agents/` | Sub-Agent-Definitionen mit Modell-Routing |
| `claude_scripts` | `~/.claude/scripts/` | Hilfsskripte |
| `claude_plugins` | `~/.claude/plugins/` | Plugin-Konfigurationen |
| `claude_mcp` | `~/.claude/mcp/` | MCP-Server-Konfigurationen |
| `claude_statusline` | `~/.claude/statusline*` | Statusline-Skript **und** der passende `statusLine`-Eintrag in `settings.json` |

#### Claude Code (standardmäßig deaktiviert)

| Kategorie | Pfad | Beschreibung |
|-----------|------|-------------|
| `claude_memories` | `~/.claude/projects/*/memory/` | Persistente Projekt-Memories (feedback, project, user, reference) |
| `claude_memory` | `~/.claude/memory/` | Memory Bridge Items (claude_memory aktivieren) |
| `claude_settings` | `~/.claude/settings.json` | Claude Code Settings (Permissions, Hooks-Config) |

#### Shell (standardmäßig aktiv)

| Kategorie | Pfad | Plattform | Beschreibung |
|-----------|------|-----------|-------------|
| `fish_config` | `~/.config/fish/` | alle | Fish-Shell-Konfiguration |
| `fish_config_macos` | `~/.config/fish/conf.d/*.macos.fish` | macOS | macOS-spezifische conf.d |
| `fish_functions` | `~/.config/fish/functions/` | alle | Fish-Funktionen |
| `fish_functions_macos` | `~/.config/fish/functions/macos/` | macOS | macOS-spezifische Funktionen |
| `starship_config` | `~/.config/starship.toml` | alle | Starship-Prompt |

### Die Statuszeile über mehrere Rechner

Die Statuszeile ist zwei Dinge auf einmal: ein Skript unter `~/.claude/` **und** ein
`statusLine`-Eintrag in `settings.json`, der darauf zeigt. Wird nur das Skript verteilt,
läuft auf jedem anderen Rechner weiterhin das, was dessen `settings.json` zufällig sagt.
Die Kategorie `claude_statusline` deckt deshalb beides ab.

Synchronisiert werden `statusline-command.sh` (der Name, den Claude Codes eigenes
`/statusline`-Setup schreibt), `statusline.sh`, `statusline.py`, `statusline.fish` und
`statusline.ps1`. Ausgeschlossen bleiben die mehrere Megabyte große Binary `statusline`
eines Fremd-Presets, deren rechnerlokale `statusline.toml` sowie `*.bak`/`*.orig`.

Den `settings.json`-Eintrag setzt `settings_ensure`: unter macOS und Linux
`bash ~/.claude/statusline-command.sh`, unter Windows der PowerShell-Port
`pwsh -NoProfile -File ~/.claude/statusline.ps1` (beide Skripte liegen im Repository und
zeigen dieselbe Zeile).

**Ein bestehender Eintrag wird nicht angetastet** — mit einer Ausnahme: Werte, die SCCS
selbst in einer früheren Version geschrieben hat, stehen in `superseded_patterns` und
werden auf den aktuellen Stand gehoben. Ohne das behielte ein Rechner, der schon einmal
mit einer älteren SCCS-Version lief, dessen Kommando für immer. Ein Eintrag, den die
Liste nicht kennt, gilt als deine eigene Wahl und bleibt. Ein solcher Austausch wird im
Ausgabetext gemeldet (`↻ settings.json: refreshed [statusLine]`) und geht durch dieselbe
Backup-Logik wie jede andere Änderung an der Datei.

Eigenes Kommando dauerhaft festhalten — dann fasst SCCS den Eintrag nie an:

```yaml
sync_categories:
  claude_statusline:
    settings_ensure:
      entries:
        statusLine:
          type: command
          command: ~/bin/meine-statuszeile
      superseded_patterns:
        statusLine:
        - type: command
          command: nichts-was-jemals-vorkommt
```

**Auf einem Rechner mit älterer `config.yaml`**: Der `settings.json`-Teil zieht beim
nächsten `sccs sync` von allein nach — fehlende `superseded_patterns` und ein veralteter
`entries`-Wert werden aus den mitgelieferten Vorgaben ergänzt. Die Scan-Felder
(`item_pattern`, `include`, `exclude`) stammen dagegen unverändert aus der eigenen Datei
und müssen dort einmal von Hand angeglichen werden, sonst wird `statusline-command.sh`
gar nicht erst eingesammelt.

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

Erkennung: `Darwin` → `macos`, `Linux` → `linux`, `Windows` → `windows`. Kategorien mit `platforms: null` synchronisieren auf allen Plattformen.

Wenn beim Start Kategorien aufgrund des `platforms`-Filters auf der aktuellen Plattform übersprungen werden, gibt SCCS einen einzeiligen Hinweis aus (nur in interaktiven Terminals, nicht in Pipes/CI):

```
ℹ Plattform: windows — Fish nicht verfügbar — übersprungen: fish_config, fish_functions
  Tipp: `sccs convert fish-to-pwsh` generiert PowerShell-Aliasse aus den Fish-Configs
```

Querverweise: [sync.md](sync.md), [platforms.md](platforms.md), [doctor.md](doctor.md)

---

## English

### Field reference

All fields a `SyncCategory` accepts in `config.yaml`:

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
| `settings_ensure` | dict | No | Entries a JSON file must carry after the sync (see below) |

`settings_ensure` itself:

| Field | Type | Description |
|-------|------|-------------|
| `target_file` | string | Target file, e.g. `~/.claude/settings.json` |
| `entries` | dict | Keys that must be present. Missing ones are added, existing ones are **not** overwritten |
| `platform_overrides` | dict | Per platform (`macos`/`linux`/`windows`). These do overwrite existing values — an explicit per-OS choice |
| `superseded_patterns` | dict | Per key, the values SCCS itself wrote in an earlier release. Only a match is replaced by the current `entries` value; anything else counts as your own choice and stays. A pattern matches when every key it names is equal in the target value — extra keys in the target do not prevent it. An empty pattern is rejected at load time, as it would match every value |
| `create_if_missing` | bool | Create the target file when absent (default: true) |
| `backup_before_modify` | bool | Back up before every change (default: true) |

### Default categories

#### Claude Code (enabled by default)

| Category | Path | Description |
|----------|------|-------------|
| `claude_framework` | `~/.claude/*.md` | SuperClaude Framework files |
| `claude_skills` | `~/.claude/skills/` | Skills (directories with SKILL.md) |
| `claude_commands` | `~/.claude/commands/` | Commands (single .md files) |
| `claude_hooks` | `~/.claude/hooks/` | Event handler scripts |
| `claude_agents` | `~/.claude/agents/` | Sub-agent definitions with model routing |
| `claude_scripts` | `~/.claude/scripts/` | Utility scripts |
| `claude_plugins` | `~/.claude/plugins/` | Plugin configurations |
| `claude_mcp` | `~/.claude/mcp/` | MCP server configs |
| `claude_statusline` | `~/.claude/statusline*` | Statusline script **and** the matching `statusLine` entry in `settings.json` |

#### Claude Code (disabled by default)

| Category | Path | Description |
|----------|------|-------------|
| `claude_memories` | `~/.claude/projects/*/memory/` | Persistent project memories (feedback, project, user, reference) |
| `claude_memory` | `~/.claude/memory/` | Memory Bridge items (enable claude_memory to use) |
| `claude_settings` | `~/.claude/settings.json` | Claude Code settings (permissions, hooks config) |

#### Shell (enabled by default)

| Category | Path | Platform | Description |
|----------|------|----------|-------------|
| `fish_config` | `~/.config/fish/` | all | Fish shell configuration |
| `fish_config_macos` | `~/.config/fish/conf.d/*.macos.fish` | macOS | macOS-specific conf.d |
| `fish_functions` | `~/.config/fish/functions/` | all | Fish custom functions |
| `fish_functions_macos` | `~/.config/fish/functions/macos/` | macOS | macOS-specific functions |
| `starship_config` | `~/.config/starship.toml` | all | Starship prompt |

### The statusline across machines

The statusline is two things at once: a script under `~/.claude/` **and** a `statusLine`
entry in `settings.json` pointing at it. Ship only the script and every other machine
keeps running whatever its own `settings.json` happens to say. The `claude_statusline`
category therefore covers both.

Synced are `statusline-command.sh` (the name Claude Code's own `/statusline` setup
writes), `statusline.sh`, `statusline.py`, `statusline.fish` and `statusline.ps1`.
Excluded are the multi-megabyte `statusline` binary a third-party preset drops, its
machine-local `statusline.toml`, and `*.bak`/`*.orig`.

The `settings.json` entry comes from `settings_ensure`: on macOS and Linux
`bash ~/.claude/statusline-command.sh`, on Windows the PowerShell port
`pwsh -NoProfile -File ~/.claude/statusline.ps1` (both scripts live in the repository and
render the same line).

**An existing entry is left alone** — with one exception: values SCCS itself wrote in an
earlier release are listed in `superseded_patterns` and are lifted to the current one.
Without that, a machine that once ran an older SCCS would keep that release's command
forever. An entry the list does not recognise counts as your own choice and stays. Such a
replacement is reported in the output (`↻ settings.json: refreshed [statusLine]`) and goes
through the same backup path as any other change to the file.

To pin your own command so SCCS never touches the entry:

```yaml
sync_categories:
  claude_statusline:
    settings_ensure:
      entries:
        statusLine:
          type: command
          command: ~/bin/my-statusline
      superseded_patterns:
        statusLine:
        - type: command
          command: nothing-that-will-ever-occur
```

**On a machine with an older `config.yaml`**: the `settings.json` half catches up by
itself on the next `sccs sync` — missing `superseded_patterns` and an outdated `entries`
value are filled in from the bundled defaults. The scan fields (`item_pattern`, `include`,
`exclude`) come from your own file unchanged and have to be aligned there once by hand,
otherwise `statusline-command.sh` is never picked up in the first place.

### Platform awareness

Categories can be restricted to specific operating systems:

```yaml
fish_config_macos:
  enabled: true
  platforms: ["macos"]              # Only sync on macOS
  local_path: ~/.config/fish/conf.d
  repo_path: .config/fish/conf.d
  item_pattern: "*.macos.fish"
```

Detection: `Darwin` → `macos`, `Linux` → `linux`, `Windows` → `windows`. Categories with `platforms: null` sync on all platforms.

When categories are skipped on the current platform due to the `platforms` filter, SCCS prints a one-line dimmed hint at startup (only in interactive terminals, not in pipes/CI):

```
ℹ Plattform: windows — Fish nicht verfügbar — übersprungen: fish_config, fish_functions
  Tipp: `sccs convert fish-to-pwsh` generiert PowerShell-Aliasse aus den Fish-Configs
```

See also: [sync.md](sync.md), [platforms.md](platforms.md), [doctor.md](doctor.md)
