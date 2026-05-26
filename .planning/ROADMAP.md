# Roadmap: SCCS — SkillsCommandsConfigsSync

## Overview

SCCS started as a YAML-configured bidirectional sync tool for Claude Code files. Its first
GSD-tracked milestone (v2.29 → v2.32.1) hardened the `sccs doctor` maintenance subsystem
across five phases, turning it from a passive checker into an active, self-healing
maintainer of the local Claude Code install. This roadmap reconstructs that completed
milestone from RELEASE_NOTES.md and git history (brownfield, 2026-05-26).

All five phases are complete. The next milestone is defined via `/gsd:new-milestone`.

## Phases

- [x] **Phase 1: StatusLine Doctor Detector** — detect + auto-fix broken statusline in settings.json (v2.29.0/.1)
- [x] **Phase 2: Doctor Optimize & Drift Detection** — optimize pass + foreign plugin/MCP drift (v2.30.0)
- [x] **Phase 3: Settings.json Hook Sanitisation** — strip disallowed hooks after every pass (v2.31.0)
- [x] **Phase 4: Hook Protection & Auto-Confirm** — protect gsd-* hooks, unattended safe maintenance (v2.32.0)
- [x] **Phase 5: npm Permission Hardening & CI Green** — npm-bin-global gate + chown safety + Linux CI (v2.32.1)

## Phase Details

### Phase 1: StatusLine Doctor Detector
**Goal**: Detect and auto-fix a broken `statusLine.command` in settings.json (stale Homebrew Cellar paths, missing binary/script), and stop the loader from dropping user `doctor:` overrides.
**Depends on**: Nothing (first GSD phase)
**Success Criteria** (what must be TRUE):
  1. `sccs doctor check` classifies statusline state into ok/missing/missing_binary/missing_script/stale_cellar/opaque/no_settings_file
  2. Stale Apple-Silicon Cellar paths auto-rewrite to the stable `/opt/homebrew/bin` symlink, with timestamped backup
  3. User-supplied `doctor:` config block survives the loader merge
**Plans**: 1 plan (CONTEXT.md present)

Plans:
- [x] 01-01: StatusLineDetector + smart `required_mode` + auto-fix + loader override fix (v2.29.0 / v2.29.1)

### Phase 2: Doctor Optimize & Drift Detection
**Goal**: One-shot `optimize` pass that installs/updates everything and surfaces drift between the user's spec and the locally installed plugins/MCP servers.
**Depends on**: Phase 1
**Success Criteria** (what must be TRUE):
  1. `sccs doctor optimize` combines install + update in one pass
  2. Foreign plugins and MCP servers are detected (marketplace-aware) and shown as drift warnings; `--strict` offers explicit removal
  3. `sccs_config` sync category propagates `config.yaml` itself across hosts
**Plans**: 1 plan

Plans:
- [x] 02-01: optimize sub-command + ForeignPlugin/MCPServer detectors + sccs_config category (v2.30.0)

### Phase 3: Settings.json Hook Sanitisation
**Goal**: Strip user-disallowed hooks from settings.json after every doctor pass, defeating upstream tools that re-inject them.
**Depends on**: Phase 2
**Success Criteria** (what must be TRUE):
  1. `doctor.disallowed_hooks:` substring patterns remove matching hook entries with a timestamped backup
  2. Empty inner/outer hook entries and event keys are pruned (no dead accumulation)
  3. Sanitiser runs last and is idempotent on a clean file
**Plans**: 1 plan

Plans:
- [x] 03-01: SettingsHookDetector + disallowed_hooks sanitiser action (v2.31.0)

### Phase 4: Hook Protection & Auto-Confirm
**Goal**: Never let the sanitiser strip protected (`gsd-*`) hooks, and let safe maintenance run unattended while destructive actions still prompt.
**Depends on**: Phase 3
**Success Criteria** (what must be TRUE):
  1. Protected hooks survive every doctor pass even if a disallowed pattern would match
  2. `auto_confirm` runs install/update/refresh without per-action prompts
  3. Destructive actions (uninstall, hook removal, statusline rewrite) still prompt every time
**Plans**: 1 plan

Plans:
- [x] 04-01: protected_hooks guard + DoctorAction.auto_confirm + canonical plugin allowlist (v2.32.0)

### Phase 5: npm Permission Hardening & CI Green
**Goal**: Close the Linux system-npm permission gap and restore green CI across platforms.
**Depends on**: Phase 4
**Success Criteria** (what must be TRUE):
  1. `npm-bin-global` check gates the npx install on `<prefix>/bin` writability, surfacing EACCES as a manual block
  2. `chown` advice suppressed for npm prefixes outside `$HOME`; only user-local prefix recommended
  3. Statusline idempotency test passes on Linux CI (tolerates platform-dependent missing_binary)
**Plans**: 1 plan

Plans:
- [x] 05-01: npm-bin-global permission gate + system-prefix chown suppression + CI fix (v2.32.1)

## Next Milestone

Not yet defined. Run `/gsd:new-milestone` (questioning → research → requirements → roadmap)
to start the next cycle. Candidate input: a fresh `/gsd:map-codebase` pass — the
2026-05-11 `.planning/codebase/CONCERNS.md` is partially stale (several items resolved in v2.30–v2.32).

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. StatusLine Doctor Detector | 1/1 | Complete | 2026-05-11 |
| 2. Doctor Optimize & Drift Detection | 1/1 | Complete | 2026-05-24 |
| 3. Settings.json Hook Sanitisation | 1/1 | Complete | 2026-05-24 |
| 4. Hook Protection & Auto-Confirm | 1/1 | Complete | 2026-05-25 |
| 5. npm Permission Hardening & CI Green | 1/1 | Complete | 2026-05-25 |
