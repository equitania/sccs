# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sccs** (SkillsCommandsConfigsSync) is a unified YAML-configured bidirectional synchronization tool for Claude Code files and optional shell configurations.

**Version**: 2.45.0

### Key Features

- **Unified YAML Configuration**: Single `config.yaml` with all sync categories
- **Flexible Categories**: Claude skills, commands, hooks, scripts, fish config, etc.
- **Bidirectional Sync**: Full two-way synchronization with conflict detection
- **Git Integration**: Auto-commit and push after sync operations
- **Doctor Update-Check** (v2.42.0): `sccs doctor check` flags OUTDATED plugins/npx tools when a newer version exists upstream (`npm view` for npm-backed tools, marketplace manifest for plugins); informational only, `--no-update-check` for offline mode

## Commands

### Development Setup

```bash
uv venv
source .venv/bin/activate  # or: venv+
uv pip install -e ".[dev]"
```

### Run CLI

```bash
# Main commands
sccs sync                    # Sync all enabled categories
sccs sync --category skills  # Sync specific category
sccs sync --dry-run          # Preview changes
sccs status                  # Show status
sccs diff <item> -c <cat>    # Show diff for item

# Configuration
sccs config show             # Show current config
sccs config init             # Create new config
sccs config validate         # Validate config
sccs config upgrade          # Adopt new default categories interactively

# Categories
sccs categories              # List categories
sccs categories enable fish  # Enable category
sccs categories disable fish # Disable category
```

### Testing

```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest --cov=sccs         # With coverage
pytest tests/test_config.py  # Single test file
```

### Code Quality

```bash
ruff check sccs/ tests/   # Lint code
ruff format sccs/ tests/  # Format code
mypy sccs/                # Type checking
```

## Architecture

```
sccs/
├── __init__.py           # Version, lazy imports
├── __main__.py           # Entry point for python -m sccs
├── cli.py                # Click CLI with command groups (largest file)
├── config/
│   ├── schema.py         # Pydantic models (SccsConfig, SyncCategory)
│   ├── loader.py         # YAML loading/saving/validation
│   ├── defaults.py       # Default configuration
│   └── migration.py      # New-category detection, MigrationStateManager
├── sync/
│   ├── item.py           # SyncItem model, scan functions
│   ├── actions.py        # ActionType enum, SyncAction, execute_action
│   ├── state.py          # SyncState, StateManager
│   ├── category.py       # CategoryHandler, CategoryStatus
│   ├── settings.py       # settings.json deep-merge sync (atomic, 0600)
│   └── engine.py         # SyncEngine (main orchestrator)
├── doctor/               # System/plugin health checks (largest subsystem)
│   ├── defaults.py       # Hardcoded plugin/npx-tool/permission-check defaults
│   ├── schema.py         # DoctorConfig, PluginSpec, NpxToolSpec, validators
│   ├── runner.py         # subprocess(shell=False, stdin=DEVNULL) + allowlist
│   ├── detectors.py      # Node/CLI/plugin/npx-tool/permission detectors
│   ├── installer.py      # build_install_plan / build_update_plan / execute_plan
│   ├── state.py          # DoctorStateManager (.doctor_state.yaml)
│   ├── reporter.py       # Rich status table + chown fix block
│   ├── managed.py        # DEFAULT_MANAGED_PATTERNS (gsd-* exclude from sync)
│   └── _paths.py         # is_home_path helper (avoids import cycle)
├── transfer/             # ZIP export/import
│   ├── manifest.py       # Pydantic models for ZIP manifest
│   ├── exporter.py       # Scan + ZIP creation
│   ├── importer.py       # ZIP extraction (zip-slip + symlink rejection)
│   └── ui.py             # questionary checkbox helpers
├── integrations/         # Antigravity IDE + Claude Desktop + OpenCode + Pi
│   ├── detectors.py      # AntigravityDetector, ClaudeDesktopDetector
│   ├── antigravity.py    # Skill→Prompt migration logic
│   ├── claude_desktop.py # Trusted-folder registration
│   ├── opencode.py       # OpenCodeDetector, agent/command convert, MCP merge
│   └── pi.py             # PiDetector, skill/agent/command export (pi.dev, verbatim copy)
├── convert/              # Fish → PowerShell profile conversion
│   ├── fish_to_pwsh.py   # Converter entry
│   ├── rules.py          # alias/set/fish_add_path translation rules
│   └── templates.py      # PowerShell profile templates
├── docs/
│   └── generator.py      # Hub README auto-generation
├── git/
│   ├── operations.py     # Git commands (commit, push, pull, status; validated)
│   └── resolve.py        # Interactive divergence resolver
├── output/
│   ├── console.py        # Rich console output
│   ├── diff.py           # Diff display and conflict resolution
│   └── merge.py          # Editor-based 3-way merge (atomic, 0600 buffer)
└── utils/
    ├── paths.py          # safe_copy, atomic_write (mode=), expand_path
    ├── hashing.py        # Content hashing (SHA256)
    ├── logging.py        # configure_logging, get_logger
    └── platform.py       # OS detection helpers

tests/                    # 24 test files; test_doctor.py is the largest
├── conftest.py           # Pytest fixtures
├── test_config.py        # Config tests
├── test_sync.py          # Sync engine tests
├── test_doctor.py        # Doctor subsystem (largest suite)
├── test_transfer.py      # ZIP export/import
├── test_importer_security.py  # Zip-slip / symlink rejection
├── test_paths_atomic.py  # atomic_write cross-platform + mode perms
└── ...                   # git, integrations, convert, settings, conflicts
```

### Key Classes

**SccsConfig** (config/schema.py): Root configuration model
```python
config = SccsConfig.model_validate(yaml_data)
enabled = config.get_enabled_categories()
```

**SyncCategory** (config/schema.py): Category configuration
```python
cat = SyncCategory(
    local_path="~/.claude/skills",
    repo_path=".claude/skills",
    item_type=ItemType.DIRECTORY,
    item_marker="SKILL.md",
)
```

**SyncEngine** (sync/engine.py): Main synchronization orchestrator
```python
engine = SyncEngine(config)
result = engine.sync(dry_run=True)
statuses = engine.get_status()
```

**CategoryHandler** (sync/category.py): Handles single category
```python
handler = engine.get_handler("claude_skills")
items = handler.scan_items()
actions = handler.detect_changes()
```

**StateManager** (sync/state.py): Persists sync state
```python
manager = StateManager()
hash = manager.get_item_hash("skills", "my-skill")
manager.update_item("skills", "my-skill", content_hash="...")
```

### Sync Flow

1. **Load Config**: YAML → SccsConfig (Pydantic validation)
2. **Create Engine**: SyncEngine with config and StateManager
3. **Scan Items**: CategoryHandler scans local and repo paths
4. **Detect Changes**: Compare current state with stored state
5. **Generate Actions**: Determine COPY_TO_REPO, COPY_TO_LOCAL, CONFLICT, etc.
6. **Execute Actions**: Perform file operations (or dry-run)
7. **Update State**: Save new hashes and timestamps

### Item Types

- **file**: Individual files (pattern: `*.md`)
- **directory**: Directories with marker file (marker: `SKILL.md`)
- **mixed**: Both files and directories

### Sync Modes

- **bidirectional**: Two-way sync (default)
- **local_to_repo**: Only push local changes
- **repo_to_local**: Only pull repo changes

## Configuration

Configuration is stored in `~/.config/sccs/config.yaml`:

```yaml
repository:
  path: ~/gitbase/sccs-sync
  auto_commit: false
  auto_push: false

sync_categories:
  claude_skills:
    enabled: true
    local_path: ~/.claude/skills
    repo_path: .claude/skills
    sync_mode: bidirectional
    item_type: directory
    item_marker: SKILL.md

global_exclude:
  - ".DS_Store"
  - "*.tmp"
```

## Environment Variables

- `SCCS_CONFIG` - Override config file path
- `HOME` - User home directory (for path expansion)

## State Files

- `~/.config/sccs/.sync_state.yaml` - Tracks last sync state
- `~/.config/sccs/sync.log` - Log file (if configured)
