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

### Skill-Pakete (HyperFrames) — ab v2.67.0

Skill-Sammlungen, die über die `skills`-CLI aus einem GitHub-Repository kommen, verwaltet der Doctor wie GSD — aber nur auf Rechnern, auf denen sie eingeschaltet sind:

```yaml
doctor:
  skill_packages: [hyperframes]
```

- **`doctor check`** zeigt eine Zeile `skills: hyperframes`. Welche Skills erwartet werden, steht in der Lock-Datei der `skills`-CLI (`~/.agents/.skill-lock.json`, Einträge mit `source: heygen-com/hyperframes`); ohne Lock gilt die mitgelieferte Liste der 20 Skills. Geprüft wird, ob jeder Skill als echtes Verzeichnis mit `SKILL.md` in `~/.claude/skills/` liegt und ob die `SKILL.md` ladbar ist (gültiges YAML, Beschreibung ≤ 1024 Zeichen). Fehlende oder nur verlinkte Skills zählen als Problem (Exit 1); eine nicht ladbare `SKILL.md` wird gelb gemeldet, ist aber kein Fehler, weil sie nur upstream behoben werden kann. Die Versionsspalte zeigt das Datum der letzten Aktualisierung aus dem Lock — die `skills`-CLI führt keine Versionsnummer, deshalb meldet `check` auch kein „update available“.
- **`doctor install`** installiert ein fehlendes Paket für Claude Code: `npx -y skills add heygen-com/hyperframes --global --agent claude-code --skill '*' --yes --copy`. `--copy` ist Absicht — standardmäßig verlinkt die CLI, und einen Symlink würde der Sync-Scan überspringen und ein Profil nur als Link parken.
- **`doctor update` / `optimize`** führen denselben Befehl immer aus. Er ersetzt jedes Skill-Verzeichnis vollständig und aktualisiert den Lock; lokale Änderungen an den Skills gehen dabei verloren.
- **Sync-Ausschluss:** Alle Skills, die der Lock dem Paket zuschreibt, sind von `sccs sync`, Export und den Agent-Exporten ausgeschlossen — auch ohne Opt-in, denn jeder Rechner holt sie ohnehin von upstream. Die mitgelieferte Namensliste wirkt nur bei eingeschaltetem Paket, damit ein eigener Skill namens `figma` auf einem Rechner ohne HyperFrames weiter synchronisiert.
- **Abschalten:** `sccs profile off hyperframes` parkt die Skills, und der Doctor installiert sie dann nicht erneut (siehe [Profiles](profiles.md)).

### Spiegel-Abgleich (zweiter Mac) — ab v2.68.0

Ein zweiter Mac soll dieselbe Software tragen wie der Live-Rechner. Der Doctor
gleicht vier Bereiche ab: Homebrew (Formulae, Casks, Taps), uv-Tools und
npm-Globals, eigene Git-Checkouts und Fisher-Plugins.

```yaml
doctor:
  mirror:
    source_host: live-mac            # Hostname des Live-Rechners; Domain-Suffix egal
    cleanup: true                    # Überzähliges unter `optimize --strict` anbieten
    repos:
      - url: git@gitlab.example:org/beam.git
        path: ~/gitbase/example/beam
    ignore_brew: []                  # Namen, die der Abgleich nie anfasst
    ignore_uv_tools: []
    ignore_npm: []
```

Der Rechner, dessen Hostname passt, ist die **Quelle**; jeder andere ist
**Spiegel**. Ohne `source_host` zeigt der Doctor keine Spiegelzeilen.

- **Quelle**: `sccs doctor update` schreibt Brewfile (`brew bundle dump`) und
  `~/.config/sccs/inventory.yaml` neu; beide werden über die Kategorien
  `homebrew_bundle` und `sccs_inventory` verteilt. `doctor check` meldet
  `STALE`, wenn die Dateien nicht mehr dem Live-Stand entsprechen. Die Quelle
  wird nie aus dem Inventar verändert. `doctor optimize` spleißt dieselben
  Spiegel-Aktionen wie `update` ein, erfasst also auf der Quelle ebenfalls
  den Bestand neu.
- **Spiegel**: `doctor check` zeigt je Bereich fehlend, überzählig, falsche
  Version (`mirror: brew`, `mirror: uv`, `mirror: npm`, `mirror: repo <name>`,
  `mirror: fisher`). Fehlendes ist rot und Exit 1; Überzähliges ist gelb und
  kein Fehler. `doctor install` installiert Fehlendes (`brew bundle install`,
  `uv tool install name==version`, `npm install -g name@version`, `git clone`,
  `git pull --ff-only`, `fisher install <name>` je Plugin einzeln — nie
  `fisher update`, das ohne Argumente jedes Plugin entfernt, das nicht in
  `fish_plugins` steht, also auf dem Install-Pfad eine Entfernung wäre); uv
  und npm werden auf die Version der Quelle gepinnt, Homebrew kennt keine
  Versionen. Ein Checkout mit lokalen Änderungen (`modified`) oder ein
  unlesbarer Checkout (`not_a_repo`) wird gelb gemeldet, ohne die Prüfung
  scheitern zu lassen, und nie angefasst — beides kann nur ein Mensch lösen.
  Ein Spiegel schreibt das Inventar nie. `check` (mit dem Standard-Update-Check),
  `install`, `update` und `optimize` laufen dafür in jedem konfigurierten
  Checkout ein `git fetch`, mit 30 Sekunden Timeout je Repository.
  `brew bundle install` läuft mit 30 Minuten Timeout, `git clone` mit
  15 Minuten; alle anderen Aktionen nutzen den Doctor-Standard von 5 Minuten.
- **Entfernen**: nur `sccs doctor optimize --strict`, eine Aktion je
  überzähligem Paket, jede einzeln zu bestätigen — `--yes` bestätigt dabei
  auch Entfernungen, wie schon bei fremden Plugins; die eigentliche
  Absicherung ist, dass Entfernungen außerhalb von `--strict` mit
  `cleanup: true` gar nicht erst in den Plan kommen. `npm`, `corepack` und
  `sccs` werden nie entfernt; ein nicht-strikter Lauf auf einem Spiegel mit
  Überzähligem und `cleanup: true` zeigt stattdessen einen einzigen
  Hinweisblock; `cleanup: false` schaltet Entfernungen ganz ab.
  Enthält der Plan eine Aktion, die `sccs` selbst neu installiert
  (`uv tool install sccs==…`), danach `sccs doctor install` erneut ausführen,
  um den Rest des Plans abzuarbeiten.

### CAO-Provider nach einem `cao update` wiederherstellen — ab v2.64.0

Der [CLI Agent Orchestrator](https://github.com/awslabs/cli-agent-orchestrator) (CAO) löst seine Provider über eine **fest verdrahtete if/elif-Kette** auf, die aus einem Enum gespeist wird — kein Erweiterungspunkt. Sein Plugin-System hilft nicht: CAO-Plugins sind reine Beobachter und können keinen Provider registrieren. Einen zusätzlichen Provider anzubinden heißt deshalb, das **installierte Paket** an sechs Stellen zu ergänzen — und jedes `cao update`, `uv tool upgrade` oder Neuinstallieren ersetzt dieses Paket und entfernt alles davon wieder. Das erste Anzeichen ist ein Worker, der nicht mehr startet.

Die Provider-Datei nur zu versionieren transportiert sie, hält CAO aber nicht am Laufen. Genau diese Lücke schließt der Doctor: `sccs doctor check` meldet einen entfernten Provider, `sccs doctor install` spielt ihn wieder ein.

**Seit v2.67.1 ist kein Provider mehr mitgeliefert.** Der einzige, Pi (`pi_cli`), wurde aus der Flotte genommen; `DEFAULT_CAO_PROVIDERS` ist leer, und ohne eigene Deklaration zeigt `doctor check` keine CAO-Zeile. Der Mechanismus bleibt für Provider, die in `doctor.cao_providers` bzw. `doctor.extra_cao_providers` deklariert sind (Name, Binary, `source_dir`, `source_file`, `package_subpath` und die Patch-Stellen mit Anker, Einfügung und Marker):

```
cao provider: <name>   ❌ MISSING   removed by a CAO update — run `sccs doctor install`
cao provider: <name>   ✅ OK        patched into /Users/…/site-packages/cli_agent_orchestrator
```

**Die Quelle liegt bewusst nicht im Paket.** SCCS wird nach PyPI und GitHub veröffentlicht; nur der *Mechanismus* (finden, prüfen, patchen) steht in `sccs/doctor/cao.py`. Die Provider-Datei selbst liegt an einem privaten Ort (`source_dir`) — dieselbe Trennlinie, nach der in v2.60.0 die CAO-Agentenprofile aus diesem Repository verschwunden sind.

**Das Opt-in ist das Zusammentreffen beider, kein Schalter.** Eine Zeile erscheint nur, wenn ein installiertes CAO **und** die Quelle des deklarierten Providers vorhanden sind. Fehlt eines von beiden, erscheint nichts.

**Ein verschobener Ankerpunkt wird gemeldet, nie repariert.** Ändert CAO seinen eigenen Aufbau, meldet der Doctor `CAO layout changed` und druckt, wo die Ankerpunkte in der Provider-Deklaration neu abzuleiten sind. Ein halb angewandter Patch hinterlässt ein Paket, das zwar importiert, aber beim Start scheitert — schlimmer als ein ungepatchtes. Aus demselben Grund läuft die Prüfung **vollständig durch, bevor die erste Datei geschrieben wird**.

Nach dem Einspielen den CAO-Server neu starten, damit der Provider geladen wird.

### Was wird geprüft?

| Komponente | Check (`check`) | Reparatur (`install` / `update`) |
|---|---|---|
| **Node.js** | installiert + Mindestversion (≥ 20) | `brew install node` (macOS), Chocolatey-Block für Windows (`irm …/install.ps1 \| iex` → `choco install nodejs`, elevated, print-only), Manual-Block für Linux (NodeSource, sudo) |
| **CLI-Tools** (opt-in: `zoxide`, `coreutils`) | `which` + (Windows) `winget list`; `on_path` / `installed_not_on_path` / `missing` — **informativ, nie Exit 1** | `winget install`/`brew install` (confirm) bzw. PowerShell-PATH-Block; SCCS mutiert nie Profil/Umgebung |
| **`claude` CLI** | Binary auf PATH | `npm install -g @anthropic-ai/claude-code` |
| **Claude-Plugins** | je nach Marketplace via `claude plugin list`; **Update verfügbar** via Marketplace-Manifest (v2.42.0) | `claude plugin install/update <name>@<marketplace>` mit korrektem `--scope <user/project/local/managed>` |
| **npx-Tools** (z.B. `@opengsd/gsd-core`, `playwright-cli`) | Binary auf PATH **oder** State-File-Marker (für Tools die kein Binary droppen); **Update verfügbar** via `npm view` (v2.42.0, nur bei gesetztem `npm_package`) | `npm install -g <pkg>@latest` bzw. `npx -y <pkg> …` |
| **Bundled Skills** (z.B. `playwright-cli`-Skill) | `SKILL.md` im konfigurierten Target-Verzeichnis existiert | Kopiert das Skill-Verzeichnis aus dem npm-Paket nach `~/.claude/skills/<name>/` |
| **Browser-Bundles** (Playwright Chromium + Firefox) | `<cache>/<bundle>-*` Verzeichnisse vorhanden | `playwright-cli install-browser <bundle>` (idempotent) |
| **Filesystem-Permissions** | `~/.npm`, `~/.claude`, `~/.config/sccs`, `npm root -g` (lib) **und** `<npm prefix>/bin` (v2.32.1) schreibbar | Manual-Block — SCCS ruft niemals `sudo` auf; System-prefix → nur user-local Prefix |
| **PATH-Prefixes** (v2.28.0) | npm-Global-Bin auf `$PATH` der aktuellen Shell — unter Windows = `<npm config get prefix>` (Prefix selbst, kein `\bin`, v2.43.2), sonst `<prefix>/bin` | Manual-Block: **PowerShell** unter Windows (`SetEnvironmentVariable`/`$env:Path`, v2.43.2), sonst bash/zsh/fish — neue Shell starten und `sccs doctor install` erneut ausführen |
| **Statusline** (v2.29.0) | `~/.claude/settings.json` → `statusLine.command` zeigt auf existierende Binary + Skript; Apple-Silicon-Homebrew-Cellar-Pfade nicht stale | Auto-Fix für `stale_cellar` (rewrite zu `/opt/homebrew/bin/<binary>` mit Backup); Manual-Block für `missing_binary`/`missing_script`/`missing`; `opaque` (Pipes/Env-Prefix) wird informativ angezeigt aber nicht eskaliert |

### Plugin-Baseline (v2.54.0)

Die mitgelieferte Baseline (`DEFAULT_CLAUDE_PLUGINS`) enthält als **required** Plugins `skill-creator`, `superpowers`, `frontend-design`, `context-mode` sowie neu `claude-security` (tiefer Vulnerability-Scan des eigenen Codes) und `claude-md-management` (Audit/Pflege von `CLAUDE.md`-Dateien). Die LSP-Plugins und Zweit-Marketplace-Einträge sind `allowlist_only` — sie werden nie installiert oder als fehlend gemeldet, gelten aber nicht als fremd bei `optimize --strict`.

⚠️ **Scope-Falle**: `/plugin install` aus einem Projekt heraus schreibt `<projekt>/.claude/settings.json` — **Projekt-Scope**, der weder auf andere Projekte noch auf andere Rechner mitreist. `doctor install` setzt dagegen ein schlichtes `claude plugin install <name>@<marketplace>` ab, also **User-Scope** — der richtige Ort für eine doctor-verwaltete Baseline. Ein nur projekt-scoped installiertes Plugin erscheint überall sonst als `MISSING`; genau diese Drift soll der Doctor aufdecken.

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
  (falls referenziert) existiert. `~` und `$VAR` werden vor der Prüfung
  expandiert (ab v2.58.2) — Claude Code führt das Kommando über eine Shell
  aus, dort sind beide Formen gültig; vorher meldete jedes mitgelieferte
  Statusline-Preset dauerhaft `binary not found`.
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

### Skill packages (HyperFrames) — since v2.67.0

Skill collections that the `skills` CLI fetches from a GitHub repository are managed like GSD — but only on machines where they are switched on:

```yaml
doctor:
  skill_packages: [hyperframes]
```

- **`doctor check`** shows a `skills: hyperframes` row. The expected skills come from the `skills` CLI lock file (`~/.agents/.skill-lock.json`, entries with `source: heygen-com/hyperframes`); without a lock the bundled list of 20 skills applies. It checks that every skill is a real directory with a `SKILL.md` in `~/.claude/skills/` and that the `SKILL.md` will load (valid YAML, description ≤ 1024 characters). Missing or merely symlinked skills count as a problem (exit 1); an unloadable `SKILL.md` is shown in yellow but is not a failure, because only upstream can fix it. The Version column shows the lock's last update date — the `skills` CLI records no version number, so `check` never reports "update available" either.
- **`doctor install`** installs a missing package for Claude Code: `npx -y skills add heygen-com/hyperframes --global --agent claude-code --skill '*' --yes --copy`. `--copy` is deliberate — the CLI symlinks by default, and a symlink would be skipped by the sync scan and parked as a bare link by a profile.
- **`doctor update` / `optimize`** always run the same command. It replaces every skill directory wholesale and refreshes the lock; local edits to those skills are lost.
- **Sync exclusion:** every skill the lock attributes to the package is excluded from `sccs sync`, export and the agent exports — even without opt-in, since each machine fetches them from upstream anyway. The bundled name list only applies to an enabled package, so a private skill called `figma` keeps syncing on a machine without HyperFrames.
- **Switching off:** `sccs profile off hyperframes` parks the skills, and the doctor then does not reinstall them (see [Profiles](profiles.md)).

### Mirror parity (second Mac) — since v2.68.0

A second Mac is to carry the same software as the live workstation. The doctor
reconciles four areas: Homebrew (formulae, casks, taps), uv tools and npm
globals, own git checkouts, and Fisher plugins.

```yaml
doctor:
  mirror:
    source_host: live-mac            # hostname of the live workstation; domain suffix ignored
    cleanup: true                    # offer removals under `optimize --strict`
    repos:
      - url: git@gitlab.example:org/beam.git
        path: ~/gitbase/example/beam
    ignore_brew: []                  # names the reconciliation never touches
    ignore_uv_tools: []
    ignore_npm: []
```

The host whose hostname matches is the **source**; every other host is a
**mirror**. Without `source_host` the doctor shows no mirror rows.

- **Source**: `sccs doctor update` rewrites the Brewfile (`brew bundle dump`)
  and `~/.config/sccs/inventory.yaml`; both travel through the `homebrew_bundle`
  and `sccs_inventory` categories. `doctor check` reports `STALE` when the files
  no longer match the live state. The source is never modified from the
  inventory. `doctor optimize` splices in the same mirror actions as
  `update`, so on the source it also re-captures the inventory.
- **Mirror**: `doctor check` reports missing, extra and wrong-version per area
  (`mirror: brew`, `mirror: uv`, `mirror: npm`, `mirror: repo <name>`,
  `mirror: fisher`). Missing is red and exit 1; extras are yellow and not a
  failure. `doctor install` installs what is missing (`brew bundle install`,
  `uv tool install name==version`, `npm install -g name@version`, `git clone`,
  `git pull --ff-only`, `fisher install <name>` one plugin at a time — never
  `fisher update`, which with no arguments uninstalls every plugin absent
  from `fish_plugins`, and would therefore be a removal on the install path);
  uv and npm are pinned to the source's version, Homebrew has no versions. A
  checkout with local changes (`modified`) or one that cannot be read
  (`not_a_repo`) is reported in yellow, without failing the check, and never
  touched — both are things only a human can fix. A mirror never writes the
  inventory. `check` (with the default update check), `install`, `update`
  and `optimize` all run `git fetch` in each configured checkout for this,
  bounded to 30 seconds per repository. `brew bundle install` runs with a
  30-minute timeout, `git clone` with 15 minutes; every other action uses
  the doctor's default of 5 minutes.
- **Removal**: only `sccs doctor optimize --strict`, one action per extra,
  each confirmed on its own — `--yes` confirms removals too, exactly as for
  foreign plugins today; the actual protection is that removals never enter
  the plan outside `--strict` with `cleanup: true`. `npm`, `corepack` and
  `sccs` are never removed; a non-strict run on a mirror with extras and
  `cleanup: true` instead prints a single advisory block; `cleanup: false`
  switches removals off entirely. If the plan contains an action that
  reinstalls `sccs` itself (`uv tool install sccs==…`), re-run
  `sccs doctor install` afterwards to work through the rest of the plan.

### Restoring a CAO provider after a `cao update` — since v2.64.0

The [CLI Agent Orchestrator](https://github.com/awslabs/cli-agent-orchestrator) (CAO) resolves providers through a **hard-coded if/elif chain** fed by an enum — not an extension point. Its plugin system does not help: CAO plugins are observers and cannot register a provider. Adding one therefore means editing the **installed package** at six sites — and every `cao update`, `uv tool upgrade` or reinstall replaces that package and removes all of it again. The first sign is a worker that no longer starts.

Versioning the provider file transports it but does not keep CAO working. That is the gap the doctor closes: `sccs doctor check` reports a wiped provider, `sccs doctor install` puts it back.

**Since v2.67.1 no provider is bundled.** The only one, pi (`pi_cli`), was retired from the fleet; `DEFAULT_CAO_PROVIDERS` is empty, and without a declaration of your own `doctor check` shows no CAO row. The mechanism remains for providers declared in `doctor.cao_providers` or `doctor.extra_cao_providers` (name, binary, `source_dir`, `source_file`, `package_subpath` and the patch sites with anchor, insertion and marker):

```
cao provider: <name>   ❌ MISSING   removed by a CAO update — run `sccs doctor install`
cao provider: <name>   ✅ OK        patched into /Users/…/site-packages/cli_agent_orchestrator
```

**The source is deliberately not bundled.** SCCS publishes to PyPI and GitHub; only the *mechanism* (locate, verify, patch) lives in `sccs/doctor/cao.py`. The provider file itself lives in a private location (`source_dir`) — the same line that took the CAO agent profiles out of this repository in v2.60.0.

**The opt-in is the pairing, not a flag.** A row appears only when an installed CAO **and** the declared provider's source are both present. Missing either means no row at all.

**A moved anchor is reported, never repaired.** If CAO changes its own layout, the doctor reports `CAO layout changed` and prints where to re-derive the anchors in the provider declaration. A half-applied patch leaves a package that imports but fails at launch — worse than an unpatched one. For the same reason verification runs to completion **before the first file is written**.

Restart the CAO server afterwards so the provider is loaded.

### PowerShell 7+ check (Windows) — since v2.45.0

On **Windows**, `sccs doctor check` verifies that modern **PowerShell 7+** (`pwsh`, not the legacy Windows PowerShell 5.1) is installed and current — it is the shell that consumes the profile produced by `sccs convert fish-to-pwsh`. The table shows a `PowerShell 7+ (pwsh)` row (`OK` / `OUTDATED` / `MISSING`), and when it's missing or older than 7.x the report prints a copy-paste suggestion below the table:

```text
PowerShell 7+ not found — install (Windows 11):
  winget install --id Microsoft.PowerShell
```

(or `winget upgrade --id Microsoft.PowerShell` when an older version is found). This is **a suggestion only** — SCCS never installs or upgrades PowerShell itself, and a missing/outdated `pwsh` does **not** flip the exit code (informational, CI-friendly). On macOS/Linux the row is hidden entirely (the check is Windows-specific).

### What is checked?

| Component | Check (`check`) | Repair (`install` / `update`) |
|---|---|---|
| **Node.js** | installed + minimum major version (≥ 20) | `brew install node` (macOS), Chocolatey block for Windows (`irm …/install.ps1 \| iex` → `choco install nodejs`, elevated, print-only), manual block for Linux (NodeSource, sudo) |
| **PowerShell 7+** (Windows only, v2.45.0) | `pwsh --version` ≥ 7.x; `OK` / `OUTDATED` / `MISSING` — **informational, never exit 1** | suggestion only: `winget install/upgrade --id Microsoft.PowerShell` (printed, never executed) |
| **CLI tools** (opt-in: `zoxide`, `coreutils`) | `which` + (Windows) `winget list`; `on_path` / `installed_not_on_path` / `missing` — **informational, never exit 1** | `winget install` / `brew install` (confirm) or a PowerShell PATH block; SCCS never mutates profile/environment |
| **`claude` CLI** | binary on PATH | `npm install -g @anthropic-ai/claude-code` |
| **Claude plugins** | per marketplace via `claude plugin list`; **update available** via marketplace manifest (v2.42.0) | `claude plugin install/update <name>@<marketplace>` with the correct `--scope <user/project/local/managed>` |
| **npx tools** (e.g. `@opengsd/gsd-core`, `playwright-cli`) | binary on PATH **or** state-file marker (for tools that don't drop a binary); **update available** via `npm view` (v2.42.0, only when `npm_package` is set) | `npm install -g <pkg>@latest` resp. `npx -y <pkg> …` |
| **Bundled skills** (e.g. the `playwright-cli` skill) | `SKILL.md` exists in the configured target directory | Copies the skill directory out of the npm package into `~/.claude/skills/<name>/` |
| **Browser bundles** (Playwright Chromium + Firefox) | `<cache>/<bundle>-*` directories present | `playwright-cli install-browser <bundle>` (idempotent) |
| **Filesystem permissions** | `~/.npm`, `~/.claude`, `~/.config/sccs`, `npm root -g` (lib) **and** `<npm prefix>/bin` (v2.32.1) writable | manual block — SCCS never invokes `sudo`; system prefix → user-local prefix only |
| **PATH prefixes** (v2.28.0) | npm global bin on `$PATH` for the current shell — on Windows = `<npm config get prefix>` (the prefix itself, no `\bin`, v2.43.2), otherwise `<prefix>/bin` | manual block: **PowerShell** on Windows (`SetEnvironmentVariable`/`$env:Path`, v2.43.2), otherwise bash/zsh/fish — start a new shell and re-run `sccs doctor install` |
| **Statusline** (v2.29.0) | `~/.claude/settings.json` → `statusLine.command` resolves to existing binary + script; Apple-Silicon Homebrew Cellar paths are not stale | auto-fix for `stale_cellar` (rewrite to `/opt/homebrew/bin/<binary>` with backup); manual block for `missing_binary`/`missing_script`/`missing`; `opaque` (pipelines/env-prefix) shown as info but not escalated |

### Plugin baseline (v2.54.0)

The bundled baseline (`DEFAULT_CLAUDE_PLUGINS`) treats `skill-creator`, `superpowers`, `frontend-design`, `context-mode` and — new — `claude-security` (deep vulnerability scanning of your own code) and `claude-md-management` (audits and maintains `CLAUDE.md` files) as **required**. The LSP plugins and second-marketplace entries are `allowlist_only`: never installed, never reported missing, but not counted as foreign by `optimize --strict`.

⚠️ **Scope pitfall**: running `/plugin install` from inside a project writes `<project>/.claude/settings.json` — **project scope**, which travels neither to other projects nor to other machines. `doctor install` instead issues a plain `claude plugin install <name>@<marketplace>`, i.e. **user scope** — the correct home for a doctor-managed baseline. A plugin that exists only at project scope shows up as `MISSING` everywhere else; that drift is exactly what the doctor is meant to surface.

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
  referenced) exists. `~` and `$VAR` are expanded before the check (since
  v2.58.2) — Claude Code runs the command through a shell, where both forms
  are valid; before that every bundled statusline preset was permanently
  reported as `binary not found`.
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
