<!--
  Capability Card — generated/maintained via the `cli-capability-card` skill.
  Audience: an LLM/agent that wants to USE this tool. Keep it dense and current.
  Regenerate the command table with scripts/introspect_cli.py after CLI changes.
-->
# sccs — Agent Capability Card

> Bidirectional, YAML-configured sync for Claude Code files (skills, commands, hooks, agents,
> scripts) and shell configs between a local `~/.claude/` and a git repository — plus a "doctor"
> that installs/heals a Claude Code setup and converters that push artefacts to OpenCode.

- **Invoke:** `sccs <command> [options]`  ·  `python -m sccs <command>`
- **Install:** `uv pip install -e ".[dev]"` (from repo root, into a `uv venv`)
- **Version:** 2.51.0  ·  **Python:** ≥3.10
- **Framework:** Click (group `sccs.cli:cli`)  ·  **Human docs:** `docs/usage/*.md`, `README.md`
- **Self-serve:** `sccs capability-card` prints this card from the installed tool (live version injected)

## Capabilities at a glance
- Two-way sync of Claude Code skills/commands/hooks/agents/scripts and shell config between
  `~/.claude/` (+ `~/.config/fish` etc.) and a git repo, with per-category direction control.
- Conflict resolution: interactive hunk-merge/editor menu, or non-interactive `--force local|repo|newer`.
- Auto-commit / auto-push / auto-pull around sync, gated by config and per-run flags.
- Timestamped backups before every overwrite; dry-run preview on every mutating command.
- Selective ZIP export/import of items for deploying configs to other machines (zip-slip-safe import).
- "Doctor": inspect & repair a Claude Code environment (Node, `claude` CLI, plugins, npx tools,
  bundled skills, Playwright browsers, filesystem permissions, statusline) — CI-friendly.
- Push Claude agents/commands/MCP servers into OpenCode (`~/.config/opencode/`), with model mapping.
- Push Claude skills/agents/commands one-way into Pi (`~/.pi/agent/`) and OpenAI Codex
  (skills verbatim → `~/.agents/skills/`, agents → `~/.codex/agents/*.toml`, commands wrapped as skills).
- Convert a Fish shell config into a PowerShell profile or a native zsh profile (best-effort
  function translation, `uname`-guarded platform files); generate a hub README for the repo.
- Inspect status/history/diffs and manage which categories are enabled.

## Command reference

| Command | Purpose | Args / Flags |
|---|---|---|
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
| `sccs export` | Export selected items as ZIP archive. | -o/--output PATH, --all, -c/--category TEXT |
| `sccs import` | Import items from an SCCS export archive. | ZIP_PATH, -n/--dry-run, --overwrite, --no-backup, --all |
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
| `sccs integrations codex export-skills` | Copy Claude skills into Codex skills (~/.agents/skills/). | -n/--dry-run, --overwrite/--no-overwrite, -s/--skill TEXT |
| `sccs integrations codex export-agents` | Convert Claude agents into Codex agent TOML files (~/.codex/agents/). | -n/--dry-run, --overwrite/--no-overwrite, -a/--agent TEXT |
| `sccs integrations codex export-commands` | Wrap Claude commands as Codex skills (~/.agents/skills/<name>/SKILL.md). | -n/--dry-run, --overwrite/--no-overwrite, -c/--command TEXT |
| `sccs integrations codex export-all` | Export skills, agents and commands to Codex in one run. | -n/--dry-run, --overwrite/--no-overwrite |
| `sccs integrations codex status` | Show Codex installation and export gaps. | — |
| `sccs integrations status` | Show detailed integration status. | — |
| `sccs integrations trust-repo` | Register SCCS repository as trusted in Claude Desktop. | -n/--dry-run |
| `sccs log` | Show sync history. | --last INTEGER |
| `sccs status` | Show synchronization status. | -c/--category TEXT, --json |
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
sccs integrations codex status                    # skills/agents/commands still to export
sccs integrations codex export-skills --dry-run
sccs integrations codex export-all                # skills verbatim → ~/.agents/skills/, agents → ~/.codex/agents/*.toml
sccs integrations codex export-agents -a reviewer # one agent only (bypasses gsd-* exclude)
```
One-way (Claude Code is source of truth). Skills copy verbatim (identical agentskills.io format);
agents become Codex agent TOML (body → `developer_instructions`, model alias → Codex model +
reasoning effort, read-only tool sets → `sandbox_mode = "read-only"`); commands are wrapped as
skills (Codex prompts are deprecated). The bundled model map is static — override via
`codex.model_map` in config. Name collisions: a real skill always wins over a same-named command
(skipped with a warning). `gsd-*` excluded by default. No MCP merge / no CLAUDE.md→AGENTS.md (v1).

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
  - `doctor optimize --strict` *removes* foreign plugins/MCP servers; doctor's hook removal / statusline
    rewrite are confirm-gated — `--yes` skips those confirms too. Use `--yes` only in CI.
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
- **Platforms:** categories can be platform-gated (e.g. `fish_config` is macOS-only by default).

## Machine-readable outputs
- **`--json`** (Core-First commands, single-line JSON on stdout via `click.echo`, never the ANSI Rich
  console): `status`, `categories list`, `config show`, `config validate`, `sync` (incl. `--dry-run`),
  `diff`, `doctor check|install|update`. Implementation: `sccs/output/json_emit.py`. Use these for
  GUI/automation consumption instead of scraping the Rich text.
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
- `docs/usage/transfer.md` — export/import (ZIP) use cases.
- `docs/usage/opencode.md` — model mapping & conversion rules.
- `docs/usage/categories.md` · `docs/usage/platforms.md` · `docs/usage/cli-reference.md` — full reference.
- Config: `~/.config/sccs/config.yaml` · env: `SCCS_CONFIG` (config path), `EDITOR`/`VISUAL` (merge/edit).
