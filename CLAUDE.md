# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sccs** (SkillsCommandsConfigsSync) is a bidirectional synchronization tool for Claude Code skills, commands, and configuration files between local (`~/.claude/`) and a Git repository.

### Sync Targets

- **Main Sync**: `~/.claude/` ↔ `.claude/` (bidirectional)
- **Config Sync**: Settings and framework files with path transformation

## Commands

### Development Setup

```bash
uv venv
source .venv/bin/activate  # or: venv+
uv pip install -e ".[dev]"
```

### Run CLI

```bash
# Main sync
sccs sync --dry-run
sccs status
sccs diff <skill-name>

# Config sync
sccs config sync --dry-run
sccs config status
```

### Testing

```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest --cov=sccs         # With coverage
pytest tests/test_specific.py  # Single test file
```

### Code Quality

```bash
black sccs/ tests/        # Format code
isort sccs/ tests/        # Sort imports
mypy sccs/                # Type checking
```

## Architecture

```
sccs/
├── cli.py          # Click CLI entry point with command groups
├── sync_engine.py  # Core bidirectional sync logic (SyncEngine)
├── config_sync.py  # Config file sync with path transformation
├── skill.py        # Skill model (directories with SKILL.md)
├── command.py      # Command model (single .md files)
├── state.py        # Sync state persistence (.sync_state.json)
├── config.py       # Path constants and repo detection
├── user_config.py  # User configuration (~/.config/sccs/)
├── diff.py         # Diff display and conflict resolution
├── logger.py       # Rich console output
└── git.py          # Git auto-commit operations
```

### Key Concepts

**Skills** are directories containing `SKILL.md` (required) and optionally `content.md`:
```
skill-name/
├── SKILL.md      # YAML frontmatter + content
└── content.md    # Optional extended reference
```

**Commands** are single Markdown files with optional YAML frontmatter:
```
command-name.md   # YAML frontmatter + content
```

### Sync Flow

1. `SyncEngine` scans local and repo directories
2. Compares mtimes and content hashes with stored state
3. Classifies each item: `UNCHANGED`, `COPY_TO_REPO`, `COPY_TO_LOCAL`, `CONFLICT`, `NEW_*`, `DELETED_*`
4. Executes actions (with conflict resolution if needed)
5. Updates `.sync_state.json` and `SYNC_LOG.md`

### Path Transformation (Config Sync)

The `PathTransformer` class converts machine-specific paths to portable placeholders:
- `{{HOME}}` → `/Users/username` or `/home/username`
- `{{CLAUDE_DIR}}` → `~/.claude`
- `{{WORKSPACE_DIR}}` → `~/gitbase` or `CLAUDE_WORKSPACE_DIR` env var

Used when syncing `settings.json` (stored as `settings.template.json` in repo).

## CLI Command Groups

The CLI uses Click with two command groups:

- **Root**: `sync`, `status`, `diff`, `log`, `init`
- **`config`**: `sync`, `status`, `export`, `import`, `show-paths`, `check`

## User Configuration

Configuration is stored in `~/.config/sccs/config.json`:

```json
{
  "repo_url": "git@github.com:user/repo.git",
  "local_skills_path": "~/.claude/commands",
  "local_commands_path": "~/.claude/commands",
  "repo_skills_path": ".claude/commands",
  "repo_commands_path": ".claude/commands"
}
```

On first run, `sccs` will prompt for the repository URL.

## State Files

- `.sync_state.json` - Tracks last sync state (mtimes, content hashes)
- `.config_sync_state.json` - Tracks config file sync state
- `SYNC_LOG.md` - Human-readable sync history

## Environment Variables

- `SCCS_REPO` - Override repository root detection
- `CLAUDE_WORKSPACE_DIR` - Override workspace directory for path transformation
