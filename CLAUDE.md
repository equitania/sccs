# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sccs** (SkillsCommandsConfigsSync) is a unified YAML-configured bidirectional synchronization tool for Claude Code files and optional shell configurations.

**Version**: 2.60.0

### Key Features

- **Unified YAML Configuration**: Single `config.yaml` with all sync categories
- **Flexible Categories**: Claude skills, commands, hooks, scripts, fish config, etc.
- **Bidirectional Sync**: Full two-way synchronization with conflict detection
- **Git Integration**: Auto-commit and push after sync operations

The notes below cover only what would be got *wrong* without them. The full
feature history — what each release added and why — lives in `RELEASE_NOTES.md`.

- **Capacity Probe** (v2.60.0): `sccs capacity [--json] [--offline]` (`sccs/capacity/`) reports remaining plan quota per agent CLI. Rules that must not be softened: **no number is ever invented** — Claude Code has no on-disk quota cache, so it is reported as `assumed`, not estimated; `_status()` keeps `unknown` distinct from `tight`, because missing data is not evidence of exhaustion and conflating them pushes work onto the billed API for no reason; `is_codex_exhausted()` requires null windows **and** an empty credit balance, since null windows alone are merely absent knowledge; and **Antigravity bills Gemini separately from the Claude/GPT models it resells**, so when Gemini is tight the fallback reviewer is **Codex, never Antigravity on a Claude model** — that would turn cross-review into self-review. Routing lives in code (`derive_routing`), not in a prompt, so it is testable and identical on every host.
- **Codex Hooks Export** (v2.59.0): `sccs integrations codex export-hooks` merges into `~/.codex/hooks.json` — the file Codex reads, **not** `~/.codex/hooks/hooks.json` (the plugin path, a standing trap). Three rules: serialization is **byte-stable** (Codex hashes each definition for its trust record, so incidental reordering forces the user back through `/hooks`); ownership is keyed on `(event, matcher, command)` in `~/.config/sccs/.codex_hooks_state.yaml`, and **SCCS may only replace a group it can account for completely** — the rule three data-loss reviews converged on; and it is deliberately **not** part of `export-all`, because hooks execute code on every matching tool call. Scripts are never copied. After any export the user must run `/hooks` in Codex.
- **Frontmatter parse split** (v2.58.4): `parse_frontmatter()` and `parse_frontmatter_ex()` have deliberately **different** broken-YAML contracts — do not unify them. The old one returns an unparsable block as part of the body, which `doctor/scope_patch.py` needs: it parses→prepends→renders as a pair, so a `gsd-*` prompt with bad frontmatter keeps it. The new one strips the block and names the cause, which the Codex/OpenCode converters need or they emit two stacked frontmatter blocks. A non-mapping block is **not** an error and is never stripped.
- **Codex model map** (v2.58.3): Codex has no discovery command, so `DEFAULT_CODEX_MODEL_MAP` is static — re-check it against `~/.codex/models_cache.json` or `codex debug models`. Policy, enforced by `TestBundledModelMapPolicy`: all three aliases share **one current top model family** and differ only in `model_reasoning_effort`; never map a tier onto an older generation's mini model. An unknown model id only warns, which is how a dead family survived unnoticed once.
- **Statusline presets** (v2.58.0–2.58.2): `sccs statusline list|use|install|show`. Two rules: `install_preset()` downloads the installer and runs `bash <file>` — **never `curl | bash`** — and install URLs are https + host-allowlisted at validation time; and every preset's `managed_paths` flow into `get_doctor_managed_excludes()`, so a multi-MB binary never reaches the repo. `StatusLineDetector` expands `~` and `$VAR` before testing a command token — without it both bundled presets report `missing_binary` forever and `doctor check` exits 1 permanently.
- **Profiles** (v2.57.0): `sccs profile on|off|list|status` switches a whole artefact group. `deactivate` **moves** artefacts to `~/.config/sccs/profiles/<name>/` — nothing is deleted, a name collision raises instead of overwriting. Load-bearing asymmetry: `DoctorConfig.installable_npx_tools()` drops a disabled profile's npx tools so `doctor install/update` cannot resurrect it, while `effective_npx_tools()` stays profile-blind so `get_doctor_managed_excludes()` keeps excluding `gsd-*` from sync.
- **OpenAI Codex Integration** (v2.53.0): skills go verbatim to `~/.agents/skills/` — **not** `~/.codex/skills/`, which is reserved for system skills; agents become `~/.codex/agents/*.toml`; commands are wrapped as skills (Codex prompts are deprecated). Collision rule: real skills always win over same-named commands. No MCP merge, no CLAUDE.md→AGENTS.md.
- **Converter literal-value safety** (v2.56.0): fish single-quoted values are literal and fish has no backtick substitution — running them through token rewriting and embedding them in a double-quoted target turns inert text into live code. `sq` values stay single-quoted; `dq`/`bare` get backtick (zsh) and `` ` ``/`$(` (PowerShell) escaping.

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
│   ├── scope_patch.py    # GSD scope-boundary auto-patch (idempotent, directive-prepend)
│   └── _paths.py         # is_home_path helper (avoids import cycle)
├── transfer/             # ZIP export/import
│   ├── manifest.py       # Pydantic models for ZIP manifest
│   ├── exporter.py       # Scan + ZIP creation
│   ├── importer.py       # ZIP extraction (zip-slip + symlink rejection)
│   └── ui.py             # questionary checkbox helpers
├── integrations/         # Antigravity IDE + Claude Desktop + OpenCode + Pi + Codex
│   ├── detectors.py      # AntigravityDetector, ClaudeDesktopDetector
│   ├── antigravity.py    # Skill→Prompt migration logic
│   ├── claude_desktop.py # Trusted-folder registration
│   ├── opencode.py       # OpenCodeDetector, agent/command convert, MCP merge
│   ├── pi.py             # PiDetector, skill/agent/command export (pi.dev, verbatim copy)
│   └── codex.py          # CodexDetector, skill copy + agent TOML + command skill-wrap
├── convert/              # Fish → PowerShell / Fish → Zsh profile conversion
│   ├── fish_to_pwsh.py   # PS converter entry (function stubs)
│   ├── rules.py          # alias/set/fish_add_path translation rules (shared regexes)
│   ├── templates.py      # PowerShell profile templates
│   ├── fish_to_zsh.py    # Zsh converter entry (zsh -n gate, uname guards)
│   ├── zsh_block.py      # Best-effort fish→zsh block translator
│   ├── zsh_rules.py      # Zsh line rules
│   ├── zsh_templates.py  # zshrc/conveniences/README templates
│   ├── claude_to_codex.py # CC → Codex conversion rules (model/effort map, sandbox_mode)
│   └── toml_write.py     # Minimal TOML emitter for Codex agent files
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
