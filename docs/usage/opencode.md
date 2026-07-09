# OpenCode Integration

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

Claude-Code-Artefakte für [OpenCode](https://opencode.ai) nutzbar machen. Die Synchronisierung ist **einseitig** (Claude Code ist die Quelle der Wahrheit): Skills und Rules werden von OpenCode nativ gelesen, Agents/Commands werden ins OpenCode-Format konvertiert, MCP-Server in `opencode.json` gemerged.

### Grundkonzept: „Skills-first, Agents-als-Subagents"

OpenCode hat drei Erweiterungsmechanismen, und sein eigenes Mentalmodell fasst sie so zusammen: **„Commands = *was* zu tun ist, Skills = *wie* es zu tun ist, Agents = *wer* es tut."** Die drei koexistieren — Skills lösen Subagents nicht ab.

Für SCCS heißt das:

- **Skills sind der Schwerpunkt und brauchen von SCCS am wenigsten.** OpenCode liest `~/.claude/skills/<name>/SKILL.md` seit **v1.16 (Juni 2026)** direkt — das Format ist mit Claude Code identisch (`name`/`description`/`license`/`compatibility`/`metadata`). SCCS kopiert oder konvertiert Skills deshalb bewusst **nicht** (Zero-Touch); das ist der reibungsloseste Weg. Es gibt in OpenCode keine Option, dieses native Lesen abzuschalten.
- **Agents werden als Subagents abgebildet.** Ein Claude-Subagent ist konzeptionell dasselbe wie ein OpenCode-`mode: subagent` — die Konvertierung schreibt eine `.md` mit `description`, `mode: subagent`, gemapptem `model` und (verlustbehaftet) `permission`. SCCS emittiert bewusst `permission` statt des in OpenCode inzwischen deprecateten `tools:`-Boolean-Maps.
- **Commands** werden dünn konvertiert (`description`, `model`, plus die OpenCode-nativen `agent`/`subtask`, falls im Claude-Frontmatter vorhanden).

### Auf einen Blick

| Artefakt | Verhalten | Aufwand |
|----------|-----------|---------|
| Skills, `CLAUDE.md` | OpenCode liest `~/.claude/skills/` und `CLAUDE.md` nativ (seit v1.16) | **keiner** (Zero-Touch) |
| Agents | Frontmatter-Konvertierung → `~/.config/opencode/agent/` (`mode: subagent`) | Export-Befehl |
| Commands | Frontmatter-Konvertierung → `~/.config/opencode/command/` | Export-Befehl |
| MCP-Server | Merge in `opencode.json` (`mcp`-Block) | Merge-Befehl |

> **Verzeichnisnamen:** SCCS schreibt in die Singular-Verzeichnisse `agent/` und `command/`. Der OpenCode-Loader liest über Brace-Globs (`{agent,agents}`, `{command,commands}`) **beide** Formen — Singular und Plural sind auf aktuellen Versionen (verifiziert gegen 1.17.x) gleichwertig gültig. Getestet gegen OpenCode (Projekt seit 2026 von `sst` nach `anomalyco` umgezogen; Docs unter opencode.ai).

### Status

```bash
# Erkannte OpenCode-Installation + offene Konvertierungen
sccs integrations opencode status
```

Zeigt den Installationspfad, ob Skills nativ gelesen werden, sowie die Agents/Commands, die noch exportiert werden müssen, und MCP-Server, die noch nicht in `opencode.json` stehen.

### Modelle zuordnen

Agents tragen ein Modell (z.B. `sonnet`). OpenCode erwartet eine vollqualifizierte `provider/model`-ID. Die Zuordnung wird **geschichtet** aufgelöst (niedrigste → höchste Priorität):

1. **Statischer Fallback** — eingebaute Default-Map (greift offline / ohne authentifizierten Provider).
2. **Live-Discovery** — `opencode models` wird abgefragt und das Tier (`sonnet`/`opus`/`haiku`) gegen die real verfügbaren Modelle gematcht (bevorzugter Provider zuerst).
3. **Explizite Config-Map** — `opencode.model_map` in der `config.yaml` pinnt einzelne Modelle.

```bash
# Interaktiv: genutzte Claude-Modelle den verfügbaren OpenCode-Modellen zuweisen
sccs integrations opencode map-models

# Vorschau ohne Schreiben
sccs integrations opencode map-models --dry-run
```

`map-models` listet die real genutzten Claude-Modelle und die in OpenCode verfügbaren Modelle, schlägt pro Modell den Familien-Match vor und schreibt die Auswahl nach `opencode.model_map` (mit Backup). Voraussetzung für Live-Discovery: ein in OpenCode authentifizierter Provider (`opencode auth login`).

### Agents & Commands exportieren

```bash
# Alle Agents konvertieren -> ~/.config/opencode/agent/
sccs integrations opencode export-agents

# Vorschau ohne Schreiben
sccs integrations opencode export-agents --dry-run

# Nur bestimmte Agents
sccs integrations opencode export-agents -a python-toolsmith -a system-architect

# Bestehende nicht überschreiben
sccs integrations opencode export-agents --no-overwrite

# Commands analog
sccs integrations opencode export-commands --dry-run
```

Konvertierungsregeln (Claude → OpenCode):

| Feld | Claude Code | OpenCode |
|------|-------------|----------|
| `name` | im Frontmatter | entfällt (Dateiname = Name) |
| `model` | `sonnet` | `anthropic/claude-sonnet-4-5` (aufgelöst) |
| `allowed-tools` | `Read Bash(git:*)` | `permission`-Objekt (`bash: {"git *": allow}`) |
| Modus | — | `mode: subagent` |

**Plugin-Artefakte werden nicht exportiert** *(ab v2.39.0)*: Doctor-gemanagte Agents/Commands (`gsd-*`, `playwright-cli` — dasselbe Managed-Registry, das auch der Sync ausschließt) fallen per Default aus `status`, `export-agents` und `export-commands` raus. So landen nur deine eigenen Artefakte in OpenCode, nicht die vom get-shit-done-Plugin installierten. Eigene Patterns ergänzt du über `opencode.exclude` (Glob, gegen den Basename). Ein explizites `-a <name>` / `-c <name>` umgeht den Exclude — so exportierst du gezielt auch einen gemanagten Agent (z.B. `-a gsd-debugger`).

### MCP-Server mergen

```bash
# mcpServers aus ~/.claude/settings.json in opencode.json mergen
sccs integrations opencode merge-mcp

# Vorschau ohne Schreiben
sccs integrations opencode merge-mcp --dry-run

# Nur bestimmte Server
sccs integrations opencode merge-mcp -s context7

# Bestehende OpenCode-Einträge überschreiben
sccs integrations opencode merge-mcp --overwrite
```

Bestehende Einträge in `opencode.json` bleiben standardmäßig erhalten; vor dem Schreiben wird ein Backup angelegt. Strukturumwandlung: `command` + `args` → ein Argv-Array, `env` → `environment`, expliziter `type: local|remote`.

### Konfiguration

```yaml
opencode:
  # Einzelne Aliase fest zuweisen (höchste Priorität)
  model_map:
    sonnet: anthropic/claude-sonnet-4-5
    opus: anthropic/claude-opus-4-1
  # Provider-Reihenfolge beim Familien-Match
  preferred_providers:
    - anthropic
  # Zusätzliche Ausschluss-Patterns (Glob, gegen Basename) — additiv zu den
  # doctor-gemanagten Defaults (gsd-*, playwright-cli)
  exclude:
    - "experimental-*"
```

Optionale (standardmäßig deaktivierte, macOS/Linux) Sync-Kategorien, falls die materialisierten Artefakte auch ins Git-Repo fließen sollen: `opencode_agents`, `opencode_commands`, `opencode_skills`.

```bash
sccs categories enable opencode_agents
```

### Einsatzbereiche

| Szenario | Empfohlener Befehl |
|----------|-------------------|
| Prüfen, was zu exportieren ist | `sccs integrations opencode status` |
| Modelle der eigenen Einrichtung zuordnen | `sccs integrations opencode map-models` |
| Einen Agent testweise übertragen | `sccs integrations opencode export-agents -a <name>` |
| MCP-Server übernehmen | `sccs integrations opencode merge-mcp --dry-run` |

Querverweise: [sync.md](sync.md), [categories.md](categories.md), [cli-reference.md](cli-reference.md)

---

## English

Make Claude Code artefacts usable in [OpenCode](https://opencode.ai). Synchronisation is **one-way** (Claude Code is the source of truth): skills and rules are read natively by OpenCode, agents/commands are converted to the OpenCode format, and MCP servers are merged into `opencode.json`.

### Core concept: "skills-first, agents-as-subagents"

OpenCode has three extension mechanisms, and its own mental model sums them up as: **"Commands are *what* to do, skills are *how* to do it, agents are *who* does it."** The three coexist — skills do not replace subagents.

For SCCS this means:

- **Skills are the focus and need the least from SCCS.** OpenCode reads `~/.claude/skills/<name>/SKILL.md` directly since **v1.16 (Jun 2026)** — the format is identical to Claude Code (`name`/`description`/`license`/`compatibility`/`metadata`). SCCS therefore deliberately does **not** copy or convert skills (zero-touch); this is the lowest-friction path. There is no OpenCode option to disable this native read.
- **Agents map to subagents.** A Claude subagent is conceptually the same as an OpenCode `mode: subagent` — the conversion writes a `.md` with `description`, `mode: subagent`, mapped `model`, and (lossy) `permission`. SCCS deliberately emits `permission` rather than OpenCode's now-deprecated `tools:` boolean map.
- **Commands** are thinly converted (`description`, `model`, plus OpenCode-native `agent`/`subtask` when present in the Claude frontmatter).

### At a Glance

| Artefact | Behaviour | Effort |
|----------|-----------|--------|
| Skills, `CLAUDE.md` | OpenCode reads `~/.claude/skills/` and `CLAUDE.md` natively (since v1.16) | **none** (zero-touch) |
| Agents | frontmatter conversion → `~/.config/opencode/agent/` (`mode: subagent`) | export command |
| Commands | frontmatter conversion → `~/.config/opencode/command/` | export command |
| MCP servers | merged into `opencode.json` (`mcp` block) | merge command |

> **Directory names:** SCCS writes to the singular `agent/` and `command/` directories. The OpenCode loader reads via brace globs (`{agent,agents}`, `{command,commands}`), so **both** singular and plural are equally valid on current versions (verified against 1.17.x). Tested against OpenCode (the project moved from `sst` to `anomalyco` in 2026; docs live at opencode.ai).

### Status

```bash
# Detected OpenCode install + outstanding conversions
sccs integrations opencode status
```

Shows the install path, a note that skills are read natively, the agents/commands still to export, and MCP servers not yet in `opencode.json`.

### Mapping Models

Agents carry a model (e.g. `sonnet`). OpenCode expects a fully-qualified `provider/model` id. Resolution is **layered** (lowest → highest precedence):

1. **Static fallback** — built-in default map (used offline / without an authenticated provider).
2. **Live discovery** — `opencode models` is queried and the tier (`sonnet`/`opus`/`haiku`) is matched against the models actually available (preferred provider first).
3. **Explicit config map** — `opencode.model_map` in `config.yaml` pins specific models.

```bash
# Interactive: assign used Claude models to available OpenCode models
sccs integrations opencode map-models

# Preview without writing
sccs integrations opencode map-models --dry-run
```

`map-models` lists the Claude models actually in use and the models available in OpenCode, suggests the family match per model, and writes the selection to `opencode.model_map` (with backup). Live discovery requires a provider authenticated in OpenCode (`opencode auth login`).

### Exporting Agents & Commands

```bash
# Convert all agents -> ~/.config/opencode/agent/
sccs integrations opencode export-agents

# Preview without writing
sccs integrations opencode export-agents --dry-run

# Specific agents only
sccs integrations opencode export-agents -a python-toolsmith -a system-architect

# Do not overwrite existing
sccs integrations opencode export-agents --no-overwrite

# Commands analogously
sccs integrations opencode export-commands --dry-run
```

Conversion rules (Claude → OpenCode):

| Field | Claude Code | OpenCode |
|-------|-------------|----------|
| `name` | in frontmatter | dropped (filename = name) |
| `model` | `sonnet` | `anthropic/claude-sonnet-4-5` (resolved) |
| `allowed-tools` | `Read Bash(git:*)` | `permission` object (`bash: {"git *": allow}`) |
| mode | — | `mode: subagent` |

**Plugin artefacts are not exported** *(since v2.39.0)*: doctor-managed agents/commands (`gsd-*`, `playwright-cli` — the same managed registry the sync engine excludes) are dropped from `status`, `export-agents` and `export-commands` by default, so only your own artefacts reach OpenCode rather than the ones installed by the get-shit-done plugin. Add your own patterns via `opencode.exclude` (glob, matched against the basename). An explicit `-a <name>` / `-c <name>` bypasses the exclude, so you can still export a managed artefact on purpose (e.g. `-a gsd-debugger`).

### Merging MCP Servers

```bash
# Merge mcpServers from ~/.claude/settings.json into opencode.json
sccs integrations opencode merge-mcp

# Preview without writing
sccs integrations opencode merge-mcp --dry-run

# Specific servers only
sccs integrations opencode merge-mcp -s context7

# Overwrite existing OpenCode entries
sccs integrations opencode merge-mcp --overwrite
```

Existing entries in `opencode.json` are kept by default; a backup is written before any change. Structure transform: `command` + `args` → a single argv array, `env` → `environment`, explicit `type: local|remote`.

### Configuration

```yaml
opencode:
  # Pin specific aliases (highest precedence)
  model_map:
    sonnet: anthropic/claude-sonnet-4-5
    opus: anthropic/claude-opus-4-1
  # Provider order for family matching
  preferred_providers:
    - anthropic
  # Extra exclude patterns (glob, matched against basename) — additive to the
  # doctor-managed defaults (gsd-*, playwright-cli)
  exclude:
    - "experimental-*"
```

Optional (disabled-by-default, macOS/Linux) sync categories, if the materialised artefacts should also flow into the Git repo: `opencode_agents`, `opencode_commands`, `opencode_skills`.

```bash
sccs categories enable opencode_agents
```

### Use Cases

| Scenario | Recommended Command |
|----------|-------------------|
| Check what to export | `sccs integrations opencode status` |
| Map models to your own setup | `sccs integrations opencode map-models` |
| Transfer one agent as a test | `sccs integrations opencode export-agents -a <name>` |
| Adopt MCP servers | `sccs integrations opencode merge-mcp --dry-run` |

See also: [sync.md](sync.md), [categories.md](categories.md), [cli-reference.md](cli-reference.md)
