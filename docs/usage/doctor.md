# Doctor — System & Plugin Health

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

Der Doctor ist ein Inspektions- und Reparatur-Werkzeug für ein vollständig
arbeitsfähiges Claude Code Setup. Er deckt Bereiche ab, die sonst manuell
und fehleranfällig zu pflegen sind: Node.js-Mindestversion, das `claude`
CLI, Claude-Plugins (über `claude plugin install/update`), npm-Helper-Tools,
gebundelte Skills im npm-Paket, Browser-Bundles für Playwright sowie
Filesystem-Berechtigungen für die fragilen Pfade.

### Subcommands

```bash
sccs doctor check                # Read-only Status-Tabelle (Exit 1 bei Problemen)
sccs doctor check --no-update-check  # Wie oben, aber ohne Live-Versionsprüfung (offline/schnell)
sccs doctor install              # Installiert fehlende Komponenten (Confirm pro Action)
sccs doctor install --yes        # Confirms überspringen (nur für CI gedacht)
sccs doctor update               # Plugins + npx-Tools aktualisieren
```

### Update-Check (ab v2.42.0)

`sccs doctor check` prüft standardmäßig **live**, ob für die doctor-verwalteten npx-Tools und Plugins eine neuere Version verfügbar ist, und markiert sie als `OUTDATED` (Detail z.B. `update available: v1.6.0`) plus eine Hinweiszeile „Updates available — run `sccs doctor update`". Quellen: npx-Tools via `npm view <npm_package> version` (read-only Registry-Query, nur für Tools mit gesetztem `npm_package` wie `@opengsd/gsd-core`), Plugins via live-refreshtem Marketplace-Manifest (`claude plugin marketplace update <name>`). **Ein verfügbares Update ist nur ein Hinweis** und ändert den Exit-Code NICHT (Exit 1 bleibt fehlenden/kaputten Komponenten vorbehalten → CI-freundlich). Jeder Netzwerkfehler degradiert still (keine Falschmeldung). `--no-update-check` schaltet die Prüfung ab → vollständig offline und schnell.

### Optionale CLI-Tools (zoxide, Coreutils) — ab v2.43.0

Opt-in: aktiviere sie in `~/.config/sccs/config.yaml` über Preset-Namen:

```yaml
doctor:
  cli_tools: [zoxide, coreutils]
```

`zoxide` (smarter `cd`) wird auf **allen** Plattformen geprüft (winget/`brew install zoxide`/Install-Script), **Microsoft Coreutils** (`Microsoft.Coreutils`, Rust-uutils-Port von `cat`/`grep`/`wc`/`cut`/`xargs`) **nur Windows** — gibt PowerShell dieselben Unix-Befehle wie Linux/macOS/WSL. Erkennung: `which` für „auf PATH", auf Windows zusätzlich `winget list --id <id>` als autoritative Install-Prüfung (fängt die WinGet-Links-nicht-auf-PATH-Falle). Zustände: `OK` / gelb „installed, not on PATH" (+ PowerShell-PATH-Copy-Paste-Block unter der Tabelle) / blau „not installed (optional)". **Nur Hinweis — fehlend = kein Exit 1.** `doctor install` bietet `winget install`/`brew install` (confirm-gated); SCCS mutiert nie selbst PATH/Profil. Hinweis: zoxide braucht zusätzlich `zoxide init <shell>` im Profil für den `z`-Befehl (bewusst nicht durch den Doctor — er stellt nur die Binary sicher); Coreutils braucht keine Profil-Init. Shell-Conflicts (PS-Aliase `cat`/`sort`/`tee` gewinnen gegen die `.exe` → mit `cat.exe`/`sort.exe` aufrufen): siehe <https://github.com/microsoft/coreutils#shell-conflicts>.

### Was wird geprüft?

| Komponente | Check (`check`) | Reparatur (`install` / `update`) |
|---|---|---|
| **Node.js** | installiert + Mindestversion (≥ 20) | `brew install node` (macOS), `winget install OpenJS.NodeJS` (Windows), Manual-Block für Linux (NodeSource, sudo) |
| **CLI-Tools** (opt-in: `zoxide`, `coreutils`) | `which` + (Windows) `winget list`; `on_path` / `installed_not_on_path` / `missing` — **informativ, nie Exit 1** | `winget install`/`brew install` (confirm) bzw. PowerShell-PATH-Block; SCCS mutiert nie Profil/Umgebung |
| **`claude` CLI** | Binary auf PATH | `npm install -g @anthropic-ai/claude-code` |
| **Claude-Plugins** | je nach Marketplace via `claude plugin list`; **Update verfügbar** via Marketplace-Manifest (v2.42.0) | `claude plugin install/update <name>@<marketplace>` mit korrektem `--scope <user/project/local/managed>` |
| **npx-Tools** (z.B. `@opengsd/gsd-core`, `playwright-cli`) | Binary auf PATH **oder** State-File-Marker (für Tools die kein Binary droppen); **Update verfügbar** via `npm view` (v2.42.0, nur bei gesetztem `npm_package`) | `npm install -g <pkg>@latest` bzw. `npx -y <pkg> …` |
| **Bundled Skills** (z.B. `playwright-cli`-Skill) | `SKILL.md` im konfigurierten Target-Verzeichnis existiert | Kopiert das Skill-Verzeichnis aus dem npm-Paket nach `~/.claude/skills/<name>/` |
| **Browser-Bundles** (Playwright Chromium + Firefox) | `<cache>/<bundle>-*` Verzeichnisse vorhanden | `playwright-cli install-browser <bundle>` (idempotent) |
| **Filesystem-Permissions** | `~/.npm`, `~/.claude`, `~/.config/sccs`, `npm root -g` (lib) **und** `<npm prefix>/bin` (v2.32.1) schreibbar | Manual-Block — SCCS ruft niemals `sudo` auf; System-prefix → nur user-local Prefix |
| **PATH-Prefixes** (v2.28.0) | `<npm config get prefix>/bin` ist auf `$PATH` der aktuellen Shell | Manual-Block mit Snippets für bash/zsh/fish — neue Shell starten und `sccs doctor install` erneut ausführen |
| **Statusline** (v2.29.0) | `~/.claude/settings.json` → `statusLine.command` zeigt auf existierende Binary + Skript; Apple-Silicon-Homebrew-Cellar-Pfade nicht stale | Auto-Fix für `stale_cellar` (rewrite zu `/opt/homebrew/bin/<binary>` mit Backup); Manual-Block für `missing_binary`/`missing_script`/`missing`; `opaque` (Pipes/Env-Prefix) wird informativ angezeigt aber nicht eskaliert |

### Beispiel-Tabelle (`sccs doctor check`)

```
                   SCCS Doctor — System & Plugin Status
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Component                       ┃ Status ┃ Detail                            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Node.js                         │ OK     │ v20.20.2                          │
│ Claude CLI                      │ OK     │ /home/user/.local/bin/claude      │
│ plugin: superpowers@…           │ OK     │ installed                         │
│ npx: @opengsd/gsd-core        │ OK     │ installed (last run cached)       │
│ npx: playwright-cli             │ OK     │ /home/user/.local/bin/playwright… │
│ skill: playwright-cli           │ OK     │ ~/.claude/skills/playwright-cli/  │
│ browsers: playwright-cli        │ OK     │ chromium, firefox                 │
│ perm: ~/.npm                    │ OK     │ user-owned, writable              │
│ perm: ~/.claude                 │ OK     │ user-owned, writable              │
│ perm: ~/.config/sccs            │ OK     │ user-owned, writable              │
│ perm: npm root -g               │ OK     │ user-owned, writable              │
│ path: npm-prefix-bin            │ OK     │ /opt/homebrew/bin                 │
│ statusline: claude-statusline   │ OK     │ /opt/homebrew/bin/node            │
└─────────────────────────────────┴────────┴───────────────────────────────────┘
```

### Statusline-Check (ab v2.29.0)

`statusline: claude-statusline` inspiziert `~/.claude/settings.json` →
`statusLine.command` und meldet einen der folgenden Zustände:

- **`OK`** — Binary auf PATH oder über absoluten Pfad erreichbar, Skript-Datei
  (falls referenziert) existiert.
- **`STALE`** — Apple-Silicon-Homebrew-Cellar-Pfad
  `/opt/homebrew/Cellar/<pkg>/<version>/bin/<binary>` zeigt auf ein Cellar-
  Verzeichnis das nicht mehr existiert (z.B. nach `brew upgrade node`).
  `sccs doctor install` bietet einen Auto-Fix an, der den Pfad zum stabilen
  Symlink `/opt/homebrew/bin/<binary>` umschreibt; ein Backup
  (`settings.json.bak-YYYYMMDD-HHMMSS`) wird vor der Mutation geschrieben.
- **`MISSING`** — `statusLine`-Key komplett abwesend, obwohl die
  `claude_statusline` Sync-Kategorie aktiviert ist und ein Statusline-Skript
  in `~/.claude/` liegt (Smart-Detect; per Default).
- **`MISSING`** (`missing_binary` / `missing_script`) — Binary oder Skript
  aus dem Command nicht auffindbar; Manual-Block zeigt den Pfad, der Fix
  liegt beim User (Reinstall? Skript-Pfad korrigieren?).
- **`INFO`** (`opaque`) — Command-Form (Pipes, `&&`, Env-Prefix, Command-
  Substitution) wird nicht geparst — keine False-Positives für Power-User-
  Setups.

`required_mode` (Spec-Feld, Default `smart`) steuert, ob ein fehlender
`statusLine`-Key zum FAIL eskaliert:

- `smart` — FAIL nur wenn Sync-Kategorie `claude_statusline` enabled UND
  Statusline-Skript existiert. Schützt Nutzer ohne Statusline vor Nags.
- `always` — fehlender Key → FAIL (für aggressive Default-Setups).
- `never` — fehlender Key → OK (für Minimal-Setups).

### Cascade-Resilience (ab v2.28.0)

`sccs doctor install` modelliert seit v2.28.0 Abhängigkeiten zwischen
Plan-Aktionen, damit ein einziger Wurzelfehler nicht in fünf identische
Folgefehler kaskadiert. Beispiel-Szenario aus einer realen Debian-13-Session:

1. Manual-Block `permission:npm root -g` wird gedruckt (root-owned
   `/usr/local/lib/node_modules/`).
2. Nachfolgende Actions (`npm install -g @playwright/cli`,
   `playwright-cli install-browser chromium/firefox`,
   `sync bundled skill playwright-cli`) listen `perm:npm root -g` als
   `depends_on_components` — sie werden als `⊘ skipped (depends on
   perm:npm root -g)` ausgegeben statt blind ausgeführt zu werden und mit
   ihren eigenen `EACCES`/`Command not found`-Fehlern zu sterben.
3. Plugin-Installs erhalten automatisch ein vorgelagertes
   `claude plugin marketplace update <name>` (deduped pro Marketplace) mit
   `soft_fail=True`. Schlägt der Refresh selbst fehl (Netzwerk-Hickser),
   erscheint er als gelbe **Warning**-Zeile, der eigentliche Install läuft
   trotzdem.
4. Erkennt der `path:npm-prefix-bin`-Detector, dass `<npm config get prefix>/bin`
   nicht auf `$PATH` ist (typisch nach `npm config set prefix ~/.npm-global`
   ohne Shell-Reload), fenced er nur die Folge-Steps die das Tool *nutzen*
   (Browser-Fetch, Bundled-Skill-Sync) — der `npm install -g`-Step selbst
   läuft weiter, weil er das Tool nicht via PATH aufruft.

### Manual-Blöcke statt sudo

Berechtigungs-Probleme werden niemals automatisch gefixt — SCCS würde dafür
sudo benötigen, was per Architektur ausgeschlossen ist. Stattdessen erzeugt
der Doctor einen **Manual-Block** mit den exakten Befehlen zum Kopieren.

Beispiel: Wenn `npm root -g` auf eine root-owned Stelle zeigt
(`/usr/lib/node_modules` auf system-installiertem Node), zeigt der Doctor
zwei Optionen:

- **Option A (empfohlen):** User-lokaler npm-Prefix
  ```bash
  mkdir -p ~/.npm-global/lib ~/.npm-global/bin
  npm config set prefix ~/.npm-global
  # PATH-Snippets für bash/zsh + fish dabei
  ```
- **Option B:** `sudo chown -R UID:GID /usr/lib/node_modules` — schnell,
  aber wird bei jedem `apt install nodejs` zurückgesetzt.

### Doctor-managed Files & Sync-Ausschluss

Dateien, die der Doctor anlegt (z.B. `gsd-*`-Skills/Hooks/Agents von
`@opengsd/gsd-core`, `~/.claude/skills/playwright-cli/`), sind in
`sccs/doctor/managed.py::DEFAULT_MANAGED_PATTERNS` registriert und werden
automatisch von `sccs sync` ausgeschlossen — andernfalls würden zwei
Maschinen, die unabhängig `sccs doctor install` laufen lassen, sich beim
Sync gegenseitig die generierten Dateien überschreiben.

### Verwaiste GSD-Artefakte aufräumen (ab v2.40.0)

GSD ist von `@opengsd/get-shit-done-redux` (npm-deprecated) auf
`@opengsd/gsd-core` umgezogen. Dessen eigenes Cleanup räumt nur `hooks/` und
`commands/` auf — verwaiste `gsd-*`-**Skills** und **Agents** aus dem alten
Paket bleiben liegen. Doctor erkennt sie über das Install-Manifest
(`~/.claude/gsd-file-manifest.json`): jedes on-disk `gsd-*`-Artefakt, das im
**frischen** Manifest fehlt, gilt als verwaist (ebenso das alte
`~/.claude/get-shit-done/`-Verzeichnis nach der Migration).

- `sccs doctor check` meldet Orphans read-only unterhalb der Tabelle.
- `sccs doctor install` / `update` / `optimize` bieten nach dem (Neu-)Install
  eine **Aufräum-Aktion** an: Orphans werden — pro Aktion bestätigungspflichtig
  (Default Nein) — nach `~/.config/sccs/gsd-orphans-backup-<timestamp>/`
  **verschoben** (nicht hart gelöscht, also wiederherstellbar). `--yes`
  überspringt die Bestätigung. Auf einem sauberen Host wird nichts angeboten.

### Konfiguration / Override

Standardmäßig werden die bundled `DEFAULT_CLAUDE_PLUGINS`, `DEFAULT_NPX_TOOLS`
und `DEFAULT_PERMISSION_CHECKS` verwendet. Im `config.yaml` lassen sich diese
Listen individuell überschreiben oder erweitern:

```yaml
doctor:
  min_node_major: 22
  extra_plugins:
    - name: my-custom-plugin
      marketplace_source: my-org/my-plugin
  extra_npx_tools:
    - name: my-cli
      invocation: ["npm", "install", "-g", "my-cli@latest"]
      detect_command: my-cli
  extra_permission_checks:
    - path: ~/my-fragile-cache
      label: my cache
      purpose: my tool writes here
  # v2.31.0 — Hooks aus settings.json nach jedem Pass entfernen (Default: leer)
  disallowed_hooks:
    - some-unwanted-hook.js
  # v2.32.0 — geschützte Hooks NIE entfernen, auch wenn disallowed matcht
  # (protection wins). Default ['gsd-'] bewahrt GSD-Hooks. [] deaktiviert Schutz.
  protected_hooks:
    - "gsd-"
```

**Auto-Update (v2.32.0):** `sccs doctor update` und `optimize` führen sichere
Wartung (Plugin-Install/Update, npx-Refresh inkl. GSD, Marketplace-,
Bundled-Skill- und Browser-Schritte) **ohne Nachfrage** aus. Destruktive Actions
(Foreign-Plugin/MCP-`uninstall`, Hook-Entfernung, Statusline-Rewrite) bleiben
confirm-pflichtig; `--yes` überspringt auch diese.

Querverweise: [cli-reference.md](cli-reference.md), [sync.md](sync.md), [categories.md](categories.md), [../architecture.md](../architecture.md)

---

## English

Doctor is an inspection and repair tool for a fully functional Claude Code
setup. It covers areas that are otherwise tedious to maintain manually:
Node.js minimum version, the `claude` CLI, Claude plugins (via
`claude plugin install/update`), npm helper tools, skills bundled inside
npm packages, browser bundles for Playwright, and filesystem permissions
on the fragile paths.

### Subcommands

```bash
sccs doctor check                # Read-only status table (exit 1 on problems)
sccs doctor check --no-update-check  # Same, but skip the live version check (offline/fast)
sccs doctor install              # Install missing components (confirm per action)
sccs doctor install --yes        # Skip confirms (CI use only)
sccs doctor update               # Update plugins + refresh npx tools
```

### Update check (since v2.42.0)

`sccs doctor check` checks **live** by default whether a newer version of the doctor-managed npx tools and plugins is available, marking them `OUTDATED` (detail e.g. `update available: v1.6.0`) plus an "Updates available — run `sccs doctor update`" hint line. Sources: npx tools via `npm view <npm_package> version` (read-only registry query, only for tools with an `npm_package` set such as `@opengsd/gsd-core`), plugins via the live-refreshed marketplace manifest (`claude plugin marketplace update <name>`). **An available update is informational only** and does NOT change the exit code (exit 1 stays reserved for missing/broken components → CI-friendly). Any network failure degrades silently (no false alarm). `--no-update-check` disables the check → fully offline and fast.

### Optional CLI tools (zoxide, Coreutils) — since v2.43.0

Opt-in: enable them in `~/.config/sccs/config.yaml` via preset names:

```yaml
doctor:
  cli_tools: [zoxide, coreutils]
```

`zoxide` (smart `cd`) is checked on **all** platforms (winget / `brew install zoxide` / install script); **Microsoft Coreutils** (`Microsoft.Coreutils`, the Rust uutils port of `cat`/`grep`/`wc`/`cut`/`xargs`) is **Windows-only** — it gives PowerShell the same UNIX commands as Linux/macOS/WSL. Detection: `which` for "on PATH"; on Windows a `winget list --id <id>` fallback is the authoritative install check (catches the WinGet-Links-not-on-PATH trap). States: `OK` / yellow "installed, not on PATH" (+ a copy-paste PowerShell PATH block below the table) / blue "not installed (optional)". **Informational only — missing = no exit 1.** `doctor install` offers `winget install` / `brew install` (confirm-gated); SCCS never edits PATH/profile itself. Note: zoxide also needs `zoxide init <shell>` in the profile for the `z` command (intentionally not done by the doctor — it only ensures the binary); Coreutils needs no profile init. Shell conflicts (PowerShell aliases `cat`/`sort`/`tee` win over the `.exe` → call `cat.exe`/`sort.exe`): see <https://github.com/microsoft/coreutils#shell-conflicts>.

### What is checked?

| Component | Check (`check`) | Repair (`install` / `update`) |
|---|---|---|
| **Node.js** | installed + minimum major version (≥ 20) | `brew install node` (macOS), `winget install OpenJS.NodeJS` (Windows), manual block for Linux (NodeSource, sudo) |
| **CLI tools** (opt-in: `zoxide`, `coreutils`) | `which` + (Windows) `winget list`; `on_path` / `installed_not_on_path` / `missing` — **informational, never exit 1** | `winget install` / `brew install` (confirm) or a PowerShell PATH block; SCCS never mutates profile/environment |
| **`claude` CLI** | binary on PATH | `npm install -g @anthropic-ai/claude-code` |
| **Claude plugins** | per marketplace via `claude plugin list`; **update available** via marketplace manifest (v2.42.0) | `claude plugin install/update <name>@<marketplace>` with the correct `--scope <user/project/local/managed>` |
| **npx tools** (e.g. `@opengsd/gsd-core`, `playwright-cli`) | binary on PATH **or** state-file marker (for tools that don't drop a binary); **update available** via `npm view` (v2.42.0, only when `npm_package` is set) | `npm install -g <pkg>@latest` resp. `npx -y <pkg> …` |
| **Bundled skills** (e.g. the `playwright-cli` skill) | `SKILL.md` exists in the configured target directory | Copies the skill directory out of the npm package into `~/.claude/skills/<name>/` |
| **Browser bundles** (Playwright Chromium + Firefox) | `<cache>/<bundle>-*` directories present | `playwright-cli install-browser <bundle>` (idempotent) |
| **Filesystem permissions** | `~/.npm`, `~/.claude`, `~/.config/sccs`, `npm root -g` (lib) **and** `<npm prefix>/bin` (v2.32.1) writable | manual block — SCCS never invokes `sudo`; system prefix → user-local prefix only |
| **PATH prefixes** (v2.28.0) | `<npm config get prefix>/bin` is on `$PATH` for the current shell | manual block with bash/zsh/fish snippets — start a new shell and re-run `sccs doctor install` |
| **Statusline** (v2.29.0) | `~/.claude/settings.json` → `statusLine.command` resolves to existing binary + script; Apple-Silicon Homebrew Cellar paths are not stale | auto-fix for `stale_cellar` (rewrite to `/opt/homebrew/bin/<binary>` with backup); manual block for `missing_binary`/`missing_script`/`missing`; `opaque` (pipelines/env-prefix) shown as info but not escalated |

### Sample `sccs doctor check` table

```
                   SCCS Doctor — System & Plugin Status
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Component                       ┃ Status ┃ Detail                            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Node.js                         │ OK     │ v20.20.2                          │
│ Claude CLI                      │ OK     │ /home/user/.local/bin/claude      │
│ plugin: superpowers@…           │ OK     │ installed                         │
│ npx: @opengsd/gsd-core        │ OK     │ installed (last run cached)       │
│ npx: playwright-cli             │ OK     │ /home/user/.local/bin/playwright… │
│ skill: playwright-cli           │ OK     │ ~/.claude/skills/playwright-cli/  │
│ browsers: playwright-cli        │ OK     │ chromium, firefox                 │
│ perm: ~/.npm                    │ OK     │ user-owned, writable              │
│ perm: ~/.claude                 │ OK     │ user-owned, writable              │
│ perm: ~/.config/sccs            │ OK     │ user-owned, writable              │
│ perm: npm root -g               │ OK     │ user-owned, writable              │
│ path: npm-prefix-bin            │ OK     │ /opt/homebrew/bin                 │
│ statusline: claude-statusline   │ OK     │ /opt/homebrew/bin/node            │
└─────────────────────────────────┴────────┴───────────────────────────────────┘
```

### Statusline check (since v2.29.0)

`statusline: claude-statusline` inspects `~/.claude/settings.json` →
`statusLine.command` and reports one of these states:

- **`OK`** — binary on PATH or reachable via absolute path, script file (if
  referenced) exists.
- **`STALE`** — Apple-Silicon Homebrew Cellar path
  `/opt/homebrew/Cellar/<pkg>/<version>/bin/<binary>` points at a Cellar
  directory that no longer exists (e.g. after `brew upgrade node`).
  `sccs doctor install` offers an auto-fix that rewrites the path to the
  stable `/opt/homebrew/bin/<binary>` symlink; a timestamped backup
  (`settings.json.bak-YYYYMMDD-HHMMSS`) is written before the mutation.
- **`MISSING`** — `statusLine` key entirely absent while the
  `claude_statusline` sync category is enabled AND a statusline script
  lives under `~/.claude/` (smart-detect, default).
- **`MISSING`** (`missing_binary` / `missing_script`) — binary or script
  from the command not found; manual block shows the path, the actual fix
  is the user's call (reinstall? correct the script path?).
- **`INFO`** (`opaque`) — command shape (pipelines, `&&`, env-prefix,
  command substitution) is not parsed — no false positives for power-user
  setups.

`required_mode` (spec field, default `smart`) controls whether a missing
`statusLine` key escalates to FAIL:

- `smart` — FAIL only when the `claude_statusline` sync category is enabled
  AND a statusline script exists. Protects users without a statusline from
  being nagged.
- `always` — missing key → FAIL (for aggressive default setups).
- `never` — missing key → OK (for minimal setups).

### Cascade resilience (since v2.28.0)

`sccs doctor install` models dependencies between plan actions so a single
root-cause failure no longer cascades into five identical follow-up errors.
Real-world Debian 13 scenario:

1. The `permission:npm root -g` manual block is printed (root-owned
   `/usr/local/lib/node_modules/`).
2. Subsequent actions (`npm install -g @playwright/cli`,
   `playwright-cli install-browser chromium/firefox`,
   `sync bundled skill playwright-cli`) declare `perm:npm root -g` in their
   `depends_on_components` — they are reported as
   `⊘ skipped (depends on perm:npm root -g)` rather than spawned blindly
   only to fail with their own redundant `EACCES` / `Command not found`.
3. Plugin installs gain an automatic preceding
   `claude plugin marketplace update <name>` step (deduplicated per
   marketplace), marked `soft_fail=True`. If the refresh itself fails (a
   network blip, an offline marketplace), it surfaces as a yellow
   **Warning** row and the install still runs.
4. When `path:npm-prefix-bin` detects that `<npm config get prefix>/bin` is
   not on `$PATH` (typical after `npm config set prefix ~/.npm-global`
   without a shell reload), only the steps that *use* the binary
   (browser-bundle fetch, bundled-skill sync) are fenced — the
   `npm install -g` itself still runs because it does not invoke the tool
   via `$PATH`.

### Manual blocks instead of sudo

Permission issues are never auto-fixed — that would require sudo, which
SCCS refuses to invoke. Instead Doctor emits a **manual block** with the
exact commands to copy.

Example: when `npm root -g` resolves to a root-owned location
(`/usr/lib/node_modules` on system-installed Node), Doctor offers two
options:

- **Option A (recommended):** user-local npm prefix
  ```bash
  mkdir -p ~/.npm-global/lib ~/.npm-global/bin
  npm config set prefix ~/.npm-global
  # PATH snippets for bash/zsh + fish included
  ```
- **Option B:** `sudo chown -R UID:GID /usr/lib/node_modules` — quick,
  but reverts on every `apt install nodejs`.

### Doctor-managed files & sync exclusion

Files that Doctor creates (e.g. `gsd-*` skills/hooks/agents from
`@opengsd/gsd-core`, `~/.claude/skills/playwright-cli/`) are registered in
`sccs/doctor/managed.py::DEFAULT_MANAGED_PATTERNS` and automatically
excluded from `sccs sync`. Otherwise two machines that independently run
`sccs doctor install` would overwrite each other's generated files on
sync.

### Cleaning up orphaned GSD artefacts (since v2.40.0)

GSD moved from `@opengsd/get-shit-done-redux` (npm-deprecated) to
`@opengsd/gsd-core`. Its own cleanup only prunes `hooks/` and `commands/` —
orphaned `gsd-*` **skills** and **agents** from the old package are left
behind. Doctor detects them via the install manifest
(`~/.claude/gsd-file-manifest.json`): any on-disk `gsd-*` artefact missing
from the **fresh** manifest counts as orphaned (as does the old
`~/.claude/get-shit-done/` directory after migration).

- `sccs doctor check` reports orphans read-only below the table.
- `sccs doctor install` / `update` / `optimize` offer a **cleanup action**
  after the (re)install: orphans are **moved** (not hard-deleted, so
  recoverable) to `~/.config/sccs/gsd-orphans-backup-<timestamp>/`, behind a
  per-action confirm prompt (default No). `--yes` skips the prompt. Nothing is
  offered on a clean host.

### Configuration / override

By default the bundled `DEFAULT_CLAUDE_PLUGINS`, `DEFAULT_NPX_TOOLS` and
`DEFAULT_PERMISSION_CHECKS` are used. They can be overridden or extended
in `config.yaml`:

```yaml
doctor:
  min_node_major: 22
  extra_plugins:
    - name: my-custom-plugin
      marketplace_source: my-org/my-plugin
  extra_npx_tools:
    - name: my-cli
      invocation: ["npm", "install", "-g", "my-cli@latest"]
      detect_command: my-cli
  extra_permission_checks:
    - path: ~/my-fragile-cache
      label: my cache
      purpose: my tool writes here
  # v2.31.0 — strip hooks from settings.json after every pass (default: empty)
  disallowed_hooks:
    - some-unwanted-hook.js
  # v2.32.0 — protected hooks are NEVER stripped, even if disallowed matches
  # (protection wins). Default ['gsd-'] preserves GSD hooks. [] disables it.
  protected_hooks:
    - "gsd-"
```

**Auto-update (v2.32.0):** `sccs doctor update` and `optimize` run safe
maintenance (plugin install/update, npx refresh incl. GSD, marketplace,
bundled-skill and browser steps) **without prompting**. Destructive actions
(foreign plugin/MCP `uninstall`, hook removal, statusline rewrite) keep their
confirm gate; `--yes` skips those too.

See also: [cli-reference.md](cli-reference.md), [sync.md](sync.md), [categories.md](categories.md), [../architecture.md](../architecture.md)
