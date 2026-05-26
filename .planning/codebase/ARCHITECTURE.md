<!-- refreshed: 2026-05-26 -->
# Architecture

**Analysis Date:** 2026-05-26

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                          CLI Layer (sccs/cli.py)                         │
│   sync  status  diff  log  config  categories  convert  docs  export    │
│                    import  integrations  doctor                          │
└──────────┬──────────┬──────────┬──────────────┬───────────────────────┘
           │          │          │              │
           ▼          ▼          ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────────────┐
│  Sync Engine  │ │  Config  │ │  Doctor  │ │  Satellite Subsystems       │
│ sccs/sync/   │ │ sccs/    │ │ sccs/    │ │  sccs/transfer/ (ZIP export)│
│              │ │ config/  │ │ doctor/  │ │  sccs/convert/ (fish→pwsh) │
│ SyncEngine   │ │          │ │          │ │  sccs/docs/ (hub README)    │
│ CategoryHndlr│ │ SccsConf │ │ Detectors│ │  sccs/integrations/         │
│ StateManager │ │ schema   │ │ Installer│ │  (Antigravity, ClaudeDesk.) │
└──────┬───────┘ │ loader   │ │ runner   │ └────────────────────────────┘
       │         └─────┬────┘ └─────┬────┘
       │               │            │
       ▼               ▼            ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    Support Layer                                         │
│  sccs/git/         sccs/output/          sccs/utils/                   │
│  operations.py     console.py (Rich)     paths.py (atomic_write)       │
│  resolve.py        diff.py               hashing.py                    │
│                    merge.py              platform.py                   │
│                                          logging.py                    │
└────────────────────────────────────────────────────────────────────────┘
       │                                            │
       ▼                                            ▼
┌──────────────────────────────────┐  ┌────────────────────────────────┐
│  Local filesystem (local_path)   │  │  Git repository (repo_path)    │
│  ~/.claude/skills/               │  │  ~/gitbase/sccs-sync/          │
│  ~/.claude/commands/             │  │  .claude/skills/               │
│  ~/.config/fish/                 │  │  .claude/commands/             │
└──────────────────────────────────┘  └────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `cli.py` | Click entry point, command groups, git orchestration | `sccs/cli.py` |
| `SccsConfig` | Root Pydantic model; validated YAML config | `sccs/config/schema.py` |
| `DoctorConfig` | Nested Pydantic model for `doctor:` YAML block | `sccs/doctor/schema.py` |
| `load_config()` | Load, merge, validate config.yaml | `sccs/config/loader.py` |
| `MigrationStateManager` | Track adopted/declined new-category offers | `sccs/config/migration.py` |
| `SyncEngine` | Orchestrate all-category or single-category sync | `sccs/sync/engine.py` |
| `CategoryHandler` | Single-category scan, detect-changes, sync | `sccs/sync/category.py` |
| `SyncItem` | Generic file/directory item representation | `sccs/sync/item.py` |
| `ActionType` / `SyncAction` | Enum of sync operations + per-item action dataclass | `sccs/sync/actions.py` |
| `StateManager` | Persist last-sync hashes and timestamps in YAML | `sccs/sync/state.py` |
| `ensure_settings()` | Non-destructive JSON deep-merge for `settings_ensure` | `sccs/sync/settings.py` |
| Detectors (doctor) | Read-only inspection: Node, CLI, plugins, npx, paths | `sccs/doctor/detectors.py` |
| `InstallPlan` / `DoctorAction` | Ordered action plan with cascade-resilience | `sccs/doctor/installer.py` |
| `execute_plan()` | Execute install/update actions with confirm + cascade-skip | `sccs/doctor/installer.py` |
| `DoctorStateManager` | Persist successful npx tool runs (detect_via_state) | `sccs/doctor/state.py` |
| `render_doctor_report()` | Rich console table for doctor check output | `sccs/doctor/reporter.py` |
| `get_doctor_managed_excludes()` | Auto-exclude doctor-managed files from sync | `sccs/doctor/managed.py` |
| Git operations | commit, push, pull, stage, remote status | `sccs/git/operations.py` |
| `DivergenceStrategy` | Handle repo divergence with interactive strategy prompt | `sccs/git/resolve.py` |
| `Console` | Rich-backed output: tables, status, conflict prompts | `sccs/output/console.py` |
| `show_diff()` | Unified diff display | `sccs/output/diff.py` |
| `interactive_merge()` | Hunk-by-hunk interactive merge + editor fallback | `sccs/output/merge.py` |
| `Exporter` / `Importer` | ZIP-archive export/import with manifest | `sccs/transfer/` |
| `AntigravityDetector` | Detect Antigravity IDE, report skill gaps | `sccs/integrations/detectors.py` |
| `ClaudeDesktopDetector` | Detect Claude Desktop, check trusted folders | `sccs/integrations/detectors.py` |
| `FishToPwshConverter` | Convert Fish shell config to PowerShell profile | `sccs/convert/fish_to_pwsh.py` |
| `DocsGenerator` | Generate hub README for the sync repository | `sccs/docs/generator.py` |
| `atomic_write()` / `safe_copy()` | Filesystem helpers with backup support | `sccs/utils/paths.py` |
| `get_current_platform()` | Cross-platform detection: macos / linux / windows | `sccs/utils/platform.py` |

## Pattern Overview

**Overall:** Config-validated → Orchestrate → Execute → Persist state

**Key Characteristics:**
- Config is a single Pydantic model tree (`SccsConfig` embeds `DoctorConfig`); all YAML validated at load time
- Lazy `__getattr__` imports in `sccs/__init__.py` keep startup fast
- Doctor subsystem is self-contained: schema + detectors + installer + runner + state + defaults
- All destructive file operations go through `atomic_write()` / `safe_copy()` with optional backup
- Doctor cascade-resilience: `DoctorAction.depends_on_components` prevents error-cascade noise after upstream failures
- Platform filtering is first-class: `SyncCategory.platforms` field + `is_platform_match()` used in both sync and hint output

## Layers

**Config Layer:**
- Purpose: Load, validate, and expose configuration as typed Pydantic models
- Location: `sccs/config/`
- Contains: Schema models, YAML loader, defaults, migration state
- Depends on: `sccs/doctor/schema.py` (embedded `DoctorConfig`)
- Used by: All layers

**Sync Layer:**
- Purpose: Bidirectional file sync between local paths and git repository
- Location: `sccs/sync/`
- Contains: `SyncEngine`, `CategoryHandler`, `SyncItem`, `ActionType`, `StateManager`, `ensure_settings`
- Depends on: Config layer, `utils/paths`, `utils/hashing`, `doctor/managed`
- Used by: CLI sync/status/diff commands

**Doctor Layer:**
- Purpose: System health checks, install/update plans, settings.json sanitisation
- Location: `sccs/doctor/`
- Contains: `schema.py` (specs), `detectors.py` (read-only), `installer.py` (plans + execution), `runner.py` (subprocess), `reporter.py` (output), `state.py` (persistence), `managed.py` (sync excludes), `defaults.py` (bundled specs)
- Depends on: `utils/platform`, `git/operations` (indirectly for `claude` binary detection)
- Used by: CLI doctor commands; `SyncEngine` imports `managed.py` for exclude patterns

**Git Layer:**
- Purpose: All git subprocess calls, remote status, divergence resolution
- Location: `sccs/git/`
- Contains: `operations.py`, `resolve.py`
- Depends on: stdlib only, no sccs imports
- Used by: CLI sync command, doctor (via `has_uncommitted_changes` in docs flow)

**Output Layer:**
- Purpose: All Rich console rendering, diff display, interactive merge
- Location: `sccs/output/`
- Contains: `console.py`, `diff.py`, `merge.py`
- Depends on: Rich, `sync/item`, `sync/actions`
- Used by: CLI everywhere

**Utility Layer:**
- Purpose: Cross-cutting helpers (paths, hashing, platform, logging)
- Location: `sccs/utils/`
- Contains: `paths.py`, `hashing.py`, `platform.py`, `logging.py`
- Depends on: stdlib only
- Used by: All layers

**Transfer Layer:**
- Purpose: ZIP export/import with JSON manifest for portable config packages
- Location: `sccs/transfer/`
- Contains: `exporter.py`, `importer.py`, `manifest.py`, `ui.py`
- Depends on: Config layer, `utils/paths`, `sync/item`
- Used by: CLI export/import commands

**Integrations Layer:**
- Purpose: Detect and bridge external tools (Antigravity IDE, Claude Desktop)
- Location: `sccs/integrations/`
- Contains: `detectors.py`, `antigravity.py`, `claude_desktop.py`
- Depends on: `utils/paths`, `utils/platform`
- Used by: CLI integrations commands, `status` command (inline)

**Convert Layer:**
- Purpose: Translate Fish shell config to PowerShell profile
- Location: `sccs/convert/`
- Contains: `fish_to_pwsh.py`, `rules.py`, `templates.py`
- Depends on: nothing in sccs
- Used by: CLI `sccs convert fish-to-pwsh`

**Docs Layer:**
- Purpose: Generate a navigation hub README for the sync repository
- Location: `sccs/docs/`
- Contains: `generator.py`
- Depends on: Config layer
- Used by: CLI `sccs docs generate`, auto-triggered when `--commit` is active in `sccs sync`

## Data Flow

### Primary Sync Path

1. `cli.py::sync()` — load config, check remote status via `sccs/git/operations.py` (`sccs/cli.py:174`)
2. `DivergenceStrategy` prompt if repo diverged from remote (`sccs/git/resolve.py:39`)
3. `SyncEngine(config)` instantiated with shared `StateManager` (`sccs/sync/engine.py:37`)
4. `SyncEngine.sync()` iterates enabled categories filtered by `is_platform_match()` (`sccs/sync/engine.py:151`)
5. Per-category: `CategoryHandler.sync()` → `scan_items()` → `detect_changes()` → `execute_action()` (`sccs/sync/category.py:106`)
6. `scan_items_for_category()` walks local and repo paths, builds `SyncItem` list (`sccs/sync/item.py:83`)
7. `determine_action()` compares current hashes against stored `StateManager` hashes to classify each item into an `ActionType` (`sccs/sync/actions.py:225`)
8. `execute_action()` calls `safe_copy()` or `safe_delete()` from `sccs/utils/paths.py` (`sccs/sync/actions.py:114`)
9. Optional: `ensure_settings()` non-destructively merges JSON entries for `settings_ensure` categories (`sccs/sync/settings.py:33`)
10. `StateManager.save()` writes updated hashes to `~/.config/sccs/.sync_state.yaml` (`sccs/sync/state.py:118`)
11. Back in CLI: optional `DocsGenerator.generate()`, then git commit + push (`sccs/cli.py:300`)

### Doctor Check → Install Path

1. `cli.py::doctor_check()` calls `_load_doctor_config()` → `_collect_doctor_statuses()` (`sccs/cli.py:1606`)
2. `_collect_doctor_statuses()` instantiates all detectors: `NodeDetector`, `ClaudeCliDetector`, `ClaudePluginDetector`, `NpxToolDetector`, `PermissionDetector`, `PathPrefixDetector`, `BundledSkillDetector`, `BrowserBundleDetector`, `StatusLineDetector`, `SettingsHookDetector`; optionally `MCPServerDetector` for `doctor optimize` (`sccs/cli.py:1511`)
3. Detector statuses returned as dict; `render_doctor_report()` builds Rich table (`sccs/doctor/reporter.py:149`)
4. `doctor_install()` calls `build_install_plan()` → `InstallPlan` of ordered `DoctorAction` objects (`sccs/doctor/installer.py:1115`)
5. Each `DoctorAction` carries: `cmd`, `component`, `depends_on_components`, `blocks_downstream`, `auto_confirm`, `soft_fail`, optional `python_callable` (`sccs/doctor/installer.py:45`)
6. `execute_plan()` iterates actions: cascade-skip if dependency failed/blocked, prompt or auto-confirm, run subprocess via `runner._run()`, record state for `detect_via_state` tools (`sccs/doctor/installer.py:1335`)
7. After execution: `_settings_hook_cleanup_actions()` sanitises `~/.claude/settings.json` by stripping `disallowed_hooks` entries (protected by `protected_hooks` allowlist) (`sccs/doctor/installer.py:940`)

### Config Load Path

1. `load_config()` reads `~/.config/sccs/config.yaml` via PyYAML (`sccs/config/loader.py:42`)
2. Raw dict is fed through `_merge_with_defaults()` (adds missing top-level keys without overwriting) (`sccs/config/loader.py:256`)
3. `SccsConfig.model_validate(data)` validates entire tree including embedded `DoctorConfig` (`sccs/config/schema.py:174`)
4. `RepositoryConfig.expand_path` + `SyncCategory.expand_paths` expand `~` at validation time
5. `MigrationStateManager` persists adopted/declined category offers in `~/.config/sccs/migration_state.yaml` (`sccs/config/migration.py:72`)

**State Management (three separate files):**
- Sync hashes: `~/.config/sccs/.sync_state.yaml` via `StateManager` (`sccs/sync/state.py`)
- Doctor npx tool marks: `~/.config/sccs/.doctor_state.yaml` via `DoctorStateManager` (`sccs/doctor/state.py`)
- Category migration offers: `~/.config/sccs/migration_state.yaml` via `MigrationStateManager` (`sccs/config/migration.py`)

## Key Abstractions

**`SyncCategory` (`sccs/config/schema.py:98`):**
- Declares what to sync, where, and how
- Key fields: `local_path`, `repo_path`, `sync_mode` (bidirectional/local_to_repo/repo_to_local), `item_type` (file/directory/mixed), `item_marker` (e.g. `SKILL.md`), `platforms`, `settings_ensure`

**`DoctorAction` (`sccs/doctor/installer.py:45`):**
- A single planned health-maintenance step with cascade-resilience metadata
- Key fields: `cmd`, `manual_block`, `runnable`, `component`, `depends_on_components`, `blocks_downstream`, `auto_confirm`, `soft_fail`, `python_callable`
- Component string conventions: `"perm:npm root -g"` (PERM_NPM_ROOT_GLOBAL), `"path:npm-prefix-bin"` (PATH_NPM_PREFIX_BIN), `"plugin:<name>"`, `"npx:<name>"`, `"statusline:<id>"`

**`SyncItem` (`sccs/sync/item.py:13`):**
- Represents a single file or directory on both sides of the sync
- Fields: `name`, `category`, `item_type`, `local_path` (absolute), `repo_path` (absolute), `content_hash`, `mtime`

**`SettingsEnsure` (`sccs/config/schema.py:71`):**
- Non-destructive JSON merge into a target file (e.g. `~/.claude/settings.json`) after sync
- `entries` = add-only (never overwrite); `platform_overrides` = overwrite for current platform

**Default spec lists (`sccs/doctor/defaults.py`):**
- `DEFAULT_CLAUDE_PLUGINS`: `PluginSpec` list (skill-creator, superpowers, frontend-design, LSP plugins, context-mode, etc.)
- `DEFAULT_NPX_TOOLS`: `NpxToolSpec` list (get-shit-done-cc with `detect_via_state=True`, playwright-cli with `post_install` + `bundled_skill` + `browser_bundles`)
- `DEFAULT_PERMISSION_CHECKS`, `DEFAULT_PATH_PREFIX_CHECKS`, `DEFAULT_STATUS_LINE_CHECKS`, `DEFAULT_IGNORED_MCP_PATTERNS`

## Entry Points

**CLI:**
- Location: `sccs/cli.py`
- Entry point: `sccs` binary via `pyproject.toml [project.scripts]`
- Root group: `cli` decorated with `@click.group`
- Sub-groups: `config`, `categories`, `convert`, `docs`, `integrations`, `doctor`

**Python module:**
- Location: `sccs/__main__.py`
- Triggers: `python -m sccs`

**Programmatic API:**
- Location: `sccs/__init__.py` (lazy `__getattr__`)
- Exports: `SyncEngine`, `SccsConfig`, `load_config`, `Console`, `DocsGenerator`, `Exporter`, `Importer`

## Architectural Constraints

- **Threading:** Single-threaded. All file operations and subprocess calls are synchronous.
- **Global state:** Module-level `_console: Console | None` singleton and `_PLATFORM_HINT_PRINTED: bool` flag in `sccs/cli.py`. Both are intentional per-process singletons.
- **Circular imports:** `sccs/config/schema.py` imports `DoctorConfig` from `sccs/doctor/schema.py`. One-way dependency; doctor layer does not import from config schema.
- **Subprocess security:** `runner._validate_head()` (`sccs/doctor/runner.py:34`) enforces an allowlist of permitted subprocess heads plus a safe-name regex. `shell=False` throughout; no `sudo` in any runnable `DoctorAction`.
- **Security exclusions:** `SccsConfig.global_exclude` hardcodes never-sync patterns for secrets, keys, tokens, `.npmrc`, `.netrc`, `fish_variables`, OAuth files, etc. (`sccs/config/schema.py:174`). Cannot be emptied by user config.

## Anti-Patterns

### Bypassing atomic_write for state or config files

**What happens:** Writing to `~/.config/sccs/*.yaml` or any synced file with direct `Path.write_text()`.
**Why it's wrong:** Power loss or crash mid-write leaves a corrupt YAML file; the state or config manager will fail to load on next run.
**Do this instead:** Use `atomic_write(path, content)` from `sccs/utils/paths.py:198`; call `create_backup(path)` before modification when overwriting existing data.

### Adding doctor actions without cascade wiring

**What happens:** A `DoctorAction` whose logic depends on a prior step (e.g. permission fix or npm install) omits `depends_on_components`.
**Why it's wrong:** If the upstream step fails (e.g. EACCES on npm root), the downstream action runs anyway, produces a confusing second error, and buries the root cause.
**Do this instead:** Set `depends_on_components=(PERM_NPM_ROOT_GLOBAL,)` or the relevant component constant from `sccs/doctor/installer.py:148`. Mark the blocking manual-block action with `blocks_downstream=True`.

### Adding doctor-managed files without managed-exclude patterns

**What happens:** A doctor-installed artifact (skill dir, config patch) is not listed in `DEFAULT_MANAGED_PATTERNS` (`sccs/doctor/managed.py`).
**Why it's wrong:** Two machines both running `sccs doctor install` each install the artifact; `sccs sync` then detects conflicts on every run.
**Do this instead:** Add a glob to `DEFAULT_MANAGED_PATTERNS` in `sccs/doctor/managed.py`. It is automatically merged into `SyncEngine._doctor_excludes` at construction time.

## Error Handling

**Strategy:** Explicit fail-fast at subsystem boundaries, surface via result dataclasses

**Patterns:**
- Config errors: `FileNotFoundError` and Pydantic `ValidationError` caught in CLI, printed, `sys.exit(1)`
- Git errors: `GitError` raised by `sccs/git/operations.py`; caught in CLI sync command
- Doctor subprocess errors: `DoctorError(stderr=...)` raised by `runner._run()`, caught per-action in `execute_plan()`
- File I/O: exceptions caught in `safe_copy()` / `safe_delete()` / `atomic_write()`, returned as `error: str` fields in result dataclasses
- Doctor soft-fail: `action.soft_fail=True` downgrades `DoctorError` to `warned` (yellow) instead of `failed` (red)
- Doctor cascade-skip: `blocked_components` / `failed_components` sets in `execute_plan()` suppress downstream noise

## Cross-Cutting Concerns

**Logging:** Python `logging` configured by `sccs/utils/logging.py:configure_logging()`. Optional log file from `config.output.log_file`. Doctor actions emit `logger.info/warning` throughout `sccs/doctor/installer.py`.

**Validation:** Pydantic v2 models with `@field_validator` on all security-sensitive fields. Input allowlist regexes defined as module-level constants in `sccs/doctor/schema.py` (`_SAFE_NAME_PATTERN`) and `sccs/git/operations.py` (`_require_no_option_prefix`, `_validate_remote`, `_validate_branch`).

**Authentication:** None — git operations use the local credential store. No API keys in SCCS config.

**Platform abstraction:** `get_current_platform()` (`sccs/utils/platform.py:31`) returns `"macos"`, `"linux"`, or `"windows"`. Used for category filtering, Fish/PowerShell detection, permission check skip-on-Windows logic, and `FishToPwshConverter` source-path fallback.

---

*Architecture analysis: 2026-05-26*
