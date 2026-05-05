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
| `claude_statusline` | `~/.claude/statusline.*` | Statusline-Skript |

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
| `claude_statusline` | `~/.claude/statusline.*` | Statusline script |

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
