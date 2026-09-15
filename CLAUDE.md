# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sccs** (SkillsCommandsConfigsSync) is a unified YAML-configured bidirectional synchronization tool for Claude Code files and optional shell configurations.

**Version**: 2.68.1

### Key Features

- **Unified YAML Configuration**: Single `config.yaml` with all sync categories
- **Flexible Categories**: Claude skills, commands, hooks, scripts, fish config, etc.
- **Bidirectional Sync**: Full two-way synchronization with conflict detection
- **Git Integration**: Auto-commit and push after sync operations

The notes below cover only what would be got *wrong* without them. The full
feature history — what each release added and why — lives in `RELEASE_NOTES.md`.

- **Optional npx tools** (v2.68.0): `NpxToolSpec.optional` — bundled `@opengsd/gsd-core` is optional, `playwright-cli` required. Absent + optional → `_INFO` row, not a problem, skipped by `_npx_install_actions` unless `include_optional`, skipped by `_npx_update_actions` always (update used to run `npx …` for every tool and thereby installed GSD on every host), skipped by the orphan cleanup. `doctor install/optimize --with-optional` opts in per run; the config is synced across hosts, so a per-host opt-in cannot live in `config.yaml`. The `gsd-*` sync exclude comes from `effective_npx_tools()`, which stays option-blind as it is profile-blind. Same release: the five required official plugins carry `marketplace_source="anthropics/claude-plugins-official"` — without it a fresh host could never register the marketplace and every official plugin was skipped.
- **Mirror parity** (v2.68.0): `sccs/doctor/mirror.py` reconciles a second Mac against the live workstation. Roles come from `doctor.mirror.source_host` matched against the normalised hostname. **Two rules are pinned by tests**: the source never receives install/remove actions, and a mirror never writes `inventory.yaml` — only `mirror_update_actions` on the source captures, via one `python_callable` action; `doctor optimize` splices in the same actions as `update`, so it captures on the source too. Removals live only in `build_optimize_plan(strict=True)` and only with `cleanup: true`; each is its own `DoctorAction` with `auto_confirm=False`, never `brew bundle cleanup` — and never `fisher update`, which with no arguments uninstalls every plugin absent from `fish_plugins`; fisher plugins install and remove one at a time (`fisher install <name>` / `fisher remove <name>`). `--yes` overrides `auto_confirm=False` for every action, removals included, same as it already does for foreign plugins. `brew bundle install` carries `timeout=1800`, `git clone` `timeout=900`; every other mirror action keeps the doctor's 300s default. Homebrew *missing* is checked against the full installed list, Homebrew *extra* against `brew leaves` — a dependency is never offered for removal. Extras are yellow, never a problem; missing/wrong version on a mirror is red and exit 1; a stale source is yellow. Every name goes through `_validate_safe_name` and every version through `_VERSION_PATTERN` before it becomes argv.
- **Fish coverage** (v2.67.2): every file under `~/.config/fish` is covered by **exactly one** enabled category, and `TestFishDefaultsCoverEachFileOnce` scans a fixture tree against the shipped defaults to keep it that way. Two categories tracking the same file (`fish_config` with `functions/*.fish` and `fish_functions` with `*.fish`) keep two independent `.sync_state.yaml` entries, so any divergence turned into a silent CONFLICT — and default `sccs sync` has no resolver without `-i`/`-f`, it only counts them. `fish_functions` is therefore disabled by default (kept as a definition for configs and deploy profiles that name it); `fish_functions_macos` stays, and `fish_config` excludes `functions/macos/*` because `fnmatch` lets `functions/*.fish` reach into subdirectories. Second half: `fish_config` now includes `scripts/*.py` and `functions/*.py` — 21 fish helpers call `scripts/shell_safety.py`, and on a second Mac every one of them failed while `sccs status` reported everything unchanged. A category can only report what it knows about.
- **Skill packages** (v2.67.0): `sccs/doctor/skill_packages.py` manages skill bundles fetched by the `skills` CLI (`npx skills add <owner/repo>`), opt-in via `doctor.skill_packages` — bundled is `hyperframes`. Three rules. **The `skills` lock file (`~/.agents/.skill-lock.json`) decides membership**, not a glob: HyperFrames' 20 skills share no prefix (`figma`, `slideshow`), so sync excludes, profile parking and the detector all read entries by `source`. The bundled `known_skills` list is only a fallback — and for sync excludes only for an *enabled* package, so a private `figma` keeps syncing on a host without HyperFrames. Lock-derived names are excluded regardless of opt-in, like `gsd-*`. **Install and update are one command** (`skills add … --agent claude-code --skill '*' --yes --copy`), verified to replace each skill directory wholesale; `--copy` is load-bearing, because the CLI symlinks by default and a symlink is skipped by the sync scan and parked as a bare link. **No update signal is invented**: the lock stores a folder hash, not a version, so `check` shows the lock date and `update` refreshes unconditionally. Missing/symlinked skills fail `check`; an unloadable `SKILL.md` (`skill_limits`) is reported yellow but does not, since only upstream can fix it. Profile `hyperframes` carries `skill_packages`, and `installable_skill_packages()` mirrors `installable_npx_tools()`.
- **Statusline sync** (v2.66.0): The statusline is two things at once — a script to carry, and a line in `settings.json` that has to point at it — and shipping only the script leaves each host running whatever its settings file said. Both halves are in `claude_statusline` now. Two traps. **`item_pattern` is `statusline*`, without the dot**: it goes through `fnmatch`, where `statusline.*` never matches `statusline-command.sh` — the name Claude Code's own `/statusline` setup writes, and therefore the file that on a real host IS the statusline. It was covered by neither pattern nor `include`, so the live script never reached the repo while a stale `statusline.sh` beside it synced happily and every other host pulled that one. And **`superseded_patterns` (`SettingsEnsure`) is what lets a corrected default reach a machine that already has the old one**: the merge is non-destructive by design, so an old command already sitting in `settings.json` would otherwise never be replaced. It names, per key, the values SCCS itself wrote in earlier releases; a match is refreshed and reported, anything else is the user's and stays. Matching is by **pattern**, not equality — every key the pattern names must be equal, extra keys in the target do not block it (a hand-added `padding` next to our `command` is still ours) — and an empty pattern is refused at validation time, because it would match every value and invert the guarantee. The same reasoning runs one level up in `_resolve_effective_settings_ensure`: a `config.yaml` written once cannot learn that a default was corrected, so the resolver fills in missing `superseded_patterns` from the bundled default and lifts an `entries` value that is itself superseded. A user-declared pattern wins over the default. The category also excludes what must never travel (the multi-MB `statusline` binary, `statusline.toml`, `*.bak`/`*.orig`) in its own right rather than relying on a preset's `managed_paths` being configured.
- **Deployment profiles** (v2.65.0): `sccs deploy export|install|revoke` (`sccs/deploy/`) ships a scenario-scoped slice of the local inventory — skills, agents, commands, shell files — to a foreign host (a customer server, no SCCS config of ours) and takes it back later. **The receipt is standalone by design**: absolute targets, the profile's `retain` list and its sweep globs live in `~/.config/sccs/.deploy_receipt.yaml`, because `revoke` on that host has nothing else to read. **`pre_existing` is decided once and sticks**: it is read back out of the existing receipt (across all profiles) and only falls back to `target.exists()` for a target no record claims — recomputing it per install made a second run see the files the first one wrote, flip everything to "was already here", and turn `revoke` into a no-op that reports a clean host. A `pre_existing` target is **neither written over nor removed**: install skips it and reports it in `skipped_foreign`, so a customer's hand-edited file is never displaced — the same ownership line as the Codex export's `foreign_target`, and the reason a deploy install passes `backup=False` (nothing foreign is overwritten, so a backup could only park OUR content in `~/.config/sccs/backups/`). An artefact WE installed that the customer then edited IS removed and flagged `modified` — two different facts about "the file changed," and collapsing them would either strand customer edits forever or delete something that predates us. **An artefact another still-installed profile also claims goes to the `shared` bucket and stays** (`odoo-server` and `fastreport` both ship `odoo-common`) — rechecked from the live receipt at revoke time, not memorized at install, so revoking one profile never pulls the ground out from under another. **The transcript is the leak, not the skill**: `~/.claude/projects/` quotes skill content verbatim into session history, so it goes too, and `~/.claude.json` is trimmed of `history` rather than deleted, since it also holds the host user's auth state — a symlinked file is followed only when its resolved target stays under home, else refused outright rather than silently reporting success on the wrong file. **`~/.config/sccs/` is purged only when we created it**: `state_dir_pre_existing` is recorded at install, and a host whose user runs `sccs` themselves keeps their config.yaml, sync state and backups — only the receipt goes. **`revoke` ends with a verification sweep** whose findings are classified three ways, because a report of success with a surviving directory is worse than no cleanup — that report is what ends the search. Pass 1 re-stats every planned removal; **pass 2 is the load-bearing one**: it re-scans the receipt's `sweep_globs` against the category directories derived from the recorded entry targets and **does not consult `pre_existing`**, the bookkeeping it exists to second-guess. Only `retain` categories and `shared` entries are exempt outright. Then: a planned removal that survived **fails**; a shipped name with **no receipt entry at all** fails (the signature of an install that wrote without recording); and a name whose entry positively records `written_by_sccs=False` **and** whose content differs from the shipped artefact is reported and labelled but does **not** fail — `claude_framework` ships `CLAUDE.md` and Claude Code creates `~/.claude/CLAUDE.md` on nearly every host, so failing there would fail everywhere, and an alarm that always fires is an alarm nobody reads. **Two conditions hold that exemption in place.** It is gated on the *recorded* `written_by_sccs`, never the *inferred* `pre_existing` — an older build marked its own artefacts `pre_existing` while overwriting them, so `RECEIPT_VERSION` is **2** and a v1 receipt is refused with instructions rather than read under the new assumption. And it is gated on content: install stores `shipped_hash` (what the bundle *would* have written) for every skipped target, and a foreign target byte-identical to it **fails** — our knowledge is on that host whoever put it there — while still never being deleted. **Every failing finding costs its profile the receipt record**, not just a failed removal: dropping it made `revoke` exit 1, print the path, and then answer the operator's re-run with "Nothing to revoke on this host" and exit 0. The `unrecorded` case needs this most — with no entry there is no directory left to re-derive. `RevokeResult`/`--json` split `leftovers` (failing) from `benign_leftovers`. `claude_memories`, `claude_plans` and `claude_todos` are refused by the schema validator at load time, never silently filtered out. Single-file categories (`starship_config`, `gitconfig`) name the FILE as `local_path`, so the importer resolves them to its parent — go through `manifest.resolves_to_parent()`, not `is_single_file_category()` alone: where the path exists on the host it also runs the export side's `is_dir()` test, and a directory outvotes the manifest fingerprint. **Ownership is keyed on the resolved target path**, never on `(category, name)` — a category's `local_path` can change between bundles, and a stale pair-keyed claim skipped the `exists()` check on a directory no install had ever touched.
- **CAO provider patches** (v2.64.0): `sccs/doctor/cao.py` re-applies the extra agent providers that a `cao update` wipes — CAO's registry is a hard-coded if/elif chain, not a plugin point, so a provider must be edited into the *installed* package at six sites. **Since v2.67.1 no provider is bundled**: pi (`pi_cli`), the only one, was retired from the fleet, so `DEFAULT_CAO_PROVIDERS` is empty and the mechanism serves only providers declared in `doctor.cao_providers`. Four rules. **The provider source is never bundled here** (a private `source_dir`) — this package goes to PyPI and GitHub, and only the mechanism belongs in it; the v2.60.0 removal of the CAO agent profiles set that line. **The opt-in is the pairing**, not a config flag: a row appears only when an installed CAO and the synced source both exist. **`anchor_lost` is reported, never repaired** — a half-applied patch leaves a package that imports but cannot launch, so a moved anchor gets a pointer to re-derive it in `DEFAULT_CAO_PROVIDERS`. And **edits accumulate per file, not per site**: `providers/manager.py` carries two sites, and deriving both from the same on-disk text makes the second write discard the first (found against a real install, not by the fixture). Verification completes before the first write, so a broken spec changes nothing.
- **Ownership adoption** (v2.63.0): `CodexDetector.adopt_in_sync()` claims targets that already equal what SCCS would write, called before every Codex export. Reason: ownership was recorded **only on write**, so a target that never needed writing never earned it — 90 targets, 18 records on a real host — and the foreign-target guard then fired on SCCS's own artefacts the moment their source changed. The load-bearing trick: equality is derived from the gap builders, because **absence of a gap already proves target-exists-and-matches**; do not add a second comparison that can disagree with the first. Any gap disqualifies (pending, blocked, collision, foreign), and excluded artefacts are skipped explicitly — `source_names()` ignores excludes, so an excluded artefact also has no gap and would otherwise be adopted by mistake.
- **Cross-assistant pass** (v2.62.0): `sccs integrations sync-all` (`sccs/integrations/sync_all.py`) detects the installed agent CLIs, shows one plan, asks once, exports to all. Three rules: `--overwrite` behaviour is the **default** here (a collection command that only creates would keep nothing current — the whole point), `--replace-foreign` is **not** (a foreign target may hold hand edits, and a convenience command must not discard them silently), and **Codex hooks stay out** exactly as in `codex export-all`. The adapters wrap the SAME detectors/writers as the individual commands — never a second export path. `collect_plans`/`apply_plans` isolate per-target failures: a detection error is recorded as `error`, never as `installed=False`, because "broken" and "absent" are different facts.
- **Export limits + foreign targets** (v2.61.0): Pi/Codex/Claude Code share the agentskills.io SKILL.md format and all three **silently drop** a skill whose description exceeds 1024 chars, whose name exceeds 64, or whose frontmatter is unparsable. Both exports copy verbatim, so the copy is byte-correct and the export reports success while the skill never loads — `sccs/integrations/skill_limits.py` checks the SOURCE, which is the only place that false success is visible. It runs **independently of gap detection** on purpose: an offending skill already copied is in sync, produces no gap, and would otherwise never be mentioned again. Second rule, in `codex.py`: `foreign_target` is a **weaker** guard than `collision` — releasable, but only by its own `--replace-foreign`, never by `--overwrite`. The two mark different risks (a stale target SCCS wrote vs. one holding somebody's hand edits) and must not imply each other. Before this split there was no flag at all that could refresh a drifted target.
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
