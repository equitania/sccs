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
sccs doctor install              # Installiert fehlende Komponenten (Confirm pro Action)
sccs doctor install --yes        # Confirms überspringen (nur für CI gedacht)
sccs doctor update               # Plugins + npx-Tools aktualisieren
```

### Was wird geprüft?

| Komponente | Check (`check`) | Reparatur (`install` / `update`) |
|---|---|---|
| **Node.js** | installiert + Mindestversion (≥ 20) | `brew install node` (macOS), `winget install OpenJS.NodeJS` (Windows), Manual-Block für Linux (NodeSource, sudo) |
| **`claude` CLI** | Binary auf PATH | `npm install -g @anthropic-ai/claude-code` |
| **Claude-Plugins** | je nach Marketplace via `claude plugin list` | `claude plugin install/update <name>@<marketplace>` mit korrektem `--scope <user/project/local/managed>` |
| **npx-Tools** (z.B. `get-shit-done-cc`, `playwright-cli`) | Binary auf PATH **oder** State-File-Marker (für Tools die kein Binary droppen) | `npm install -g <pkg>@latest` bzw. `npx -y <pkg> …` |
| **Bundled Skills** (z.B. `playwright-cli`-Skill) | `SKILL.md` im konfigurierten Target-Verzeichnis existiert | Kopiert das Skill-Verzeichnis aus dem npm-Paket nach `~/.claude/skills/<name>/` |
| **Browser-Bundles** (Playwright Chromium + Firefox) | `<cache>/<bundle>-*` Verzeichnisse vorhanden | `playwright-cli install-browser <bundle>` (idempotent) |
| **Filesystem-Permissions** | `~/.npm`, `~/.claude`, `~/.config/sccs`, `npm root -g` user-owned + writable | Manual-Block — SCCS ruft niemals `sudo` auf |
| **PATH-Prefixes** (v2.28.0) | `<npm config get prefix>/bin` ist auf `$PATH` der aktuellen Shell | Manual-Block mit Snippets für bash/zsh/fish — neue Shell starten und `sccs doctor install` erneut ausführen |

### Beispiel-Tabelle (`sccs doctor check`)

```
                   SCCS Doctor — System & Plugin Status
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Component                       ┃ Status ┃ Detail                            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Node.js                         │ OK     │ v20.20.2                          │
│ Claude CLI                      │ OK     │ /home/user/.local/bin/claude      │
│ plugin: superpowers@…           │ OK     │ installed                         │
│ npx: get-shit-done-cc           │ OK     │ installed (last run cached)       │
│ npx: playwright-cli             │ OK     │ /home/user/.local/bin/playwright… │
│ skill: playwright-cli           │ OK     │ ~/.claude/skills/playwright-cli/  │
│ browsers: playwright-cli        │ OK     │ chromium, firefox                 │
│ perm: ~/.npm                    │ OK     │ user-owned, writable              │
│ perm: ~/.claude                 │ OK     │ user-owned, writable              │
│ perm: ~/.config/sccs            │ OK     │ user-owned, writable              │
│ perm: npm root -g               │ OK     │ user-owned, writable              │
└─────────────────────────────────┴────────┴───────────────────────────────────┘
```

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
`get-shit-done-cc`, `~/.claude/skills/playwright-cli/`), sind in
`sccs/doctor/managed.py::DEFAULT_MANAGED_PATTERNS` registriert und werden
automatisch von `sccs sync` ausgeschlossen — andernfalls würden zwei
Maschinen, die unabhängig `sccs doctor install` laufen lassen, sich beim
Sync gegenseitig die generierten Dateien überschreiben.

### Konfiguration / Override

Standardmäßig werden die bundled `DEFAULT_CLAUDE_PLUGINS`, `DEFAULT_NPX_TOOLS`
und `DEFAULT_PERMISSION_CHECKS` verwendet. Im `config.yaml` lassen sich diese
Listen individuell überschreiben oder erweitern:

```yaml
doctor:
  min_node_major: 20
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
```

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
sccs doctor install              # Install missing components (confirm per action)
sccs doctor install --yes        # Skip confirms (CI use only)
sccs doctor update               # Update plugins + refresh npx tools
```

### What is checked?

| Component | Check (`check`) | Repair (`install` / `update`) |
|---|---|---|
| **Node.js** | installed + minimum major version (≥ 20) | `brew install node` (macOS), `winget install OpenJS.NodeJS` (Windows), manual block for Linux (NodeSource, sudo) |
| **`claude` CLI** | binary on PATH | `npm install -g @anthropic-ai/claude-code` |
| **Claude plugins** | per marketplace via `claude plugin list` | `claude plugin install/update <name>@<marketplace>` with the correct `--scope <user/project/local/managed>` |
| **npx tools** (e.g. `get-shit-done-cc`, `playwright-cli`) | binary on PATH **or** state-file marker (for tools that don't drop a binary) | `npm install -g <pkg>@latest` resp. `npx -y <pkg> …` |
| **Bundled skills** (e.g. the `playwright-cli` skill) | `SKILL.md` exists in the configured target directory | Copies the skill directory out of the npm package into `~/.claude/skills/<name>/` |
| **Browser bundles** (Playwright Chromium + Firefox) | `<cache>/<bundle>-*` directories present | `playwright-cli install-browser <bundle>` (idempotent) |
| **Filesystem permissions** | `~/.npm`, `~/.claude`, `~/.config/sccs`, `npm root -g` user-owned + writable | manual block — SCCS never invokes `sudo` |
| **PATH prefixes** (v2.28.0) | `<npm config get prefix>/bin` is on `$PATH` for the current shell | manual block with bash/zsh/fish snippets — start a new shell and re-run `sccs doctor install` |

### Sample `sccs doctor check` table

```
                   SCCS Doctor — System & Plugin Status
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Component                       ┃ Status ┃ Detail                            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Node.js                         │ OK     │ v20.20.2                          │
│ Claude CLI                      │ OK     │ /home/user/.local/bin/claude      │
│ plugin: superpowers@…           │ OK     │ installed                         │
│ npx: get-shit-done-cc           │ OK     │ installed (last run cached)       │
│ npx: playwright-cli             │ OK     │ /home/user/.local/bin/playwright… │
│ skill: playwright-cli           │ OK     │ ~/.claude/skills/playwright-cli/  │
│ browsers: playwright-cli        │ OK     │ chromium, firefox                 │
│ perm: ~/.npm                    │ OK     │ user-owned, writable              │
│ perm: ~/.claude                 │ OK     │ user-owned, writable              │
│ perm: ~/.config/sccs            │ OK     │ user-owned, writable              │
│ perm: npm root -g               │ OK     │ user-owned, writable              │
└─────────────────────────────────┴────────┴───────────────────────────────────┘
```

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
`get-shit-done-cc`, `~/.claude/skills/playwright-cli/`) are registered in
`sccs/doctor/managed.py::DEFAULT_MANAGED_PATTERNS` and automatically
excluded from `sccs sync`. Otherwise two machines that independently run
`sccs doctor install` would overwrite each other's generated files on
sync.

### Configuration / override

By default the bundled `DEFAULT_CLAUDE_PLUGINS`, `DEFAULT_NPX_TOOLS` and
`DEFAULT_PERMISSION_CHECKS` are used. They can be overridden or extended
in `config.yaml`:

```yaml
doctor:
  min_node_major: 20
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
```

See also: [cli-reference.md](cli-reference.md), [sync.md](sync.md), [categories.md](categories.md), [../architecture.md](../architecture.md)
