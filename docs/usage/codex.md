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

Codex zeigt Skills nicht als Claude-ähnliche Slash-Command-Liste. Nach dem
Export werden sie kontextabhängig aktiviert; einen bestimmten Skill forderst du
explizit mit `$<skill-name>` an. Starte eine neue Codex-Sitzung, falls deren
Skill-Liste bereits gecacht ist.

**Sichere Updates — zwei Schalter für zwei Risiken:** SCCS merkt sich die Ziele,
die es selbst erzeugt hat, in `~/.config/sccs/.codex_export_state.yaml`.
Ein Update eines SCCS-eigenen Ziels braucht `--overwrite` (oder `--force`).
Ein Ziel, das SCCS **nicht** geschrieben hat — vorhanden oder in Codex von Hand
geändert — braucht das eigene `--replace-foreign`, weil dort fremde Handarbeit
liegen kann. Die beiden Schalter implizieren einander bewusst nicht; ohne den
passenden bleibt ein vorhandenes Ziel unangetastet. Absolut bleibt dagegen die
Kollisionsregel: ein Command, dessen Skill-Platz von einem echten Skill belegt
ist, wird nie geschrieben — auch `--replace-foreign` hebt das nicht auf.
Skill-Verzeichnisse mit Symlinks werden nicht exportiert, weil Links außerhalb
des Quelldirectory in Codex unzuverlässig oder kaputt wären.

**Was Codex ablehnen wird, wird vorher benannt.** Skills werden wortgleich
kopiert — eine Description über 1024 Zeichen, ein Name über 64 Zeichen oder ein
unparsbares Frontmatter kommt also unverändert am Ziel an, und Codex lädt den
Skill stillschweigend nicht. `codex status` und der Export melden solche Skills
namentlich mit der gemessenen Länge. Das ist ein Hinweis, kein Abbruch: die
Kopie selbst ist korrekt.

**Agent-Konvertierung**: Der Markdown-Body wird zu `developer_instructions`, `description` wird übernommen, das Claude-Modell-Alias (`sonnet`/`opus`/`haiku`) wird auf ein Codex-Modell plus `model_reasoning_effort` gemappt. Eine `tools:`-Allowlist, die nur Lese-Tools enthält, wird zu `sandbox_mode = "read-only"`; jede andere Allowlist wird konservativ zu `workspace-write` und mit einer Warnung markiert. Codex hat keine per-Tool-Entsprechung — prüfe daher die gewünschte `approval_policy` separat.

**Modell-Mapping wird vor Agentenexport geprüft**: Die mitgelieferte Zuordnung
(`opus`/`sonnet` → `gpt-5.6-terra`, `haiku` → `gpt-5.6-luna`, Effort
`high`/`medium`/`low`) wird gegen `~/.codex/models_cache.json` validiert, wenn
der Cache vorhanden ist. Ein nicht vorhandener Modell-Slug bricht den
Agentenexport ab; ohne Cache meldet SCCS die fehlende Prüfung ausdrücklich.

Die Zuordnung folgt einer Regel: Alle drei Aliase zeigen auf die **aktuelle Top-Modellfamilie** und unterscheiden sich nur im `model_reasoning_effort` — ein Claude-Tier ist ein Tiefen-Signal, und genau das drückt Codex über den Effort aus. Ein Alias wird nie auf das kleine Modell einer älteren Generation gemappt.

Ob die Zuordnung noch zur installierten CLI passt, verrät der lokale Modell-Cache von Codex (in der Fish-Shell):

```fish
python3 -c "import json,pathlib;print([m['slug'] for m in json.loads(pathlib.Path.home().joinpath('.codex/models_cache.json').read_text())['models']])"
```

**Unlesbares Frontmatter** *(seit v2.58.4)*: Lässt sich der Frontmatter-Block einer Quelldatei nicht als YAML lesen, wird er beim Export **abgetrennt** (statt im Body zu landen, wo er ein zweites Frontmatter erzeugt hätte) und die Warnung nennt Ursache und Fundstelle: `invalid YAML in frontmatter: expected <block end>, but found '[' (line 3, column 29)` — Zeilen- und Spaltenangabe beziehen sich auf die **Datei**. Häufigster Auslöser ist `argument-hint: [a] [b...]`: das ist Claude Codes dokumentierte Syntax, aber kein gültiges YAML. Fix an der Quelle: in Anführungszeichen setzen — `argument-hint: "[a] [b...]"` parst sauber und Claude Code zeigt es unverändert an.

### Hooks exportieren

`sccs integrations codex export-hooks` überträgt die Hook-Einträge aus
`~/.claude/settings.json` nach `~/.codex/hooks.json`.

**Zehn Events sind übertragbar**: `PreToolUse`, `PostToolUse`,
`PermissionRequest`, `PreCompact`, `SessionStart`, `SessionEnd`,
`SubagentStart`, `SubagentStop`, `UserPromptSubmit`, `Stop`. Alles andere —
darunter `PostToolUseFailure`, `Notification`, `PostToolBatch` — kennt Codex
nicht und wird mit Warnung verworfen. Von Claudes Handler-Typen ist nur
`command` übertragbar; `http`, `prompt` und `agent` fallen weg.

**Skripte bleiben, wo sie sind.** Die Kommandos zeigen weiterhin auf
`~/.claude/hooks/` — ein Skript, eine Quelle der Wahrheit. Codex braucht dafür
ein vorhandenes `~/.claude/hooks/`.

**Matcher werden unverändert übernommen.** Codex feuert Tool-Events nur für
`Bash`, `apply_patch` (Aliase `Edit`/`Write`) und MCP-Namen — ein Matcher wie
`Bash|Read|Grep|Glob` greift dort nur bei `Bash`. Der Export warnt, schreibt den
Matcher aber nicht um: sobald Codex mehr Werkzeuge abdeckt, greift der Eintrag
von selbst.

**Deine eigenen Einträge bleiben unangetastet.** SCCS merkt sich in
`~/.config/sccs/.codex_hooks_state.yaml`, welche Einträge es geschrieben hat,
und fasst nur diese an. Ein in Claude gelöschter Hook verschwindet beim nächsten
Export auch hier.

**Nach dem Export: `/hooks` in Codex ausführen.** Codex vertraut Hooks über
einen Hash und führt neue oder geänderte Einträge erst nach einer Freigabe aus.

**Nicht Teil von `export-all`** — Hooks führen bei jedem Tool-Aufruf Code aus,
das gehört hinter eine bewusste Entscheidung.

> **Einschränkung:** Bearbeite exportierte Einträge nicht direkt in
> `hooks.json`. Der Besitz-Schlüssel ist `(Event, Matcher, Kommando)` — änderst
> du das Kommando eines Eintrags, erkennt SCCS ihn beim nächsten Export nicht
> mehr als eigenen und legt das Original erneut an, jetzt neben deiner
> Änderung. Fügst du stattdessen nur einen weiteren Handler in eine bestehende
> Gruppe ein, erkennt SCCS die Gruppe als fremd bearbeitet, lässt sie
> unangetastet und überspringt den eigenen Eintrag mit einer Warnung, statt ihn
> ein zweites Mal einzutragen. Ändere Hooks in Claude Code und exportiere neu.

**Kollisionen (Commands)**: Commands landen im selben Skill-Baum wie Skills. Ein Command, dessen Name mit einem Claude-Skill kollidiert oder dessen Ziel-Verzeichnis ein echter Skill ist (trägt mehr als die verpackte `SKILL.md`), wird **nie geschrieben** — der Skill gewinnt, der Command wird mit Warnung übersprungen. Bereits verpackte Commands (Verzeichnis mit genau einer `SKILL.md`) bleiben re-exportierbar.

**Plugin-Artefakte werden nicht exportiert**: Doctor-gemanagte Skills/Agents/Commands (`gsd-*`, `playwright-cli`) fallen per Default aus `status` und den Export-Befehlen raus. Eigene Patterns ergänzt du über `codex.exclude` (Glob, gegen den Basename). Ein explizites `-s`/`-a`/`-c` umgeht den Exclude. Ein Name, den es in `~/.claude/` gar nicht gibt, bricht seit v2.58.3 mit `No such agent/skill/command` und Exit-Code 1 ab — ein Tippfehler sieht damit nicht mehr wie ein erfolgreicher Lauf ohne Änderungen aus.

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
    sonnet: gpt-5.6-terra
  # ... oder additiv ergänzen
  extra_model_map:
    haiku: gpt-5.6-luna
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

Codex does not show skills as a Claude-style slash-command list. After export,
skills activate contextually; request a specific one explicitly with
`$<skill-name>`. Start a new Codex session if its skill list has already been
cached.

**Safe updates — two switches for two risks:** SCCS records the targets it
created in `~/.config/sccs/.codex_export_state.yaml`. Updating a target SCCS owns
requires `--overwrite` (or `--force`). A target SCCS did **not** write —
pre-existing, or edited by hand in Codex — requires the separate
`--replace-foreign`, because it may carry somebody's edits. The two deliberately
do not imply each other; without the matching one an existing target is left
alone. The collision rule stays absolute: a command whose skill slot is claimed
by a real skill is never written, `--replace-foreign` included. Skill directories
containing symlinks are not exported because links outside the source directory
would be unreliable or broken in Codex.

**What Codex will reject is named up front.** Skills are copied verbatim, so a
description over 1024 characters, a name over 64, or unparsable frontmatter
arrives unchanged — and Codex silently declines to load it. `codex status` and
the export name such skills with the measured length. This is a report, not a
failure: the copy itself is correct.

**Agent conversion**: the Markdown body becomes `developer_instructions`, `description` carries over, the Claude model alias (`sonnet`/`opus`/`haiku`) is mapped to a Codex model plus `model_reasoning_effort`. A `tools:` allowlist containing only read-only tools becomes `sandbox_mode = "read-only"`; every other allowlist is conservatively mapped to `workspace-write` and marked with a warning. Codex has no per-tool equivalent, so review the desired `approval_policy` separately.

**Model mapping is checked before agent export**: the bundled map
(`opus`/`sonnet` → `gpt-5.6-terra`, `haiku` → `gpt-5.6-luna`, effort
`high`/`medium`/`low`) is validated against `~/.codex/models_cache.json` when
the cache exists. A missing model slug stops the agent export; SCCS explicitly
warns when no cache is available for validation.

The map follows one rule: all three aliases point at the **current top model family** and differ only in `model_reasoning_effort` — a Claude tier is a depth signal, and effort is exactly how Codex expresses depth. An alias is never mapped onto an older generation's small model.

To check the map against the installed CLI, read the model catalogue Codex caches locally (fish shell):

```fish
python3 -c "import json,pathlib;print([m['slug'] for m in json.loads(pathlib.Path.home().joinpath('.codex/models_cache.json').read_text())['models']])"
```

**Unreadable frontmatter** *(since v2.58.4)*: when a source file's frontmatter block does not parse as YAML, the block is **stripped** on export (rather than left in the body, where it would produce a second frontmatter block) and the warning names cause and position: `invalid YAML in frontmatter: expected <block end>, but found '[' (line 3, column 29)` — line and column refer to the **file**. The most common trigger is `argument-hint: [a] [b...]`: that is Claude Code's documented syntax, but not valid YAML. Fix it at the source by quoting — `argument-hint: "[a] [b...]"` parses cleanly and Claude Code displays it unchanged.

### Exporting Hooks

`sccs integrations codex export-hooks` transfers the hook entries from
`~/.claude/settings.json` into `~/.codex/hooks.json`.

**Ten events transfer**: `PreToolUse`, `PostToolUse`, `PermissionRequest`,
`PreCompact`, `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop`,
`UserPromptSubmit`, `Stop`. Everything else — including `PostToolUseFailure`,
`Notification`, `PostToolBatch` — is unknown to Codex and dropped with a
warning. Of Claude's handler types, only `command` is portable; `http`,
`prompt` and `agent` are dropped.

**Scripts stay where they are.** The commands keep pointing at
`~/.claude/hooks/` — one script, one source of truth. Codex needs that
`~/.claude/hooks/` directory to exist for them to run.

**Matchers are carried over unchanged.** Codex only fires tool events for
`Bash`, `apply_patch` (aliases `Edit`/`Write`) and MCP names — a matcher like
`Bash|Read|Grep|Glob` only ever fires there for `Bash`. The export warns but
does not rewrite the matcher: once Codex covers more tools, the entry starts
working on its own.

**Your own entries are left alone.** SCCS tracks which entries it wrote in
`~/.config/sccs/.codex_hooks_state.yaml` and touches only those. A hook
deleted in Claude disappears here on the next export too.

**After exporting: run `/hooks` in Codex.** Codex trusts hooks by a hash and
only runs new or changed entries after you approve them.

**Not part of `export-all`** — hooks execute code on every tool call, which
belongs behind a deliberate decision.

> **Limitation:** do not edit an exported entry directly in `hooks.json`. The
> ownership key is `(event, matcher, command)` — change an entry's command and
> SCCS no longer recognizes it as its own on the next export, so it recreates
> the original next to your edit. Add another handler to an existing group
> instead, and SCCS treats the group as hand-edited, leaves it alone, and
> skips re-adding its own entry with a warning rather than writing it a second
> time. Edit hooks in Claude Code and re-export instead.

**Collisions (commands)**: commands land in the same skill tree as skills. A command whose name collides with a Claude skill, or whose target directory is a real skill (carries more than the wrapped `SKILL.md`), is **never written** — the skill wins and the command is skipped with a warning. Previously wrapped commands (a directory holding exactly one `SKILL.md`) stay re-exportable.

**Plugin artefacts are not exported**: doctor-managed skills/agents/commands (`gsd-*`, `playwright-cli`) are dropped from `status` and the export commands by default. Add your own patterns via `codex.exclude` (glob, matched against the basename). An explicit `-s`/`-a`/`-c` bypasses the exclude. Since v2.58.3 a name that does not exist in `~/.claude/` fails with `No such agent/skill/command` and exit code 1 — a typo no longer reads like a successful no-op run.

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
    sonnet: gpt-5.6-terra
  # ... or extend additively
  extra_model_map:
    haiku: gpt-5.6-luna
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
