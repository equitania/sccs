<!-- refreshed: 2026-05-26 -->
# Codebase Structure

**Analysis Date:** 2026-05-26

## Directory Layout

```
sccs/                          # Project root
├── sccs/                      # Main Python package
│   ├── __init__.py            # Version (2.32.1), lazy __getattr__ exports
│   ├── __main__.py            # python -m sccs entry point
│   ├── cli.py                 # Click CLI: all command groups (1812 lines)
│   ├── config/                # Config loading, schema, migration
│   │   ├── __init__.py        # Public config API exports
│   │   ├── schema.py          # Pydantic models: SccsConfig, SyncCategory, SettingsEnsure
│   │   ├── loader.py          # load_config(), save_config(), adopt_new_categories()
│   │   ├── defaults.py        # Default YAML template string
│   │   └── migration.py       # MigrationStateManager, detect_new_categories()
│   ├── sync/                  # Sync engine subsystem
│   │   ├── __init__.py        # Public sync API exports
│   │   ├── engine.py          # SyncEngine — multi-category orchestrator
│   │   ├── category.py        # CategoryHandler — single-category logic
│   │   ├── item.py            # SyncItem dataclass + scan_items_for_category()
│   │   ├── actions.py         # ActionType enum, SyncAction, execute_action()
│   │   ├── state.py           # StateManager — hash/timestamp persistence
│   │   └── settings.py        # ensure_settings() — JSON deep-merge
│   ├── doctor/                # System health check subsystem
│   │   ├── __init__.py        # Public doctor API exports
│   │   ├── schema.py          # DoctorConfig, PluginSpec, NpxToolSpec, StatusLineCheckSpec, etc.
│   │   ├── defaults.py        # DEFAULT_CLAUDE_PLUGINS, DEFAULT_NPX_TOOLS, DEFAULT_*_CHECKS
│   │   ├── detectors.py       # Read-only detectors: NodeDetector, ClaudePluginDetector, etc.
│   │   ├── installer.py       # DoctorAction, InstallPlan, build_*_plan(), execute_plan()
│   │   ├── runner.py          # Subprocess execution: _run(), allowlisted heads, DoctorError
│   │   ├── reporter.py        # render_doctor_report(), has_problems(), render_execute_result()
│   │   ├── state.py           # DoctorStateManager — npx tool mark persistence
│   │   └── managed.py         # DEFAULT_MANAGED_PATTERNS, get_doctor_managed_excludes()
│   ├── git/                   # Git subprocess wrapper
│   │   ├── __init__.py        # Public git API exports
│   │   ├── operations.py      # commit, push, pull, fetch, stage, get_remote_status, etc.
│   │   └── resolve.py         # DivergenceStrategy, prompt_divergence_strategy(), apply_divergence_strategy()
│   ├── output/                # Rich console output
│   │   ├── __init__.py        # Public output API exports
│   │   ├── console.py         # Console class (Rich wrapper, tables, status, prompts)
│   │   ├── diff.py            # show_diff(), generate_diff(), show_conflict()
│   │   └── merge.py           # interactive_merge(), edit_in_editor(), DiffHunk
│   ├── transfer/              # ZIP export/import
│   │   ├── __init__.py        # Public transfer API exports
│   │   ├── exporter.py        # Exporter class, scan/select/export to ZIP
│   │   ├── importer.py        # Importer class, load manifest/select/apply
│   │   ├── manifest.py        # ExportManifest, ManifestItem, serialize/deserialize
│   │   └── ui.py              # interactive_export_selection(), interactive_import_selection()
│   ├── integrations/          # External tool bridges
│   │   ├── __init__.py        # Public integrations API exports
│   │   ├── detectors.py       # AntigravityDetector, ClaudeDesktopDetector
│   │   ├── antigravity.py     # migrate_skills_to_prompts()
│   │   └── claude_desktop.py  # register_trusted_folder()
│   ├── convert/               # Shell config converters
│   │   ├── __init__.py        # Public convert API exports
│   │   ├── fish_to_pwsh.py    # FishToPwshConverter, ConversionReport
│   │   ├── rules.py           # Conversion rule definitions
│   │   └── templates.py       # PowerShell output templates
│   ├── docs/                  # Hub README generator
│   │   ├── __init__.py        # Public docs API exports
│   │   └── generator.py       # DocsGenerator, DocsResult, _discover_readmes()
│   └── utils/                 # Cross-cutting utilities
│       ├── __init__.py        # Public utils API exports
│       ├── paths.py           # atomic_write, safe_copy, safe_delete, create_backup, find_files
│       ├── hashing.py         # file_hash(), directory_hash(), get_mtime()
│       ├── platform.py        # get_current_platform(), is_platform_match(), is_shell_available()
│       └── logging.py         # configure_logging()
├── tests/                     # pytest test suite (24 files)
│   ├── conftest.py            # Shared fixtures
│   ├── test_cli.py            # CLI command smoke tests
│   ├── test_config.py         # Config load/save/validate
│   ├── test_sync.py           # SyncEngine integration tests
│   ├── test_doctor.py         # Doctor detectors/installer/reporter
│   ├── test_settings.py       # ensure_settings() unit tests
│   ├── test_transfer.py       # Export/import round-trip tests
│   ├── test_paths_atomic.py   # atomic_write() tests
│   ├── test_paths_security.py # Path traversal / security tests
│   ├── test_importer_security.py # ZIP security (path traversal)
│   ├── test_platform.py       # Platform detection tests
│   ├── test_platform_utils.py # Platform utility helpers
│   ├── test_merge.py          # Interactive merge hunk tests
│   ├── test_diff.py           # Diff generation tests
│   ├── test_convert.py        # Fish→PowerShell conversion tests
│   ├── test_docs.py           # Hub README generation tests
│   ├── test_integrations.py   # Antigravity/Claude Desktop detector tests
│   ├── test_migration.py      # Category migration state tests
│   ├── test_conflict_resolution.py # Conflict resolve flow tests
│   ├── test_console.py        # Console output tests
│   ├── test_git_operations.py # Git wrapper tests
│   ├── test_git_resolve.py    # DivergenceStrategy tests
│   ├── test_hashing.py        # Hash utility tests
│   └── test_cli.py            # (CLI integration tests)
├── docs/                      # User documentation
│   └── usage/                 # Usage guides
├── .planning/                 # GSD planning artifacts (not committed)
│   ├── codebase/              # Codebase map documents (this file)
│   └── phases/                # Implementation phase plans
├── .claude/                   # Claude Code config for this project
│   ├── commands/              # Project slash commands
│   └── skills/                # Project skills
├── .github/
│   └── workflows/             # CI workflows
├── pyproject.toml             # Package metadata, dependencies, tool config
├── CLAUDE.md                  # Project guidance for Claude Code
└── README.md                  # User documentation
```

## Directory Purposes

**`sccs/config/`:**
- Purpose: YAML config load/save, Pydantic schema validation, new-category migration
- Key files: `schema.py` (all Pydantic models), `loader.py` (file I/O), `migration.py` (migration state), `defaults.py` (default YAML template)
- Config lives at: `~/.config/sccs/config.yaml`

**`sccs/sync/`:**
- Purpose: Core bidirectional file sync logic
- Key files: `engine.py` (top-level orchestrator), `category.py` (per-category handler), `actions.py` (action execution), `state.py` (persistence)
- State lives at: `~/.config/sccs/.sync_state.yaml`

**`sccs/doctor/`:**
- Purpose: Claude Code environment health checks and maintenance automation
- Key files: `schema.py` (spec dataclasses), `defaults.py` (bundled lists), `detectors.py` (read-only checks), `installer.py` (action planning + execution, 1460 lines), `runner.py` (subprocess layer), `reporter.py` (Rich output), `state.py` (npx persistence), `managed.py` (sync excludes)
- Doctor state lives at: `~/.config/sccs/.doctor_state.yaml`

**`sccs/git/`:**
- Purpose: Thin wrapper over `git` subprocess; no business logic
- Key files: `operations.py` (all git commands), `resolve.py` (divergence strategy)

**`sccs/output/`:**
- Purpose: All user-facing terminal output
- Key files: `console.py` (main `Console` class with `print_*` methods), `diff.py` (unified diff), `merge.py` (interactive hunk merge)

**`sccs/transfer/`:**
- Purpose: ZIP-based portable config export/import
- Key files: `exporter.py`, `importer.py`, `manifest.py` (JSON manifest schema), `ui.py` (questionary TUI)

**`sccs/integrations/`:**
- Purpose: Optional bridges to Antigravity IDE and Claude Desktop
- Key files: `detectors.py` (presence detection + gap analysis), `antigravity.py` (skill migration), `claude_desktop.py` (trusted folder registration)

**`sccs/convert/`:**
- Purpose: One-off Fish → PowerShell config translation
- Key files: `fish_to_pwsh.py` (main converter), `rules.py` (conversion rules), `templates.py` (PS output templates)

**`sccs/utils/`:**
- Purpose: Shared utilities with no sccs imports
- Key files: `paths.py` (`atomic_write`, `safe_copy`, backup management, glob matching), `platform.py` (OS detection), `hashing.py` (SHA-256 file/dir hash)

**`tests/`:**
- Purpose: pytest test suite; co-located by concern, not by module
- Key files: `conftest.py` (fixtures), `test_sync.py` (engine integration), `test_doctor.py` (doctor subsystem), `test_paths_security.py` + `test_importer_security.py` (security regression)

## Key File Locations

**Entry Points:**
- `sccs/cli.py`: All CLI commands (1812 lines) — primary entry point
- `sccs/__main__.py`: `python -m sccs` entry
- `sccs/__init__.py`: Version constant and lazy programmatic API

**Configuration:**
- `pyproject.toml`: Package metadata, runtime deps, ruff/mypy/pytest/coverage config
- `sccs/config/schema.py`: Root `SccsConfig` model (the schema the config.yaml must match)
- `sccs/config/defaults.py`: Default YAML template used by `sccs config init`
- `sccs/doctor/defaults.py`: Bundled DEFAULT_CLAUDE_PLUGINS and DEFAULT_NPX_TOOLS lists

**Core Logic:**
- `sccs/sync/engine.py`: `SyncEngine` — sync entry point for the sync layer
- `sccs/sync/category.py`: `CategoryHandler` — per-category scan/detect/execute
- `sccs/sync/actions.py`: `ActionType` enum + `execute_action()` — actual file operations
- `sccs/doctor/installer.py`: `build_install_plan()`, `build_update_plan()`, `build_optimize_plan()`, `execute_plan()` — entire doctor action pipeline (1460 lines)
- `sccs/doctor/detectors.py`: All read-only health check classes

**State Files (runtime, not in repo):**
- `~/.config/sccs/config.yaml`: User configuration
- `~/.config/sccs/.sync_state.yaml`: Last-sync hashes and timestamps
- `~/.config/sccs/.doctor_state.yaml`: Successful npx tool run markers
- `~/.config/sccs/migration_state.yaml`: Adopted/declined category migration state

## Naming Conventions

**Files:**
- `snake_case.py` throughout
- `__init__.py` in every package directory with explicit public exports

**Classes:**
- `PascalCase` (e.g. `SyncEngine`, `CategoryHandler`, `DoctorAction`, `SccsConfig`)
- Detector classes end in `Detector` (`NodeDetector`, `ClaudePluginDetector`)
- Status dataclasses end in `Status` (`NodeStatus`, `PluginStatus`, `PermissionStatus`)
- Config spec dataclasses end in `Spec` (`PluginSpec`, `NpxToolSpec`, `StatusLineCheckSpec`)
- Result dataclasses end in `Result` (`SyncResult`, `ExecuteResult`, `DocsResult`)

**Functions:**
- `snake_case`; private helpers prefixed with `_` (e.g. `_run`, `_confirm`, `_validate_head`)
- Builder functions follow `build_*_plan()` pattern (`build_install_plan`, `build_update_plan`, `build_optimize_plan`)
- Detector methods follow `get_status()` / `get_statuses()` pattern

**Constants:**
- `UPPER_SNAKE_CASE` for module-level constants (e.g. `DEFAULT_CLAUDE_PLUGINS`, `PERM_NPM_ROOT_GLOBAL`, `PATH_NPM_PREFIX_BIN`)

## Where to Add New Code

**New sync category support (new item_type or scan logic):**
- Item scanning: `sccs/sync/item.py` — extend `scan_items_for_category()` or add a new `_scan_*_items()` private function
- Action logic: `sccs/sync/actions.py` — extend `determine_action()` if new ActionType needed
- Schema: `sccs/config/schema.py` — add field to `SyncCategory` if new config knob needed

**New doctor check (new detector):**
- Spec model: `sccs/doctor/schema.py` — add a new `*CheckSpec` or `*Spec` Pydantic model
- Default list: `sccs/doctor/defaults.py` — add `DEFAULT_*` constant
- Detector: `sccs/doctor/detectors.py` — add a new `*Detector` class with `get_status()` / `get_statuses()`
- DoctorConfig: `sccs/doctor/schema.py::DoctorConfig` — add field + `effective_*()` method
- Plan builder: `sccs/doctor/installer.py` — add `_*_actions()` helper function, wire into `build_install_plan()` + `build_update_plan()` + `build_optimize_plan()`
- Reporter: `sccs/doctor/reporter.py` — add `_*_row()` + `render_doctor_report()` entry + `has_problems()` entry
- CLI: `sccs/cli.py::_collect_doctor_statuses()` — instantiate new detector

**New CLI command:**
- Add to `sccs/cli.py` using `@cli.command()` or `@cli.group()` decorator pattern
- Sub-commands use nested `@group.command("name")` pattern

**New utility helper:**
- Filesystem helpers: `sccs/utils/paths.py`
- Hashing: `sccs/utils/hashing.py`
- Platform logic: `sccs/utils/platform.py`

**New integration:**
- Detector: `sccs/integrations/detectors.py` — add `*Info` dataclass + `*Detector` class
- Action: new file `sccs/integrations/<name>.py`
- Wire into: `sccs/cli.py::integrations_group` command group

**Tests:**
- Co-locate by concern: `tests/test_<module>.py`
- Security regression tests in `tests/test_paths_security.py` or `tests/test_importer_security.py`
- Doctor-specific tests in `tests/test_doctor.py`

## Special Directories

**`.planning/`:**
- Purpose: GSD codebase map and phase plan documents
- Generated: Partially (codebase docs are generated by `/gsd:map-codebase`)
- Committed: Yes (to git)

**`.claude/`:**
- Purpose: Claude Code project config (commands, skills for this project's development)
- Generated: No
- Committed: Yes

**`.worktrees/`:**
- Purpose: Git worktrees for parallel branch development (e.g. `memory-bridge` feature branch)
- Generated: Yes (by git)
- Committed: No

**`dist/`:**
- Purpose: Built wheel/sdist artifacts from `uv build`
- Generated: Yes
- Committed: No

**`.venv/`:**
- Purpose: UV-managed virtual environment
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-05-26*
