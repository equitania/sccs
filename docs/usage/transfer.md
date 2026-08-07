# Export/Import (Customer Deployment)

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

Konfigurationen selektiv als ZIP-Archiv exportieren und auf anderen Systemen importieren — ideal für Kundendeployments, bei denen nicht das gesamte Repository übertragen werden soll.

### Export

```bash
# Interaktive Auswahl per Checkbox
sccs export

# Alles exportieren (ohne Auswahl)
sccs export --all

# Eigenen Ausgabepfad angeben
sccs export -o ~/Desktop/kunde-config.zip

# Nur bestimmte Kategorien
sccs export -c claude_skills
sccs export -c claude_skills -c claude_agents

# Kombiniert: Nur Skills, ohne Interaktion
sccs export -c claude_skills --all -o skills.zip

# Ausnahmsweise auch doctor-verwaltete Items mitnehmen
sccs export --include-managed
```

**Doctor-verwaltete Items sind ausgeschlossen** *(ab v2.55.0)*: Alles, was `sccs doctor install`
selbst installiert — die `gsd-*`-Skills/Agents/Hooks aus `@opengsd/gsd-core` sowie `playwright-cli` —
erscheint weder in der Auswahlliste noch im Archiv. Der Zielrechner erzeugt diese Dateien mit seinem
eigenen `sccs doctor install` in der jeweils aktuellen Version; ein eingefrorener Schnappschuss im
ZIP würde nur veralten. Dieselbe Registry (`sccs/doctor/managed.py`) filtert bereits den Sync und die
OpenCode-/Pi-/Codex-Exporte. Erweitern lässt sie sich über `doctor.managed_excludes` in der
`config.yaml`; `--include-managed` schaltet den Filter für einen Lauf komplett ab.

Der Filter greift auf **Item**-Ebene: eine eigene Datei namens `gsd-notizen.md` *innerhalb* eines
selbst geschriebenen Skills bleibt erhalten.

Die interaktive Auswahl zeigt alle verfügbaren Items gruppiert nach Kategorie mit Checkboxen:

```
? Select items to export (42 available):
  ── Claude Code Skills ──
  [✔] code-review
  [✔] git-workflow
  [ ] internal-tool
  ── Claude Agents ──
  [✔] code-reviewer
  ── Fish Shell (macos only) ──
  [✔] config.fish  (macos only)
```

**Vorauswahl pro Detailansicht** *(ab v2.51.0)*: Bevor die Item-Checkbox einer Gruppe mit mehr als
5 Items erscheint, fragt SCCS, ob die Items **alle vorausgewählt** (bisheriges Verhalten) oder
**alle abgewählt** starten sollen. So lassen sich gezielt wenige Items anklicken, ohne jeden Eintrag
einzeln abzuwählen. Gilt gleichermaßen für Export und Import; Gruppen mit ≤5 Items werden weiterhin
automatisch komplett übernommen.

### Import

```bash
# Interaktive Auswahl, was importiert werden soll
sccs import config.zip

# Alles importieren
sccs import config.zip --all

# Vorschau ohne Schreiben
sccs import config.zip --dry-run

# Bestehende Dateien überschreiben (mit automatischem Backup)
sccs import config.zip --overwrite

# Ohne Backup überschreiben
sccs import config.zip --overwrite --no-backup

# Ausnahmsweise auch doctor-verwaltete Items schreiben
sccs import config.zip --include-managed
```

**Der Import filtert symmetrisch** *(ab v2.55.0)*: Archive, die vor v2.55.0 erzeugt wurden, enthalten
die `gsd-*`-Items und `playwright-cli` noch. Sie werden weder zur Auswahl angeboten noch geschrieben —
sonst läge ein eingefrorener Schnappschuss neben dem, was `sccs doctor install` lokal pflegt, und der
Sync ignoriert genau diese Pfade, sodass die Drift nie wieder auffällt. Die Archiv-Zusammenfassung
meldet weiterhin den **rohen** Inhalt des ZIPs (ehrlich darüber, was drin ist); die Zahl der
übersprungenen Items steht separat darunter:

```
  Categories: 16
  Items: 327

Skipping 129 doctor-managed items (gsd-*, playwright-cli) — 'sccs doctor install' maintains those locally
  Use --include-managed to import them anyway
```

### Einsatzbereiche

| Szenario | Empfohlener Befehl |
|----------|-------------------|
| Skills an Kunden liefern | `sccs export -c claude_skills -o kunde.zip` |
| Fish-Config für Linux-Server | `sccs export -c fish_config -c fish_functions --all` |
| Komplett-Setup für neues System | `sccs export --all -o full-setup.zip` |
| Vorschau vor dem Import | `sccs import setup.zip --dry-run` |
| Sicheres Update bestehender Configs | `sccs import setup.zip --overwrite` |

Querverweise: [sync.md](sync.md), [categories.md](categories.md), [memory-bridge.md](memory-bridge.md), [cli-reference.md](cli-reference.md)

---

## English

Selectively export configurations as ZIP archives and import them on other systems — ideal for customer deployments where the full repository should not be transferred.

### Export

```bash
# Interactive checkbox selection
sccs export

# Export everything (no prompt)
sccs export --all

# Custom output path
sccs export -o ~/Desktop/customer-config.zip

# Specific categories only
sccs export -c claude_skills
sccs export -c claude_skills -c claude_agents

# Combined: only skills, non-interactive
sccs export -c claude_skills --all -o skills.zip

# Exceptionally include doctor-managed items too
sccs export --include-managed
```

**Doctor-managed items are excluded** *(since v2.55.0)*: anything `sccs doctor install` installs
itself — the `gsd-*` skills/agents/hooks from `@opengsd/gsd-core` plus `playwright-cli` — appears
neither in the selection list nor in the archive. The target machine reproduces those files with its
own `sccs doctor install` at the then-current version; a frozen snapshot inside the ZIP would only
go stale. The same registry (`sccs/doctor/managed.py`) already filters sync and the OpenCode/Pi/Codex
exports. Extend it via `doctor.managed_excludes` in `config.yaml`; `--include-managed` disables the
filter for a single run.

The filter works at **item** level: your own file named `gsd-notes.md` *inside* a skill you wrote
stays in the archive.

The interactive selection shows all available items grouped by category with checkboxes:

```
? Select items to export (42 available):
  ── Claude Code Skills ──
  [✔] code-review
  [✔] git-workflow
  [ ] internal-tool
  ── Claude Agents ──
  [✔] code-reviewer
  ── Fish Shell (macos only) ──
  [✔] config.fish  (macos only)
```

**Per-detail-view pre-selection** *(since v2.51.0)*: before the item checkbox of any group with more
than 5 items appears, SCCS asks whether items start **all pre-selected** (legacy behaviour) or
**all deselected**, so you can cherry-pick a few items without deselecting every entry. Applies to
both export and import; groups with ≤5 items are still auto-included in full.

### Import

```bash
# Interactive selection of what to import
sccs import config.zip

# Import everything
sccs import config.zip --all

# Preview without writing
sccs import config.zip --dry-run

# Overwrite existing files (with automatic backup)
sccs import config.zip --overwrite

# Overwrite without backup
sccs import config.zip --overwrite --no-backup

# Exceptionally write doctor-managed items too
sccs import config.zip --include-managed
```

**Import filters symmetrically** *(since v2.55.0)*: archives created before v2.55.0 still carry the
`gsd-*` items and `playwright-cli`. They are neither offered for selection nor written — otherwise a
frozen snapshot would sit next to whatever `sccs doctor install` maintains locally, and since sync
ignores exactly those paths the drift would never surface again. The archive summary still reports the
**raw** ZIP contents (honest about what is inside); the number of skipped items is printed separately
below it:

```
  Categories: 16
  Items: 327

Skipping 129 doctor-managed items (gsd-*, playwright-cli) — 'sccs doctor install' maintains those locally
  Use --include-managed to import them anyway
```

### Use Cases

| Scenario | Recommended Command |
|----------|-------------------|
| Deliver skills to customer | `sccs export -c claude_skills -o customer.zip` |
| Fish config for Linux server | `sccs export -c fish_config -c fish_functions --all` |
| Full setup for new system | `sccs export --all -o full-setup.zip` |
| Preview before import | `sccs import setup.zip --dry-run` |
| Safe update of existing configs | `sccs import setup.zip --overwrite` |

See also: [sync.md](sync.md), [categories.md](categories.md), [memory-bridge.md](memory-bridge.md), [cli-reference.md](cli-reference.md)
