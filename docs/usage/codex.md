# OpenAI Codex Integration

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

Claude-Code-Artefakte für die [OpenAI Codex CLI](https://developers.openai.com/codex/) nutzbar machen. Die Synchronisierung ist **einseitig** (Claude Code ist die Quelle der Wahrheit): Skills werden verbatim kopiert, Agenten in Codex-Agent-TOML konvertiert, Commands als Codex-Skills verpackt.

> Codex liest Skills im offenen [agentskills.io](https://agentskills.io)-Standard — das `SKILL.md`-Format ist **identisch** zu Claude Code, daher werden Skills **verbatim kopiert**. Wichtig: Das User-Skill-Verzeichnis von Codex ist `~/.agents/skills/` (NICHT `~/.codex/skills/` — dort liegen nur die von OpenAI mitgelieferten System-Skills). Codex' eigene Custom Prompts (`~/.codex/prompts/`) sind **offiziell deprecated**; Skills sind der dokumentierte Migrationspfad für Slash-Command-artige Prompts — deshalb exportiert SCCS Commands als Skills.

### Auf einen Blick

| Artefakt | Quelle | Ziel | Methode |
|----------|--------|------|---------|
| Skills | `~/.claude/skills/<name>/` | `~/.agents/skills/<name>/` | ganzes Verzeichnis kopieren (verbatim) |
| Agents | `~/.claude/agents/<name>.md` | `~/.codex/agents/<name>.toml` | Frontmatter → TOML konvertieren |
| Commands | `~/.claude/commands/<name>.md` | `~/.agents/skills/<name>/SKILL.md` | als Codex-Skill verpacken |

### Status

```bash
# Erkannte Codex-Installation + offene Exporte
sccs integrations codex status
```

Zeigt den Installationspfad (`~/.codex`), die Zielverzeichnisse sowie die Skills, Agents und Commands, die noch exportiert werden müssen (`missing`/`outdated`/`collision`).

### Skills, Agents & Commands exportieren

```bash
# Skills exportieren -> ~/.agents/skills/
sccs integrations codex export-skills

# Vorschau ohne Schreiben
sccs integrations codex export-skills --dry-run

# Nur bestimmte Skills
sccs integrations codex export-skills -s astro -s sccs

# Agents (-> TOML) und Commands (-> Skills)
sccs integrations codex export-agents --dry-run
sccs integrations codex export-commands -c finalize

# Alles in einem Lauf
sccs integrations codex export-all
```

**Agent-Konvertierung**: Der Markdown-Body wird zu `developer_instructions`, `description` wird übernommen, das Claude-Modell-Alias (`sonnet`/`opus`/`haiku`) wird auf ein Codex-Modell plus `model_reasoning_effort` gemappt. Eine `tools:`-Allowlist, die nur Lese-Tools enthält, wird zu `sandbox_mode = "read-only"`; alles andere wird mit EINER Warnung verworfen (Codex steuert Zugriff über `sandbox_mode`/`approval_policy`, nicht pro Tool).

**Modell-Mapping ist statisch**: Codex hat — anders als OpenCode — keinen Discovery-Befehl. Die mitgelieferte Zuordnung (z. B. `sonnet` → `gpt-5.1-codex`, Effort `medium`) veraltet mit der Zeit; korrigiere sie über `codex.model_map`/`codex.extra_model_map` in der Config. Unbekannte Werte werden mit Warnung unverändert durchgereicht.

**Kollisionen (Commands)**: Commands landen im selben Skill-Baum wie Skills. Ein Command, dessen Name mit einem Claude-Skill kollidiert oder dessen Ziel-Verzeichnis ein echter Skill ist (trägt mehr als die verpackte `SKILL.md`), wird **nie geschrieben** — der Skill gewinnt, der Command wird mit Warnung übersprungen. Bereits verpackte Commands (Verzeichnis mit genau einer `SKILL.md`) bleiben re-exportierbar.

**Plugin-Artefakte werden nicht exportiert**: Doctor-gemanagte Skills/Agents/Commands (`gsd-*`, `playwright-cli`) fallen per Default aus `status` und den Export-Befehlen raus. Eigene Patterns ergänzt du über `codex.exclude` (Glob, gegen den Basename). Ein explizites `-s`/`-a`/`-c` umgeht den Exclude.

**Nicht abgedeckt (v1)**: kein MCP-Merge nach `~/.codex/config.toml` und kein CLAUDE.md → AGENTS.md. Für eine einmalige Komplett-Migration bietet Codex selbst den `/import`-Befehl an; der SCCS-Export ist der wiederholbare, inkrementelle Weg danach.

### Konfiguration

```yaml
codex:
  # Codex-Home überschreiben (Default: ~/.codex)
  base_dir: ~/.codex
  # Skill-Zielverzeichnis überschreiben (Default: ~/.agents/skills)
  skills_dir: ~/.agents/skills
  # Modell-Zuordnung voll ersetzen (None = Bundled-Default)
  model_map:
    sonnet: gpt-5.1-codex
  # ... oder additiv ergänzen
  extra_model_map:
    haiku: gpt-5.1-codex-mini
  # Reasoning-Effort pro Alias (Default: opus=high, sonnet=medium, haiku=low)
  reasoning_effort_map:
    sonnet: high
  # Zusätzliche Ausschluss-Patterns (Glob, gegen Basename) — additiv zu den
  # doctor-gemanagten Defaults (gsd-*, playwright-cli)
  exclude:
    - "experimental-*"
```

### Einsatzbereiche

| Szenario | Empfohlener Befehl |
|----------|-------------------|
| Prüfen, was zu exportieren ist | `sccs integrations codex status` |
| Einen Skill testweise übertragen | `sccs integrations codex export-skills -s <name>` |
| Alles auf einmal übertragen | `sccs integrations codex export-all --dry-run` |

Querverweise: [opencode.md](opencode.md), [pi.md](pi.md), [sync.md](sync.md), [cli-reference.md](cli-reference.md)

---

## English

Make Claude Code artefacts usable in the [OpenAI Codex CLI](https://developers.openai.com/codex/). Synchronisation is **one-way** (Claude Code is the source of truth): skills are copied verbatim, agents are converted into Codex agent TOML, commands are wrapped as Codex skills.

> Codex reads skills in the open [agentskills.io](https://agentskills.io) standard — the `SKILL.md` format is **identical** to Claude Code, so skills are **copied verbatim**. Note: Codex's user skill directory is `~/.agents/skills/` (NOT `~/.codex/skills/`, which holds only the OpenAI-bundled system skills). Codex's own custom prompts (`~/.codex/prompts/`) are **officially deprecated**; skills are the documented migration target for slash-command-style prompts — which is why SCCS exports commands as skills.

### At a Glance

| Artefact | Source | Target | Method |
|----------|--------|--------|--------|
| Skills | `~/.claude/skills/<name>/` | `~/.agents/skills/<name>/` | copy whole directory (verbatim) |
| Agents | `~/.claude/agents/<name>.md` | `~/.codex/agents/<name>.toml` | convert frontmatter → TOML |
| Commands | `~/.claude/commands/<name>.md` | `~/.agents/skills/<name>/SKILL.md` | wrap as Codex skill |

### Status

```bash
# Detected Codex install + outstanding exports
sccs integrations codex status
```

Shows the install path (`~/.codex`), the target directories, and the skills, agents and commands still to export (`missing`/`outdated`/`collision`).

### Exporting Skills, Agents & Commands

```bash
# Export skills -> ~/.agents/skills/
sccs integrations codex export-skills

# Preview without writing
sccs integrations codex export-skills --dry-run

# Specific skills only
sccs integrations codex export-skills -s astro -s sccs

# Agents (-> TOML) and commands (-> skills)
sccs integrations codex export-agents --dry-run
sccs integrations codex export-commands -c finalize

# Everything in one run
sccs integrations codex export-all
```

**Agent conversion**: the Markdown body becomes `developer_instructions`, `description` carries over, the Claude model alias (`sonnet`/`opus`/`haiku`) is mapped to a Codex model plus `model_reasoning_effort`. A `tools:` allowlist containing only read-only tools becomes `sandbox_mode = "read-only"`; anything else is dropped with ONE warning (Codex governs access via `sandbox_mode`/`approval_policy`, not per tool).

**Model mapping is static**: unlike OpenCode, Codex has no discovery command. The bundled map (e.g. `sonnet` → `gpt-5.1-codex`, effort `medium`) will age; correct it via `codex.model_map`/`codex.extra_model_map` in the config. Unknown values pass through unchanged with a warning.

**Collisions (commands)**: commands land in the same skill tree as skills. A command whose name collides with a Claude skill, or whose target directory is a real skill (carries more than the wrapped `SKILL.md`), is **never written** — the skill wins and the command is skipped with a warning. Previously wrapped commands (a directory holding exactly one `SKILL.md`) stay re-exportable.

**Plugin artefacts are not exported**: doctor-managed skills/agents/commands (`gsd-*`, `playwright-cli`) are dropped from `status` and the export commands by default. Add your own patterns via `codex.exclude` (glob, matched against the basename). An explicit `-s`/`-a`/`-c` bypasses the exclude.

**Out of scope (v1)**: no MCP merge into `~/.codex/config.toml` and no CLAUDE.md → AGENTS.md. For a one-time full migration Codex itself offers the `/import` command; the SCCS export is the repeatable, incremental path afterwards.

### Configuration

```yaml
codex:
  # Override the Codex home (default: ~/.codex)
  base_dir: ~/.codex
  # Override the skill target directory (default: ~/.agents/skills)
  skills_dir: ~/.agents/skills
  # Fully replace the model map (None = bundled default)
  model_map:
    sonnet: gpt-5.1-codex
  # ... or extend additively
  extra_model_map:
    haiku: gpt-5.1-codex-mini
  # Reasoning effort per alias (default: opus=high, sonnet=medium, haiku=low)
  reasoning_effort_map:
    sonnet: high
  # Extra exclude patterns (glob, matched against basename) — additive to the
  # doctor-managed defaults (gsd-*, playwright-cli)
  exclude:
    - "experimental-*"
```

### Use Cases

| Scenario | Recommended Command |
|----------|-------------------|
| Check what to export | `sccs integrations codex status` |
| Transfer one skill as a test | `sccs integrations codex export-skills -s <name>` |
| Transfer everything at once | `sccs integrations codex export-all --dry-run` |

See also: [opencode.md](opencode.md), [pi.md](pi.md), [sync.md](sync.md), [cli-reference.md](cli-reference.md)
