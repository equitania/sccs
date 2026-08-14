# Profiles — Artefakt-Gruppen ein- und ausschalten

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

Ein Profil bündelt die Skills, Agents, `settings.json`-Hooks und die Statusline, die **eine** Extension in `~/.claude/` installiert. `sccs profile off <name>` schaltet die Gruppe ab, `sccs profile on <name>` holt sie zurück.

### Wozu

Jede Skill- und Agent-Description landet beim Session-Start im System-Prompt des Modells, und jeder `PreToolUse`-Hook startet bei **jedem** Read-, Write- und Bash-Aufruf einen Prozess — unabhängig davon, ob die Extension an diesem Tag gebraucht wird.

Das mitgelieferte Profil `gsd` umfasst auf einem typischen Setup 71 Skills, 34 Agents und 19 Hook-Einträge, davon acht `PreToolUse`-Guards. Abgeschaltet spart das rund 5.000 Tokens Kontext pro Session und alle Hook-Prozesse in der Werkzeugschleife.

### Subcommands

```bash
sccs profile list                # Profile + Zustand
sccs profile off gsd             # Gruppe parken (Confirm; --yes überspringt ihn)
sccs profile on gsd              # Gruppe zurückholen
sccs profile status gsd          # Detail inkl. geparkter Artefakte
sccs profile list --json         # Maschinenlesbar
```

### Was beim Abschalten passiert

1. Passende Skill-Verzeichnisse aus `~/.claude/skills/` **wandern** nach `~/.config/sccs/profiles/<name>/skills/`.
2. Passende Agent-Dateien aus `~/.claude/agents/` wandern nach `~/.config/sccs/profiles/<name>/agents/`.
3. Hook-Einträge, deren `command` ein Muster des Profils enthält, werden aus `settings.json` entfernt und im Profil-Zustand gesichert.
4. Zeigt die `statusLine` auf ein Skript des Profils, wird sie auf das Preset aus `statusline_fallback_preset` umgestellt (siehe [Statusline](#statusline)); der alte Wert wird gesichert. Eine fremde Statusline (z.B. Starship) bleibt unangetastet.
5. Der Zustand landet in `~/.config/sccs/.profile_state.yaml`.

**Es wird nichts gelöscht.** Alles wird verschoben und ist über `sccs profile on` vollständig wiederherstellbar. Kollidiert eine Datei mit einer gleichnamigen im Parkbereich, bricht der Vorgang mit einer Fehlermeldung ab, statt zu überschreiben.

Die Hook-Dateien selbst (`~/.claude/hooks/gsd-*.js`) bleiben liegen — sie kosten keinen Kontext und laufen ohne Eintrag in `settings.json` nicht.

### Wichtig: Wirkung erst in der nächsten Session

Claude Code liest Skills, Agents und Hooks **einmal beim Session-Start**. Ein Profilwechsel wirkt daher erst in der nächsten Session. „Dynamisch dazuholen" heißt konkret:

```bash
sccs profile on gsd    # und dann eine neue Claude-Code-Session starten
```

Wer mitten in einer laufenden Session doch einen einzelnen geparkten Skill braucht, liest dessen `SKILL.md` direkt aus dem Parkbereich und folgt ihr — dafür ist kein Registry-Eintrag nötig.

### Zusammenspiel mit dem Doctor

Ohne Gegenmaßnahme würde der nächste `sccs doctor install/update` die Artefakte per npx sofort zurückschreiben. Deshalb überspringt der Doctor die npx-Tools eines abgeschalteten Profils (`DoctorConfig.installable_npx_tools()`). Für `gsd` ist das `@opengsd/gsd-core`; damit unterbleiben auch der `--force-statusline`-Patch und die Orphan-Prüfung.

Die **Sync-Excludes bleiben davon unberührt**: `effective_npx_tools()` liefert weiterhin die vollständige Liste, damit `gsd-*` in `get_doctor_managed_excludes()` erhalten bleibt. Andernfalls würde `sccs sync` liegengebliebene `gsd-*`-Dateien plötzlich ins Repository schieben.

Der Parkbereich liegt außerhalb von `~/.claude/` und damit ohnehin außerhalb des Sync-Scopes.

`doctor.protected_hooks` (Default `gsd-`) schützt weiterhin gegen `disallowed_hooks` — eine ausdrücklich angeforderte Profil-Abschaltung sticht diesen Schutzwall.

### Eigene Profile

Profile stehen in `~/.config/sccs/config.yaml` unter dem Top-Level-Schlüssel `profiles:`. Ein Eintrag mit dem Namen eines mitgelieferten Profils **ersetzt** dessen Spezifikation vollständig.

```yaml
profiles:
  odoo:
    description: "Odoo-Skills — nur in Odoo-Repos gebraucht"
    skills: ["odoo*", "eq-*", "fr-*"]
    agents: ["odoo-developer*", "fastreport-*"]
    hooks: []
```

| Feld | Bedeutung |
|------|-----------|
| `description` | Anzeigetext in `sccs profile list` |
| `skills` | fnmatch-Globs gegen Verzeichnisnamen in `~/.claude/skills/` |
| `agents` | fnmatch-Globs gegen Dateinamen in `~/.claude/agents/` |
| `hooks` | Substring-Muster gegen `hooks[*].hooks[*].command` — gleiche Semantik wie `doctor.disallowed_hooks` |
| `statusline_fallback_preset` | Name des Statusline-Presets, auf das umgestellt wird |
| `npx_tools` | Namen der Doctor-npx-Tools, die diese Artefakte installieren |

Profilnamen dürfen nur Kleinbuchstaben, Ziffern, `-` und `_` enthalten.

## Statusline

Manche Extensions bringen ihre eigene Statusleiste mit — GSD zum Beispiel setzt `statusLine` auf `hooks/gsd-statusline.js`. Wird das Profil abgeschaltet, zeigt der Eintrag auf ein Skript, das nicht mehr eingebunden ist, und die Zeile bleibt leer. Deshalb gehört zu jedem solchen Profil ein Preset, auf das zurückgefallen wird.

Ein **Preset** benennt eine Statusleiste: ihr Kommando, wie man erkennt ob sie installiert ist, und optional wie sie installiert wird.

```bash
sccs statusline list                            # Presets, installiert?, aktiv?
sccs statusline install claude-code-statusline  # herunterladen und installieren
sccs statusline use claude-code-statusline      # settings.json umstellen
sccs statusline show                            # aktueller Eintrag
```

### Mitgelieferte Presets

| Preset | Kommando | Installation |
|--------|----------|--------------|
| `builtin` | `"$HOME/.claude/statusline.sh"` | keine — dein eigenes Shell-Skript |
| `claude-code-statusline` | `~/.claude/statusline` | [glauberlima/claude-code-statusline](https://github.com/glauberlima/claude-code-statusline) |

`claude-code-statusline` zeigt Verzeichnis, Git-Branch, Dateiänderungen, Modell, Kontextauslastung mit Fortschrittsbalken und Kosten. Konfiguriert wird es in `~/.claude/statusline.toml` (Optionen: `cost`, `messages`, `messages_language`, `usage_bar_style`).

### Installation

`sccs statusline install <name>` und `sccs doctor install` laden das Installationsskript in eine temporäre Datei und führen es mit `bash <datei>` aus — **nie** `curl … | bash` durch eine Shell. Damit wird nichts, was aus der Konfiguration stammt, jemals von einer Shell interpretiert.

Zusätzliche Absicherung:

- Install-URLs müssen `https` sein und auf einen Host der Allowlist zeigen (`raw.githubusercontent.com`, `github.com`, `objects.githubusercontent.com`) — geprüft beim Laden der Konfiguration, nicht erst bei der Ausführung
- Das heruntergeladene Skript darf nicht leer und nicht größer als 512 KB sein
- Die Aktion ist bestätigungspflichtig und steht standardmäßig auf **Nein**

Unter Windows bricht die automatische Installation ab und zeigt stattdessen den PowerShell-Befehl an.

### Binary bleibt aus dem Repository

`claude-code-statusline` legt ein mehrere Megabyte großes Binary in `~/.claude/` ab, dazu eine maschinenlokale `statusline.toml`. Beide stehen in `managed_paths` des Presets und landen darüber in den Sync-Excludes — `sccs sync` schiebt sie nicht ins Git-Repository. Das gilt für **alle** bekannten Presets, nicht nur das aktive: sonst würde ein Wechsel der Statusleiste plötzlich das Binary der vorherigen einsammeln.

Dein eigenes `statusline.sh` ist davon **nicht** betroffen und wird weiterhin synchronisiert.

### Eigene Presets

```yaml
statusline:
  active: claude-code-statusline
  presets:
    starship:
      description: "Starship prompt as statusline"
      command: "starship prompt"
```

| Feld | Bedeutung |
|------|-----------|
| `command` | Wert für `statusLine.command`; Claude Code führt ihn über eine Shell aus, `~` und `$HOME` expandieren |
| `padding` | Optionales `statusLine.padding`; bei `null` wird der Schlüssel weggelassen |
| `marker_path` | Pfad (relativ zu `~/.claude/` oder absolut), dessen Existenz „installiert" beweist |
| `install_url` | https-URL eines POSIX-Installers, Host aus der Allowlist |
| `install_url_windows` | https-URL des PowerShell-Installers, wird als Hinweis angezeigt |
| `managed_paths` | Bloße Dateinamen, die das Preset in `~/.claude/` ablegt — landen in den Sync-Excludes |

`active` ist rein deklarativ: SCCS schreibt `statusLine` nur bei `sccs statusline use` oder beim Abschalten eines Profils. Der Doctor meldet lediglich, wenn das unter `active` genannte Preset fehlt.

---

## English

A profile bundles the skills, agents, `settings.json` hooks and statusline that **one** extension installs into `~/.claude/`. `sccs profile off <name>` switches the group off; `sccs profile on <name>` brings it back.

### Why

Every skill and agent description is loaded into the model's system prompt at session start, and every `PreToolUse` hook spawns a process on **each** Read, Write and Bash call — whether or not the extension is used that day.

The bundled `gsd` profile covers 71 skills, 34 agents and 19 hook entries on a typical setup, eight of them `PreToolUse` guards. Switching it off saves roughly 5,000 context tokens per session plus every hook process in the tool loop.

### Subcommands

```bash
sccs profile list                # Profiles and their state
sccs profile off gsd             # Park the group (confirm; --yes skips it)
sccs profile on gsd              # Bring it back
sccs profile status gsd          # Detail incl. parked artefacts
sccs profile list --json         # Machine-readable
```

### What switching off does

1. Matching skill directories **move** from `~/.claude/skills/` to `~/.config/sccs/profiles/<name>/skills/`.
2. Matching agent files move from `~/.claude/agents/` to `~/.config/sccs/profiles/<name>/agents/`.
3. Hook entries whose `command` contains one of the profile's patterns are removed from `settings.json` and recorded in the profile state.
4. If `statusLine` points at one of the profile's scripts it is switched to the preset named by `statusline_fallback_preset` (see [Statusline](#statusline-1)) and the old value is stored. An unrelated statusline (e.g. Starship) is left alone.
5. State is written to `~/.config/sccs/.profile_state.yaml`.

**Nothing is deleted.** Everything is moved and fully restorable via `sccs profile on`. If an item collides with a same-named one in the parking area, the operation aborts with an error instead of overwriting.

The hook files themselves (`~/.claude/hooks/gsd-*.js`) stay in place — they cost no context and do not run without an entry in `settings.json`.

### Important: takes effect in the next session

Claude Code reads skills, agents and hooks **once at session start**, so a profile switch only takes effect in the next session. "Pull it in on demand" concretely means:

```bash
sccs profile on gsd    # then start a new Claude Code session
```

If you need a single parked skill mid-session, read its `SKILL.md` straight from the parking area and follow it — no registry entry required.

### Interaction with the doctor

Left alone, the next `sccs doctor install/update` would write the artefacts straight back via npx. The doctor therefore skips the npx tools of a switched-off profile (`DoctorConfig.installable_npx_tools()`). For `gsd` that is `@opengsd/gsd-core`, which also suppresses the `--force-statusline` patch and the orphan check.

**Sync excludes are deliberately unaffected**: `effective_npx_tools()` still returns the full list so `gsd-*` stays in `get_doctor_managed_excludes()`. Otherwise `sccs sync` would suddenly start pushing leftover `gsd-*` files to the repository.

The parking area lives outside `~/.claude/` and is therefore out of sync scope anyway.

`doctor.protected_hooks` (default `gsd-`) still protects against `disallowed_hooks` — an explicitly requested profile switch overrides that guard.

### Custom profiles

Profiles live in `~/.config/sccs/config.yaml` under the top-level `profiles:` key. An entry named like a bundled profile **fully replaces** its spec.

```yaml
profiles:
  odoo:
    description: "Odoo skills — only needed inside Odoo repos"
    skills: ["odoo*", "eq-*", "fr-*"]
    agents: ["odoo-developer*", "fastreport-*"]
    hooks: []
```

| Field | Meaning |
|-------|---------|
| `description` | Label shown by `sccs profile list` |
| `skills` | fnmatch globs against directory names in `~/.claude/skills/` |
| `agents` | fnmatch globs against file names in `~/.claude/agents/` |
| `hooks` | Substring patterns against `hooks[*].hooks[*].command` — same semantics as `doctor.disallowed_hooks` |
| `statusline_fallback_preset` | Name of the statusline preset to switch to |
| `npx_tools` | Names of the doctor npx tools that install these artefacts |

Profile names may contain lowercase letters, digits, `-` and `_` only.

## Statusline

Some extensions bring their own statusline — GSD points `statusLine` at `hooks/gsd-statusline.js`. Switch the profile off and that entry refers to a script that is no longer wired up, leaving the line blank. Every such profile therefore names a preset to fall back to.

A **preset** names one statusline: its command, how to tell whether it is installed, and optionally how to install it.

```bash
sccs statusline list                            # Presets, installed?, active?
sccs statusline install claude-code-statusline  # download and install
sccs statusline use claude-code-statusline      # point settings.json at it
sccs statusline show                            # current entry
```

### Bundled presets

| Preset | Command | Installation |
|--------|---------|--------------|
| `builtin` | `"$HOME/.claude/statusline.sh"` | none — your own shell script |
| `claude-code-statusline` | `~/.claude/statusline` | [glauberlima/claude-code-statusline](https://github.com/glauberlima/claude-code-statusline) |

`claude-code-statusline` shows directory, git branch, file changes, model, context usage with a progress bar, and cost. Configure it in `~/.claude/statusline.toml` (options: `cost`, `messages`, `messages_language`, `usage_bar_style`).

### Installing

`sccs statusline install <name>` and `sccs doctor install` download the install script to a temp file and run it as `bash <file>` — **never** `curl … | bash` through a shell. Nothing originating in configuration is ever interpreted by a shell.

Additional guards:

- Install URLs must be `https` and point at an allowlisted host (`raw.githubusercontent.com`, `github.com`, `objects.githubusercontent.com`), checked at config-load time rather than at execution time
- The downloaded script must be non-empty and no larger than 512 KB
- The action requires confirmation and defaults to **No**

On Windows the automatic install aborts and prints the PowerShell command instead.

### The binary stays out of the repository

`claude-code-statusline` drops a multi-megabyte binary into `~/.claude/` plus a machine-local `statusline.toml`. Both are listed in the preset's `managed_paths` and therefore land in the sync excludes — `sccs sync` will not push them to the git repository. This applies to **all** known presets, not just the active one: otherwise switching statuslines would suddenly make sync pick up the previous one's binary.

Your own `statusline.sh` is unaffected and keeps syncing.

### Custom presets

```yaml
statusline:
  active: claude-code-statusline
  presets:
    starship:
      description: "Starship prompt as statusline"
      command: "starship prompt"
```

| Field | Meaning |
|-------|---------|
| `command` | Value for `statusLine.command`; Claude Code runs it through a shell, so `~` and `$HOME` expand |
| `padding` | Optional `statusLine.padding`; omitted from settings.json when null |
| `marker_path` | Path (relative to `~/.claude/`, or absolute) whose existence proves it is installed |
| `install_url` | https URL of a POSIX installer, host from the allowlist |
| `install_url_windows` | https URL of the PowerShell installer, shown as a hint |
| `managed_paths` | Bare file names the preset drops into `~/.claude/` — added to the sync excludes |

`active` is purely declarative: SCCS writes `statusLine` only on `sccs statusline use` or when a profile is switched off. The doctor merely reports when the preset named by `active` is missing.
