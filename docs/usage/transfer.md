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
```

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
```

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
