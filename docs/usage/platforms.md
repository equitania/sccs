# Plattformen / Platforms — Windows & PowerShell

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

Querverweise: [categories.md](categories.md), [sync.md](sync.md)

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

See also: [categories.md](categories.md), [sync.md](sync.md)
