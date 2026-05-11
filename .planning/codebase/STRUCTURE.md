<!-- refreshed: 2026-05-11 -->
# Codebase Structure

**Analysis Date:** 2026-05-11

## Directory Layout

```
sccs/                            # Project root
├── sccs/                        # Main package
│   ├── __init__.py              # Version 2.28.1; lazy __getattr__ imports
│   ├── __main__.py              # python -m sccs entry point
│   ├── cli.py                   # All Click commands and groups (~1686 lines)
│   ├── config/                  # Config load/validate/migrate subsystem
│   │   ├── __init__.py          # Public API: load_config, adopt_new_categories, etc.
│   │   ├── schema.py            # Pydantic models (SccsConfig, SyncCategory, RepositoryConfig…)
│   │   ├── loader.py            # YAML I/O: load_config(), save_config(), validate_config_file()
│   │   ├── defaults.py          # Default config YAML text; generate_default_config()
│   │   └── migration.py        # MigrationStateManager, detect_new_categories(), get_categories_to_offer()
│   ├── sync/                    # Bidirectional sync engine
│   │   ├── __init__.py          # Exports SyncEngine, SyncResult
│   │   ├── engine.py            # SyncEngine orchestrator; merges doctor excludes
│   │   ├── category.py          # CategoryHandler: scan_items(), detect_changes(), execute_actions()
│   │   ├── actions.py           # ActionType enum + SyncAction dataclass + execute_action()
│   │   ├── item.py              # SyncItem dataclass; scan_local_items(), scan_repo_items()
│   │   ├── state.py             # StateManager, SyncState, ItemState → .sync_state.yaml
│   │   └── settings.py          # SettingsEnsure execution (JSON settings patching post-sync)
│   ├── doctor/                  # System health check subsystem
│   │   ├── __init__.py          # Empty (no public API; CLI imports directly)
│   │   ├── schema.py            # Pydantic specs: PluginSpec, NpxToolSpec, BundledSkillSpec,
│   │   │                        #   PermissionCheckSpec, PathPrefixCheckSpec, NodeInstallSpec, DoctorConfig
│   │   ├── defaults.py          # DEFAULT_CLAUDE_PLUGINS, DEFAULT_NPX_TOOLS,
│   │   │                        #   DEFAULT_PERMISSION_CHECKS, DEFAULT_PATH_PREFIX_CHECKS,
│   │   │                        #   get_node_install_spec()
│   │   ├── detectors.py         # Read-only status dataclasses + detector classes:
│   │   │                        #   NodeDetector, ClaudeCliDetector, ClaudePluginDetector,
│   │   │                        #   ClaudeMarketplaceDetector, NpxToolDetector,
│   │   │                        #   PermissionDetector, PathPrefixDetector,
│   │   │                        #   BundledSkillDetector, BrowserBundleDetector
│   │   ├── installer.py         # DoctorAction dataclass; build_install_plan(),
│   │   │                        #   build_update_plan(), execute_plan(), ExecuteResult
│   │   ├── reporter.py          # render_doctor_report(), has_problems(), render_execute_result()
│   │   ├── runner.py            # _run() subprocess sandbox; DoctorError;
│   │   │                        #   run_claude_plugin_list(), run_claude_marketplace_list(),
│   │   │                        #   run_node_version(), which()
│   │   ├── state.py             # DoctorStateManager; NpxToolMark → .doctor_state.yaml
│   │   └── managed.py           # get_doctor_managed_excludes(); DEFAULT_MANAGED_PATTERNS
│   ├── config/                  # (see above)
│   ├── git/                     # Git operations
│   │   ├── __init__.py          # Exports commit, push, pull, stage_all, get_remote_status, has_uncommitted_changes
│   │   ├── operations.py        # Git CLI wrappers (no shell=True; list[str] argv)
│   │   └── resolve.py           # DivergenceStrategy enum, prompt_divergence_strategy(),
│   │                            #   apply_divergence_strategy()
│   ├── output/                  # Terminal rendering (Rich)
│   │   ├── __init__.py          # Exports Console, show_diff
│   │   ├── console.py           # Console class: print_sync_result(), print_status(),
│   │   │                        #   print_categories_list(), print_integrations_status(),
│   │   │                        #   resolve_conflict(), confirm()
│   │   ├── diff.py              # show_diff() unified diff display
│   │   └── merge.py             # interactive_merge(), edit_in_editor()
│   ├── integrations/            # External tool integrations
│   │   ├── __init__.py
│   │   ├── detectors.py         # AntigravityDetector, ClaudeDesktopDetector
│   │   ├── antigravity.py       # migrate_skills_to_prompts()
│   │   └── claude_desktop.py    # register_trusted_folder()
│   ├── transfer/                # ZIP export/import
│   │   ├── __init__.py
│   │   ├── exporter.py          # Exporter: scan_available_items(), export_to_zip()
│   │   ├── importer.py          # Importer: load_manifest(), apply()
│   │   ├── manifest.py          # TransferManifest Pydantic model
│   │   └── ui.py                # interactive_export_selection(), interactive_import_selection()
│   ├── convert/                 # Shell config conversion
│   │   ├── __init__.py          # Exports FishToPwshConverter
│   │   ├── fish_to_pwsh.py      # FishToPwshConverter: convert_directory(), ConversionReport
│   │   ├── rules.py             # Fish → PowerShell conversion rules
│   │   └── templates.py         # PowerShell output templates
│   ├── docs/                    # Hub README generation
│   │   ├── __init__.py
│   │   └── generator.py         # DocsGenerator: generate(), render_readme(), DocsResult
│   └── utils/                   # Shared low-level helpers
│       ├── __init__.py
│       ├── paths.py             # safe_copy(), atomic_write(), create_backup(),
│       │                        #   find_files(), ensure_dir()
│       ├── hashing.py           # hash_file(), hash_content() — SHA-256
│       ├── platform.py          # get_current_platform(), is_shell_available(),
│       │                        #   is_platform_match(), get_platform_skipped_categories()
│       └── logging.py           # configure_logging(), get_logger()
├── tests/                       # Test suite
│   ├── conftest.py              # Pytest fixtures (tmp_path, mock configs, etc.)
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_sync.py
│   ├── test_doctor.py
│   ├── test_git_operations.py
│   ├── test_git_resolve.py
│   ├── test_convert.py
│   ├── test_transfer.py
│   ├── test_integrations.py
│   ├── test_migration.py
│   ├── test_settings.py
│   ├── test_merge.py
│   ├── test_diff.py
│   ├── test_console.py
│   ├── test_hashing.py
│   ├── test_platform.py
│   ├── test_platform_utils.py
│   ├── test_paths_atomic.py
│   ├── test_paths_security.py
│   ├── test_conflict_resolution.py
│   ├── test_importer_security.py
│   └── test_docs.py
├── docs/                        # Project documentation (Markdown)
│   └── usage/                   # Usage guides (sync.md, memory-bridge.md, etc.)
├── .claude/                     # Claude Code local config
│   ├── commands/                # Project-specific slash commands
│   └── skills/                  # Project-specific skills
├── .planning/                   # GSD planning artefacts
│   └── codebase/                # Codebase map documents (this directory)
├── pyproject.toml               # Single source of truth for deps, build, tools
├── CLAUDE.md                    # Project instructions for Claude Code
└── .worktrees/                  # Git worktrees for feature branches
    └── memory-bridge/           # Inactive worktree (memory bridge feature)
```

## Directory Purposes

**`sccs/` (package root):**
- `__init__.py`: Version constant (`2.28.1`), lazy `__getattr__` for heavy imports
- `__main__.py`: Enables `python -m sccs`; calls `main()` from `cli.py`
- `cli.py`: Monolithic CLI module — all Click groups and command implementations live here. Functions `_collect_doctor_statuses()` and `_load_doctor_config()` are module-level helpers that aggregate detector calls before passing to installer/reporter.

**`sccs/config/`:**
- `schema.py`: All Pydantic config models. Import `SccsConfig` from here.
- `loader.py`: `load_config()` returns `SccsConfig`; `load_raw_user_data()` returns raw dict for migration checks; `validate_config_file()` returns `(bool, list[str])`
- `defaults.py`: `generate_default_config()` returns default YAML string (used by `sccs config init`)
- `migration.py`: `detect_new_categories(raw_data)`, `get_categories_to_offer(raw_data, mgr)`, `MigrationStateManager` (persists to `~/.config/sccs/.migration_state.yaml`)

**`sccs/sync/`:**
- `engine.py`: `SyncEngine` is instantiated per CLI invocation with `SccsConfig`. Calls `get_doctor_managed_excludes()` at init to merge into `effective_global_exclude`.
- `category.py`: `CategoryHandler` holds one `SyncCategory` config + `StateManager`. `detect_changes()` returns `list[SyncAction]`. `execute_actions()` writes files.
- `state.py`: `StateManager` loads/saves `~/.config/sccs/.sync_state.yaml`. Keys are `"category:item_name"`.
- `settings.py`: `SettingsEnsurer.ensure()` patches JSON settings files post-sync (e.g. VS Code settings.json). Called by CategoryHandler when `SyncCategory.settings_ensure` is set.

**`sccs/doctor/`:**
- `schema.py`: Pydantic specs are the config-facing contract. All field validators enforce a security allowlist (`_SAFE_NAME_PATTERN`). `DoctorConfig.effective_*()` methods merge user overrides with bundled defaults.
- `defaults.py`: Bundled baselines — hardcoded `DEFAULT_CLAUDE_PLUGINS` and `DEFAULT_NPX_TOOLS` (e.g. `get-shit-done-cc`, `@playwright/cli`). `get_node_install_spec(platform)` returns platform-specific `NodeInstallSpec`.
- `detectors.py`: Each detector class has one or two public methods (`get_status()` or `get_statuses(specs)`). All return `@dataclass` instances — never raise on "not found", return status objects with `installed=False` / `available=False`.
- `installer.py`: `DoctorAction` is the central abstraction. `build_install_plan()` inspects status objects and emits actions. `execute_plan()` processes them sequentially, maintaining `blocked_components: set[str]` to skip cascade-dependent actions.
- `managed.py`: `DEFAULT_MANAGED_PATTERNS` lists glob patterns for files written by doctor-installed tools (e.g. `gsd-*` skills). `get_doctor_managed_excludes(doctor_cfg)` merges these with `doctor_cfg.managed_excludes`.

**`sccs/git/`:**
- `operations.py`: All git commands use `subprocess.run(["git", ...], ...)` pattern. `get_remote_status()` returns `dict` with `behind`, `ahead`, `diverged`, `up_to_date` keys.
- `resolve.py`: `DivergenceStrategy` enum (`ABORT`, `PULL_REBASE`, `MERGE`, `PUSH_FORCE_WITH_LEASE`). In non-TTY contexts `prompt_divergence_strategy()` auto-returns `ABORT`.

**`sccs/integrations/`:**
- `detectors.py`: `AntigravityDetector.get_info()` checks `~/.antigravity/`; `get_skill_gaps()` returns skills in `~/.claude/skills/` not yet mirrored. `ClaudeDesktopDetector.get_info()` reads Claude Desktop config JSON; `is_repo_trusted()` checks `localAgentModeTrustedFolders`.

**`sccs/transfer/`:**
- Security note: `importer.py` validates all paths inside the ZIP against a traversal allowlist (see `test_importer_security.py`). Archives must contain a `manifest.json` (validated by `TransferManifest`).

**`sccs/utils/`:**
- `paths.py`: `atomic_write()` writes to a `.tmp` sibling then renames — no partial writes. `create_backup()` appends `.bak` suffix with category tag.
- `platform.py`: Returns `"macos"`, `"linux"`, or `"windows"`. Used by both sync platform filtering and doctor node-install hint selection.

## Key File Locations

**Entry Points:**
- `sccs/__main__.py`: `python -m sccs` entry
- `sccs/cli.py:main()` (line 1679): `cli(obj={})` — Click root
- `sccs/cli.py:cli` (line 67): Click group definition with global `-v` / `--no-color` flags

**Configuration:**
- `pyproject.toml`: All build metadata, dependencies (`click`, `rich`, `pydantic`, `pyyaml`, `questionary`), optional `[dev]` extras, ruff + mypy config
- `~/.config/sccs/config.yaml`: Runtime user config (not in repo)

**Core Logic:**
- `sccs/sync/engine.py`: `SyncEngine.sync()` — main sync orchestration
- `sccs/sync/category.py`: `CategoryHandler.detect_changes()` — diff logic
- `sccs/doctor/installer.py`: `build_install_plan()`, `execute_plan()` — doctor mutation logic
- `sccs/doctor/detectors.py`: All 9 detector classes — doctor read-only logic
- `sccs/config/schema.py:174`: `SccsConfig` — root config model

**State Files (runtime, not in repo):**
- `~/.config/sccs/.sync_state.yaml`: Sync item hashes
- `~/.config/sccs/.doctor_state.yaml`: Npx tool install marks
- `~/.config/sccs/.migration_state.yaml`: Adopted/declined categories

**Testing:**
- `tests/conftest.py`: Shared fixtures
- `tests/test_doctor.py`: Doctor cascade tests (122+ tests as of v2.28.1)
- `tests/test_sync.py`: SyncEngine + CategoryHandler tests
- `tests/test_importer_security.py`: ZIP path-traversal security tests
- `tests/test_paths_security.py`: Path utility security tests

## Naming Conventions

**Files:**
- Snake_case module names: `fish_to_pwsh.py`, `actions.py`, `engine.py`
- No `_impl` / `_base` suffixes — one implementation per module
- Test files: `test_<module_name>.py` in `tests/` (flat, not mirroring package structure)

**Classes:**
- Pydantic models: PascalCase + descriptive suffix (`SccsConfig`, `SyncCategory`, `DoctorConfig`, `PluginSpec`, `NpxToolSpec`)
- Dataclasses: PascalCase (`SyncAction`, `SyncResult`, `DoctorAction`, `NodeStatus`, `ItemState`)
- Click groups: `@cli.group("name")` with `_group` suffix on the Python function (`doctor_group`, `convert_group`, `integrations_group`)
- Detector classes: `<Subject>Detector` (`NodeDetector`, `ClaudePluginDetector`, `PermissionDetector`)
- Status dataclasses: `<Subject>Status` (`NodeStatus`, `PluginStatus`, `NpxToolStatus`)

**Functions:**
- Private helpers in `cli.py`: `_collect_doctor_statuses()`, `_load_doctor_config()`, `_run_migration_check()`, `_interactive_migration_prompt()`
- Validator methods in Pydantic models: `_validate_<field>()` (class methods decorated with `@field_validator`)
- Public CLI callbacks: named after the command (`sync`, `status`, `diff`, `doctor_check`, `doctor_install`)

**Constants:**
- `DEFAULT_*` prefix for bundled baselines in `doctor/defaults.py`
- `_SAFE_*_PATTERN` for security allowlist regexes (private, module-level)

## Where to Add New Code

**New CLI command:**
- Add `@cli.command("name")` or `@cli.group("name")` in `sccs/cli.py`
- Follow existing pattern: load config, create engine/detector, display via `console`
- Add tests in `tests/test_cli.py`

**New sync category (config default):**
- Add entry to `DEFAULT_SYNC_CATEGORIES` in `sccs/config/defaults.py`
- The migration system will detect and offer it to existing users automatically via `detect_new_categories()`

**New doctor detector:**
1. Add Pydantic spec model to `sccs/doctor/schema.py` (follow `PluginSpec` / `NpxToolSpec` pattern with `_SAFE_NAME_PATTERN` validation)
2. Add default list to `sccs/doctor/defaults.py`
3. Add `effective_<name>()` method to `DoctorConfig` in `sccs/doctor/schema.py`
4. Add `@dataclass` status class and detector class to `sccs/doctor/detectors.py`
5. Add action-building function to `sccs/doctor/installer.py`
6. Add rendering rows to `sccs/doctor/reporter.py`
7. Wire into `_collect_doctor_statuses()` and all three doctor commands in `sccs/cli.py`

**New utility helper:**
- File-system operations: `sccs/utils/paths.py`
- Content hashing: `sccs/utils/hashing.py`
- Platform checks: `sccs/utils/platform.py`
- Logging: `sccs/utils/logging.py`

**New external integration:**
- Add detector class to `sccs/integrations/detectors.py`
- Add action module (e.g. `sccs/integrations/myapp.py`)
- Wire into `sccs/cli.py` integrations group

**New transfer format feature:**
- Exporter changes: `sccs/transfer/exporter.py`
- Importer changes: `sccs/transfer/importer.py`; always add security test to `tests/test_importer_security.py`

## Special Directories

**`.planning/`:**
- Purpose: GSD planning artefacts (phases, codebase maps)
- Generated: Partially (by GSD tools)
- Committed: Yes

**`.worktrees/memory-bridge/`:**
- Purpose: Git worktree for memory bridge feature branch
- Contains its own copy of the `sccs/` package with additional `memory/` module
- Status: Inactive / experimental; not part of main build

**`.claude/`:**
- Purpose: Claude Code project-local config (commands + skills)
- Committed: Yes (part of the SCCS sync payload itself)

**`dist/`:**
- Purpose: Built wheel/sdist artifacts from `uv build`
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-05-11*
