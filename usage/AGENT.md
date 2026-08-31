<!--
  Capability Card — generated/maintained via the `cli-capability-card` skill.
  Audience: an LLM/agent that wants to USE this tool. Keep it dense and current.
  Refresh the command table from `sccs <group> <cmd> --help` after CLI changes.
-->
# sccs — Agent Capability Card

> Bidirectional, YAML-configured sync for Claude Code files (skills, commands, hooks, agents,
> scripts) and shell configs between a local `~/.claude/` and a git repository — plus a "doctor"
> that installs/heals a Claude Code setup and converters that push artefacts to OpenCode.

- **Invoke:** `sccs <command> [options]`  ·  `python -m sccs <command>`
- **Install:** `uv pip install -e ".[dev]"` (from repo root, into a `uv venv`)
- **Version:** 2.59.0  ·  **Python:** ≥3.10
- **Framework:** Click (group `sccs.cli:cli`)  ·  **Human docs:** `docs/usage/*.md`, `README.md`
- **Self-serve:** `sccs capability-card` prints this card from the installed tool (live version injected)

## Capabilities at a glance
- Two-way sync of Claude Code skills/commands/hooks/agents/scripts and shell config between
  `~/.claude/` (+ `~/.config/fish` etc.) and a git repo, with per-category direction control.
- Conflict resolution: interactive hunk-merge/editor menu, or non-interactive `--force local|repo|newer`.
- Auto-commit / auto-push / auto-pull around sync, gated by config and per-run flags.
- Timestamped backups before every overwrite; dry-run preview on every mutating command.
- Selective ZIP export/import of items for deploying configs to other machines (zip-slip-safe import).
- Report how much plan quota each orchestrated agent CLI has left (`sccs capacity`), with the
  provenance of every number, so a supervisor routes by remaining capacity instead of guessing.
- "Doctor": inspect & repair a Claude Code environment (Node, `claude` CLI, plugins, npx tools,
  bundled skills, Playwright browsers, filesystem permissions, statusline) — CI-friendly.
- Push Claude agents/commands/MCP servers into OpenCode (`~/.config/opencode/`), with model mapping.
- Push Claude skills/agents/commands one-way into Pi (`~/.pi/agent/`) and OpenAI Codex
  (skills verbatim → `~/.agents/skills/`, agents → `~/.codex/agents/*.toml`, commands wrapped as skills),
  requiring `--overwrite` for SCCS-managed targets and the separate `--replace-foreign` for targets
  SCCS did not write. Both exports also name the skills the target will refuse to load.
- Convert a Fish shell config into a PowerShell profile or a native zsh profile (best-effort
  function translation, `uname`-guarded platform files); generate a hub README for the repo.
- Park a whole extension's artefacts (skills, agents, hooks, statusline) with `profile off`, without
  deleting anything — the doctor stops reinstalling them while parked.
- Pick which statusline Claude Code runs (`statusline use|install`), including a confirm-gated
  third-party installer that is never piped from curl into a shell.
- Inspect status/history/diffs and manage which categories are enabled.

## Command reference

| Command | Purpose | Args / Flags |
|---|---|---|
| `sccs capacity` | Remaining plan quota per agent CLI (codex from its session rollout, antigravity live via `agy -p "/usage"`, claude_code assumed), plus derived routing advice: image-generation target, independent reviewer, parallel-worker gate. | --json, --offline |
| `sccs capability-card` | Print this capability card to stdout (raw Markdown, live version injected) — primary self-description surface for agents. | — |
| `sccs categories disable` | Disable a category. | CATEGORY_NAME |
| `sccs categories enable` | Enable a category. | CATEGORY_NAME |
| `sccs categories list` | List all categories. | --all, --json |
| `sccs config edit` | Open configuration in editor. | — |
| `sccs config init` | Initialize configuration file. | --force, --repo-path PATH (non-interactive) |
| `sccs config show` | Show current configuration. | --json |
| `sccs config upgrade` | Check for new default categories and add them to config. | — |
| `sccs config validate` | Validate configuration file. | --json |
| `sccs convert fish-to-pwsh` | Generate a PowerShell profile from Fish shell configuration. | --src PATH, --dst PATH, --force, -n/--dry-run, --conveniences/--no-conveniences |
| `sccs convert fish-to-zsh` | Generate a zsh profile from Fish shell configuration (best-effort function translation; platform files get `uname` guards; never emits broken zsh). | --src PATH, --dst PATH, --force, -n/--dry-run, --conveniences/--no-conveniences |
| `sccs diff` | Show diff for items. | [ITEM_NAME], -c/--category TEXT, --json |
| `sccs docs generate` | Generate hub README for the sync repository. | -n/--dry-run, --commit, --push |
| `sccs doctor check` | Status table of Node.js, claude CLI, plugins, npx tools (+ opt-in CLI tools zoxide/coreutils); live-checks for newer plugin/npx-tool versions (OUTDATED, informational, exit unchanged); shows Node + CLI-tool install commands inline. | --update-check/--no-update-check, --json |
| `sccs doctor install` | Install missing system components after a confirm prompt per action; also pins scope boundaries in externally-delivered `gsd-*` prompts (idempotent, directive-prepend). | --yes, --json |
| `sccs doctor optimize` | Bring the local Claude environment in line with the spec. | --strict, --yes |
| `sccs doctor update` | Update Claude plugins and refresh npx helper tools; re-pins scope boundaries in `gsd-*` prompts after the refresh. | --yes, --json |
| `sccs export` | Export selected items as ZIP archive. | -o/--output PATH, --all, -c/--category TEXT, --include-managed |
| `sccs import` | Import items from an SCCS export archive. | ZIP_PATH, -n/--dry-run, --overwrite, --no-backup, --all, --include-managed |
| `sccs integrations migrate-skills` | Migrate Claude Code skills to Antigravity prompts. | -n/--dry-run, --overwrite/--no-overwrite, -s/--skill TEXT |
| `sccs integrations opencode export-agents` | Convert Claude agents into OpenCode agents (~/.config/opencode/agent/). | -n/--dry-run, --overwrite/--no-overwrite, -a/--agent TEXT |
| `sccs integrations opencode export-commands` | Convert Claude commands into OpenCode commands (~/.config/opencode/command/). | -n/--dry-run, --overwrite/--no-overwrite, -c/--command TEXT |
| `sccs integrations opencode map-models` | Interactively assign Claude model aliases to available OpenCode models. | -n/--dry-run |
| `sccs integrations opencode merge-mcp` | Merge Claude MCP servers into opencode.json (~/.config/opencode/). | -n/--dry-run, --overwrite, -s/--server TEXT |
| `sccs integrations opencode status` | Show OpenCode installation and conversion gaps. | — |
| `sccs integrations pi export-skills` | Copy Claude skills into Pi skills (~/.pi/agent/skills/). | -n/--dry-run, --overwrite/--no-overwrite, -s/--skill TEXT |
| `sccs integrations pi export-agents` | Copy Claude agents into Pi as individual skills (~/.pi/agent/skills/). | -n/--dry-run, --overwrite/--no-overwrite, -a/--agent TEXT |
| `sccs integrations pi export-commands` | Copy Claude commands into Pi prompt templates (~/.pi/agent/prompts/). | -n/--dry-run, --overwrite/--no-overwrite, -c/--command TEXT |
| `sccs integrations pi export-all` | Export skills, agents and commands to Pi in one run. | -n/--dry-run, --overwrite/--no-overwrite |
| `sccs integrations pi status` | Show Pi installation and export gaps. | — |
| `sccs integrations codex export-skills` | Copy Claude skills into Codex skills (~/.agents/skills/). | -n/--dry-run, --overwrite/--no-overwrite, --force, --replace-foreign, -s/--skill TEXT |
| `sccs integrations codex export-agents` | Convert Claude agents into Codex agent TOML files (~/.codex/agents/). | -n/--dry-run, --overwrite/--no-overwrite, --force, --replace-foreign, -a/--agent TEXT |
| `sccs integrations codex export-commands` | Wrap Claude commands as Codex skills (~/.agents/skills/<name>/SKILL.md). | -n/--dry-run, --overwrite/--no-overwrite, --force, --replace-foreign, -c/--command TEXT |
| `sccs integrations codex export-all` | Export skills, agents and commands to Codex in one run. | -n/--dry-run, --overwrite/--no-overwrite, --force, --replace-foreign |
| `sccs integrations codex export-hooks` | Merge Claude hook entries into ~/.codex/hooks.json. | -n/--dry-run |
| `sccs integrations codex status` | Show Codex installation and export gaps. | — |
| `sccs integrations sync-all` | Export to every installed agent CLI in one confirmed pass. | -n/--dry-run, -y/--yes, --replace-foreign, -t/--target TEXT, --json |
| `sccs integrations status` | Show detailed integration status. | — |
| `sccs integrations trust-repo` | Register SCCS repository as trusted in Claude Desktop. | -n/--dry-run |
| `sccs log` | Show sync history. | --last INTEGER |
| `sccs profile list` | List configured profiles and whether they are switched on. | --json |
| `sccs profile off` | Park NAME's artefacts (skills, agents, `settings.json` hooks, statusline) — moved to `~/.config/sccs/profiles/<name>/`, never deleted. | NAME, -y/--yes, --json |
| `sccs profile on` | Bring NAME's parked artefacts back into `~/.claude/` (three-way hook merge, original grouping preserved). | NAME, -y/--yes, --json |
| `sccs profile status` | Detail for NAME, or every profile when NAME is omitted. | [NAME], --json |
| `sccs status` | Show synchronization status. | -c/--category TEXT, --json |
| `sccs statusline install` | Download and run preset NAME's installer (temp file + `bash <file>`, never `curl \| bash`; confirm defaults to No). | NAME, -y/--yes, --use/--no-use, --json |
| `sccs statusline list` | List presets with installed/active/configured state and version. | --json |
| `sccs statusline show` | Print the `statusLine` entry currently in settings.json. | --json |
| `sccs statusline use` | Point settings.json at preset NAME and record it as `statusline.active` in config.yaml. | NAME, --json |
| `sccs sync` | Synchronize files between local and repository. | -c/--category TEXT, -n/--dry-run, -f/--force local\|repo\|newer, -i/--interactive, --commit, --no-commit, --push, --no-push, --pull, --no-pull-check, --docs/--no-docs, --migrate/--no-migrate, --json |

Notation: `[ARG]` optional positional · `ARG` required positional · `a|b` choice · `--flag` boolean.

Global flags (before the subcommand): `-v/--verbose`, `--no-color`, `--version`.

## Recipes

### Preview then sync everything, commit and push
```bash
sccs sync --dry-run        # inspect planned actions, write nothing
sccs sync --commit --push  # apply, commit (overrides auto_commit=false), push to remote
```
Without `--commit/--push`, behaviour follows `repository.auto_commit/auto_push` in the config.

### Receive shared configs (subscriber)
```bash
sccs sync --pull               # pull remote, then sync into local
sccs sync --force repo         # non-interactive: repo wins all conflicts
sccs sync -c claude_skills --pull   # one category only
```

### Resolve conflicts
```bash
sccs sync -i                   # interactive menu: keep local/repo, diff, hunk-merge, editor, skip, abort
sccs sync --force newer        # or auto-resolve by mtime; also: --force local | --force repo
sccs diff my-skill -c claude_skills   # inspect a single item's diff first
```

### Deploy configs to another machine (ZIP)
```bash
sccs export -c claude_skills -o customer.zip   # selective export (omit -c/--all for interactive picker)
sccs export --all -o full-setup.zip            # everything, no prompt
# Doctor-managed items (gsd-*, playwright-cli) are excluded from export AND import;
# the target machine reproduces them via `sccs doctor install`. Override: --include-managed
# (pre-2.55.0 archives still contain them — the import skips them and says how many)
# Interactive picker (no --all): per detail view (groups >5 items) you first choose whether items
# start all-selected or none-selected, then toggle individually. Same prompt on interactive import.
# on the target machine:
sccs import full-setup.zip --dry-run           # preview
sccs import full-setup.zip --overwrite         # apply, with automatic backup of replaced files
```

### Heal a Claude Code environment
```bash
sccs doctor check              # read-only status table; exits 1 if anything is wrong (use in CI gates)
sccs doctor check --no-update-check  # skip the live version check → fully offline/fast
sccs doctor install            # install missing pieces, confirm per action
sccs doctor install --yes      # unattended (CI): skip all confirms
sccs doctor update             # update plugins + refresh npx tools (safe maintenance, no prompts)
sccs doctor optimize --strict  # install + remove foreign plugins/MCP servers (destructive: still confirms)
# Opt-in optional CLI tools (informational, never exit 1): set in config.yaml →
#   doctor: { cli_tools: [zoxide, coreutils] }   # zoxide all-OS, coreutils Windows-only (winget)
```

### Push artefacts to OpenCode
```bash
sccs integrations opencode status                 # what still needs converting
sccs integrations opencode map-models             # map Claude model aliases → provider/model ids
sccs integrations opencode export-agents --dry-run
sccs integrations opencode export-agents          # → ~/.config/opencode/agent/
sccs integrations opencode export-commands
sccs integrations opencode merge-mcp -s context7  # merge one MCP server into opencode.json
```
One-way (Claude Code is source of truth). Skills/`CLAUDE.md` are read natively by OpenCode — no export needed.

### Push artefacts to Pi (pi.dev)
```bash
sccs integrations pi status                       # skills/agents/commands still to export
sccs integrations pi export-skills --dry-run
sccs integrations pi export-all                   # skills + agents → ~/.pi/agent/skills/, commands → prompts/
sccs integrations pi export-skills -s astro       # one skill only (bypasses gsd-* exclude)
```
One-way (Claude Code is source of truth). Pi has no subagent concept: skills + agents become Pi skills, commands become prompt templates. Format-identical, so copied verbatim (no conversion, no model mapping). `gsd-*` excluded by default.

### Push artefacts to OpenAI Codex (codex CLI)
```bash
sccs integrations sync-all -n                     # every installed assistant: one plan, nothing written
sccs integrations sync-all                        # plan, ONE confirmation, export everywhere
sccs integrations sync-all -t pi --json           # one assistant, machine-readable
sccs integrations codex status                    # skills/agents/commands still to export
sccs integrations codex export-skills --dry-run
sccs integrations codex export-all                # skills verbatim → ~/.agents/skills/, agents → ~/.codex/agents/*.toml
sccs integrations codex export-all --overwrite    # update targets SCCS previously created
sccs integrations codex export-skills --replace-foreign  # also replace targets SCCS did NOT write
sccs integrations codex export-agents -a reviewer # one agent only (bypasses gsd-* exclude)
sccs integrations codex export-hooks --dry-run   # 10 shared events; others dropped with a warning
```
One-way (Claude Code is source of truth). Skills copy verbatim (identical agentskills.io format);
agents become Codex agent TOML (body → `developer_instructions`, model alias → Codex model +
reasoning effort, read-only tool sets → `sandbox_mode = "read-only"`); commands are wrapped as
skills (Codex prompts are deprecated). Bundled model map (v2.58.3): `opus`/`sonnet` →
`gpt-5.6-terra`, `haiku` → `gpt-5.6-luna`, efforts `high`/`medium`/`low`. All three aliases share
ONE current model family and differ only in reasoning effort — Codex has no discovery *command*,
but caches a catalogue at `~/.codex/models_cache.json` (one `slug` per entry) to validate the map
before agent export; a missing configured slug aborts the export. SCCS tracks the targets it creates
in `~/.config/sccs/.codex_export_state.yaml`, adopting any target that already matches byte for byte
so ownership is not limited to targets it happened to write. Two independent switches, because they cover two
different risks: `--overwrite` (or `--force`) updates targets SCCS recorded as its own, while
`--replace-foreign` is required for a target SCCS did not write — one that may hold hand edits.
Neither implies the other. Both exports additionally report skills the target will refuse to load
(description > 1024 chars, name > 64, unparsable frontmatter) — reported, never blocking, and shown
in `status` even when nothing is left to export. A name passed to `-s`/`-a`/`-c`
that does not exist in `~/.claude/` fails with `No such agent/skill/command` and exit 1 (a name that is
merely already in sync still succeeds). Name collisions: a real skill always wins over a same-named
command (skipped with a warning). `gsd-*` excluded by default. No MCP merge / no CLAUDE.md→AGENTS.md (v1).
A source file whose frontmatter is not valid YAML exports with the block stripped and a warning naming
the file line/column (v2.58.4); the usual cause is `argument-hint: [a] [b...]` — quote it to fix.
Hooks are a separate, deliberate export: `export-hooks` is NOT part of `export-all` (hooks execute
code on every tool call) and merges into `~/.codex/hooks.json` rather than owning it — entries SCCS
did not write are left alone. Run `/hooks` in Codex after exporting; until you approve there, the
new or changed entries do not run.

### Convert Fish config to PowerShell or zsh; regenerate hub README
```bash
sccs convert fish-to-pwsh --dry-run      # source defaults to ~/.config/fish
sccs convert fish-to-pwsh --src ~/.config/fish --dst ~/profile.ps1 --force
sccs convert fish-to-zsh --dry-run       # zsh profile → <repo>/.config/zsh (default dst)
sccs convert fish-to-zsh --force         # prints idempotent copy-paste activation one-liner
sccs docs generate --commit              # rebuild the repo's navigation README
```
fish-to-zsh translates functions/control flow best-effort (falls back to commented stubs, never
emits broken zsh); `*.macos.fish`/`*.linux.fish` are converted inside `uname` guards. Distribute
via the disabled-by-default `zsh_config` category.

### Park an extension / choose a statusline
```bash
sccs profile list                              # profiles and their state
sccs profile off gsd                           # park 71 skills + 34 agents + 17 hook entries
sccs profile status gsd                        # what is parked, and where
sccs profile on gsd                            # restore everything, hooks in their original grouping
sccs statusline list                           # presets: installed? in use? configured?
sccs statusline install claude-code-statusline # third-party installer, confirm-gated
sccs statusline use builtin                    # switch back to ~/.claude/statusline.sh
```
Nothing is deleted — parked artefacts move to `~/.config/sccs/profiles/<name>/`, and a parked
profile's npx tools are dropped from `doctor install/update` so the next pass cannot resurrect it.
`profile off` also swaps a statusline owned by that profile for its `statusline_fallback_preset`.
Both switches take effect in the NEXT Claude Code session.

### Inspect & manage
```bash
sccs status                    # changed items per category (+ inline integration status)
sccs log --last 10             # recent sync history
sccs categories list --all     # include disabled categories
sccs categories enable opencode_agents
sccs config show               # current config; also: validate | edit | init [--force] | upgrade
```

## Guardrails & gotchas
- **Destructive / overwriting:**
  - `sync --force local|repo` overwrites the losing side; `sync --force newer` decides by mtime — no per-item prompt.
  - `import --overwrite` replaces existing files (a timestamped backup is made *unless* `--no-backup`).
  - Codex exports keep the two overwrite risks apart: `--overwrite`/`--force` updates only targets
    recorded as SCCS-managed, `--replace-foreign` is needed for a target SCCS did not write (it may
    carry hand edits). Without the matching option, an existing target is skipped. A command whose
    skill slot is claimed by a real skill is never written — `--replace-foreign` does not release that.
  - `doctor optimize --strict` *removes* foreign plugins/MCP servers; doctor's hook removal / statusline
    rewrite are confirm-gated — `--yes` skips those confirms too. Use `--yes` only in CI.
  - `integrations sync-all` updates existing SCCS-managed targets by DEFAULT (unlike the individual
    export commands) — that is what makes it a maintenance command. It still never touches a foreign
    target without `--replace-foreign`, and never exports Codex hooks.
  - Mutating commands honour `-n/--dry-run` (or `--dry-run`) — preview first when unsure.
- **Backups:** writes land in `~/.config/sccs/backups/<category>/<item>.<timestamp>.bak` before overwrite.
- **Prerequisites:** `sccs config init` must have produced `~/.config/sccs/config.yaml`; sync needs a valid
  `repository.path` git repo. `doctor` needs Node ≥20 + the `claude` CLI for plugin steps. OpenCode
  `map-models` live-discovery needs an authenticated provider (`opencode auth login`).
- **Interactive prompts (block on input):** `sync -i`, `export`/`import` without `--all`,
  `opencode map-models`, `config init`/`config edit`. Non-interactive escapes: `--all`, `--force`,
  `--yes`, `--dry-run`, or pass explicit `-c`/`-a`/`-s` selectors.
- **Doctor-managed files excluded from sync:** `gsd-*` and `playwright-cli` artefacts (registry in
  `sccs/doctor/managed.py`) are skipped by `sync` and by OpenCode `export-*`/`status`, so independently
  doctored machines don't clobber each other. Bypass per-item with an explicit `-a <name>`/`-c <name>`.
- **Auto-commit semantics:** `--commit`/`--push`/`--pull` override config; `--no-commit`/`--no-push` force off.
- **Permissions:** doctor never runs `sudo`; permission problems are emitted as copy-paste manual blocks.
- **Profiles take effect next session:** skills, agents and hooks are read once at session start;
  `profile on/off` never touches the running session. A name collision in the parking area raises
  instead of overwriting (that state would mean data loss).
- **Statusline commands run through a shell:** `~` and `$VAR` in `statusLine.command` are valid and
  are expanded by the doctor's check before it looks for the file (v2.58.2). `statusline use|install`
  writes both `~/.claude/settings.json` and `statusline.active` in config.yaml; the latter is what
  `doctor install` reads when deciding whether to offer the installer.
- **Platforms:** categories can be platform-gated (e.g. `fish_config` is macOS-only by default).

## Machine-readable outputs
- **`--json`** (Core-First commands, single-line JSON on stdout via `click.echo`, never the ANSI Rich
  console): `status`, `categories list`, `config show`, `config validate`, `sync` (incl. `--dry-run`),
  `diff`, `doctor check|install|update`, `profile on|off|list|status`, `statusline list|show|use`.
  Implementation: `sccs/output/json_emit.py`. Use these for GUI/automation consumption instead of
  scraping the Rich text. `doctor check --json` carries `statusline_presets` (every known preset with
  `installed`/`is_active`/`is_configured`/`version`) next to the `status_lines` integrity check.
- **`sccs capacity --json`**: per-provider quota windows (both `used_percent` and remaining, since providers
  disagree on which half they report), a `source` naming each number's provenance (`session-cache` / `live` /
  `assumed` / `unavailable`), and a `routing` block. `unknown` is deliberately distinct from `tight`.
- **Self-serve card:** `sccs capability-card` → this card as raw Markdown (self-description; version
  always live-injected).
- **Non-interactive escapes:** `config init --repo-path PATH` bypasses the interactive prompt.
- **Exit codes:** `sccs doctor check` exits non-zero when problems exist (an *available update* is
  informational only and does NOT affect the exit code — pass `--no-update-check` in CI to skip the
  network call entirely); config/sync errors also exit non-zero.
- **State:** persists as YAML under `~/.config/sccs/` (`.sync_state.yaml`, doctor state) — read those
  files directly if you need structured state.

## Deeper docs
- `docs/usage/sync.md` — workflows, conflict resolution, backups, config schema.
- `docs/usage/doctor.md` — every check, cascade-resilience, statusline, manual blocks.
- `docs/usage/profiles.md` — profiles, statusline presets, install safety (DE/EN).
- `docs/usage/transfer.md` — export/import (ZIP) use cases.
- `docs/usage/opencode.md` — model mapping & conversion rules.
- `docs/usage/categories.md` · `docs/usage/platforms.md` · `docs/usage/cli-reference.md` — full reference.
- Config: `~/.config/sccs/config.yaml` · env: `SCCS_CONFIG` (config path), `EDITOR`/`VISUAL` (merge/edit).
