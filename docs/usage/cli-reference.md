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
- Deployment (Kundenhosts, mit Rückweg) → [deploy.md](deploy.md)
- Memory Bridge → [memory-bridge.md](memory-bridge.md)
- Kategorien → [categories.md](categories.md)
- Profile & Statusline → [profiles.md](profiles.md)
- OpenCode-Integration → [opencode.md](opencode.md)
- Kapazitätssonde → [capacity.md](capacity.md)

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
sccs export --include-managed    # Auch doctor-verwaltete Items (gsd-*, playwright-cli)
sccs import config.zip           # Interaktive Auswahl + importieren
sccs import config.zip --dry-run # Vorschau ohne Schreiben
sccs import config.zip --all     # Alles importieren
sccs import config.zip --include-managed  # Auch doctor-verwaltete Items schreiben
# Für einen fremden Host (Kunde) meist das passendere Werkzeug: sccs deploy (siehe unten)

# Deployment (benanntes Profil MIT Rückweg für einen fremden Host — anders als Export/Import oben, siehe deploy.md)
sccs deploy list                        # Profile auflisten
sccs deploy show odoo-server            # Zeigen, was ein Profil bündeln würde
sccs deploy show odoo-server --platform linux  # Gegen andere Zielplattform prüfen
sccs deploy export odoo-server -o kunde.zip     # Bundle aus einem Profil bauen
sccs deploy install kunde.zip           # Bundle installieren + Quittung schreiben
sccs deploy install kunde.zip -n        # Vorschau ohne zu schreiben
sccs deploy status                      # Zeigen, was SCCS auf diesem Host installiert hat
sccs deploy revoke                      # Entfernen, was SCCS installiert hat, + verifizieren
sccs deploy revoke --profile fastreport # Falls mehrere Profile auf dem Host koexistieren

# Kategorien
sccs categories list             # Aktivierte Kategorien
sccs categories list --all       # Alle (inkl. deaktivierte)
sccs categories enable fish      # Kategorie aktivieren
sccs categories disable fish     # Kategorie deaktivieren

# Doctor (System & Plugin Health)
sccs doctor check                # Read-only Status-Tabelle (Exit 1 bei Problemen)
sccs doctor check --no-update-check  # Ohne Live-Versionsprüfung (offline/schnell)
sccs doctor install              # Installiert fehlende Komponenten (Confirm pro Action)
sccs doctor install --yes        # Skip Confirms (CI use only)
sccs doctor update               # Plugins + npx-Tools aktualisieren

# Profile (LOKALE Artefakt-Gruppen parken, um den System-Prompt zu verkleinern — ungleich den Deployment-Profilen oben, siehe profiles.md)
sccs profile list                # Profile + Zustand anzeigen
sccs profile off gsd             # Gruppe parken (verschoben, nicht gelöscht)
sccs profile on gsd              # Geparkte Gruppe zurückholen
sccs profile status gsd          # Detail zu einem Profil (ohne Name: alle)

# Statusline (Presets für die Statusleiste, siehe profiles.md)
sccs statusline list             # Verfügbare Presets anzeigen
sccs statusline use claude-code-statusline      # settings.json auf ein Preset umstellen
sccs statusline install claude-code-statusline  # Preset herunterladen + installieren
sccs statusline show             # Aktuellen statusLine-Eintrag anzeigen

# Kapazität (verbleibendes Plan-Kontingent je Agent-CLI)
sccs capacity                    # Rich-Tabelle + Routing-Empfehlung
sccs capacity --json             # Einzeiliges JSON für Orchestrator/GUI
sccs capacity --offline          # Ohne Netzwerk-Probe (Antigravity /usage)

# Konvertierung (Shell-Profile aus der Fish-Config generieren)
sccs convert fish-to-pwsh        # PowerShell-Profil aus der Fish-Config erzeugen
sccs convert fish-to-zsh         # Zsh-Profil aus der Fish-Config erzeugen

# Dokumentation
sccs docs generate               # Hub-README für das Sync-Repository generieren

# Capability Card (für LLM-/Agent-Konsum)
sccs capability-card             # Capability Card (usage/AGENT.md) ausgeben

# Integrationen (Antigravity, Claude Desktop, OpenCode, Pi, Codex)
sccs integrations status                       # Integrations-Report
sccs integrations sync-all -n                  # Alle installierten Assistenten: Plan ohne Schreiben
sccs integrations sync-all                     # Plan zeigen, EINMAL bestätigen, alles exportieren
sccs integrations sync-all --replace-foreign   # zusätzlich Codex-Ziele ersetzen, die SCCS nicht schrieb
sccs integrations opencode status              # OpenCode: Installation + offene Konvertierungen
sccs integrations opencode map-models          # CC-Modelle den OpenCode-Modellen zuweisen
sccs integrations opencode export-agents -n    # Agents konvertieren (Vorschau)
sccs integrations opencode export-commands -n  # Commands konvertieren (Vorschau)
sccs integrations opencode merge-mcp -n        # MCP-Server in opencode.json mergen (Vorschau)
sccs integrations pi status                    # Pi: Installation + offene Exporte
sccs integrations pi export-all -n             # Skills/Agents/Commands nach Pi (Vorschau)
sccs integrations codex status                 # Codex: Installation + offene Exporte
sccs integrations codex export-skills -n       # Skills verbatim nach ~/.agents/skills (Vorschau)
sccs integrations codex export-agents -n       # Agents -> Codex-TOML (Vorschau)
sccs integrations codex export-commands -n     # Commands als Codex-Skills verpacken (Vorschau)
sccs integrations codex export-all -n          # Alles in einem Lauf (Vorschau)
```

---

## English

Full reference for every `sccs` subcommand. Topic-specific workflows live
in the other usage docs:

- Sync workflow → [sync.md](sync.md)
- Doctor → [doctor.md](doctor.md)
- Export/Import → [transfer.md](transfer.md)
- Deployment (customer hosts, with a way back) → [deploy.md](deploy.md)
- Memory Bridge → [memory-bridge.md](memory-bridge.md)
- Categories → [categories.md](categories.md)
- Profiles & statusline → [profiles.md](profiles.md)
- OpenCode integration → [opencode.md](opencode.md)
- Capacity probe → [capacity.md](capacity.md)

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
sccs export --include-managed    # Include doctor-managed items (gsd-*, playwright-cli)
sccs import config.zip           # Interactive selection + import
sccs import config.zip --dry-run # Preview without writing
sccs import config.zip --all     # Import everything
sccs import config.zip --include-managed  # Write doctor-managed items too
# For a foreign (customer) host, sccs deploy is usually the better tool (see below)

# Deploy (a named profile WITH a way back, for a foreign host — unlike Export/Import above, see deploy.md)
sccs deploy list                        # List deployment profiles
sccs deploy show odoo-server            # Show what a profile would bundle
sccs deploy show odoo-server --platform linux  # Check against a different target platform
sccs deploy export odoo-server -o customer.zip  # Build a bundle from a profile
sccs deploy install customer.zip        # Install a bundle + write the receipt
sccs deploy install customer.zip -n     # Preview without writing
sccs deploy status                      # Show what SCCS installed on this host
sccs deploy revoke                      # Remove what SCCS installed, and verify it is gone
sccs deploy revoke --profile fastreport # When several profiles coexist on the host

# Categories
sccs categories list             # List enabled categories
sccs categories list --all       # All (incl. disabled)
sccs categories enable fish      # Enable category
sccs categories disable fish     # Disable category

# Doctor (system & plugin health)
sccs doctor check                # Read-only status table (exit 1 on problems)
sccs doctor check --no-update-check  # Skip the live version check (offline/fast)
sccs doctor install              # Install missing components (confirm per action)
sccs doctor install --yes        # Skip confirms (CI use only)
sccs doctor update               # Update plugins + refresh npx tools

# Profiles (park LOCAL artefact groups to shrink the system prompt — unrelated to the deployment profiles above, see profiles.md)
sccs profile list                # Show profiles + their state
sccs profile off gsd             # Park a group (moved aside, not deleted)
sccs profile on gsd              # Bring a parked group back
sccs profile status gsd          # Detail for one profile (omit name for all)

# Statusline (statusline presets, see profiles.md)
sccs statusline list             # List available presets
sccs statusline use claude-code-statusline      # Point settings.json at a preset
sccs statusline install claude-code-statusline  # Download and install a preset
sccs statusline show             # Show the current statusLine entry

# Capacity (remaining plan quota per agent CLI)
sccs capacity                    # Rich table + routing advice
sccs capacity --json             # Single-line JSON for an orchestrator/GUI
sccs capacity --offline          # Skip the network probe (Antigravity /usage)

# Convert (generate shell profiles from the Fish config)
sccs convert fish-to-pwsh        # Generate a PowerShell profile from the Fish config
sccs convert fish-to-zsh         # Generate a zsh profile from the Fish config

# Docs
sccs docs generate               # Generate the hub README for the sync repository

# Capability card (for LLM/agent consumption)
sccs capability-card             # Print the capability card (usage/AGENT.md)

# Integrations (Antigravity, Claude Desktop, OpenCode, Pi, Codex)
sccs integrations status                       # Integration report
sccs integrations sync-all -n                  # Every installed assistant: plan, write nothing
sccs integrations sync-all                     # Show the plan, confirm ONCE, export everywhere
sccs integrations sync-all --replace-foreign   # also replace Codex targets SCCS did not write
sccs integrations opencode status              # OpenCode: install + outstanding conversions
sccs integrations opencode map-models          # Assign CC models to OpenCode models
sccs integrations opencode export-agents -n    # Convert agents (preview)
sccs integrations opencode export-commands -n  # Convert commands (preview)
sccs integrations opencode merge-mcp -n        # Merge MCP servers into opencode.json (preview)
sccs integrations pi status                    # Pi: install + outstanding exports
sccs integrations pi export-all -n             # Skills/agents/commands to Pi (preview)
sccs integrations codex status                 # Codex: install + outstanding exports
sccs integrations codex export-skills -n       # Copy skills verbatim to ~/.agents/skills (preview)
sccs integrations codex export-agents -n       # Agents -> Codex TOML (preview)
sccs integrations codex export-commands -n     # Wrap commands as Codex skills (preview)
sccs integrations codex export-all -n          # Everything in one run (preview)
```
