# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sccs** (SkillsCommandsConfigsSync) is a unified YAML-configured bidirectional synchronization tool for Claude Code files and optional shell configurations.

**Version**: 2.6.0

### Key Features

- **Unified YAML Configuration**: Single `config.yaml` with all sync categories
- **Flexible Categories**: Claude skills, commands, hooks, scripts, fish config, etc.
- **Bidirectional Sync**: Full two-way synchronization with conflict detection
- **Git Integration**: Auto-commit and push after sync operations

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
├── cli.py                # Click CLI with command groups
├── config/
│   ├── __init__.py       # Config module exports
│   ├── schema.py         # Pydantic models (SccsConfig, SyncCategory)
│   ├── loader.py         # YAML loading/saving/validation
│   └── defaults.py       # Default configuration
├── sync/
│   ├── __init__.py       # Sync module exports
│   ├── item.py           # SyncItem model, scan functions
│   ├── actions.py        # ActionType enum, SyncAction, execute_action
│   ├── state.py          # SyncState, StateManager
│   ├── category.py       # CategoryHandler, CategoryStatus
│   └── engine.py         # SyncEngine (main orchestrator)
├── git/
│   ├── __init__.py       # Git module exports
│   └── operations.py     # Git commands (commit, push, status)
├── output/
│   ├── __init__.py       # Output module exports
│   ├── console.py        # Rich console output
│   └── diff.py           # Diff display and conflict resolution
└── utils/
    ├── __init__.py       # Utils module exports
    ├── paths.py          # Path utilities, safe_copy, find_files
    └── hashing.py        # Content hashing (SHA256)

tests/
├── conftest.py           # Pytest fixtures
├── test_config.py        # Config tests
└── test_sync.py          # Sync engine tests
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
