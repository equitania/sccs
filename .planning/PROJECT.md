# SCCS — SkillsCommandsConfigsSync

## What This Is

SCCS is a unified, YAML-configured bidirectional synchronization tool for Claude Code
files (skills, commands, hooks, scripts) and optional shell configurations between a
local `~/.claude/` and a Git repository. It also ships `sccs doctor` — a maintenance
subsystem that keeps the local Claude Code installation healthy (plugins, MCP servers,
statusline, settings.json hook hygiene). It is for developers who run Claude Code across
multiple machines and want their setup to stay in sync and self-healing.

## Core Value

A developer's Claude Code environment stays consistent and healthy across every machine —
sync moves the files, doctor keeps the local install correct. If everything else fails,
sync must never lose or corrupt a file.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ Unified YAML config with flexible sync categories (skills, commands, hooks, scripts, fish) — core
- ✓ Bidirectional sync with conflict detection and three sync modes — core
- ✓ Git integration (auto-commit / auto-push after sync) — core
- ✓ Doctor: StatusLine detector + auto-fix for stale Homebrew Cellar paths — Phase 1 (v2.29.0)
- ✓ Doctor: config loader preserves user `doctor:` overrides — Phase 1 (v2.29.1)
- ✓ Doctor: `optimize` sub-command + foreign-plugin/MCP-server drift detection — Phase 2 (v2.30.0)
- ✓ Doctor: settings.json hook sanitisation (`disallowed_hooks`) — Phase 3 (v2.31.0)
- ✓ Doctor: `protected_hooks` guard + `auto_confirm` for safe maintenance — Phase 4 (v2.32.0)
- ✓ Doctor: `npm-bin-global` permission gate + system-prefix chown suppression + CI green on Linux — Phase 5 (v2.32.1)

### Active

<!-- Current scope. Building toward these. Defined via /gsd:new-milestone. -->

(None — Doctor Maturation milestone complete. Next milestone TBD via `/gsd:new-milestone`.)

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Executing the statusline script as a liveness probe — would run arbitrary user code inside doctor (too invasive)
- Auto-fix for nvm/asdf/Linuxbrew/Intel-Homebrew statusline patterns — current support is Apple Silicon Homebrew only
- Separate `requirements.txt` — `pyproject.toml` is the single source of truth (project-wide rule)

## Context

- **Brownfield reconstruction (2026-05-26):** GSD planning files (PROJECT/STATE/ROADMAP)
  were missing. The codebase was already mapped (`.planning/codebase/`, 2026-05-11) and a
  single Phase 1 CONTEXT.md existed, but the v2.29→v2.32.1 work shipped outside the GSD
  flow (no PLAN/SUMMARY artifacts). These docs were reconstructed from RELEASE_NOTES.md and
  git history to make GSD usable again.
- The doctor subsystem grew rapidly across v2.29–v2.32 in response to real incidents on the
  user's own machines (stale Cellar Node path, GSD re-injecting hooks, system-npm EACCES).
- `.planning/codebase/CONCERNS.md` (2026-05-11) is partially stale — several items it flags
  were resolved in v2.30–v2.32. Re-map before treating it as authoritative.

## Constraints

- **Tech stack**: Python 3.10–3.13, Click CLI, Pydantic config models — established, no rewrite
- **Package manager**: UV only (never pip) — project-wide rule
- **Compatibility**: Cross-platform macOS / Linux / Windows — CI runs on Linux; never assume macOS paths
- **Dependencies**: `pyproject.toml` is the single source of truth
- **Versioning**: increment version + date (DD.MM.YYYY) on every feature; required for image build

## Key Decisions

<!-- Decisions that constrain future work. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| StatusLine `required` is smart-detected, not static | Don't nag users who never configured a statusline | ✓ Good |
| Doctor never strips `gsd-*` hooks (protected_hooks) | GSD plugin breaks if its hooks are removed | ✓ Good |
| `auto_confirm` only on safe maintenance; destructive actions always prompt | Unattended updates without risking deletions | ✓ Good |
| `chown` advice suppressed for npm prefixes outside `$HOME` | Chowning `/usr/lib` leaves `/usr/bin` root-owned — the trap that caused the incident | ✓ Good |
| Reconstruct GSD docs from history rather than re-run new-project | Project is live since v2.29; new-project would discard real context | — Pending |

---
*Last updated: 2026-05-26 after brownfield GSD reconstruction*
