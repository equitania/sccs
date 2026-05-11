<!-- refreshed: 2026-05-11 -->
# Architecture

**Analysis Date:** 2026-05-11

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                          CLI Layer (Click)                               │
│  `sccs/cli.py`                                                           │
│  Groups: sync │ status │ diff │ log │ config │ categories │ convert      │
│          docs │ export │ import │ integrations │ doctor                   │
└──────┬────────────┬──────────────┬────────────────┬──────────────────────┘
       │            │              │                │
       ▼            ▼              ▼                ▼
┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌─────────────────────┐
│  Sync    │  │  Doctor  │  │ Integrations │  │  Transfer / Docs /  │
│  Engine  │  │  Engine  │  │  Detectors   │  │  Convert subsystems │
│`sync/`   │  │`doctor/` │  │`integrations`│  │`transfer/` `docs/`  │
│          │  │          │  │              │  │`convert/`           │
└────┬─────┘  └────┬─────┘  └──────────────┘  └─────────────────────┘
     │              │
     ▼              ▼
┌──────────────┐  ┌──────────────────────────────────────────────────────┐
│  Config      │  │  Doctor Cascade                                       │
│  `config/`   │  │  defaults → detectors → installer → reporter         │
│  Pydantic    │  │  `doctor/defaults.py` `doctor/detectors.py`           │
│  SccsConfig  │  │  `doctor/installer.py` `doctor/reporter.py`           │
│  + YAML I/O  │  │  `doctor/runner.py` (subprocess sandbox)              │
└────┬─────────┘  └──────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Persistence Layer                                                        │
│  `~/.config/sccs/config.yaml`     — user config (Pydantic-validated)    │
│  `~/.config/sccs/.sync_state.yaml` — sync item hashes + timestamps      │
│  `~/.config/sccs/.doctor_state.yaml` — npx tool install markers         │
│  `~/.config/sccs/.migration_state.yaml` — adopted/declined categories   │
└──────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | Key File(s) |
|-----------|----------------|-------------|
| CLI | Click command groups, flag parsing, user output orchestration | `sccs/cli.py` |
| SyncEngine | Coordinate per-category sync, merge doctor excludes | `sccs/sync/engine.py` |
| CategoryHandler | Scan items, detect changes, execute actions per category | `sccs/sync/category.py` |
| SyncAction / ActionType | Immutable action record (COPY_TO_REPO, CONFLICT, etc.) | `sccs/sync/actions.py` |
| StateManager | Persist item hashes + timestamps in `.sync_state.yaml` | `sccs/sync/state.py` |
| SccsConfig | Root Pydantic model; validates entire `config.yaml` | `sccs/config/schema.py` |
| SyncCategory | Per-category config (paths, mode, item_type, platforms) | `sccs/config/schema.py` |
| DoctorConfig | Doctor block in `config.yaml`; `effective_*()` methods merge defaults+overrides | `sccs/doctor/schema.py` |
| Doctor defaults | `DEFAULT_CLAUDE_PLUGINS`, `DEFAULT_NPX_TOOLS`, `DEFAULT_PERMISSION_CHECKS`, `DEFAULT_PATH_PREFIX_CHECKS` | `sccs/doctor/defaults.py` |
| Detectors | Read-only inspection dataclasses: `NodeStatus`, `ClaudeCliStatus`, `PluginStatus`, `NpxToolStatus`, `PermissionStatus`, `PathPrefixStatus`, `BundledSkillStatus`, `BrowserBundleStatus`, `MarketplaceStatus` | `sccs/doctor/detectors.py` |
| DoctorAction | Immutable action plan step with cascade-resilience fields (`blocks_downstream`, `depends_on_components`, `soft_fail`) | `sccs/doctor/installer.py` |
| Installer | `build_install_plan()` / `build_update_plan()` → `InstallPlan` → `execute_plan()` | `sccs/doctor/installer.py` |
| Reporter | Rich table rendering for `doctor check` and inline `status` hints | `sccs/doctor/reporter.py` |
| Runner | Security-hardened subprocess sandbox (no shell=True, no sudo, argv allowlist) | `sccs/doctor/runner.py` |
| DoctorStateManager | Persist npx tool install marks in `.doctor_state.yaml` for `detect_via_state` tools | `sccs/doctor/state.py` |
| ManagedExcludes | Contributes doctor-installed glob patterns → excluded from sync | `sccs/doctor/managed.py` |
| MigrationStateManager | Track adopted/declined new-default categories across sessions | `sccs/config/migration.py` |
| Console | Rich-based terminal output, conflict prompts, status tables | `sccs/output/console.py` |
| Git operations | `commit`, `push`, `pull`, `stage_all`, `get_remote_status` | `sccs/git/operations.py` |
| DivergenceStrategy | Interactive/CI-aware diverged-repo resolution | `sccs/git/resolve.py` |
| Integrations | Detect Antigravity IDE + Claude Desktop; migrate skills; trust-repo | `sccs/integrations/` |
| Transfer | Export/import ZIP archives with manifest (`sccs export` / `sccs import`) | `sccs/transfer/` |
| Convert | Fish → PowerShell profile transpiler | `sccs/convert/` |
| Docs generator | Hub README generation from category READMEs | `sccs/docs/generator.py` |
| Platform utils | `get_current_platform()`, `is_shell_available()`, `get_platform_skipped_categories()` | `sccs/utils/platform.py` |

## Pattern Overview

**Overall:** Layered CLI tool — Click front-end → domain engines → Pydantic-validated config → dataclass-based action/status models → YAML state persistence.

**Key Characteristics:**
- All domain models (config, sync, doctor) use `@dataclass` or `pydantic.BaseModel` — no plain dicts crossing module boundaries
- "Plan then execute" pattern in both sync and doctor: detection is always read-only, mutations come from explicit action execution
- Cascade-resilience in doctor: `DoctorAction.blocks_downstream` + `depends_on_components` lets the installer skip downstream steps when a prerequisite fails (e.g. bad npm permissions block npx install which blocks post_install steps)
- All subprocess calls go through `sccs/doctor/runner.py:_run()` — no `shell=True`, no sudo, argv head validated against allowlist regex
- Doctor-installed files (skills from npm packages, gsd hooks) are automatically added to `global_exclude` via `managed.py` so they never appear as sync conflicts

## Layers

**CLI Layer:**
- Purpose: Parse flags, load config, build console, orchestrate calls to domain engines, display results
- Location: `sccs/cli.py`
- Contains: Click groups (`cli`, `sync`, `config`, `categories`, `convert_group`, `docs_group`, `integrations_group`, `doctor_group`) and ~20 subcommands
- Depends on: All other layers
- Used by: End user, `sccs/__main__.py`

**Config Layer:**
- Purpose: Load, validate, migrate, and persist `~/.config/sccs/config.yaml`
- Location: `sccs/config/`
- Contains: `schema.py` (Pydantic models), `loader.py` (YAML I/O), `defaults.py` (default YAML text), `migration.py` (new-category detection + `MigrationStateManager`)
- Depends on: `sccs/doctor/schema.py` (DoctorConfig embedded in SccsConfig)
- Used by: CLI, SyncEngine, Doctor subsystem

**Sync Layer:**
- Purpose: Bidirectional file synchronization per category
- Location: `sccs/sync/`
- Contains: `engine.py` (SyncEngine orchestrator), `category.py` (CategoryHandler, scan + diff + execute), `actions.py` (ActionType enum + SyncAction dataclass), `item.py` (SyncItem), `state.py` (StateManager + SyncState + ItemState), `settings.py` (SettingsEnsure execution)
- Depends on: `sccs/config/schema.py`, `sccs/doctor/managed.py`, `sccs/utils/`
- Used by: CLI `sync`, `status`, `diff`, `log` commands

**Doctor Layer:**
- Purpose: Read-only environment health checks + platform-aware install/update plans
- Location: `sccs/doctor/`
- Contains: `schema.py` (Pydantic specs), `defaults.py` (bundled baselines), `detectors.py` (status dataclasses + detector classes), `installer.py` (DoctorAction, InstallPlan, execute_plan), `reporter.py` (Rich tables), `runner.py` (subprocess sandbox), `state.py` (DoctorStateManager), `managed.py` (doctor-owned file exclusion)
- Depends on: `sccs/utils/platform.py`, `sccs/utils/logging.py`
- Used by: CLI `doctor` group; `SyncEngine` imports `managed.py`

**Output Layer:**
- Purpose: All terminal rendering (Rich-based)
- Location: `sccs/output/`
- Contains: `console.py` (Console class), `diff.py` (unified diff display), `merge.py` (interactive hunk merge + editor launch)
- Depends on: `rich`
- Used by: CLI, doctor reporter

**Git Layer:**
- Purpose: Wrap git CLI operations; divergence detection and resolution
- Location: `sccs/git/`
- Contains: `operations.py` (commit, push, pull, stage_all, get_remote_status), `resolve.py` (DivergenceStrategy enum + apply/prompt functions)
- Depends on: subprocess (via allowlist pattern like runner.py)
- Used by: CLI sync command, docs generate command

**Integrations Layer:**
- Purpose: Detect and interop with Antigravity IDE and Claude Desktop
- Location: `sccs/integrations/`
- Contains: `detectors.py` (AntigravityDetector, ClaudeDesktopDetector), `antigravity.py` (skill migration), `claude_desktop.py` (trust-repo registration)
- Depends on: filesystem inspection
- Used by: CLI `integrations` group; inline in `status` command

**Transfer Layer:**
- Purpose: Portable ZIP export/import of sync items across machines
- Location: `sccs/transfer/`
- Contains: `exporter.py` (Exporter, scan + build ZIP), `importer.py` (Importer, manifest validation + apply), `manifest.py` (TransferManifest Pydantic model), `ui.py` (questionary-based interactive selection)
- Depends on: `sccs/config/`, zipfile, questionary
- Used by: CLI `export` / `import` commands

**Utils Layer:**
- Purpose: Shared low-level helpers
- Location: `sccs/utils/`
- Contains: `paths.py` (safe_copy, atomic_write, create_backup, find_files), `hashing.py` (SHA-256 content hashing), `platform.py` (platform detection + shell availability), `logging.py` (configure_logging, get_logger)
- Depends on: stdlib only
- Used by: all other layers

## Data Flow

### Sync Flow (`sccs sync`)

1. CLI loads config via `load_config()` (`sccs/config/loader.py`)
2. Migration check: `detect_new_categories()` / `get_categories_to_offer()` (`sccs/config/migration.py`)
3. Remote status check via `get_remote_status()` (`sccs/git/operations.py`); divergence handled by `DivergenceStrategy` (`sccs/git/resolve.py`)
4. `SyncEngine.__init__()` merges `doctor_managed_excludes` into `effective_global_exclude` (`sccs/sync/engine.py:61-62`)
5. `engine.sync()` iterates enabled categories → `CategoryHandler.detect_changes()` → list of `SyncAction`
6. Each `SyncAction` executed via `execute_action()` (`sccs/sync/actions.py`); uses `safe_copy` / `atomic_write` from `sccs/utils/paths.py`
7. `StateManager.update_item()` persists new hash + mtime to `~/.config/sccs/.sync_state.yaml`
8. Optional: `DocsGenerator.generate()` updates hub README (`sccs/docs/generator.py`)
9. Optional git: `stage_all()` → `commit()` → `push()` (`sccs/git/operations.py`)

### Doctor Flow (`sccs doctor check / install / update`)

1. `_load_doctor_config()` extracts `config.doctor` (a `DoctorConfig`) from `SccsConfig` (`sccs/cli.py:1529`)
2. `_collect_doctor_statuses()` instantiates all detectors and calls `get_status()` / `get_statuses()` on each — **read-only** (`sccs/cli.py:1492-1526`):
   - `NodeDetector` → `NodeStatus`
   - `ClaudeCliDetector` → `ClaudeCliStatus`
   - `ClaudePluginDetector` → list of `PluginStatus`
   - `ClaudeMarketplaceDetector` → list of `MarketplaceStatus`
   - `NpxToolDetector` → list of `NpxToolStatus`
   - `PermissionDetector` → list of `PermissionStatus`
   - `PathPrefixDetector` → list of `PathPrefixStatus`
   - `BundledSkillDetector` → list of `BundledSkillStatus`
   - `BrowserBundleDetector` → list of `BrowserBundleStatus`
3. `check`: `render_doctor_report()` builds Rich table; `has_problems()` sets exit code (`sccs/doctor/reporter.py`)
4. `install` / `update`: `build_install_plan()` / `build_update_plan()` returns `InstallPlan` (list of `DoctorAction`) (`sccs/doctor/installer.py`)
5. `execute_plan()` processes actions sequentially; `blocks_downstream=True` on manual blocks adds component to `blocked_components` set; actions with matching `depends_on_components` entries are skipped; `soft_fail=True` actions mark `warned` not `failed`
6. `DoctorStateManager.mark_installed()` writes to `~/.config/sccs/.doctor_state.yaml` for `detect_via_state=True` tools

### Config Migration Flow (`sccs config upgrade` / pre-sync)

1. `load_raw_user_data()` reads raw YAML dict from `~/.config/sccs/config.yaml` (`sccs/config/loader.py`)
2. `detect_new_categories(raw_data)` compares keys against `DEFAULT_SYNC_CATEGORIES` (`sccs/config/migration.py`)
3. `get_categories_to_offer(raw_data, mgr)` filters out previously declined (from `MigrationStateManager`) — skipped in CI (non-TTY)
4. `adopt_new_categories(names, config_path)` appends YAML blocks to file (`sccs/config/__init__.py`)
5. `MigrationStateManager.mark_adopted()` / `mark_declined()` writes `~/.config/sccs/.migration_state.yaml`

## Key Abstractions

**SccsConfig (Pydantic):**
- Purpose: Single source of truth for all configuration, validated on load
- Location: `sccs/config/schema.py:174`
- Pattern: Nested Pydantic models — `RepositoryConfig`, `dict[str, SyncCategory]`, `DoctorConfig`, `OutputConfig`, `ConflictResolutionConfig`, `PathTransformConfig`

**SyncAction (dataclass):**
- Purpose: Immutable record of one planned file operation; carries `SyncItem`, `ActionType`, source/dest paths
- Location: `sccs/sync/actions.py:41`
- Pattern: Produced by `CategoryHandler.detect_changes()`, consumed by `execute_action()`

**DoctorAction (dataclass):**
- Purpose: Immutable planned install/update step with cascade-resilience metadata
- Location: `sccs/doctor/installer.py:37`
- Fields: `label`, `cmd`, `manual_block`, `runnable`, `component`, `blocks_downstream`, `depends_on_components`, `soft_fail`, `python_callable`, `npx_tool_name`
- Pattern: Produced by `build_install_plan()` / `build_update_plan()`, consumed by `execute_plan()`

**Status dataclasses (doctor):**
- Purpose: Read-only result structs from each detector — never mutated after construction
- Location: `sccs/doctor/detectors.py`
- Classes: `NodeStatus`, `ClaudeCliStatus`, `PluginStatus` (with `detection_source`, `scope`, `found_marketplace`), `NpxToolStatus`, `BundledSkillStatus`, `BrowserBundleStatus`, `PermissionStatus`, `PathPrefixStatus`, `MarketplaceStatus`

## Entry Points

**`sccs/__main__.py`:**
- Calls `from sccs.cli import main; main()`
- Triggers lazy imports defined in `sccs/__init__.py.__getattr__`

**`sccs/cli.py:main()`:**
- `cli(obj={})` — Click context root
- All subcommands registered via `@cli.command()` / `@cli.group()` decorators

**`sccs/__init__.py`:**
- Lazy `__getattr__` for `SyncEngine`, `SccsConfig`, `load_config`, `Console`, `DocsGenerator`, `Exporter`, `Importer`
- Keeps startup fast; heavy modules only imported when accessed

## Architectural Constraints

- **Threading:** Single-threaded; no async, no threads. All subprocess calls are blocking (via `runner._run()` with `capture_output=True`).
- **Global state:** One module-level global in `sccs/cli.py`: `_console: Console | None` (accessed via `get_console()` / `set_console()`). Also `_PLATFORM_HINT_PRINTED: bool` to suppress repeated hints.
- **Subprocess security:** All external process execution goes through `sccs/doctor/runner.py:_run()` (doctor) or subprocess calls in `sccs/git/operations.py` (git). Both validate argv[0] against `_SAFE_HEAD_PATTERN`. No `shell=True` anywhere in the codebase. No sudo execution — privileged steps are printed as `manual_block` only.
- **Config loading:** `load_config()` expands `~` in all path fields via Pydantic `field_validator`. No raw path strings cross layer boundaries after config is loaded.
- **Circular imports:** `sccs/config/schema.py` imports `sccs/doctor/schema.py` (DoctorConfig is embedded in SccsConfig). All other inter-module imports are top-down (CLI → engines → utils).

## Anti-Patterns

### Calling detectors inside `build_install_plan()`
**What happens:** Re-running detectors inside the installer instead of passing the already-collected status dict from `_collect_doctor_statuses()`
**Why it's wrong:** Runs expensive subprocess checks twice; produces stale results if system state changed between calls
**Do this instead:** Pass status dicts from `_collect_doctor_statuses()` through to `build_install_plan()` / `build_update_plan()` as shown in `sccs/cli.py:1611-1622`

### Writing directly to config.yaml with string manipulation
**What happens:** Replacing text in config YAML with `str.replace()` (only used in `config_init` for repo path)
**Why it's wrong:** Fragile if YAML structure changes; bypasses Pydantic validation
**Do this instead:** For new category adoption use `adopt_new_categories()` in `sccs/config/__init__.py` which appends validated YAML blocks. For general mutations load → mutate model → dump.

### Using `shell=True` or string interpolation in subprocess calls
**What happens:** Any caller that bypasses `runner._run()` or `git/operations.py` patterns
**Why it's wrong:** Command injection vulnerability; violates the security contract documented in `sccs/doctor/runner.py:1-8`
**Do this instead:** Always build `list[str]` argv, pass to `runner._run()` or subprocess directly with `shell=False`

## Error Handling

**Strategy:** Exceptions propagated to CLI layer; CLI catches expected exceptions (FileNotFoundError, KeyError) and calls `console.print_error()` + `sys.exit(1)`. Doctor layer uses `DoctorError` exception from `sccs/doctor/runner.py` to signal subprocess failures with structured returncode + stderr.

**Patterns:**
- Config not found: `FileNotFoundError` → CLI prints error + "Run sccs config init" hint
- Doctor subprocess fail: `DoctorError` caught in `execute_plan()` → action marked `failed`; `soft_fail=True` → marked `warned` instead
- Sync conflict: Not an exception — represented as `ActionType.CONFLICT` in the action plan, surfaced via `SyncResult.conflicts` count
- Git push fail: Non-fatal warning via `console.print_warning()`

## Cross-Cutting Concerns

**Logging:** `sccs/utils/logging.py:configure_logging()` called once in CLI group callback. Module-level loggers via `get_logger(name)`. Log file path from `config.output.log_file` when config loads successfully.

**Validation:** Input validation in Pydantic models (`field_validator`) for all config fields. Separate allowlist regex validation (`_SAFE_NAME_PATTERN`, `_SAFE_HEAD_PATTERN`) in doctor schema and runner for security-sensitive fields.

**Platform filtering:** `sccs/utils/platform.py:is_platform_match()` used by SyncEngine to skip categories whose `platforms` list excludes the current OS. `get_platform_skipped_categories()` feeds the one-shot hint printed in CLI group callback.

---

*Architecture analysis: 2026-05-11*
