# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sccs** (SkillsCommandsConfigsSync) is a unified YAML-configured bidirectional synchronization tool for Claude Code files and optional shell configurations.

**Version**: 2.69.0

### Key Features

- **Unified YAML Configuration**: Single `config.yaml` with all sync categories
- **Flexible Categories**: Claude skills, commands, hooks, scripts, fish config, etc.
- **Bidirectional Sync**: Full two-way synchronization with conflict detection
- **Git Integration**: Auto-commit and push after sync operations

## Maintainer notes — read before touching the subsystem

Each line below names a rule that gets broken without it. The reasoning, the
incident behind it and the exact edge cases are in [`docs/development/maintainer-notes.md`](docs/development/maintainer-notes.md) —
**read the matching section there before changing that code**. The release
history lives in `RELEASE_NOTES.md`.

- **Trust ceilings** (`deploy/install.py`, `doctor/schema.py`): deploy without a config writes only inside default category roots; `post_install` runs only the tool's own binary, and only bundled steps skip the prompt. → [Security ceilings](docs/development/maintainer-notes.md#security-ceilings)
- **Optional npx tools** (`doctor/installer.py`): optional + absent = INFO, never installed or updated without `--with-optional`; a missing marketplace *with* a source is added by a runnable action, test via `execute_plan`. → [Doctor](docs/development/maintainer-notes.md#doctor)
- **Mirror parity** (`doctor/mirror.py`): the source never receives install/remove actions, a mirror never writes `inventory.yaml`; removals only under `optimize --strict` + `cleanup: true`; never `brew bundle cleanup` or bare `fisher update`. → [Doctor](docs/development/maintainer-notes.md#doctor)
- **Skill packages** (`doctor/skill_packages.py`): membership comes from `~/.agents/.skill-lock.json`, not a glob; `--copy` is load-bearing. → [Doctor](docs/development/maintainer-notes.md#doctor)
- **CAO provider patches** (`doctor/cao.py`): no provider source is ever bundled; `anchor_lost` is reported, never repaired; edits accumulate per file. → [Doctor](docs/development/maintainer-notes.md#doctor)
- **Profiles / statusline presets** (`doctor/profiles.py`, `doctor/statusline.py`): `installable_npx_tools()` is profile-aware, `effective_npx_tools()` stays blind; installers run as `bash <file>`, never `curl | bash`. → [Doctor](docs/development/maintainer-notes.md#doctor)
- **Fish coverage / statusline sync** (`config/defaults.py`, `sync/settings.py`): every fish file in exactly one enabled category; `item_pattern` is `statusline*` without the dot; `superseded_patterns` match by pattern. → [Sync categories](docs/development/maintainer-notes.md#sync-categories)
- **Deployment profiles** (`sccs/deploy/`): `pre_existing` is sticky, foreign targets are never written or removed, ownership is keyed on the resolved target path, `RECEIPT_VERSION` is 2. → [Deploy](docs/development/maintainer-notes.md#deploy)
- **Codex / Pi / OpenCode** (`sccs/integrations/`, `convert/`): skills go to `~/.agents/skills/`, hooks to `~/.codex/hooks.json` and never into `export-all`; `--replace-foreign` is not implied by `--overwrite`; the two frontmatter parsers stay different. → [Integrations](docs/development/maintainer-notes.md#integrations-codex-pi-opencode)
- **Capacity probe** (`sccs/capacity/`): never invent a number; `unknown` ≠ `tight`; Gemini tight → Codex, never Antigravity on Claude. → [Capacity](docs/development/maintainer-notes.md#capacity)
- **Converter literals** (`convert/`): fish single-quoted values stay literal; escape backticks and `$(` in double-quoted targets. → [Converters](docs/development/maintainer-notes.md#converters)

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

**Machine-readable output (v2.50.0)**: the Core-First commands accept `--json`
for GUI/automation consumption (single-line JSON via `click.echo`, never the
ANSI-forcing Rich Console): `status`, `categories list`, `config show`,
`config validate`, `sync` (incl. `--dry-run`), `diff`, `doctor check|install|update`.
`config init --repo-path PATH` runs non-interactively (bypasses the prompt).
See `sccs/output/json_emit.py`.

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

Module layout, key classes (`SccsConfig`, `SyncCategory`, `SyncEngine`,
`CategoryHandler`, `StateManager`), sync flow, item types and sync modes:
[`docs/development/code-map.md`](docs/development/code-map.md) — read it when
orienting in an unfamiliar part of the tree; `ls`/`grep` beat it when they disagree.

- **Subprocesses**: a new external command goes through `sccs/doctor/runner.py`
  (`shell=False`, `stdin=DEVNULL`, validated head). The few direct `subprocess.run`
  sites (`git/operations.py`, the editor in `cli.py` and `output/merge.py`,
  `doctor/statusline.py`, the `zsh -n` check in `convert/fish_to_zsh.py`) each use a
  fixed argv or a validated head — never add one that does neither, never `shell=True`.

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
