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
- **Capacity Probe** (v2.60.0): `sccs capacity [--json] [--offline]` (`sccs/capacity/`) reports how much plan quota each orchestrated agent CLI has left, so a CAO supervisor routes by remaining capacity instead of guessing. Three sources, and the payload names which is which because they differ in trustworthiness: **codex** = `session-cache`, parsed from the `rate_limits` event in the newest `~/.codex/sessions/**/*.jsonl` rollout (free, no network, but only as fresh as the last Codex session — `derive_routing` flags a snapshot older than one 5h window); **antigravity** = `live` via `agy -p "/usage"`, because `agy` has no `usage` subcommand but *does* expand slash commands in print mode (costs one tiny request, hence `--offline`); **claude_code** = `assumed`, since Claude Code keeps no on-disk quota cache and `/usage` is interactive only — no numbers are invented. Four load-bearing details: (1) providers disagree on which half of the fraction they report (Codex emits `used_percent`, Antigravity emits remaining), so `QuotaWindow` carries both and derives the missing one; (2) a window whose `resets_at` has passed is marked `expired` and counts as 100 % free, because the snapshot describes a window that has since rolled over; (3) `_status()` keeps `unknown` distinct from `tight` — missing data is not evidence of exhaustion, and conflating them would push image work onto the billed API for no reason; (4) **Antigravity bills Gemini separately from the Claude/GPT models it resells**, which is why `QuotaScope` is a list — when Gemini is tight the fallback reviewer is Codex, NOT Antigravity on a Claude model, since that would turn cross-review into self-review. `RoutingAdvice` (image generation target, independent reviewer, parallel-worker gate, plus human-readable constraints) is derived in code rather than left to a prompt so it is testable and identical on every host
- **Codex Hooks Export** (v2.59.0): `sccs integrations codex export-hooks` (`sccs/integrations/codex_hooks.py`) merges the `hooks` block of `~/.claude/settings.json` into `~/.codex/hooks.json` — the target Codex actually reads, NOT `~/.codex/hooks/hooks.json` (the plugin path). Pure translation lives in `sccs/convert/claude_to_codex_hooks.py`: only the 10 events both sides share transfer (`PreToolUse`, `PostToolUse`, `PermissionRequest`, `PreCompact`, `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop`, `UserPromptSubmit`, `Stop`); everything else — `PostToolUseFailure`, `Notification`, `PostToolBatch` included — drops with a warning, and of Claude's handler types only `type: "command"` is portable (`http`/`prompt`/`agent` dropped). Scripts are never copied; commands keep pointing at `~/.claude/hooks/`. Three load-bearing details: (1) **byte-stability** — Codex records hook trust against a hash of each definition, so `serialize_hooks_document()` pins key order and group order rather than letting `json.dumps` vary run to run, or every export would force the user back through `/hooks` even when nothing changed; (2) **ownership key** `(event, matcher, command)` tracked in `~/.config/sccs/.codex_hooks_state.yaml` — SCCS only ever touches entries under a key it wrote, so a hand-edit that changes the command text falls outside that key and the next export recreates the original next to it, while hand-adding a sibling handler to an owned group leaves the key intact and is now (fix `e69ee6e`) suppressed with a warning instead of duplicated — `merge_hooks()`'s `foreign_keys` check; (3) **not part of `export-all`**, deliberately — hooks execute code on every tool call, which belongs behind its own command, never a side effect of a broader export. After any export the user must run `/hooks` in Codex or the new/changed entries simply do not run.
- **Frontmatter parse split** (v2.58.4): `parse_frontmatter()` and `parse_frontmatter_ex()` have deliberately DIFFERENT broken-YAML contracts, and the split is load-bearing. Old function: an unparsable block comes back as part of the body, fences included — `doctor/scope_patch.py` parses→prepends→renders as a **pair**, and `render_frontmatter({}, body)` returns the body untouched, so a `gsd-*` prompt with bad frontmatter keeps it. New function: returns `(metadata, body, error)`, strips the block and names the cause — used by the Codex/OpenCode converters, which emit their own header and were producing documents with two stacked frontmatter blocks. Trigger case is real and not exotic: `argument-hint: [a] [b...]` is Claude Code's documented syntax and invalid YAML. Two further details: the error's line number is FILE-relative (`_FENCE_LINE_OFFSET`), because a block-relative one is always off by the fence; and a non-mapping block (a Markdown `---\n# Heading\n---`) is NOT an error and never stripped — only a real `YAMLError` is. `parse_error=` on `convert_agent_frontmatter`/`wrap_command_as_skill` replaces the "has no description" warning, which is false when the field exists but could not be read
- **Codex model map refresh + selection guard** (v2.58.3): `DEFAULT_CODEX_MODEL_MAP` pointed at `gpt-5.1-codex`/`gpt-5.1-codex-mini`, a family Codex has retired — every exported agent TOML carried a dead `model` id, which nobody noticed because an unknown id only warns. Now `opus`/`sonnet` → `gpt-5.6-terra`, `haiku` → `gpt-5.6-luna`. **Owner's mapping policy, enforced by `TestBundledModelMapPolicy`**: all three aliases share ONE current top model family and differ only in `model_reasoning_effort` — never map a tier onto an older generation's mini model. Codex still has no discovery *command*, but it does cache a machine-readable catalogue at `~/.codex/models_cache.json` (`slug` per entry) — that is how you re-check the map. Two fixes rode along: `integrations status` called `get_agent_gaps()` without the model maps (`sccs/cli.py`), so it rendered agent TOML against the bundled defaults and disagreed with `integrations codex status` for anyone overriding `codex.model_map`; and an unknown name in `-s`/`-a`/`-c` used to exit 0 in silence, because a gap list cannot tell "already in sync" from "does not exist" — the new `CodexDetector.source_names(kind)` supplies the source-tree names so a typo fails with `No such agent/skill/command` and exit 1
- **Statusline presets** (v2.58.0): `sccs statusline list|use|install|show` picks which statusline Claude Code runs. A preset carries `command`, `padding`, `marker_path` (installed-check), `install_url` and `managed_paths`; bundled: `builtin` (`~/.claude/statusline.sh`) and `claude-code-statusline` (glauberlima binary). Config lives in the top-level `statusline:` key; `ProfileSpec.statusline_fallback_preset` names what a parked profile falls back to. Two load-bearing details: `install_preset()` downloads the installer to a temp file and runs `bash <file>` — never `curl | bash` through a shell — and install URLs are https + host-allowlisted at *validation* time; and every preset's `managed_paths` flow into `get_doctor_managed_excludes()` so the multi-MB binary never reaches the repo (`sccs/doctor/statusline.py`). Since v2.58.1 `doctor check` prints a row for the configured-or-live preset in EVERY state (`installed · in use` / `installed · not in use` / `MISSING`) with the binary's version via `version_arg` — `detect_version()` bypasses `runner._run` on purpose, because that validator rejects the absolute path a statusline marker always is
- **Statusline path expansion + chosen-preset persistence** (v2.58.2): `StatusLineDetector` expands `~` and `$VAR` before testing a `statusLine.command` token (`_expand_command_token` in `sccs/doctor/detectors.py`). Without it BOTH bundled presets and the `claude_statusline` category's own `settings_ensure` command reported `missing_binary` forever — `shlex.split` leaves the tilde in place, so `Path("~/.claude/statusline").is_file()` is always False and `doctor check` exited 1 permanently. Two follow-ons in the same release: `doctor check --json` now carries `statusline_presets` (the Rich table got those rows in v2.58.1, the JSON payload did not — sccs-gui saw only the false alarm), and `sccs statusline use|install` records the choice as `statusline.active` in config.yaml via `save_statusline_active()` (no-op when unchanged, because rewriting the YAML drops the user's comments). The doctor's install action now fires for a preset that is configured **or** live, matching `reporter._statusline_preset_row` — `sccs profile off` sets the fallback preset in settings.json only, so the old `is_configured`-only gate printed a MISSING row for a statusline it then refused to install
- **Profiles** (v2.57.0): `sccs profile on|off|list|status` switches a whole artefact group of one extension. `deactivate` **moves** matching skills/agents to `~/.config/sccs/profiles/<name>/`, strips matching `settings.json` hook entries (recording them for restore) and swaps a matching `statusLine` for the `statusline_fallback_preset`; `activate` reverses all of it. Nothing is deleted; a name collision in the parking area raises instead of overwriting. State in `~/.config/sccs/.profile_state.yaml`. Doctor integration is the load-bearing part: `DoctorConfig.installable_npx_tools()` drops a disabled profile's npx tools so `doctor install/update` cannot resurrect it, while `effective_npx_tools()` stays profile-blind so `get_doctor_managed_excludes()` keeps excluding `gsd-*` from sync. Bundled profile: `gsd` (`sccs/doctor/profiles.py:DEFAULT_PROFILES`)
- **Converter literal-value safety** (v2.56.0): fish single-quoted values are literal (no expansion, no substitution) and fish has no backtick substitution at all — `convert_set_gx` used to run every value through `rewrite_fish_tokens` and embed it in a *double*-quoted target string, turning inert text into live code. Now: `sq` values are emitted single-quoted (`_sq()` / PowerShell `'…'`), `dq`/`bare` values get backtick escaping via `_dq_escape()` (zsh) and `` ` ``/`$(` escaping via `_ps_dq_escape()` (PowerShell). Intended features preserved: unquoted `(cmd)` → `$(cmd)` and `$var` expansion still work
- **Transfer excludes doctor-managed items** (v2.55.0): `Exporter` mirrors `SyncEngine.effective_global_exclude` and filters `get_doctor_managed_excludes()` (`gsd-*`, `playwright-cli`) out of the selection UI and the ZIP; `Importer` filters symmetrically (`importable_manifest()`, `--all` and parsed selections) so pre-2.55.0 archives cannot write them back. The target machine reproduces those via `sccs doctor install`. Filter applies to items only (a `gsd-*.md` file *inside* your own skill survives); `--include-managed` on both commands is the escape hatch
- **Doctor Plugin-Baseline** (v2.54.0): `claude-security` and `claude-md-management` (both `@claude-plugins-official`) joined `DEFAULT_CLAUDE_PLUGINS` as *required* entries — checked, installed and updated on every host. Scope caveat documented in `docs/usage/doctor.md`: `/plugin install` from inside a project writes project-scoped `<project>/.claude/settings.json`, while `doctor install` installs user-scoped
- **Doctor Update-Check** (v2.42.0): `sccs doctor check` flags OUTDATED plugins/npx tools when a newer version exists upstream (`npm view` for npm-backed tools, marketplace manifest for plugins); informational only, `--no-update-check` for offline mode
- **GSD Scope-Boundary Auto-Patch** (v2.49.0): `sccs doctor install/update` prepends a SCOPE BOUNDARY directive to externally-delivered `gsd-*` prompts that run unbounded `find`/`grep -r` scans not pinned to the git project root. Idempotent (versioned sentinel), directive-prepend only (vendor snippets untouched), gated by `NpxToolSpec.patch_scope_boundary`
- **Self-serve Capability Card** (v2.51.0): `sccs capability-card` prints the agent capability card (`usage/AGENT.md`) as raw Markdown to stdout with the live `__version__` injected into the header. Card is bundled into the wheel via hatchling `force-include` (`sccs/data/AGENT.md`), with a repo-checkout fallback for editable installs. See `_find_capability_card()` in `sccs/cli.py`
- **Export/Import Pre-selection Prompt** (v2.51.0): the interactive two-stage export/import asks, per detail view (groups with >5 items), whether items start all-selected or all-deselected — so users can pick just a few without deselecting each entry. `prompt_default_checked()` threads a `default_checked` flag into the item-choice builders in `sccs/transfer/ui.py`
- **OpenAI Codex Integration** (v2.53.0): `sccs integrations codex` exports Claude artefacts one-way to the Codex CLI. Skills verbatim → `~/.agents/skills/` (identical agentskills.io SKILL.md format; NOT `~/.codex/skills/`, which is reserved for system skills); agents → `~/.codex/agents/*.toml` (body → `developer_instructions`, model alias → Codex model + `model_reasoning_effort`, read-only tool sets → `sandbox_mode`); commands wrapped as Codex skills (Codex prompts are deprecated). Collision rule: real skills always win over same-named commands. Hand-rolled TOML emitter in `sccs/convert/toml_write.py` (round-trip-tested); static model map (no discovery in Codex), override via `CodexConfig`. No MCP merge / no CLAUDE.md→AGENTS.md in v1
- **Fish → Zsh Conversion** (v2.52.0): `sccs convert fish-to-zsh` generates a native zsh profile from the fish config for machines without fish. Best-effort translation of functions AND control flow (`sccs/convert/zsh_block.py`); platform files converted inside `uname` guards; every generated file validated with `zsh -n` (fallback to commented stubs — never emits broken zsh). New disabled-by-default category `zsh_config`; activation via idempotent copy-paste one-liner printed after conversion and shown in the generated README (v2.52.1; SCCS never edits `~/.zshrc` itself — `ACTIVATION_ONE_LINER` in `sccs/convert/zsh_templates.py`)

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
