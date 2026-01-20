# SCCS - Skills, Commands, Configs Sync

Bidirectional synchronization tool for Claude Code skills, commands, and configuration files.

## Features

- **Bidirectional Sync**: Synchronize between local `~/.claude/` and a Git repository
- **Skills**: Directory-based skills with `SKILL.md` and optional `content.md`
- **Commands**: Single Markdown files with optional YAML frontmatter
- **Config Sync**: Settings and framework files with path transformation
- **Conflict Resolution**: Interactive resolution for conflicting changes
- **Git Integration**: Optional auto-commit and push after sync

## Installation

```bash
pip install sccs
```

Or with UV:

```bash
uv pip install sccs
```

## First Run Setup

On first run, SCCS will ask for your repository URL:

```bash
sccs status
# → Enter your skills repository URL: https://github.com/user/claude-skills.git
```

Configuration is stored in `~/.config/sccs/config.json`.

## Usage

### Basic Commands

```bash
# Show sync status
sccs status

# Synchronize skills and commands
sccs sync

# Preview changes without applying
sccs sync --dry-run

# Show diff for a specific skill
sccs diff my-skill

# Show diff for a command
sccs diff my-command --command
```

### Config Sync

```bash
# Show config status
sccs config status

# Sync configuration files
sccs config sync

# Export local config to repository
sccs config export

# Import config from repository
sccs config import

# Show path placeholder values
sccs config show-paths
```

### Options

```bash
# Force direction (skip prompts)
sccs sync --force local   # Local wins
sccs sync --force repo    # Repository wins

# Auto-commit changes
sccs sync --auto-commit

# Auto-commit and push
sccs sync --auto-commit --auto-push

# Verbose output
sccs sync --verbose
```

## Directory Structure

### Local (~/.claude/)
```
~/.claude/
├── skills/           # Skill directories
│   └── my-skill/
│       ├── SKILL.md
│       └── content.md
├── commands/         # Command files
│   └── my-command.md
└── settings.json     # Configuration
```

### Repository
```
repo/
├── .claude/
│   ├── skills/       # Synced skills
│   ├── commands/     # Synced commands
│   └── config/       # Configuration templates
├── .sync_state.json  # Sync state tracking
└── SYNC_LOG.md       # Sync history
```

## Path Placeholders

For portable configuration files, SCCS uses placeholders:

| Placeholder | Value |
|-------------|-------|
| `{{HOME}}` | `/Users/username` or `/home/username` |
| `{{CLAUDE_DIR}}` | `~/.claude` |
| `{{WORKSPACE_DIR}}` | `~/gitbase` or `CLAUDE_WORKSPACE_DIR` env var |
| `{{USERNAME}}` | Current username |

## Configuration

User configuration is stored in `~/.config/sccs/config.json`:

```json
{
  "repo_url": "https://github.com/user/claude-skills.git",
  "repo_path": "/path/to/local/repo",
  "auto_commit": false,
  "auto_push": false
}
```

## License

AGPL-3.0 - Equitania Software GmbH
