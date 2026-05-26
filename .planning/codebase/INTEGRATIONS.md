# External Integrations

**Analysis Date:** 2026-05-26

## External Binaries (subprocess invocations)

All subprocess calls go through validated wrappers — never `shell=True`. Two wrappers enforce this contract:

- `sccs/git/operations.py:_run_git()` — git only; validates remote/branch names via regex
- `sccs/doctor/runner.py:_run()` — doctor subprocesses; argv[0] validated against `_SAFE_HEAD_PATTERN`; `sudo` hard-blocked

### git

**What:** Bidirectional file sync commit and push after category sync operations.

**Invoked via:** `sccs/git/operations.py` — wraps `subprocess.run(["git", ...], shell=False)`

**Commands used:**
- `git rev-parse`, `git status --porcelain`, `git add`, `git commit -m`, `git push`
- `git clone` (for repo init), `git fetch`, `git pull`, `git init`

**Triggered by:** `sccs sync` (when `auto_commit: true` or `auto_push: true` in config), `sccs/sync/engine.py`

**Auth:** Relies on the user's ambient git credential configuration (SSH keys, credential helpers). SCCS does not manage git credentials.

**Validation:** remote names validated by `_GIT_REMOTE_PATTERN`, branch names by `_GIT_BRANCH_PATTERN` (both block `-` prefix to prevent option injection). Force-push uses `--force-with-lease` only.

---

### claude (Claude Code CLI)

**What:** Doctor subsystem detects, installs, updates, and removes Claude Code plugins and MCP servers by shelling out to the `claude` CLI.

**Invoked via:** `sccs/doctor/runner.py:_run()` and helpers `run_claude_plugin_list()`, `run_claude_mcp_list()`, `run_claude_marketplace_list()`

**Commands used:**
- `claude plugin list` — detect installed plugins (`sccs/doctor/detectors.py:ClaudePluginDetector`)
- `claude plugin install <name@marketplace>` — install missing plugins (`sccs/doctor/installer.py`)
- `claude plugin update <name@marketplace> [--scope <scope>]` — update installed plugins
- `claude plugin uninstall <name@marketplace> [--scope <scope>]` — remove foreign plugins (optimize --strict)
- `claude plugin marketplace list` — detect registered marketplaces (`sccs/doctor/detectors.py:ClaudeMarketplaceDetector`)
- `claude plugin marketplace update <name>` — refresh stale marketplace metadata (soft-fail)
- `claude plugin marketplace add <source>` — register a missing marketplace
- `claude mcp list` — detect registered MCP servers (`sccs/doctor/detectors.py:MCPServerDetector`)
- `claude mcp remove <name> -s user` — remove foreign MCP servers (optimize --strict)

**Timeout:** 15 s for plugin list/marketplace list; 20 s for mcp list

**Triggered by:** `sccs doctor check`, `sccs doctor install`, `sccs doctor update`, `sccs doctor optimize`

**Detection:** `shutil.which("claude")` in `ClaudeCliDetector.get_status()` (`sccs/doctor/detectors.py`)

**Install action:** `npm install -g @anthropic-ai/claude-code` queued when CLI is absent

---

### npm / npx

**What:** Doctor manages Node.js-based tools via npm/npx.

**Invoked via:** `sccs/doctor/runner.py:_run()`

**Commands used:**
- `npm install -g @anthropic-ai/claude-code` — install Claude Code CLI
- `npm install -g @playwright/cli@latest` — install/update playwright-cli
- `npm root -g` — resolve npm global root directory (for bundled-skill copy)
- `npm config get prefix` — resolve npm bin dir (PATH gap detection)
- `npx -y get-shit-done-cc --claude --global --force-statusline` — GSD environment setup

**Default npx tools** (configured in `sccs/doctor/defaults.py:DEFAULT_NPX_TOOLS`):
- `get-shit-done-cc` — detected via doctor state file (no binary on PATH); runs `npx -y`
- `playwright-cli` — detected via `shutil.which("playwright-cli")`; installed via `npm install -g`

**Post-install steps** (also re-run on update):
- `playwright-cli install-browser chromium`
- `playwright-cli install-browser firefox`

**Bundled skill copy:** After `playwright-cli` install, `npm root -g` is called to locate `@playwright/cli/skills/playwright-cli/` and copy it to `~/.claude/skills/playwright-cli/`

---

## Files Read and Written

### `~/.claude/settings.json` (Claude Code settings)

**Read by:**
- `sccs/doctor/detectors.py:StatusLineDetector` — inspect `statusLine.command` for stale Cellar paths and missing binaries
- `sccs/doctor/detectors.py:SettingsHookDetector` — find hook entries matching `disallowed_hooks` patterns

**Written by:**
- `sccs/doctor/installer.py:_status_line_actions()` — auto-fix stale Homebrew Cellar path in `statusLine.command` (writes backup before modify)
- `sccs/doctor/installer.py:_settings_hook_cleanup_actions()` — remove disallowed hook entries (writes timestamped backup before modify, e.g. `settings.json.bak-20260526-143021`)
- `sccs/sync/settings.py:ensure_settings()` — non-destructive JSON merge: adds missing keys from `settings_ensure` category config; never overwrites existing keys; writes backup before modify

**Backup pattern:** `settings.json.bak-YYYYMMDD-HHMMSS` written alongside the original before any mutation

**Interaction:** All writes use `json.loads` / `json.dumps(indent=2) + "\n"` round-trip; UTF-8 throughout

---

### `~/.config/sccs/config.yaml` (SCCS configuration)

**Read by:** `sccs/config/loader.py:load_config()` — primary config load path on every command

**Written by:**
- `sccs/config/loader.py` — `sccs config init`, `sccs config upgrade`, `sccs categories enable/disable`
- `sccs/config/migration.py:MigrationStateManager` — records which default categories have been offered to the user

**Path override:** `SCCS_CONFIG` environment variable overrides default path

**Format:** YAML; loaded with `yaml.safe_load`, written with `yaml.dump`

---

### `~/.config/sccs/.sync_state.yaml` (sync state)

**Read/Written by:** `sccs/sync/state.py:StateManager` — tracks per-item content hashes and timestamps across sync runs; used for change detection in `sync/category.py`

---

### `~/.config/sccs/.doctor_state.yaml` (doctor state)

**Read/Written by:** `sccs/doctor/state.py:DoctorStateManager` — records successful `npx` invocations for tools that do not drop a binary on PATH (notably `get-shit-done-cc`); used by `NpxToolDetector` as fallback when `shutil.which()` finds nothing

---

### `~/.config/sccs/sync.log` (optional log file)

**Written by:** `sccs/utils/logging.py` — when logging is configured in `config.yaml`

---

## Claude Desktop Integration

**File:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS only)

**What:** `sccs/integrations/claude_desktop.py:register_trusted_folder()` reads and writes this file to add the SCCS sync repository to `preferences.localAgentModeTrustedFolders`

**Platform:** macOS only; returns error on Linux/Windows

**Triggered by:** `sccs config` commands that expose trust registration

**Writes backup** via `sccs/utils/paths.py:create_backup()` before any modification

---

## Antigravity IDE Integration

**What:** `sccs/integrations/antigravity.py` + `sccs/integrations/detectors.py` — migrate Claude Code `SKILL.md` files to Antigravity IDE prompt files

**Files read:** `~/.claude/skills/*/SKILL.md` files

**Files written:** Antigravity prompts directory (path resolved at runtime)

**No subprocess calls** — pure filesystem copy via `sccs/utils/paths.py:atomic_write()`

---

## Node.js Environment Detection

**What:** Doctor detects Node.js version and validates `min_node_major` (default: 20)

**Via:** `sccs/doctor/runner.py:run_node_version()` — calls `node --version`

**Install hints** (print-only, never executed by SCCS):
- macOS: `brew install node`
- Linux/Windows: manual URL blocks surfaced as text

---

## Filesystem Permission Checks

**What:** Doctor scans known-fragile paths for foreign ownership that breaks npm/npx

**Default paths checked** (`sccs/doctor/defaults.py:DEFAULT_PERMISSION_CHECKS`):
- `~/.npm` — npm cache directory
- `~/.claude` — Claude config directory
- `~/.config/sccs` — SCCS config directory
- `npm root -g` (resolved at runtime) — npm global root (lib/node_modules)
- `npm config get prefix` + `/bin` (resolved at runtime) — npm global bin directory

**Detection:** `sccs/doctor/detectors.py:PermissionDetector` — recursive ownership scan capped at 500 entries

**Remediation:** print-only manual blocks (`sudo chown ...`); SCCS never calls sudo

---

## ZIP Transfer (Export/Import)

**What:** `sccs/transfer/` — machine-to-machine config portability via ZIP archives

**Format:** `.zip` file containing `sccs-manifest.json` + directory tree of selected items

**No network calls** — purely local filesystem read/write via `zipfile` stdlib module

**Triggered by:** `sccs export` / `sccs import` CLI commands

---

## Webhooks and Callbacks

**Incoming:** None

**Outgoing:** None — SCCS makes no HTTP requests; all operations are local filesystem + subprocess

---

## Environment Configuration Summary

**Required variables:** None — all paths have defaults

**Optional variables:**
- `SCCS_CONFIG` — override config file path
- `PLAYWRIGHT_BROWSERS_PATH` — override browser cache location

**Secrets:** None — SCCS does not handle API keys, tokens, or credentials

---

*Integration audit: 2026-05-26*
