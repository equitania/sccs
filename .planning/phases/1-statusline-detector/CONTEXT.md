---
phase: 1
slug: statusline-detector
version: 2.29.0
date: 2026-05-11
plan_doc: PLAN_v2.29.0.md
---

# Phase 1 — StatusLine Doctor Detector — CONTEXT

## Phase boundary (locked, no scope creep)

**In scope:**
- New `StatusLineCheckSpec` + `StatusLineStatus` + `StatusLineDetector`
- Inspect `~/.claude/settings.json` → `statusLine.command`, classify into states (ok/missing/missing_binary/missing_script/stale_cellar/opaque/no_settings_file)
- Auto-fix action: rewrite stale Cellar paths → Homebrew bin-symlink, with backup
- Reporter row, CLI wiring (analogous to `path_prefix_checks`)
- Tests, docs, RELEASE_NOTES, version bump 2.28.1 → 2.29.0

**Out of scope (deferred):**
- Executing the statusline script as a liveness probe (would run user code in doctor — too invasive)
- Shell-pipeline parsing beyond `<binary> <script> [args...]` shape
- Auto-fix for nvm/asdf/Linuxbrew/Intel-Homebrew patterns (this phase: Apple Silicon Homebrew only)
- Coupling doctor auto-fix to `claude_statusline` sync category (kept independent)

## Locked decisions (from discussion)

### D1 — `required` default: Smart-Detect

`StatusLineCheckSpec.required` is **dynamically computed**, not a static spec
field. The detector evaluates:

```
required = (
    "claude_statusline" in enabled_sync_categories
    AND any(path in ~/.claude exists for path in ["statusline.sh", "statusline.py",
            "statusline.ps1", "statusline.fish", "hooks/gsd-statusline.js"])
)
```

- **Rationale:** Users who never asked for a statusline shouldn't be nagged.
  Users with the sync category enabled AND a statusline script present
  obviously care → missing `statusLine` key is a real failure.
- **Implementation hint for researcher/planner:** Sync-category enablement
  must be read via `sccs.config.loader` (same path that
  `sccs/cli.py:_collect_doctor_statuses` uses). Skript-Existenz prüft der
  Detector über `pathlib.Path(...).exists()`.
- **Schema implication:** `required: bool` field on `StatusLineCheckSpec`
  becomes `required_mode: Literal["always", "never", "smart"] = "smart"`.

### D2 — Auto-fix scope: Apple Silicon Homebrew only

Pattern matched and rewritten:

```
/opt/homebrew/Cellar/<pkg>/<version>/bin/<binary>   →   /opt/homebrew/bin/<binary>
```

- **Out of phase scope:**
  - `/usr/local/Cellar/...` (Intel Homebrew) — same pattern, but no
    user-reported incident yet; defer to follow-up if requested.
  - `/home/linuxbrew/.linuxbrew/Cellar/...` — Linux Homebrew, defer.
  - `~/.nvm/versions/node/vX/bin/node` — versioned shims, ambiguous which
    version to fix to; **WARN only, no auto-fix**.
- **Stale detection:** `pathlib.Path("/opt/homebrew/Cellar/<pkg>/<version>")
  .is_dir()` is False. Pattern: regex
  `^/opt/homebrew/Cellar/([^/]+)/([^/]+)/.*/(.+)$`.
- **Rewrite safety:** Replace only inside JSON string value. Preserve
  surrounding quoting/escaping. Idempotency check: if string already lacks
  Cellar segment, no-op.

### D3 — Opaque commands: INFO + skip

If `shlex.split(command)` produces a structure that doesn't match
`<binary> <script> [args...]` — i.e. contains `|`, `&&`, `;`, env-var prefix
(`FOO=bar node ...`), or backticks/`$(...)` — state is `opaque`.

- Reporter: blue `–` symbol, detail `"custom command shape, not checked"`.
- No false positives, no nagging.
- Power-users with intentional pipelines see clear acknowledgement.
- Installer: no action emitted for opaque state.

### D4 — Sync coupling: Independent

Doctor and `claude_statusline` sync category remain **orthogonal**:

- Doctor reads `settings.json` **read-only** during `check`.
- Auto-fix on `stale_cellar` mutates `settings.json` directly with a
  timestamped backup (`settings.json.bak-YYYYMMDD-HHMMSS`, same convention as
  `settings_ensure.backup_before_modify`).
- Doctor does **NOT** invoke `SyncEngine` or trigger `settings_ensure`
  re-application.

**Why:** Simpler dependency graph, easier to test in isolation, follows the
pattern of `PathPrefixDetector` (read-only diagnosis, separate installer
action).

**Side note:** The existing `settings_ensure` block on `claude_statusline`
already handles platform overrides at sync time. Doctor's auto-fix is a
narrower repair tool for the "Homebrew bumped Node, stale Cellar path"
class of failure — it doesn't replace ensure-block semantics.

## Open knobs for researcher/planner

These are **implementation choices**, not user-facing decisions — downstream
agents resolve them:

1. **Component cascade behavior:** `blocks_downstream` for stale_cellar?
   Current plan says False. Verify against other detector patterns in
   `sccs/doctor/installer.py:_blocking_components`.
2. **Reporter symbol selection:** Match existing `–` / `!` / `OK` symbol
   palette from `sccs/doctor/reporter.py`. Don't invent new symbols.
3. **Test fixture HOME setup:** Pattern used by `TestPathPrefixDetector`
   (likely `tmp_path` + monkeypatch on `Path.home()` or `os.environ["HOME"]`).
   Reuse, don't reinvent.
4. **Schema field name for `required_mode`:** `Literal["always", "never",
   "smart"]` vs separate boolean `required` + `smart_detect`. Planner picks
   the cleaner Pydantic shape.

## Constraints / non-negotiables

- **Cross-platform:** Detector must not crash on Linux or Windows. On
  non-Darwin platforms with no Cellar pattern, `stale_cellar` state cannot
  occur — fine. Detector still parses the command and classifies missing-
  binary/script.
- **Settings.json integrity:** Auto-fix MUST preserve JSON validity. Backup
  before write. If JSON load fails, abort fix with clear error.
- **Backwards-compat:** No breaking changes to existing detectors, reporter
  signatures, or installer interfaces. Additive only.
- **Test isolation:** No test may touch real `~/.claude/settings.json`.

## Deferred ideas (NOT this phase)

- Live-execution probe (run statusline once, check exit code).
- Auto-fix Intel Homebrew + Linuxbrew Cellar patterns.
- nvm/asdf versioned-shim auto-fix.
- Periodic Cellar drift check (cron-like) — out of scope, sccs is invoked.
- GUI hint when stale_cellar detected during normal sccs commands.

## Downstream guidance

**For researcher** (gsd-phase-researcher): Investigate
- `sccs/doctor/detectors.py:PathPrefixDetector` as nearest pattern match
- `sccs/config/defaults.py` for `claude_statusline` sync category structure
- `sccs/doctor/installer.py:_path_prefix_actions` for installer-action shape
- `tests/test_doctor.py:TestPathPrefixDetector` for test fixtures
- Whether any utility for "read enabled sync categories" already exists
  in `sccs.config.loader` (needed for D1 smart-detect)

**For planner** (gsd-planner): Decompose into atomic commits along the
TDD sequence already in `PLAN_v2.29.0.md` (schema → detector → reporter →
installer → CLI → tests → docs → version bump). Verify the order honors
D1's runtime dependency on sync-category enablement (detector must be able
to query config at check-time).
