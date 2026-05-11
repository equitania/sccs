# External Integrations

**Analysis Date:** 2026-05-11

## External Binaries (subprocess invocations)

All subprocess calls go through one of two hardened wrappers:
- `sccs/doctor/runner.py:_run()` — doctor subsystem; validates `argv[0]` against `_SAFE_HEAD_PATTERN`; `shell=False` always; `stdin=DEVNULL`
- `sccs/git/operations.py:_run_git()` — git subsystem; prepends `["git"]`; `shell=False` always

### git

**Purpose:** Sync repository operations (commit, push, pull, clone, status, fetch)

**Invocation module:** `sccs/git/operations.py`

**Commands used:**
- `git rev-parse --show-toplevel` — repo root detection
- `git status --porcelain` — change detection
- `git add -A` / `git add -- <files>` — staging
- `git commit -m <msg> [--author <name>]` — commits
- `git push [-u] <remote> [<branch>]` — normal push
- `git push --force-with-lease <remote> [<branch>]` — force push (uses `--force-with-lease`, not `--force`)
- `git fetch` — remote refresh
- `git pull [--rebase]` — pull
- `git clone [--depth] -- <url> <dest>` — clone
- `git init` — repo init
- `git rev-list --left-right --count HEAD...origin/<branch>` — ahead/behind check

**Security:** Remote names validated against `_GIT_REMOTE_PATTERN`; branch names against `_GIT_BRANCH_PATTERN`; author against `_GIT_AUTHOR_PATTERN`; clone URL checked for leading `-`

### claude (Claude Code CLI)

**Purpose:** Plugin management for Claude Code environment setup

**Invocation module:** `sccs/doctor/runner.py`, `sccs/doctor/installer.py`

**Commands used:**
- `claude plugin list` — detect installed plugins (`runner.run_claude_plugin_list()`)
- `claude plugin marketplace list` — detect registered marketplaces (`runner.run_claude_marketplace_list()`)
- `claude plugin marketplace update <name>` — refresh stale marketplace cache (auto-queued in install plan)
- `claude plugin marketplace add <source>` — register a new marketplace (queued when `marketplace_source` configured)
- `claude plugin install <name>[@<marketplace>]` — install missing plugin
- `claude plugin update <name>[@<marketplace>] [--scope <scope>]` — update installed plugin

**Detection:** `shutil.which("claude")` in `sccs/doctor/detectors.py:ClaudeCliDetector`

**Install action (when missing):** `npm install -g @anthropic-ai/claude-code` — queued by `sccs/doctor/installer.py:_claude_cli_action()`

### npm

**Purpose:** Global package management for Node.js tools

**Invocation module:** `sccs/doctor/detectors.py`, `sccs/doctor/installer.py`, `sccs/doctor/defaults.py`

**Commands used:**
- `npm root -g` — resolve global node_modules path (permission check + bundled skill copy)
- `npm config get prefix` — resolve `<prefix>/bin` for PATH check
- `npm install -g @anthropic-ai/claude-code` — install Claude CLI
- `npm install -g @playwright/cli@latest` — install/update playwright-cli (defined in `sccs/doctor/defaults.py:DEFAULT_NPX_TOOLS`)
- `npm config set prefix ~/.npm-global` — shown in manual fix block (print-only, never executed)

### npx

**Purpose:** Run one-shot Node.js tools without global install

**Invocation module:** `sccs/doctor/defaults.py`, `sccs/doctor/installer.py`

**Commands used:**
- `npx -y get-shit-done-cc --claude --global --force-statusline` — patches `~/.claude/` config (no binary dropped on PATH; detected via doctor state file)

**Note:** `-y` flag is mandatory — without it, npx hangs on stdin on fresh Linux hosts because `capture_output=True` hides the prompt

### playwright-cli

**Purpose:** Browser automation; installed globally via npm

**Invocation module:** `sccs/doctor/defaults.py` (post_install), `sccs/doctor/installer.py`

**Commands used:**
- `playwright-cli install-browser chromium` — download Chromium bundle
- `playwright-cli install-browser firefox` — download Firefox bundle

**Detection:** `shutil.which("playwright-cli")`

**Browser cache:** Resolved at runtime via `$PLAYWRIGHT_BROWSERS_PATH` or platform default:
- Linux: `~/.cache/ms-playwright/`
- macOS: `~/Library/Caches/ms-playwright/`
- Windows: `%LOCALAPPDATA%/ms-playwright/`

### node

**Purpose:** Node.js version detection

**Invocation module:** `sccs/doctor/runner.py:run_node_version()`

**Commands used:**
- `node --version` — returns version string; parsed for major version by `parse_node_major()`

**Minimum version:** 20 (defined in `sccs/doctor/defaults.py:MIN_NODE_MAJOR`)

### brew (macOS only)

**Purpose:** Node.js installation on macOS

**Invocation module:** `sccs/doctor/defaults.py:NODE_INSTALL["macos"]`

**Commands used:**
- `brew install node` — only queued when Node.js is missing and platform is `macos`

### winget (Windows only)

**Purpose:** Node.js installation on Windows

**Invocation module:** `sccs/doctor/defaults.py:NODE_INSTALL["windows"]`

**Commands used:**
- `winget install OpenJS.NodeJS` — only queued when Node.js is missing and platform is `windows`

---

## Data Storage

**Config file:**
- Location: `~/.config/sccs/config.yaml` (overridable via `$SCCS_CONFIG`)
- Format: YAML, read/written by `sccs/config/loader.py`
- Schema: `sccs/config/schema.py:SccsConfig` (Pydantic)

**Sync state:**
- Location: `~/.config/sccs/.sync_state.yaml`
- Format: YAML — maps `{category: {item: {hash, timestamp}}}`
- Manager: `sccs/sync/state.py:StateManager`

**Doctor state:**
- Location: `~/.config/sccs/.doctor_state.yaml`
- Format: YAML — records successful npx tool invocations for tools without PATH binary
- Manager: `sccs/doctor/state.py:DoctorStateManager`

**Log file:**
- Location: `~/.config/sccs/sync.log` (if configured)
- Handler: `sccs/utils/logging.py:get_logger()`

---

## Filesystem Touchpoints

| Path | Purpose | Access |
|------|---------|--------|
| `~/.config/sccs/` | All SCCS state, config, logs | read/write |
| `~/.config/sccs/config.yaml` | Main config | read/write |
| `~/.config/sccs/.sync_state.yaml` | Sync state | read/write |
| `~/.config/sccs/.doctor_state.yaml` | Doctor state | read/write |
| `~/.claude/` | Claude Code config dir | read/write (sync target) |
| `~/.claude/skills/` | Claude skills (sync category) | read/write |
| `~/.claude/skills/playwright-cli/` | Bundled skill copy from npm | write (managed, excluded from sync) |
| `~/.npm/` | npm cache — permission check target | read (ownership scan only) |
| `~/.npm-global/` | User-local npm prefix (recommended fix) | mentioned in manual blocks |
| `~/Library/Caches/ms-playwright/` | Playwright browser bundles (macOS) | read (bundle detection) |
| `~/.cache/ms-playwright/` | Playwright browser bundles (Linux) | read (bundle detection) |
| `~/.antigravity/` | Antigravity IDE install dir | read (detection in `sccs/integrations/detectors.py`) |
| `~/.antigravity/prompts/` | Antigravity prompt files | read/write (skill sync) |
| `/Applications/Claude.app` | Claude Desktop (macOS) | read (existence check) |
| `~/Library/Application Support/Claude/claude_desktop_config.json` | Claude Desktop config | read (trusted folders) |
| `<repo>/` | Sync repository (configured path) | read/write |

---

## Claude Plugin Marketplaces

Configured in `sccs/doctor/defaults.py:DEFAULT_CLAUDE_PLUGINS`:

| Plugin | Marketplace | Source |
|--------|-------------|--------|
| `skill-creator` | `claude-plugins-official` | — |
| `superpowers` | `claude-plugins-official` | — |
| `frontend-design` | `claude-plugins-official` | — |
| `context-mode` | `context-mode` | `mksglu/context-mode` |
| `claude-mem` | (bare name) | `thedotmack/claude-mem` |

Marketplace detection: `sccs/doctor/detectors.py:ClaudeMarketplaceDetector` parses `claude plugin marketplace list`

---

## Third-Party Integrations (detection only, no subprocess)

**Antigravity IDE:**
- Detection: `~/.antigravity/` dir existence
- Skill gap sync: `sccs/integrations/detectors.py:AntigravityDetector`
- Copies `~/.claude/skills/<name>/SKILL.md` → `~/.antigravity/prompts/<name>.md`

**Claude Desktop (macOS only):**
- Detection: `/Applications/Claude.app` dir existence
- Config read: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Used for: trusted folder check (`sccs/integrations/detectors.py:ClaudeDesktopDetector`)

---

## CI/CD & Distribution

**Hosting:**
- PyPI — published as `sccs` package
- GitHub: `https://github.com/equitania/sccs` (homepage, issues, docs)

**CI Pipeline:**
- Not detected in repo (no `.github/workflows/` or `.gitlab-ci.yml` found in source)

**Build:**
- `uv build` — produces wheel via hatchling
- Wheel includes only `sccs/` package (`[tool.hatch.build.targets.wheel] packages = ["sccs"]`)

---

## Environment Variables

**Required / important:**
- `SCCS_CONFIG` — override config file path
- `HOME` — used for `~` expansion throughout
- `PATH` — inspected by `PathPrefixDetector` for npm-prefix-bin check
- `PLAYWRIGHT_BROWSERS_PATH` — override Playwright browser cache root

**Never read (security):**
- `.env` files — not used; no secrets stored

---

*Integration audit: 2026-05-11*
