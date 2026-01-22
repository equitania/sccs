# SCCS - SkillsCommandsConfigsSync

Unified YAML-configured bidirectional synchronization tool for Claude Code files and optional shell configurations.

## Features

- **Unified YAML Configuration**: Single `config.yaml` with all sync categories
- **Flexible Categories**: Sync Claude skills, commands, hooks, scripts, and more
- **Optional Shell Configs**: Fish shell, Starship prompt, and custom configs
- **Bidirectional Sync**: Full two-way synchronization with conflict detection
- **Git Integration**: Auto-commit and push after sync operations
- **Rich Console Output**: Beautiful terminal output with Rich
- **Path Transformation**: Machine-independent configuration files

## Installation

```bash
pip install sccs
```

Or with UV (recommended):

```bash
uv pip install sccs
```

For development:

```bash
git clone https://github.com/equitania/sccs.git
cd sccs
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Quick Start

```bash
# Initialize configuration
sccs config init

# Show sync status
sccs status

# Preview changes
sccs sync --dry-run

# Synchronize all enabled categories
sccs sync

# Sync specific category
sccs sync --category claude_skills
```

## Configuration

Configuration is stored in `~/.config/sccs/config.yaml`:

```yaml
# Repository settings
repository:
  path: ~/gitbase/sccs-sync
  remote: origin
  auto_commit: false
  auto_push: false
  commit_prefix: "[SYNC]"

# Sync categories
sync_categories:
  claude_framework:
    enabled: true
    description: "SuperClaude Framework files"
    local_path: ~/.claude
    repo_path: .claude/framework
    sync_mode: bidirectional
    item_type: file
    include:
      - "CLAUDE.md"
      - "PERSONAS.md"
      # ... more files

  claude_skills:
    enabled: true
    local_path: ~/.claude/skills
    repo_path: .claude/skills
    sync_mode: bidirectional
    item_type: directory
    item_marker: SKILL.md

  fish_config:
    enabled: true
    local_path: ~/.config/fish
    repo_path: .config/fish
    sync_mode: bidirectional
    item_type: mixed
    include:
      - "config.fish"
      - "functions/*.fish"
    exclude:
      - "fish_history"
      - "*.local.fish"
```

## Configuration Reference

The complete structure of `~/.config/sccs/config.yaml`:

```yaml
# ═══════════════════════════════════════════════════════════════
# SCCS Configuration File
# ═══════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────
# Repository Settings
# ─────────────────────────────────────────────────────────────────
repository:
  path: ~/gitbase/sccs-sync      # Local repository path
  remote: origin                  # Git remote name for push
  auto_commit: false              # Auto-commit after sync
  auto_push: false                # Auto-push after commit
  commit_prefix: "[SYNC]"         # Prefix for commit messages

# ─────────────────────────────────────────────────────────────────
# Sync Categories
# Each category defines what to sync and how
# ─────────────────────────────────────────────────────────────────
sync_categories:

  # Example: Claude Skills (directories with marker file)
  claude_skills:
    enabled: true                 # Enable/disable this category
    description: "Claude Code Skills"
    local_path: ~/.claude/skills  # Source path (supports ~)
    repo_path: .claude/skills     # Destination in repository
    sync_mode: bidirectional      # bidirectional | local_to_repo | repo_to_local
    item_type: directory          # file | directory | mixed
    item_marker: SKILL.md         # Marker file for directory items
    include:                      # Glob patterns to include
      - "*"
    exclude:                      # Glob patterns to exclude
      - "_archive/*"
      - "*.tmp"

  # Example: Claude Commands (single files)
  claude_commands:
    enabled: true
    description: "Claude Code Commands"
    local_path: ~/.claude/commands
    repo_path: .claude/commands
    sync_mode: bidirectional
    item_type: file
    item_pattern: "*.md"          # File pattern for file items
    include:
      - "*"
    exclude:
      - "_*.md"                   # Private commands
      - "*.local.md"              # Local overrides

  # Example: Fish Shell (mixed files and directories)
  fish_config:
    enabled: true
    description: "Fish Shell Configuration"
    local_path: ~/.config/fish
    repo_path: .config/fish
    sync_mode: bidirectional
    item_type: mixed              # Both files and directories
    include:
      - "config.fish"
      - "functions/*.fish"
      - "conf.d/*.fish"
    exclude:
      - "fish_history"            # Never sync history
      - "fish_variables"          # Machine-specific
      - "*.local.fish"            # Local overrides

# ─────────────────────────────────────────────────────────────────
# Global Excludes (apply to all categories)
# ─────────────────────────────────────────────────────────────────
global_exclude:
  - ".DS_Store"
  - "*.swp"
  - "*~"
  - ".git"
  - "__pycache__"
  - "*.pyc"
  - ".env"
  - "*.local"
  - "*.local.*"

# ─────────────────────────────────────────────────────────────────
# Conflict Resolution
# ─────────────────────────────────────────────────────────────────
conflict_resolution:
  default: prompt                 # prompt | local | repo | newest
  per_category:
    claude_framework: repo        # Framework always from repo
    fish_config: local            # Local fish config wins

# ─────────────────────────────────────────────────────────────────
# Path Transformations (for machine-independent configs)
# ─────────────────────────────────────────────────────────────────
path_transforms:
  placeholders:
    HOME: "{{HOME}}"
    USER: "{{USER}}"
    HOSTNAME: "{{HOSTNAME}}"
  transform_files:
    - pattern: "settings.template.json"
      source: "settings.json"

# ─────────────────────────────────────────────────────────────────
# Output Settings
# ─────────────────────────────────────────────────────────────────
output:
  verbose: false
  colored: true
  log_file: ~/.config/sccs/sync.log
  sync_history: ~/.config/sccs/history.yaml
```

### Category Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | bool | No | Enable/disable category (default: true) |
| `description` | string | No | Human-readable description |
| `local_path` | string | **Yes** | Local source path (supports `~`) |
| `repo_path` | string | **Yes** | Path in repository |
| `sync_mode` | string | No | `bidirectional`, `local_to_repo`, `repo_to_local` |
| `item_type` | string | No | `file`, `directory`, `mixed` (default: file) |
| `item_marker` | string | No | Marker file for directory items (e.g., `SKILL.md`) |
| `item_pattern` | string | No | Glob pattern for file items (e.g., `*.md`) |
| `include` | list | No | Patterns to include (default: `["*"]`) |
| `exclude` | list | No | Patterns to exclude (default: `[]`) |

## CLI Commands

### Main Commands

```bash
# Synchronize files
sccs sync                    # Sync all enabled categories
sccs sync --category skills  # Sync specific category
sccs sync --dry-run          # Preview without changes
sccs sync --force local      # Force local version in conflicts
sccs sync --force repo       # Force repo version in conflicts

# Status and diff
sccs status                  # Show status of all categories
sccs status --category fish  # Status of specific category
sccs diff <item> --category <cat>  # Show diff for item

# History
sccs log                     # Show sync history
sccs log --last 20           # Show last 20 entries
```

### Configuration Commands

```bash
sccs config show             # Show current configuration
sccs config init             # Create new configuration
sccs config init --force     # Overwrite existing config
sccs config edit             # Open config in editor
sccs config validate         # Validate configuration
```

### Category Management

```bash
sccs categories              # List all categories (alias: list)
sccs categories --all        # Include disabled categories
sccs categories enable fish  # Enable a category
sccs categories disable fish # Disable a category
```

## Sync Categories

### Claude Code Categories (enabled by default)

| Category | Path | Description |
|----------|------|-------------|
| `claude_framework` | `~/.claude/*.md` | SuperClaude Framework files |
| `claude_skills` | `~/.claude/skills/` | Skills (directories with SKILL.md) |
| `claude_commands` | `~/.claude/commands/` | Commands (single .md files) |
| `claude_hooks` | `~/.claude/hooks/` | Event handler scripts |
| `claude_scripts` | `~/.claude/scripts/` | Utility scripts |
| `claude_plugins` | `~/.claude/plugins/` | Plugin configurations |
| `claude_mcp` | `~/.claude/mcp/` | MCP server configs |

### Shell Categories (enabled by default)

| Category | Path | Description |
|----------|------|-------------|
| `fish_config` | `~/.config/fish/` | Fish shell configuration |
| `fish_functions` | `~/.config/fish/functions/` | Fish custom functions |
| `starship_config` | `~/.config/starship.toml` | Starship prompt |

### Optional Categories (disabled by default)

| Category | Path | Description |
|----------|------|-------------|
| `claude_plans` | `~/.claude/plans/` | Session plans |
| `claude_todos` | `~/.claude/todos/` | Persistent TODO lists |
| `git_config` | `~/.gitconfig` | Git configuration |
| `project_templates` | Custom | Project templates |

## Sync Modes

Each category can use one of three sync modes:

- **bidirectional**: Changes flow both ways (default)
- **local_to_repo**: Only push local changes to repository
- **repo_to_local**: Only pull repository changes locally

## Item Types

Categories can contain different item types:

- **file**: Individual files (e.g., `*.md`, `config.fish`)
- **directory**: Directories with marker file (e.g., skills with `SKILL.md`)
- **mixed**: Both files and directories

## Conflict Resolution

When both local and repo have changes:

```yaml
conflict_resolution:
  default: prompt              # prompt | local | repo | newest
  per_category:
    claude_framework: repo     # Framework always from repo
    fish_config: local         # Local fish config wins
```

Or use force flags:
```bash
sccs sync --force local   # Local wins all conflicts
sccs sync --force repo    # Repository wins all conflicts
```

## Directory Structure

### Local

```
~/.claude/
├── CLAUDE.md, PERSONAS.md, ...  # Framework files
├── skills/
│   └── my-skill/
│       └── SKILL.md
├── commands/
│   └── my-command.md
├── hooks/
├── scripts/
└── mcp/

~/.config/
├── fish/
│   ├── config.fish
│   └── functions/
└── starship.toml
```

### Repository

```
repo/
├── .claude/
│   ├── framework/    # Framework files
│   ├── skills/       # Skills
│   ├── commands/     # Commands
│   └── ...
└── .config/
    ├── fish/         # Fish config
    └── starship.toml # Starship config
```

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=sccs

# Format code
black sccs/ tests/
isort sccs/ tests/

# Type checking
mypy sccs/
```

## License

AGPL-3.0 - Equitania Software GmbH
