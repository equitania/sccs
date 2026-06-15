# CLI-Referenz / CLI Reference

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

Vollständige Referenz aller `sccs` Subcommands. Detaillierte Workflows
finden sich themenspezifisch in den anderen Usage-Docs:

- Sync-Workflow → [sync.md](sync.md)
- Doctor → [doctor.md](doctor.md)
- Export/Import → [transfer.md](transfer.md)
- Memory Bridge → [memory-bridge.md](memory-bridge.md)
- Kategorien → [categories.md](categories.md)
- OpenCode-Integration → [opencode.md](opencode.md)

```bash
# Synchronisierung
sccs sync                        # Alle aktivierten Kategorien
sccs sync -c skills              # Bestimmte Kategorie
sccs sync -n                     # Vorschau (Dry-Run)
sccs sync -i                     # Interaktive Konfliktauflösung
sccs sync --force local          # Lokale Version erzwingen
sccs sync --force repo           # Repo-Version erzwingen
sccs sync --force newer          # Neuere Datei erzwingen (mtime)
sccs sync --commit --push        # Mit Git-Commit und Push
sccs sync --pull                 # Vorher Remote-Änderungen ziehen

# Status und Diff
sccs status                      # Sync-Status aller Kategorien
sccs diff                        # Alle Unterschiede anzeigen
sccs diff -c skills              # Diffs einer Kategorie
sccs log                         # Sync-Verlauf

# Konfiguration
sccs config show                 # Konfiguration anzeigen
sccs config init                 # Neue Konfiguration erstellen
sccs config edit                 # Im Editor öffnen
sccs config validate             # Konfiguration prüfen

# Export/Import
sccs export                      # Interaktive Auswahl + ZIP erstellen
sccs export --all -o config.zip  # Alles exportieren
sccs export -c claude_skills     # Nur bestimmte Kategorie
sccs import config.zip           # Interaktive Auswahl + importieren
sccs import config.zip --dry-run # Vorschau ohne Schreiben
sccs import config.zip --all     # Alles importieren

# Kategorien
sccs categories list             # Aktivierte Kategorien
sccs categories list --all       # Alle (inkl. deaktivierte)
sccs categories enable fish      # Kategorie aktivieren
sccs categories disable fish     # Kategorie deaktivieren

# Doctor (System & Plugin Health)
sccs doctor check                # Read-only Status-Tabelle (Exit 1 bei Problemen)
sccs doctor install              # Installiert fehlende Komponenten (Confirm pro Action)
sccs doctor install --yes        # Skip Confirms (CI use only)
sccs doctor update               # Plugins + npx-Tools aktualisieren

# Integrationen (Antigravity, Claude Desktop, OpenCode)
sccs integrations status                       # Integrations-Report
sccs integrations opencode status              # OpenCode: Installation + offene Konvertierungen
sccs integrations opencode map-models          # CC-Modelle den OpenCode-Modellen zuweisen
sccs integrations opencode export-agents -n    # Agents konvertieren (Vorschau)
sccs integrations opencode export-commands -n  # Commands konvertieren (Vorschau)
sccs integrations opencode merge-mcp -n        # MCP-Server in opencode.json mergen (Vorschau)
```

---

## English

Full reference for every `sccs` subcommand. Topic-specific workflows live
in the other usage docs:

- Sync workflow → [sync.md](sync.md)
- Doctor → [doctor.md](doctor.md)
- Export/Import → [transfer.md](transfer.md)
- Memory Bridge → [memory-bridge.md](memory-bridge.md)
- Categories → [categories.md](categories.md)
- OpenCode integration → [opencode.md](opencode.md)

```bash
# Synchronization
sccs sync                        # All enabled categories
sccs sync -c skills              # Specific category
sccs sync -n                     # Preview (dry-run)
sccs sync -i                     # Interactive conflict resolution
sccs sync --force local          # Force local version
sccs sync --force repo           # Force repo version
sccs sync --force newer          # Force newer file (by mtime)
sccs sync --commit --push        # With git commit and push
sccs sync --pull                 # Pull remote changes first

# Status and diff
sccs status                      # Sync status of all categories
sccs diff                        # Show all differences
sccs diff -c skills              # Diffs for a category
sccs log                         # Sync history

# Configuration
sccs config show                 # Show configuration
sccs config init                 # Create new configuration
sccs config edit                 # Open in editor
sccs config validate             # Validate configuration

# Export/Import
sccs export                      # Interactive selection + create ZIP
sccs export --all -o config.zip  # Export everything
sccs export -c claude_skills     # Specific category only
sccs import config.zip           # Interactive selection + import
sccs import config.zip --dry-run # Preview without writing
sccs import config.zip --all     # Import everything

# Categories
sccs categories list             # List enabled categories
sccs categories list --all       # All (incl. disabled)
sccs categories enable fish      # Enable category
sccs categories disable fish     # Disable category

# Doctor (system & plugin health)
sccs doctor check                # Read-only status table (exit 1 on problems)
sccs doctor install              # Install missing components (confirm per action)
sccs doctor install --yes        # Skip confirms (CI use only)
sccs doctor update               # Update plugins + refresh npx tools

# Integrations (Antigravity, Claude Desktop, OpenCode)
sccs integrations status                       # Integration report
sccs integrations opencode status              # OpenCode: install + outstanding conversions
sccs integrations opencode map-models          # Assign CC models to OpenCode models
sccs integrations opencode export-agents -n    # Convert agents (preview)
sccs integrations opencode export-commands -n  # Convert commands (preview)
sccs integrations opencode merge-mcp -n        # Merge MCP servers into opencode.json (preview)
```
