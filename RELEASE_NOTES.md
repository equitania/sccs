# Release Notes

## Version 2.26.0 (05.05.2026)

### Added
- **`sccs doctor check` now verifies bundled Claude skills and browser bundles, not just the npm tool's binary on PATH.** Two diagnostic gaps from v2.25.x are closed:
  1. **Bundled skills:** `BundledSkillDetector` checks that each `NpxToolSpec.bundled_skill.target/SKILL.md` exists. Without this, deleting `~/.claude/skills/playwright-cli/` left `check` happily reporting OK while Claude couldn't see the skill anymore.
  2. **Browser bundles:** `BrowserBundleDetector` scans the resolved Playwright cache (`$PLAYWRIGHT_BROWSERS_PATH` → platform default: `~/.cache/ms-playwright` on Linux, `~/Library/Caches/ms-playwright` on macOS, `%LOCALAPPDATA%\ms-playwright` on Windows) for `<bundle>-*` subdirectories. Missing browsers now surface as `MISSING` rows instead of failing silently at first `pw open`.
- **New `NpxToolSpec.browser_bundles: list[str]`** — declarative list of bundles a tool downloads via a separate post-install step. Validated with the same safe-name allowlist as `name`. Playwright-CLI default ships `["chromium", "firefox"]`; future tools that mirror this pattern get the diagnostic for free.
- **Targeted repair actions in `build_install_plan`.** When the npm tool itself is on PATH but a bundled skill or browser is missing, the install plan now queues a single repair action — `_bundled_skill_action` or `<binary> install-browser <name>` — instead of re-running the entire install chain. When the tool itself is missing, the existing install path already covers everything; the new actions are deduplicated to avoid double-runs.
- **Reporter integration:** `_bundled_skill_row` and `_browser_bundle_row` add two new rows per `NpxToolSpec` that opts in. `has_problems()` and `render_inline_summary()` count them so a missing skill or browser flips the doctor exit code to 1.

### Tests
- 20 new tests in `tests/test_doctor.py` across 6 classes: `TestBundledSkillDetector` (3), `TestBrowserBundleDetector` (6, incl. env-override + macOS path regression), `TestBundledSkillReporter` (2), `TestBrowserBundleReporter` (3), `TestBuildInstallPlanWithBundles` (3, incl. dedup-guard when tool itself is missing), `TestHasProblemsWithBundles` (3).

## Version 2.25.1 (05.05.2026)

### Fixed
- **`sccs doctor update` failed for plugins installed under a non-`user` scope.** Real-world incident on Debian 13: `claude plugin list` reported `superpowers@claude-plugins-official` as installed, but `claude plugin update superpowers@claude-plugins-official` (which defaults to `--scope user`) responded with `Plugin "superpowers" is not installed at scope user`. The plugin was installed under a different scope (e.g. `project` or `local`), so the default-`user` lookup never found it. Fix has two parts:
  1. `ClaudePluginDetector` now reads the `Scope: <value>` line from each plugin's metadata block in `claude plugin list` and stores it on `PluginStatus.scope`.
  2. `_plugin_update_actions` forwards the detected scope as `--scope <user|project|local|managed>` so `claude plugin update` looks in the correct place. Unknown scope values are silently dropped (defensive against a future Claude CLI release that introduces a new scope).
- **Generic soft-fail for `not installed at scope X` errors during plugin updates.** When the detector classified a plugin as installed but `claude plugin update` still rejects it as "not installed at scope X", `execute_plan` now records the action as `skipped` (with the original stderr in `detail`) rather than `failed`. Detection said the plugin is there — this is a list/update mismatch in the Claude CLI, not a real install problem, so it shouldn't turn the doctor report red.

### Tests
- 9 new tests in `tests/test_doctor.py`:
  - `TestPluginScopeDetection` (4): `Scope: user`/`Scope: project` extraction, `None` when missing, no scope-bleed across neighbouring plugin blocks in the list output.
  - `TestPluginUpdateActionScopeForwarding` (3): `--scope project` appended when known, omitted when `None`, dropped silently when value is unknown (e.g. `weirdscope`).
  - `TestPluginUpdateScopeMismatchSoftFail` (2): "not installed at scope user" is reclassified `skipped`; unrelated update errors still surface as `failed`.

## Version 2.25.0 (05.05.2026)

### Added
- **`sccs doctor` now installs browser bundles and the bundled Claude skill for `playwright-cli` automatically.** Two reproducibility issues from v2.24.0 are addressed:
  1. **"Browser not found" on first use:** `npm install -g @playwright/cli@latest` ships only the CLI — Chromium and Firefox bundles are downloaded separately via `playwright-cli install-browser <name>`. Doctor now appends both calls as `post_install` actions on every install/update. The command is idempotent (skips when the requested version is already in the local cache, downloads otherwise), so the same calls double as the automated update check.
  2. **Skill missing from Claude:** `@playwright/cli` ships a Claude skill at `<npm root -g>/@playwright/cli/skills/playwright-cli/` (SKILL.md + 11 reference docs), but Claude only discovers skills under `~/.claude/skills/`. Doctor now resolves the npm global root at execute-time and copies the directory into place. The destination is auto-excluded from `sccs sync` via `DEFAULT_MANAGED_PATTERNS` so two machines that both run `sccs doctor` cannot fight over the tree.
- **Generic mechanism, not a special case.** Two new fields on `NpxToolSpec` carry the heavy lifting:
  - `post_install: list[list[str]]` — argv lists executed sequentially after the main `invocation` succeeds. Same security validation as `invocation` (head must not start with `-`, must match the safe-name pattern). Idempotent commands here also serve as the automated update probe.
  - `bundled_skill: BundledSkillSpec | None` — declarative pointer to a directory inside the npm package; doctor resolves `npm root -g` at runtime, copies into the configured target.
- `DoctorAction.python_callable: Callable[[], None] | None` — in-process action backing the bundled-skill copy. Avoids whitelisting `cp` in the runner and keeps path resolution Python-side. `execute_plan` runs callables under the same confirm-prompt + error-handling flow as subprocess actions.
- `managed.DEFAULT_MANAGED_PATTERNS` gains `playwright-cli` → `["playwright-cli"]` so the skill directory is silently skipped by `sccs sync`.

### Tests
- 10 new tests in `tests/test_doctor.py::TestPlaywrightCliBundling`: defaults presence, schema validation, install-plan composition (main + chromium + firefox + skill-sync ordering), update-plan re-run guarantee, `_sync_bundled_skill` happy path + overwrite + missing-source error, `execute_plan` with `python_callable`, post-install argv-injection guard.

## Version 2.24.0 (05.05.2026)

### Added
- **`sccs doctor` now manages [Playwright CLI](https://github.com/microsoft/playwright-cli) (`@playwright/cli`).** A second entry has been added to `DEFAULT_NPX_TOOLS`: `playwright-cli` is now installed/updated via `npm install -g @playwright/cli@latest` whenever the user runs `sccs doctor install` or `sccs doctor update`. The detector resolves the binary via `shutil.which("playwright-cli")` (`detect_via_state=False`), so a fresh machine reports `missing` until the install action runs. The previous fish-shell workaround (`pw-update.fish`) is no longer required — both entry points stay compatible because they use the exact same `npm install -g` invocation.
- **Why `npm install -g` instead of `npx -y`?** Playwright CLI ships a real binary on PATH that is invoked many times per session. A one-shot `npx -y` would re-fetch the package on every call. `npm install -g …@latest` handles both fresh installs and updates because `_npx_update_actions` re-runs the same invocation.
- **Out of scope (intentional):** SCCS does *not* attempt to copy a `SKILL.md` out of the npm package. `@playwright/cli@0.1.11` does not ship one, so the corresponding step in the fish workaround prints `SKILL.md not found in npm package (non-critical)` and was the source of "skills are not installed correctly" confusion. Skill content for `playwright-cli` belongs in the sccs-sync repo under `.claude/skills/playwright-cli/` and is distributed via `sccs sync`.

### Tests
- 3 new tests in `tests/test_doctor.py`:
  - `TestRunnerSecurity::test_default_playwright_cli_uses_npm_install_global` — regression guard against a future refactor that switches to `npx`.
  - `TestNpxToolDetector::test_playwright_cli_present_when_binary_on_path` — end-to-end check that the new default flows through `NpxToolDetector` with `detect_via_state=False`.
  - `TestNpxToolDetector::test_playwright_cli_missing_when_binary_absent` — without state-file fallback, missing binary must surface as not-installed so `build_install_plan` picks up the action.

## Version 2.23.0 (04.05.2026)

### Added
- **`sccs doctor` now verifies filesystem permissions for known-fragile paths.** Triggered by a real-world incident on Debian 13: a `~/.npm/_cacache/` subtree owned by root (leftover from a prior `sudo npm` run) silently broke every subsequent `npx ...` invocation with EACCES — and there was no diagnostic to tell the user which directory was misowned or how to fix it. Doctor now scans the relevant directories, reports any foreign-owned entries, and prints the exact `sudo chown -R UID:GID <path>` command to copy. SCCS itself never invokes sudo (HARD RULE) — the user runs the fix manually.
- New module: `sccs/doctor/schema.py::PermissionCheckSpec` (Pydantic model with path/label/purpose), `sccs/doctor/detectors.py::PermissionStatus + PermissionDetector` (capped recursive ownership scan with `_MAX_PATHS_SCANNED=500` and `_MAX_OFFENDERS_REPORTED=5` so doctor stays fast even on huge caches).
- New defaults: `DEFAULT_PERMISSION_CHECKS` ships three baseline checks — `~/.npm` (npx/npm cache), `~/.claude` (claude plugin install target), `~/.config/sccs` (doctor + sync state).
- `DoctorConfig.permission_checks` (override) and `DoctorConfig.extra_permission_checks` (append) for users who want to add their own paths via `~/.config/sccs/config.yaml`.
- Reporter changes: the doctor table now contains a `perm: <path>` row per check; below the table, any failing check prints its `purpose`, up to 3 example offending paths and the exact `sudo chown` fix command.
- `sccs status` inline summary appends `[red]perm issues: N[/red]` when any permission check fails.

### Hardened
- Permission issues feed into `build_install_plan` / `build_update_plan` as runnable=False manual blocks at the *front* of the plan, so the user sees the chown command before any subsequent npm/npx/claude action would have failed with EACCES.
- The detector skips entirely on Windows (`sys.platform == "win32"` or no `os.getuid`) and reports the path as `?` in the table — POSIX uid/gid checks don't map cleanly onto NT ACLs, and `sudo chown` wouldn't apply there.

### Tests
- 7 new tests in `tests/test_doctor.py`:
  - `TestPermissionDetector` — 5 cases: nonexistent path → OK; user-owned path → OK; foreign-owned root → flagged with offending paths + correct fix command; offender list capped; `~` expansion via `HOME` monkeypatch.
  - `TestPermissionInstallPlan` — 2 cases: foreign-owned path produces a runnable=False manual block at the front of the plan; default checks include `~/.npm` and `~/.claude` and `~/.config/sccs` (regression guard).

## Version 2.22.1 (04.05.2026)

### Fixed
- **`sccs doctor install` hung indefinitely on Debian 13 (and any Linux host without an `npx` cache).** Root cause was a two-step interaction:
  - `defaults.py` invoked `npx get-shit-done-cc ...` without the `-y` flag, so on a host where the package was not yet cached `npx` printed `Need to install the following packages: get-shit-done-cc — Ok to proceed? (y)` to stdout and waited on stdin.
  - `runner._run` used `subprocess.run(..., capture_output=True)`, which pipes stdout/stderr (so the prompt was invisible to the user) but inherits stdin from the parent — so `npx` waited for an answer that the user could not see was being asked. Net effect: the doctor process froze for the full 300 s subprocess timeout.
  - On macOS the same code path worked because previous doctor sprints had already populated the `npx` cache, so `npx` skipped the confirmation prompt entirely.
- `DEFAULT_NPX_TOOLS[0].invocation` now starts with `["npx", "-y", ...]` so the npx confirmation auto-accepts on every host. `-y` is a no-op on cached hosts (macOS), so the change is safe there too.

### Hardened
- **`runner._run` now passes `stdin=subprocess.DEVNULL`** to every doctor subprocess. SCCS doctor is non-interactive by contract — every confirmation is collected up-front via `questionary` *before* the subprocess runs, so any child process that still asks for stdin should fail fast (EOF) instead of hanging the parent for `timeout` seconds. Defends against future hangs from `claude plugin install` (potential "Trust this marketplace?" prompts) and any other tool that might silently expect stdin.

### Tests
- 2 new tests in `tests/test_doctor.py::TestRunnerSecurity`:
  - `test_run_passes_stdin_devnull` — patches `subprocess.run` and asserts that `_run(["echo", "x"])` forwards `stdin=subprocess.DEVNULL`.
  - `test_default_npx_get_shit_done_uses_dash_y` — asserts `DEFAULT_NPX_TOOLS[0].invocation[1] == "-y"` so a future refactor that drops the flag is caught at test time, not on a Debian box.

## Version 2.22.0 (04.05.2026)

### Added
- **Doctor-managed file exclusion from `sccs sync`.** Files installed by `sccs doctor install` (currently the `gsd-*` skills/agents/hooks dropped by `npx get-shit-done-cc --claude --global`) are reproducible from the doctor manifest, so syncing them across machines was a guaranteed conflict source. The sync engine now silently excludes them so the same machine can run both `sccs doctor install` and `sccs sync` without producing conflicts on the next pull.
- New module `sccs/doctor/managed.py` with:
  - `DEFAULT_MANAGED_PATTERNS: dict[str, list[str]]` mapping bundled doctor tool names to their installed glob patterns. Initial entry: `get-shit-done-cc → ["gsd-*"]`.
  - `get_doctor_managed_excludes(doctor_config)` — returns the deduplicated, sorted glob list to merge into the sync engine's effective exclude list. Honours `doctor.npx_tools` membership, so removing the npx tool also drops its patterns.
- New `DoctorConfig.managed_excludes: list[str]` field for user-supplied patterns when shipping additional npx tools or plugins via `~/.config/sccs/config.yaml`.
- `SyncEngine.effective_global_exclude` (new attribute) is the concatenation of `config.global_exclude` plus the doctor-managed patterns; passed through to every `CategoryHandler`.

### Fixed
- **`sccs sync --pull` no longer reports 64 conflicts on machines that ran `sccs doctor install` independently.** Root cause: the `gsd-*` skills/agents/hooks installed by `get-shit-done-cc` carry per-machine differences (timestamps, install order) that produce hash mismatches in `claude_skills`, `claude_hooks` and `claude_agents`. Excluding them from sync entirely is the correct fix because their canonical source is the doctor manifest, not the SCCS repository.

### Tests
- 6 new `tests/test_doctor.py::TestDoctorManagedExcludes` cases covering: bundled gsd-* contribution, user override append, deduplication, npx-tool-removal drop, end-to-end SyncEngine integration, and a directory-scan filter test that verifies `find_directories(exclude=["gsd-*"])` actually skips the gsd-managed entries.

## Version 2.21.4 (04.05.2026)

### Fixed
- **GitHub Actions `lint` job (mypy step) failed on v2.21.3.** Three errors surfaced:
  - `sccs/doctor/reporter.py:86,87` — `render_doctor_report` reused the loop variable name `st` for both the `plugins` list (`PluginStatus`) and the `npx_tools` list (`NpxToolStatus`); mypy correctly flagged the implicit type narrowing collision (`Incompatible types in assignment`). Renamed the variables to `plugin_st` / `npx_st` so each loop has its own typed name.
  - `sccs/config/defaults.py:433` — `get_default_settings_ensure` returned `cat_default.get("settings_ensure")` whose static type is `Any`, while the function is declared as `-> dict[str, Any] | None` (`no-any-return`). Added an explicit `isinstance(block, dict)` narrowing before returning so mypy can prove the return type.
- All three errors were pre-existing on origin/main but only surfaced now because the CI mypy step compiles the same source set as the local `uv run mypy sccs/` command. Local `pytest` and `ruff` were already clean — this is a strict-type-check fix only, no runtime behaviour change.

## Version 2.21.3 (04.05.2026)

### Fixed
- **`sccs doctor update` failed for plugins installed under a non-default marketplace.** Two cases observed in the wild:
  - `claude plugin update superpowers@claude-plugins-official` returned `✘ Failed to update plugin "superpowers@claude-plugins-official": Plugin "superpowers" is not installed`, because `superpowers` was actually installed via `superpowers-marketplace` (correctly classified as `alternative` in v2.21.2 but the update still targeted the configured marketplace).
  - `claude plugin update claude-mem` returned `✘ Failed to update plugin "claude-mem": Plugin "claude-mem" not found`, because the bundled `PluginSpec(name="claude-mem", marketplace=None)` produced `install_target == "claude-mem"` while the CLI requires `<name>@<marketplace>` even though the install side accepts the bare name.
- The new helper `installer._effective_update_target(status)` always prefers `PluginStatus.found_marketplace` (what `claude plugin list` actually reports) over the user-configured marketplace; falls back to `spec.install_target` only when no marketplace was detected at all. Update labels and argv now both reflect the effective target.

### Tests
- 3 new tests in `tests/test_doctor.py::TestBuildUpdatePlan` covering: bare-name spec gets `name@found_marketplace`, alternative-marketplace spec uses `name@found_marketplace` instead of the configured one, and the bare-name fallback when no marketplace is detectable.
- `_make_status_set` test helper now accepts `plugin_found_marketplace` and `plugin_detection_source` so future plan tests can simulate the alternative-marketplace classification.

## Version 2.21.2 (04.05.2026)

### Fixed
- **`sccs doctor check` reported `superpowers@claude-plugins-official` as MISSING when the plugin was actually installed under a different marketplace** (e.g. `superpowers@superpowers-marketplace`). The previous detector did a case-insensitive substring search and a bare-token lookup; neither catches a plugin that is installed under an alternative marketplace, because the only token in `claude plugin list` is the joined `name@marketplace` string. `ClaudePluginDetector._detect_plugin` now uses a regex with explicit word boundaries (`(?<![\w\-])<name>@<marketplace>`) so:
  - `superpowers@superpowers-marketplace` correctly satisfies a request for `superpowers@<anything>` and is reported as `OUTDATED` with detail `installed via superpowers-marketplace` (not MISSING — the plugin is there, just from a different source);
  - the longer name `superpowers-developing-for-claude-code@superpowers-marketplace` no longer false-matches a request for the shorter `superpowers` name (regression that the bare-token fallback also missed).
- New `PluginStatus.detection_source: str` field with values `"exact" | "alternative" | "bare" | "missing"` and `PluginStatus.found_marketplace: str | None` so the reporter can render the alternative-marketplace case explicitly.
- `sccs doctor check`'s inline-summary line now appends `[yellow]alt marketplace: N[/yellow]` when any plugin was found under a non-configured marketplace, so the user gets a one-line heads-up alongside the existing `plugins missing: N`.

### Tests
- 4 new tests in `tests/test_doctor.py::TestClaudePluginDetector` covering the alternative-marketplace classification, word-boundary protection against the longer-name false match, exact-match precedence, and the no-marketplace-configured first-match case.

## Version 2.21.1 (04.05.2026)

### Fixed
- **`sccs doctor check` reported `get-shit-done-cc` as MISSING even right after a successful `sccs doctor install`.** Root cause: the tool only patches `~/.claude/` configuration and never drops a binary on `PATH`, so the previous `shutil.which()`-only detection could never observe a successful install. SCCS now persists per-tool run markers in `~/.config/sccs/.doctor_state.yaml` and the `NpxToolDetector` consults the state file as a fallback for tools that opt in via `detect_via_state=True`. The marker carries a hash of the invocation list, so changing the configured argv (e.g. removing `--force-statusline`) invalidates the state and the tool is reported as missing again until re-installed.
- The bundled `get-shit-done-cc` default in `sccs/doctor/defaults.py` now sets `detect_via_state=True`. Existing user configs continue to work — the field defaults to False and is therefore opt-in.

### Added
- New module `sccs/doctor/state.py` (`DoctorStateManager`, `DoctorState`, `NpxToolMark`).
- `NpxToolStatus.detection_source: str` (`"path" | "state" | "missing"`) so the reporter can distinguish "found on PATH" from "found via state cache".
- 10 new tests in `tests/test_doctor.py` covering `DoctorStateManager` round-trip, invocation-hash invalidation, corrupt-yaml resilience, the new state-fallback paths in `NpxToolDetector` and the install-success state-write contract.

## Version 2.21.0 (04.05.2026)

### Added
- **`sccs doctor` — system & plugin health checks** for Claude Code environments. New top-level command group with three subcommands:
  - `sccs doctor check` — read-only Rich status table for Node.js (>= 20), the `claude` CLI, the configured Claude plugins (`skill-creator`, `superpowers`, `frontend-design`, `context-mode`, `claude-mem`) and the bundled npx helper tool (`get-shit-done-cc`). Exit-code 1 when anything is missing or outdated.
  - `sccs doctor install` — installs missing components after an explicit `questionary.confirm` per action (default: No). `--yes` skips prompts for CI use only.
  - `sccs doctor update` — refreshes installed plugins via `claude plugin update` and re-runs each npx tool to fetch the latest release.
- **Platform-aware Node.js install hints** in `sccs/doctor/defaults.py:NODE_INSTALL`:
  - macOS → `brew install node` (runnable)
  - Windows → `winget install OpenJS.NodeJS` (runnable)
  - Linux → NodeSource `setup_20.x` + `apt-get install` (print-only — SCCS never invokes `sudo`)
- **Hardcoded defaults with config override.** New `doctor:` block in `~/.config/sccs/config.yaml` lets users append `extra_plugins` / `extra_npx_tools` without losing the bundled defaults, or fully replace them with `plugins:` / `npx_tools:`. Legacy configs without a `doctor:` key keep working — `SccsConfig.doctor` defaults to a fully-populated `DoctorConfig`.
- New module `sccs/doctor/` (~700 LOC across `defaults.py`, `schema.py`, `runner.py`, `detectors.py`, `installer.py`, `reporter.py`).
- 40 new tests in `tests/test_doctor.py` covering schema validation, argument-injection guards, all four detectors, install/update plan construction, and the print-only sudo guarantee.

### Security
- `sccs/doctor/runner.py` mirrors the argument-injection guard from `sccs/git/operations.py`: every command head is validated against an allowlist regex, leading `-` is rejected (no option-injection), and the literal string `sudo` is rejected at the runner *and* schema layers (`NodeInstallSpec` validator). `subprocess.run` is always called with `shell=False`.
- The Linux Node-install spec uses `runnable=False` so the NodeSource recipe (which requires `sudo`) is rendered as a copy-paste block and *cannot* be auto-executed by accident.

## Version 2.20.3 (28.04.2026)

### Fixed
- **`platform_overrides` from bundled defaults are now auto-applied to user configs that pre-date v2.20.0.** Symptom: a Windows user upgrading from v2.19.x or earlier kept seeing `[missing: bc]` in the Claude Code statusline because `~/.claude/settings.json` still pointed at `statusline.sh`. Root cause: `sccs config upgrade` adopts new categories but does not patch new *fields* into existing user-config blocks, so a `claude_statusline` entry written by an older SCCS lacked `settings_ensure.platform_overrides`. The Windows-only override that should have rewritten `statusLine.command` to `pwsh -NoProfile -File ~/.claude/statusline.ps1` therefore never ran. The sync engine now resolves an *effective* `settings_ensure` per category at sync time: when the user has no block, the bundled default is used; when the user has a block but `platform_overrides` is empty or missing the current platform, the missing platform keys are filled in from the default. The user's `entries`, `target_file` and per-platform overrides they did define are never overwritten. Six new tests in `tests/test_settings.py::TestResolveEffectiveSettingsEnsure` cover the four merge scenarios plus the no-default and empty-default fallbacks.

### Added
- `sccs.config.defaults.get_default_settings_ensure(category_name)` — returns the bundled `settings_ensure` block for a default category, or `None`. Used by the sync engine for the merge above; available for downstream tooling.

## Version 2.20.2 (28.04.2026)

### Fixed
- **`sccs convert fish-to-pwsh` failed on Windows with `Source directory not found: C:\Users\<user>\.config\fish`.** The default `--src` path was hard-coded to `~/.config/fish`, which on Windows expands to a directory that doesn't exist (Fish is not installed there — that's the entire point of converting *to* PowerShell). On Windows the default now resolves to `<repo>/.config/fish`, i.e. the synced copy that `sccs sync --pull` brings in from macOS/Linux. macOS/Linux behaviour is unchanged. When the repo source is also missing, the error message now points the user at `sccs sync --pull` or passing `--src` explicitly. Two new tests in `tests/test_convert.py::TestFishToPwshCliDefaults` cover the Windows positive and negative path. Help text and the `convert` group docstring document the platform-dependent default.

## Version 2.20.1 (28.04.2026)

### Fixed
- **Misleading platform hint on Linux with Fish installed.** `sccs sync` printed `ℹ Plattform: linux — Fish nicht verfügbar — übersprungen: fish_config_macos, fish_functions_macos`, although Fish was installed — only the macOS-specific subcategories were filtered out by their `platforms: ["macos"]` rule. `sccs/cli.py::_print_platform_hint` now distinguishes the two skip reasons via `is_shell_available()`: when the shell is installed but the categories are platform-restricted, the hint reads `"<Shell>-Kategorien plattformspezifisch übersprungen: …"`; the legacy `"<Shell> nicht verfügbar — übersprungen: …"` wording (and the `sccs convert fish-to-pwsh` tip on Windows) only fires when the shell binary is actually missing. Three new tests in `tests/test_cli.py::TestPlatformHint` cover both wordings plus the silent no-skip case.

## Version 2.20.0 (28.04.2026)

### Added
- **Platform-aware `settings_ensure`**: `SettingsEnsure` (and the underlying YAML schema) gains a new `platform_overrides: dict[str, dict]` field. Values from the entry matching the current platform are deep-merged into the target file and — unlike normal `entries` — overwrite existing keys, because they express explicit per-OS choices (e.g. "on Windows the statusLine command must point to PowerShell, not bash"). Sibling keys not mentioned in the override are preserved through the deep-merge.
- **PowerShell statusline** (`statusline.ps1`): Cross-platform port of `statusline.sh` using `ConvertFrom-Json` and native PowerShell math. No external dependencies (no `jq`, no `bc`). Same on-screen layout as the bash version: model · progress bar · % · tokens · cache efficiency · cost · lines · git · directory.
- The `claude_statusline` default category now ships a Windows override so `~/.claude/settings.json` automatically points to `pwsh -NoProfile -File ~/.claude/statusline.ps1` on Windows machines while keeping `statusline.sh` on macOS/Linux.
- Five new tests in `tests/test_settings.py::TestPlatformOverrides` covering replace-on-match, ignore-on-mismatch, deep-merge of nested dicts, key-creation, and legacy behaviour without overrides.

### Changed
- `claude_statusline.include` adds `statusline.ps1` to the rotation alongside `statusline.sh`, `statusline.py` and `statusline.fish`.
- `SettingsEnsureResult` gains a `keys_overridden: list[str]` field so callers can distinguish added-because-missing from overwritten-by-platform.

## Version 2.19.1 (28.04.2026)

### Fixed
- **Windows: `sccs sync` aborted writing JSON files (e.g. `~/.claude/settings.json`)** with `WinError 183: Cannot create a file when that file already exists`. Root cause: `atomic_write()` and `safe_copy()` used `os.rename()` / `Path.rename()` to swap the staged temp file into place, which is non-atomic on Windows when the target already exists. Both helpers now use `os.replace()`, which atomically overwrites on POSIX *and* Windows. Affects every category whose sync touches an existing file on Windows; the `claude_statusline` settings_ensure step is the most visible path.
- New `tests/test_paths_atomic.py` (12 tests) including a static guard that fails the suite if `os.rename(` is reintroduced into `sccs/utils/paths.py`.

### Security
- The Fish→PowerShell converter now skips files matching `*secret*`, `*secrets*`, `*token*`, `*credential*`, `*password*` and the explicit `99-secrets.fish` filename so credential material can never leak from a private Fish config into a generated `.ps1` artefact. Two regression tests in `tests/test_convert.py` (`test_skips_secret_files`, plus updated skip count) pin this behaviour.

### Changed
- `sccs/convert/rules.py`: `set -gx VAR "$OTHER_VAR"` now correctly rewrites `$OTHER_VAR` (a Fish env-var reference) to `$env:OTHER_VAR`, while preserving PowerShell built-ins (`$HOME`, `$PWD`, `$PROFILE`, `$PSScriptRoot`, `$args`, `$_`). Previously the rewrite was hard-coded to `$HOME` only, leaving every other `$VAR` reference broken on Windows.

## Version 2.19.0 (28.04.2026)

### Added
- **Windows / PowerShell support.** SCCS now runs cleanly on Windows 11 with PowerShell 7+. Fish-only categories (`fish_config`, `fish_functions`) are filtered out automatically via the existing `platforms` mechanism so no `~/.config/fish/` is needed.
- **New default category `powershell_profile`** (disabled by default, `platforms: ["windows"]`). Local path defaults to `~/Documents/PowerShell`; OneDrive users can override `local_path` in their config when Documents lives under OneDrive.
- **New CLI command `sccs convert fish-to-pwsh`.** Generates a modular PowerShell profile (`Microsoft.PowerShell_profile.ps1` + `conf.d/*.ps1` + `functions/*.ps1`) from `~/.config/fish/`. Aliases (`alias name=value`), env vars (`set -gx`), `fish_add_path` and abbreviations are translated; Fish functions are emitted as commented stubs because their syntax (`begin/end`, `string match`, `$argv[N]`) is not auto-portable. `--src`, `--dst`, `--force`, `--dry-run` supported.
- **Startup platform hint.** When categories are skipped on the current OS due to `platforms` filtering, `sccs` prints a one-line dimmed hint (e.g. `ℹ Plattform: windows — Fish nicht verfügbar — übersprungen: fish_config, fish_functions`). Suppressed in non-TTY contexts.
- New module `sccs/convert/` with `FishToPwshConverter`, regex-based `rules.py`, and `templates.py` for the generated profile entry point and README.
- `sccs.utils.platform` gains `is_shell_available()`, `detect_shell_for_category()`, `get_unavailable_shells_for_enabled_categories()`, and `get_platform_skipped_categories()`.

### Changed
- `fish_config` and `fish_functions` defaults now declare `platforms: ["macos", "linux"]` so they are skipped on Windows. No effect on existing macOS/Linux setups.

### Tests
- 17 new conversion tests (`tests/test_convert.py`) covering rule pipeline, directory walking, dry-run behaviour, backup-on-overwrite, and stub emission.
- 13 new platform tests (`tests/test_platform_utils.py`) covering shell detection and platform-skipped category reporting.

## Version 2.18.0 (24.04.2026)

### Added
- **Interactive divergence resolution** when `sccs sync` detects the local branch has diverged from its remote (previously the sync aborted with "Please merge or rebase manually before syncing"). The user is now offered a questionary prompt with four strategies:
  - **Rebase** — `pull --rebase`, replays local commits on top of remote (linear history).
  - **Merge** — `pull`, creates a merge commit.
  - **Force-push** — `push --force-with-lease` (lease refuses the overwrite if remote advanced since last fetch).
  - **Abort** — leave the repository unchanged.
  The prompt auto-answers *Abort* in non-interactive contexts (CI, pipes), preserving the previous fail-loud behaviour.
- New `force_push()` operation in `sccs/git/operations.py` using `--force-with-lease`, exported via `sccs.git.force_push`.
- New module `sccs/git/resolve.py` with `DivergenceStrategy`, `prompt_divergence_strategy()`, `apply_divergence_strategy()` — small, testable, UI-free core around the interactive prompt.

### Security
- **MEDIUM**: Block git argument injection through manipulated `RepositoryConfig.remote`. A hostile `config.yaml` with `remote: "--upload-pack=/tmp/evil"` could previously inject a git option into `git push` and trigger arbitrary command execution (CVE-2017-1000117 class). `RepositoryConfig.remote` now rejects values that don't match a strict pattern (`^[A-Za-z0-9_][A-Za-z0-9_.\-]*$`). The subprocess layer (`sccs/git/operations.py`) validates `remote`, `branch`, and clone URLs as defence-in-depth, and `clone_repo` now inserts `--` before the URL so git stops parsing options there.
- **MEDIUM**: Refuse to follow symlinks in `safe_copy()` and `create_backup()` (`sccs/utils/paths.py`). A crafted symlink in a tracked sync directory (e.g. `~/.claude/skills/evil/SKILL.md -> /etc/passwd`) would otherwise leak target file contents into the git repository on the next sync. Directory copies now pass `symlinks=True` so nested links are preserved as links rather than dereferenced.

### Tests
- 41 new tests total: `tests/test_paths_security.py` (9), `TestArgumentInjectionHardening` (6), `TestRemoteValidation` (12), `TestForcePush` (5), `tests/test_git_resolve.py` (12). Total: **412** (previous baseline 371).

## Version 2.17.1 (22.04.2026)

### Security
- **CRITICAL**: Fix arbitrary file write through manipulated ZIP manifests (`sccs/transfer/importer.py`). A hostile archive could previously set `local_path` or `item.name` to attacker-controlled values (e.g. `~/.ssh/authorized_keys` or `../../.bashrc`) and have `sccs import` write to those paths. The importer now (1) requires the manifest category to exist in the local config, (2) rejects any `local_path` that does not match the local category, (3) refuses item names containing traversal components or absolute paths, and (4) validates the resolved target stays underneath the category's base directory.
- **HIGH**: Reject symlink entries in ZIP archives before extraction (CWE-61). Previously the Zip-Slip check validated only member names, not Unix symlink entries; a crafted symlink could point outside the staging directory so that the subsequent copy step wrote files into `/tmp` or any other path.
- Add `shutil.copytree(..., symlinks=False)` as defense-in-depth on directory imports.
- 18 new regression tests in `tests/test_importer_security.py`.

### Changed
- `Importer` now takes an optional `SccsConfig` in its constructor; CLI `sccs import` always passes the active config. Calls without a config keep working in legacy mode for tests and scripted use, but the CLI refuses to run without a local config so the allowlist check is always active.
- `save_config()` and `adopt_new_categories()` wrap directory/serialization/write errors in a new `ConfigWriteError` (subclass of `OSError`) instead of propagating raw IO exceptions. Failures are also logged.
- Coverage threshold raised from 60% to the current baseline of 66% to lock in the new security tests. Target remains 80% — see TODO in `pyproject.toml`.
- Added `sccs.utils.logging` with a thin `logging.getLogger("sccs")` wrapper and `configure_logging()`; the CLI entry point wires it up using `config.output.log_file` and the `--verbose` flag.

### Added
- 18 new tests covering the security fixes (389 total).

## Version 2.17.0 (29.03.2026)

### Added
- Integrations sub-package (`sccs/integrations/`) for Antigravity IDE and Claude Desktop
- `sccs integrations status` — detect Antigravity and Claude Desktop installations
- `sccs integrations migrate-skills` — copy Claude Code skills to Antigravity prompts (`SKILL.md` → `<name>.md`)
- `sccs integrations trust-repo` — register SCCS repo in Claude Desktop trusted folders
- Inline integration status in `sccs status` output
- 28 new tests for integration detectors, migration, and trust registration (353 total)

### Changed
- Version bump 2.16.0 → 2.17.0

## Version 2.16.0 (26.03.2026)

### Added
- Selective ZIP export/import for deploying configurations to customer systems
- `sccs export` command with interactive questionary checkbox selection
- `sccs import` command with dry-run preview, overwrite control, and automatic backup
- New `sccs/transfer/` module: manifest, exporter, importer, and UI helpers
- `questionary` dependency for interactive checkbox prompts with [✔]/[ ] indicators
- Path traversal protection (CWE-22) on ZIP import
- Platform hints in export manifest for cross-platform awareness
- Two-stage hierarchical export/import selection (areas → items)
- 37 new tests for transfer functionality (325 total)

### Changed
- Export/import uses two-stage navigation: first choose areas (Claude Code, Fish Shell, Shell Tools), then pick individual items — replaces flat 171-item list
- Category grouping with platform-aware separation (Fish Shell vs Fish Shell macOS)
- Small groups (≤5 items) auto-included without extra prompt
- CI migration tests now platform-aware (macOS-only categories excluded on Linux)

### Fixed
- `test_migration.py` assertions failed on Linux CI due to macOS-only categories in expected counts

## Version 2.14.0 (23.03.2026)

### Added
- User-specific framework category `claude_user_framework` (SOUL.md, PRINCIPLES.md, PERSONAS.md, RULES.md) — disabled by default, opt-in for personal config sync across machines
- Platform filtering in migration prompts — macOS-only categories no longer offered on Linux/Windows

### Changed
- `claude_framework` category reduced to shared core files (CLAUDE.md, COMMANDS.md, FLAGS.md, MCP.md, MODES.md, ORCHESTRATOR.md)
- Migration "Add all" prompt clarified: `(No = decide individually)` to avoid confusion

### Fixed
- `detect_new_categories()` mypy `no-any-return` error resolved with explicit type annotation

## Version 2.13.0 (22.03.2026)

### Added
- Config Migration Assistant: detects new default categories and offers interactive adoption during `sccs sync`
- `sccs config upgrade` command to review and adopt new categories (re-offers previously declined)
- `--no-migrate` flag on `sccs sync` to skip migration check
- Migration state tracking (`~/.config/sccs/.migration_state.yaml`) to remember declined categories
- CI/non-TTY support: prints notice instead of interactive prompt
- `load_raw_user_data()` and `adopt_new_categories()` in config loader

### Changed
- Version bump to 2.13.0
- SCCS Skill updated with migration module and config upgrade command

## Version 2.12.0 (22.03.2026)

### Changed
- Version bump to v2.12.0

## Version 2.11.0 (22.03.2026)

### Added
- Claude Agents sync category (`claude_agents`) for sub-agent definitions with model routing
- Claude Settings sync category (`claude_settings`, disabled by default) for permissions and hooks config
- Auto-generate hub README when `--commit` is used (no extra `--docs` flag needed)
- `--no-docs` flag to suppress automatic README generation during commit

### Changed
- SCCS Skill updated with new categories and docs commands documentation
- Version bump to 2.11.0

## Version 2.10.0 (14.03.2026)

### Added
- Claude Memory sync category (`claude_memories`, disabled by default)

### Changed
- README update with v2.10.0 features, --force newer and claude_memories docs

### Fixed
- SIM115 lint error in test_diff.py

## Version 2.9.0

### Changed
- Smart conflict resolution with --force newer option
- Project health fixes

## Version 2.8.0

### Added
- Hub README generator (`sccs docs generate`)

## Version 2.7.0

### Changed
- Memory Bridge documentation

## Version 2.6.0

### Changed
- CLI docs, bilingual README, test coverage boost and dev tooling

## Version 2.5.0

### Changed
- Project health audit: ruff, security fixes, CI/CD and dependency bounds

## Version 2.4.0

### Added
- Settings.json ensure-logic for statusline category

## Version 2.3.0

### Fixed
- Recursive file scanning for subdirectory patterns

## Version 2.2.0

### Added
- Git pull-check before sync
- Statusline category

## Version 2.1.1

### Changed
- Add README.md to fish_config sync
