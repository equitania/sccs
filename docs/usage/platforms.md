# Plattformen / Platforms — Windows, PowerShell & Zsh

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

### Windows / PowerShell-Support

Auf Windows 11 mit PowerShell 7+ läuft SCCS direkt:

```powershell
# Installation
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install sccs

# Konfiguration anlegen
sccs config init

# PowerShell-Profile-Kategorie aktivieren und syncen
sccs categories enable powershell_profile
sccs sync --category powershell_profile
```

Fish-Kategorien (`fish_config`, `fish_functions`) sind durch `platforms: ["macos", "linux"]` automatisch ausgeschlossen — kein Fehler, kein Sync-Versuch.

### Windows-CLI-Tools im Doctor (zoxide, Coreutils) — ab v2.43.0

`sccs doctor` kann optional prüfen, ob **zoxide** und **Microsoft Coreutils** installiert sind, und bei der Installation via `winget` helfen. Aktivierung in `~/.config/sccs/config.yaml`:

```yaml
doctor:
  cli_tools: [zoxide, coreutils]
```

Coreutils (`Microsoft.Coreutils`) bringt PowerShell die nativen Unix-Textwerkzeuge (`cat`/`grep`/`wc`/`cut`/`xargs`); `winget list` erkennt auch eine Installation, die noch nicht auf dem PATH liegt (WinGet-Links-Falle), und `doctor check` zeigt dann einen kopierbaren PowerShell-PATH-Block. Details im [doctor-Guide](doctor.md). Hinweis: zoxide braucht zusätzlich `zoxide init powershell` im Profil für den `z`-Befehl.

### Fish → PowerShell Konvertierung

Auf macOS/Linux generiert ein einmaliger CLI-Aufruf ein modulares PowerShell-Profil aus deiner Fish-Konfiguration:

```bash
# Vorschau
sccs convert fish-to-pwsh --dry-run

# Konvertieren ins Sync-Repo
sccs convert fish-to-pwsh

# Ergebnis prüfen
ls ~/gitbase/sccs-sync/.config/powershell/
# Microsoft.PowerShell_profile.ps1
# conf.d/  functions/  README.md
```

Was wird konvertiert:

| Fish | PowerShell | Hinweis |
|---|---|---|
| `alias name=value` | `Set-Alias -Name name -Value value -Scope Global -Force` | Wert ohne Whitespace |
| `alias name='cmd args'` | `function name { cmd args @args }` | Mit Argumenten — `@args`-Splatting |
| `set -gx VAR value` | `$env:VAR = "value"` | `$HOME` bleibt `$HOME` |
| `fish_add_path /opt/bin` | duplikatsicheres `$env:PATH`-Prepend | Nutzt `[IO.Path]::PathSeparator` |
| `abbr -a name expansion` | `Set-Alias` oder `function` | Kürzeste Semantik |
| `*.macos.fish`, `*.linux.fish` | übersprungen | Plattform-spezifisch |
| Fish-Funktionen (`function … end`) | Stub mit Original als Kommentar | Manuell portieren |

Nach Edits in `~/.config/fish/` einfach `sccs convert fish-to-pwsh --force` erneut aufrufen — bestehende Zieldateien werden mit `.bak` gesichert.

#### Komfort-Shortcuts (`95-conveniences.ps1`) — ab v2.45.0

Zusätzlich legt der Converter `conf.d/95-conveniences.ps1` mit den gewohnten Fish-Shortcuts an — PowerShell-nativ, damit sie unter Windows direkt funktionieren:

| Shortcut | Wirkung |
|---|---|
| `ll` / `la` / `l` | Listing (bevorzugt `eza`/`lsd`, sonst `Get-ChildItem`) |
| `..` / `...` / `....` | eine/zwei/drei Ebenen hoch (statt `cd ..`) |
| `which` / `touch` / `mkcd` | Unix-Helfer (Pfad zeigen / Datei anlegen / Verzeichnis anlegen + hinein) |

Die Datei lädt **zuletzt** in `conf.d/` und gewinnt damit bewusst über die automatisch konvertierten `ls`/`ll` (die oft GNU/BSD-Flags tragen, die PowerShell nicht versteht). Bearbeiten oder löschen erlaubt; mit `sccs convert fish-to-pwsh --no-conveniences` komplett überspringen.

### Fish → Zsh Konvertierung — ab v2.52.0

Für Rechner **ohne installierte fish-Shell** (z.B. Standard-zsh auf macOS) generiert `sccs convert fish-to-zsh` ein natives zsh-Profil aus der Fish-Konfiguration — Aliase, Env-Vars **und Funktionen** stehen dann direkt in zsh bereit:

```bash
# Vorschau
sccs convert fish-to-zsh --dry-run

# Konvertieren ins Sync-Repo
sccs convert fish-to-zsh

# Ergebnis prüfen
ls ~/gitbase/sccs-sync/.config/zsh/
# zshrc  conf.d/  functions/  README.md
```

**Aktivierung** (einmalig — SCCS editiert `~/.zshrc` nie selbst, daher als fertiger Copy-Paste-Einzeiler; idempotent, mehrfaches Ausführen erzeugt keine Duplikate):

```zsh
grep -qxF 'source ~/.config/zsh/zshrc' ~/.zshrc 2>/dev/null || echo 'source ~/.config/zsh/zshrc' >> ~/.zshrc
```

**Verteilung** auf andere Maschinen über die neue (per Default deaktivierte) Kategorie:

```bash
sccs categories enable zsh_config
sccs sync --category zsh_config
```

Was wird konvertiert:

| Fish | Zsh | Hinweis |
|---|---|---|
| `alias name=value` / `alias name 'value'` | `alias name='value'` | zsh-Aliase tragen Argumente nativ |
| `set -gx VAR value` | `export VAR="value"` | unquoted `~` wird zu `$HOME` |
| `set -gx VAR 'value'` | `export VAR='value'` | einfach gequotet = literal, siehe unten |
| `fish_add_path /opt/bin` | duplikatsicheres `PATH`-Prepend | `[[ ":$PATH:" != … ]]`-Guard |
| `abbr -a name expansion` | `alias name='expansion'` | |
| `function … end` | echte zsh-Funktion `name() { … }` | Best-Effort inkl. `-d`/`--argument-names` |
| `if/else if/for/while/switch/begin` | `if/elif/for/while/case/{ }` | auch in conf.d-Dateien |
| `set -l/-g/-e/-q` | `local`/`typeset -g`/`unset`/`[[ -v ]]` | |
| `command -q X` | `command -v X >/dev/null 2>&1` | ebenso `type -q`, `functions -q` |
| `$argv`, `$argv[1]`, `(count $argv)`, `$status` | `"$@"`, `$1`, `$#`, `$?` | |
| `(cmd)` | `$(cmd)` | Command-Substitution |
| `*.macos.fish`, `*.linux.fish` | **konvertiert** mit `uname`-Guard | Abweichung zu fish-to-pwsh! |
| `string`, `math`, `argparse`, `set -U`, `psub` | `# fish-untranslated:`-Kommentar | Manuell portieren |

**Wichtigste Abweichung zu fish-to-pwsh**: Plattform-Dateien werden nicht übersprungen, sondern in einen `[[ "$(uname)" == "Darwin" ]]`- bzw. `"Linux"`-Guard gewickelt — ein generiertes Profil funktioniert damit auf beiden Plattformen. Außerdem werden Funktionen **übersetzt statt gestubbt**; nur zu fish-spezifische Dateien (>30 % unübersetzbare Zeilen, Event-Handler, unbalancierte Blöcke) fallen auf kommentierte Stubs zurück — es wird nie syntaktisch kaputtes zsh erzeugt (`zsh -n`-Gate in der Test-Suite).

`conf.d/95-conveniences.zsh` ergänzt bewusst minimal nur, was zsh fehlt (`..`/`...`/`....`, `mkcd`); Opt-out via `--no-conveniences`. Secret-Dateien (`*secret*`, `*token*`, …) und `*.local.fish` werden weiterhin übersprungen.

**Literale Werte bleiben literal** *(ab v2.56.0)*: In fish unterdrücken einfache Quotes jede Expansion, und Backticks kennt fish überhaupt nicht als Command-Substitution. Beides wird jetzt respektiert — `set -gx B 'text (whoami)'` wird zu `export B='text (whoami)'` (nicht `"$(whoami)"`), und ein Backtick wird in doppelt gequoteten Werten escaped. Die gewollten Umwandlungen bleiben unangetastet: ein **unquoted** `(cmd)` wird weiter zu `$(cmd)`, und `$var` expandiert weiter. Der PowerShell-Konverter verhält sich analog (dort `$(…)` und Backtick). Ohne diese Unterscheidung konnte eine importierte fremde `config.fish` inerten Text in ausführbaren Code verwandeln — das `zsh -n`-Gate erkennt das nicht, weil die Zeile syntaktisch korrekt ist.

Querverweise: [categories.md](categories.md), [sync.md](sync.md), [doctor.md](doctor.md)

---

## English

### Windows / PowerShell Support

SCCS runs natively on Windows 11 with PowerShell 7+:

```powershell
# Install
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install sccs

# Initialize config
sccs config init

# Enable and sync the PowerShell profile category
sccs categories enable powershell_profile
sccs sync --category powershell_profile
```

Fish categories (`fish_config`, `fish_functions`) carry `platforms: ["macos", "linux"]` and are skipped automatically on Windows — no error, no sync attempt.

### Windows CLI tools in the doctor (zoxide, Coreutils) — since v2.43.0

`sccs doctor` can optionally check whether **zoxide** and **Microsoft Coreutils** are installed and help install them via `winget`. Enable it in `~/.config/sccs/config.yaml`:

```yaml
doctor:
  cli_tools: [zoxide, coreutils]
```

Coreutils (`Microsoft.Coreutils`) gives PowerShell the native UNIX text tools (`cat`/`grep`/`wc`/`cut`/`xargs`); `winget list` also detects an install that hasn't made it onto PATH yet (the WinGet-Links trap), and `doctor check` then prints a copy-paste PowerShell PATH block. See the [doctor guide](doctor.md). Note: zoxide additionally needs `zoxide init powershell` in the profile for the `z` command.

### Fish → PowerShell Conversion

On macOS/Linux a one-shot CLI command generates a modular PowerShell profile from your Fish configuration:

```bash
# Preview
sccs convert fish-to-pwsh --dry-run

# Convert into the sync repo
sccs convert fish-to-pwsh

# Inspect
ls ~/gitbase/sccs-sync/.config/powershell/
# Microsoft.PowerShell_profile.ps1
# conf.d/  functions/  README.md
```

Conversion rules:

| Fish | PowerShell | Note |
|---|---|---|
| `alias name=value` | `Set-Alias -Name name -Value value -Scope Global -Force` | Single-word value |
| `alias name='cmd args'` | `function name { cmd args @args }` | With args — uses `@args` splatting |
| `set -gx VAR value` | `$env:VAR = "value"` | `$HOME` stays `$HOME` |
| `fish_add_path /opt/bin` | duplicate-aware `$env:PATH` prepend | Uses `[IO.Path]::PathSeparator` |
| `abbr -a name expansion` | `Set-Alias` or `function` | Closest semantic fit |
| `*.macos.fish`, `*.linux.fish` | skipped | Platform-specific |
| Fish functions (`function … end`) | Stub with original as comment | Port by hand |

After editing Fish files, just rerun `sccs convert fish-to-pwsh --force` — existing target files are backed up as `.bak`.

#### Comfort shortcuts (`95-conveniences.ps1`) — since v2.45.0

The converter also writes `conf.d/95-conveniences.ps1` with the Fish-style shortcuts you're used to — all PowerShell-native so they work on Windows out of the box:

| Shortcut | Effect |
|---|---|
| `ll` / `la` / `l` | Listing (prefers `eza`/`lsd`, else `Get-ChildItem`) |
| `..` / `...` / `....` | Go up one/two/three levels (instead of `cd ..`) |
| `which` / `touch` / `mkcd` | Unix helpers (resolve path / create file / make dir + cd) |

This file loads **last** in `conf.d/` and intentionally wins over the auto-converted `ls`/`ll` (which often carry GNU/BSD flags PowerShell rejects). Edit or delete it, or pass `sccs convert fish-to-pwsh --no-conveniences` to skip it entirely.

### Fish → Zsh Conversion — since v2.52.0

For machines **without fish installed** (e.g. stock macOS zsh), `sccs convert fish-to-zsh` generates a native zsh profile from your Fish configuration — aliases, env vars **and functions** become directly available in zsh:

```bash
# Preview
sccs convert fish-to-zsh --dry-run

# Convert into the sync repo
sccs convert fish-to-zsh

# Inspect
ls ~/gitbase/sccs-sync/.config/zsh/
# zshrc  conf.d/  functions/  README.md
```

**Activation** (one-time — SCCS never edits `~/.zshrc` itself, so it ships as a ready copy-paste one-liner; idempotent, re-running never duplicates the line):

```zsh
grep -qxF 'source ~/.config/zsh/zshrc' ~/.zshrc 2>/dev/null || echo 'source ~/.config/zsh/zshrc' >> ~/.zshrc
```

**Distribution** to other machines via the new (disabled-by-default) category:

```bash
sccs categories enable zsh_config
sccs sync --category zsh_config
```

Conversion rules:

| Fish | Zsh | Note |
|---|---|---|
| `alias name=value` / `alias name 'value'` | `alias name='value'` | zsh aliases carry arguments natively |
| `set -gx VAR value` | `export VAR="value"` | unquoted `~` becomes `$HOME` |
| `set -gx VAR 'value'` | `export VAR='value'` | single-quoted = literal, see below |
| `fish_add_path /opt/bin` | duplicate-aware `PATH` prepend | `[[ ":$PATH:" != … ]]` guard |
| `abbr -a name expansion` | `alias name='expansion'` | |
| `function … end` | real zsh function `name() { … }` | Best-effort incl. `-d`/`--argument-names` |
| `if/else if/for/while/switch/begin` | `if/elif/for/while/case/{ }` | Also inside conf.d files |
| `set -l/-g/-e/-q` | `local`/`typeset -g`/`unset`/`[[ -v ]]` | |
| `command -q X` | `command -v X >/dev/null 2>&1` | Same for `type -q`, `functions -q` |
| `$argv`, `$argv[1]`, `(count $argv)`, `$status` | `"$@"`, `$1`, `$#`, `$?` | |
| `(cmd)` | `$(cmd)` | Command substitution |
| `*.macos.fish`, `*.linux.fish` | **converted** with a `uname` guard | Divergence from fish-to-pwsh! |
| `string`, `math`, `argparse`, `set -U`, `psub` | `# fish-untranslated:` comment | Port by hand |

**Key divergence from fish-to-pwsh**: platform files are not skipped but wrapped in a `[[ "$(uname)" == "Darwin" ]]` / `"Linux"` guard, so one generated profile works on both platforms. Functions are **translated instead of stubbed**; only overly fish-specific files (>30 % untranslatable lines, event handlers, unbalanced blocks) fall back to commented stubs — the converter never emits syntactically broken zsh (a `zsh -n` gate is part of the test suite).

`conf.d/95-conveniences.zsh` deliberately adds only what zsh genuinely lacks (`..`/`...`/`....`, `mkcd`); opt out via `--no-conveniences`. Secret-like files (`*secret*`, `*token*`, …) and `*.local.fish` remain excluded.

**Literal values stay literal** *(since v2.56.0)*: fish single quotes suppress every expansion, and fish has no backtick command substitution whatsoever. Both are now honoured — `set -gx B 'text (whoami)'` becomes `export B='text (whoami)'` (not `"$(whoami)"`), and backticks are escaped inside double-quoted values. The intended conversions are untouched: an **unquoted** `(cmd)` still becomes `$(cmd)`, and `$var` still expands. The PowerShell converter behaves analogously (there: `$(…)` and the backtick). Without that distinction an imported foreign `config.fish` could turn inert text into executable code — the `zsh -n` gate cannot catch it, because the generated line is syntactically valid.

See also: [categories.md](categories.md), [sync.md](sync.md), [doctor.md](doctor.md)
