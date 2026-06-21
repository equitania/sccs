# Pi Integration

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

Claude-Code-Artefakte für [Pi](https://pi.dev) (`@earendil-works/pi-coding-agent`) nutzbar machen. Die Synchronisierung ist **einseitig** (Claude Code ist die Quelle der Wahrheit): Skills und Agenten werden zu Pi-Skills, Commands zu Pi-Prompt-Templates.

> Pi kennt **kein Subagent-Konzept** wie Claude Code — Agenten in Pi sind TypeScript-Tools, keine Markdown-Definitionen. Deshalb werden Claude-Agenten als einzelne Pi-Skills (root-`.md` in `skills/`) abgelegt. Das `SKILL.md`-Frontmatter (`name`/`description`) ist **format-identisch** zu Claude Code, daher wird **verbatim kopiert** — keine Frontmatter-Konvertierung und kein Modell-Mapping.

### Auf einen Blick

| Artefakt | Quelle | Ziel | Methode |
|----------|--------|------|---------|
| Skills | `~/.claude/skills/<name>/` | `~/.pi/agent/skills/<name>/` | ganzes Verzeichnis kopieren |
| Agents | `~/.claude/agents/<name>.md` | `~/.pi/agent/skills/<name>.md` | als Einzel-Skill kopieren |
| Commands | `~/.claude/commands/<name>.md` | `~/.pi/agent/prompts/<name>.md` | als Prompt-Template kopieren |

### Status

```bash
# Erkannte Pi-Installation + offene Exporte
sccs integrations pi status
```

Zeigt den Installationspfad (`~/.pi/agent`) sowie die Skills, Agents und Commands, die noch exportiert werden müssen (`missing`/`outdated`).

### Skills, Agents & Commands exportieren

```bash
# Skills exportieren -> ~/.pi/agent/skills/
sccs integrations pi export-skills

# Vorschau ohne Schreiben
sccs integrations pi export-skills --dry-run

# Nur bestimmte Skills
sccs integrations pi export-skills -s astro -s sccs

# Bestehende nicht überschreiben
sccs integrations pi export-skills --no-overwrite

# Agents (-> als Skills) und Commands (-> als Prompts)
sccs integrations pi export-agents --dry-run
sccs integrations pi export-commands -c finalize

# Alles in einem Lauf
sccs integrations pi export-all
```

**Plugin-Artefakte werden nicht exportiert**: Doctor-gemanagte Skills/Agents/Commands (`gsd-*`, `playwright-cli` — dasselbe Managed-Registry, das auch der Sync ausschließt) fallen per Default aus `status` und den Export-Befehlen raus. So landen nur deine eigenen Artefakte in Pi, nicht die vom get-shit-done-Plugin installierten. Eigene Patterns ergänzt du über `pi.exclude` (Glob, gegen den Basename). Ein explizites `-s <name>` / `-a <name>` / `-c <name>` umgeht den Exclude — so exportierst du gezielt auch ein gemanagtes Artefakt.

### Konfiguration

```yaml
pi:
  # Pi-Resource-Root überschreiben (Default: ~/.pi/agent)
  base_dir: ~/.pi/agent
  # Zusätzliche Ausschluss-Patterns (Glob, gegen Basename) — additiv zu den
  # doctor-gemanagten Defaults (gsd-*, playwright-cli)
  exclude:
    - "experimental-*"
```

### Einsatzbereiche

| Szenario | Empfohlener Befehl |
|----------|-------------------|
| Prüfen, was zu exportieren ist | `sccs integrations pi status` |
| Einen Skill testweise übertragen | `sccs integrations pi export-skills -s <name>` |
| Alles auf einmal übertragen | `sccs integrations pi export-all --dry-run` |

Querverweise: [opencode.md](opencode.md), [sync.md](sync.md), [cli-reference.md](cli-reference.md)

---

## English

Make Claude Code artefacts usable in [Pi](https://pi.dev) (`@earendil-works/pi-coding-agent`). Synchronisation is **one-way** (Claude Code is the source of truth): skills and agents become Pi skills, commands become Pi prompt templates.

> Pi has **no subagent concept** like Claude Code — agents in Pi are TypeScript tools, not Markdown definitions. Claude agents are therefore placed as individual Pi skills (root `.md` in `skills/`). The `SKILL.md` frontmatter (`name`/`description`) is **format-identical** to Claude Code, so artefacts are **copied verbatim** — no frontmatter conversion and no model mapping.

### At a Glance

| Artefact | Source | Target | Method |
|----------|--------|--------|--------|
| Skills | `~/.claude/skills/<name>/` | `~/.pi/agent/skills/<name>/` | copy whole directory |
| Agents | `~/.claude/agents/<name>.md` | `~/.pi/agent/skills/<name>.md` | copy as individual skill |
| Commands | `~/.claude/commands/<name>.md` | `~/.pi/agent/prompts/<name>.md` | copy as prompt template |

### Status

```bash
# Detected Pi install + outstanding exports
sccs integrations pi status
```

Shows the install path (`~/.pi/agent`) and the skills, agents and commands still to export (`missing`/`outdated`).

### Exporting Skills, Agents & Commands

```bash
# Export skills -> ~/.pi/agent/skills/
sccs integrations pi export-skills

# Preview without writing
sccs integrations pi export-skills --dry-run

# Specific skills only
sccs integrations pi export-skills -s astro -s sccs

# Do not overwrite existing
sccs integrations pi export-skills --no-overwrite

# Agents (-> as skills) and commands (-> as prompts)
sccs integrations pi export-agents --dry-run
sccs integrations pi export-commands -c finalize

# Everything in one run
sccs integrations pi export-all
```

**Plugin artefacts are not exported**: doctor-managed skills/agents/commands (`gsd-*`, `playwright-cli` — the same managed registry the sync engine excludes) are dropped from `status` and the export commands by default, so only your own artefacts reach Pi rather than the ones installed by the get-shit-done plugin. Add your own patterns via `pi.exclude` (glob, matched against the basename). An explicit `-s <name>` / `-a <name>` / `-c <name>` bypasses the exclude, so you can still export a managed artefact on purpose.

### Configuration

```yaml
pi:
  # Override the Pi resource root (default: ~/.pi/agent)
  base_dir: ~/.pi/agent
  # Extra exclude patterns (glob, matched against basename) — additive to the
  # doctor-managed defaults (gsd-*, playwright-cli)
  exclude:
    - "experimental-*"
```

### Use Cases

| Scenario | Recommended Command |
|----------|-------------------|
| Check what to export | `sccs integrations pi status` |
| Transfer one skill as a test | `sccs integrations pi export-skills -s <name>` |
| Transfer everything at once | `sccs integrations pi export-all --dry-run` |

See also: [opencode.md](opencode.md), [sync.md](sync.md), [cli-reference.md](cli-reference.md)
