# Codebase Concerns

**Analysis Date:** 2026-05-11

---

## Tech Debt

**No TODO/FIXME/HACK/XXX markers in source:**
- Grep over `sccs/` finds zero actionable debt markers. The only hit is a category
  description string (`"Claude Code persistent TODO lists"`) in
  `sccs/config/defaults.py:136` — not a code marker.

**`config: DoctorConfig` parameter unused in plan builders:**
- Files: `sccs/doctor/installer.py:748`, `sccs/doctor/installer.py:788`
- Issue: Both `build_install_plan` and `build_update_plan` accept `config` as
  their first positional argument but immediately annotate it `# noqa: ARG001`.
  The parameter exists for API symmetry but carries zero runtime effect — any
  caller passing per-user doctor config overrides (e.g. `min_node_major`) to
  these functions today gets silently ignored.
- Impact: Future callers expecting config-driven plan customisation will be
  surprised; the `min_node_major` override in `~/.config/sccs/config.yaml` is
  only consulted upstream in the CLI, not inside the planner.
- Fix: Either remove the parameter and fix call sites, or thread `config` into
  `_node_action` so the override actually takes effect.

**`_validate_safe_name` pattern not used in doctor layer:**
- File: `sccs/doctor/runner.py:21,34-42`
- Issue: `_validate_head` guards `argv[0]` but there is no equivalent guard on
  user-supplied strings that become later argv elements (e.g. plugin names,
  marketplace names, scope values resolved from `claude plugin list` output).
  Plugin names flow from `PluginSpec.name` (user config) into
  `["claude", "plugin", "install", spec.install_target]` without a character-
  class check. Marketplace names flow similarly. The existing `_SAFE_HEAD_PATTERN`
  allowlist (`^[A-Za-z0-9_][A-Za-z0-9_./@\-]*$`) would be appropriate here too.
- Impact: A malicious or malformed `config.yaml` entry with a name containing
  shell-relevant characters (e.g. `;rm -rf`) would be passed as an argv element.
  Because `shell=False` is enforced, actual code execution via shell metacharacters
  is blocked, but unexpected subprocess errors and confusing output are possible.
- Fix: Apply `_validate_head` (or a sibling `_validate_arg`) to
  `spec.name`, `spec.marketplace`, and scope strings before appending to argv
  lists in `_plugin_install_actions` / `_plugin_update_actions`.

---

## Known Bugs / Recent Incidents

**Debian 13 multi-user terminal server — npm root owned by multiple users (v2.28.1, 2026-05-06):**
- Symptoms: `npm install -g @playwright/cli@latest` died with EACCES on
  `/usr/local/lib/node_modules/` (root-owned with packages from several users);
  `claude plugin install <name>@claude-plugins-official` died with "Plugin not
  found in marketplace" because the marketplace was never registered on that box.
- Fixed in: v2.28.0 (cascade-resilience, auto-marketplace-update, PATH detector)
  and v2.28.1 (`ClaudeMarketplaceDetector`, multi-user-aware Option B suppression).
- Residual risk: The `is_multi_user` heuristic in `PermissionStatus`
  (`sccs/doctor/detectors.py:213-222`) triggers only when `≥2 distinct non-root
  foreign uids` are found within `_MAX_PATHS_SCANNED = 500` entries. A very large
  `~/.npm` cache on a 3-user box could exhaust the scan cap before the second
  foreign uid is seen, causing Option B (`sudo chown -R`) to be shown when it
  should be suppressed. Low probability but worth noting.

**Homebrew Node major-version upgrade breaking Cellar paths in user settings.json (identified 2026-05-11):**
- Symptoms: When Homebrew upgrades Node (e.g. 24 → 26), the versioned Cellar
  path embedded in `~/.claude/settings.json`'s `statusLine.command` (e.g.
  `/opt/homebrew/Cellar/node/24.x.x/bin/node ...`) becomes stale and Claude's
  statusline silently stops working.
- Root cause: `settings_ensure` in `sccs/config/defaults.py:186-207` writes
  `~/.claude/statusline.sh` as the command — this is fine — but `get-shit-done-cc`
  (the npx patcher) may embed absolute Cellar paths into `statusline.sh` or
  `settings.json` depending on the version it finds at run time. No doctor check
  exists that re-validates the `statusLine.command` value after a Node upgrade.
- Files: `sccs/config/defaults.py:186-207`, `sccs/doctor/defaults.py` (no
  statusLine detector present)
- Gap: `sccs doctor check` has no `StatuslineDetector` — it does not verify that
  `~/.claude/settings.json` actually contains a valid `statusLine` key, nor that
  the referenced script exists and is executable.
- Fix approach: Add a lightweight `StatuslineDetector` to
  `sccs/doctor/detectors.py` that reads `~/.claude/settings.json`, checks for
  the `statusLine.command` key, and verifies the referenced file exists. Wire it
  into `sccs doctor check` output and add a repair action to `build_install_plan`
  that re-runs the `get-shit-done-cc` invocation when the check fails.

---

## Security Considerations

**`_validate_head` in `sccs/doctor/runner.py` — correct but incomplete:**
- File: `sccs/doctor/runner.py:34-42`
- The guard rejects `argv[0]` values starting with `-` or containing characters
  outside `[A-Za-z0-9_./@\-]`, and explicitly blocks `sudo`. This is the right
  design. However it only validates position 0; see "Tech Debt → `_validate_safe_name`
  pattern not used in doctor layer" above for the gap in later argv positions.

**`platform_overrides` in `settings_ensure` always overwrites existing values:**
- File: `sccs/sync/settings.py:96-101`, `sccs/config/defaults.py:197-206`
- The comment at `settings.py:96` correctly documents this: "Platform overrides
  ALWAYS apply for the current platform — they're an explicit per-OS choice, so
  they overwrite even if the key already exists."
- Risk: A user who has manually customised `statusLine` in `~/.claude/settings.json`
  on Windows will have their value silently replaced on every `sccs sync` run
  that touches the `claude_statusline` category. The backup (`backup_before_modify:
  true`) mitigates data loss but the overwrite is silent — no diff is shown.
- Fix approach: Surface `keys_overridden` in the sync console output so the user
  knows their manual value was replaced. Currently `keys_overridden` is populated
  (`sccs/sync/settings.py:19`) but not printed by the engine or reporter.

**`claude_memories` category disabled by default — correct, but comment is the only guard:**
- File: `sccs/config/defaults.py:144-158`
- The comment "may contain sensitive info" is the only protection. There is no
  content-scanning or redaction; if a user enables this category, all memory
  files (including any that capture API keys or passwords mentioned in conversation)
  are synced to the git repository verbatim.
- Recommendation: Document explicitly in `sccs config show` output that
  `claude_memories` may contain sensitive data, and consider a pre-sync warning
  when the category is enabled.

**`atomic_write` in `sccs/utils/paths.py` — not audited here:**
- The settings mutation path (`sccs/sync/settings.py:131`) relies on `atomic_write`
  from `sccs/utils/paths.py`. Correctness of the atomic write (temp file +
  rename) is assumed but not verified in this audit. A non-atomic write failure
  mid-sync could corrupt `~/.claude/settings.json`. The `backup_before_modify`
  flag is the safety net.

---

## Performance Bottlenecks

**`PermissionDetector._check` recursive scan capped at 500 entries:**
- File: `sccs/doctor/detectors.py:34-36`, `sccs/doctor/detectors.py:699-724`
- Problem: `path.rglob("*")` on `~/.npm` with thousands of cached packages can
  be slow even with the 500-entry cap. On a cold npm cache the first 500 entries
  may all be from a single large package and give a misleading "no foreign
  ownership" result.
- Impact: `sccs doctor check` may feel slow on developer machines with large caches.
- Improvement path: Replace `rglob("*")` with `os.scandir` for the top two
  directory levels only (root + one level down), which covers the typical
  foreign-ownership pattern without descending into deep package trees.

**`_run(["npm", "root", "-g"])` called twice per doctor pass:**
- Files: `sccs/doctor/detectors.py:498-513` (`_resolve_npm_root_global`) and
  `sccs/doctor/installer.py:569` (`_sync_bundled_skill`)
- Both functions invoke `npm root -g` independently with no shared cache. On
  slow machines or under network load (nvm shims), this adds 2× npm startup cost
  per doctor pass.
- Improvement path: Resolve `npm root -g` once in the doctor CLI entry point and
  inject the result.

---

## Fragile Areas

**`ClaudeMarketplaceDetector._parse_registered` regex — format-dependent:**
- File: `sccs/doctor/detectors.py:416-447`
- Why fragile: The parser relies on `claude plugin marketplace list` emitting
  `❯ <name>` header lines. The Claude CLI has changed output format before
  (the plugin list format changed between 0.x and 1.x). A format change would
  cause all marketplaces to appear unregistered, triggering spurious
  `blocks_downstream` manual blocks that prevent every plugin install.
- The secondary fallback (`Name: <name>` lines, lines 443-446) partially
  mitigates this but does not cover all possible future formats.
- Safe modification: Add a unit test fixture for the current format and keep the
  fallback parser updated alongside any Claude CLI version bumps.

**`ClaudePluginDetector._detect_plugin` regex — partial-name false-negatives:**
- File: `sccs/doctor/detectors.py:325-329`
- The negative lookbehind `(?<![\w\-])` guards against `superpowers` matching
  `superpowers-developing-for-claude-code`, but the character class `[\w\-]`
  uses `\w` which is locale-dependent in Python's `re` module (matches
  `[a-zA-Z0-9_]` in ASCII mode). A plugin name containing non-ASCII characters
  could produce unexpected match results.
- Impact: Low — current plugin names are ASCII only. Risk increases if the
  marketplace ever ships plugins with Unicode names.

**`settings_ensure` `platform_overrides` key is injected from bundled defaults for old user configs:**
- File: `sccs/sync/category.py:27-43`, `sccs/config/defaults.py:417-435`
- `_resolve_effective_settings_ensure` silently merges the bundled
  `platform_overrides` into any user config that predates v2.20.0 (when the
  field was introduced). This is intentional but means user configs from before
  that version are quietly upgraded on every sync without explicit acknowledgement.
- Safe modification: The logic is correct as implemented. Document this merge
  behaviour in the `sccs config upgrade` output so users understand why their
  settings are being written.

**Linux `NodeInstallSpec` hardcodes NodeSource 20.x:**
- File: `sccs/doctor/defaults.py:171-175`
- `manual_block` contains `setup_20.x` literally. When `MIN_NODE_MAJOR` is
  bumped (it is currently 20, line 17), the manual block text must be updated
  separately — there is no derivation linking the two.
- Impact: A future `MIN_NODE_MAJOR = 22` bump without updating the manual block
  text would give users a working-but-outdated install command.
- Fix approach: Generate the `manual_block` string dynamically from
  `MIN_NODE_MAJOR` rather than hardcoding `20`.

**Windows `powershell_profile` local_path assumes `~/Documents/PowerShell`:**
- File: `sccs/config/defaults.py:288-308`
- The comment at line 286 explicitly documents the OneDrive edge case:
  `~/OneDrive/Documents/PowerShell` is the real path on machines with OneDrive
  folder redirection enabled. This is a common Windows default. The only
  mitigation is a comment telling users to override `local_path`.
- Impact: Silent sync failure (no files found at `~/Documents/PowerShell`) or
  incorrect files synced on OneDrive-enabled machines.
- Fix approach: At category scan time, check both
  `~/Documents/PowerShell` and `~/OneDrive/Documents/PowerShell`; use whichever
  exists, or surface a warning when neither is found.

---

## Scaling Limits

**`_MAX_PATHS_SCANNED = 500` in `PermissionDetector`:**
- File: `sccs/doctor/detectors.py:34`
- Current capacity: scans up to 500 entries per checked path.
- Limit: Misses foreign-owned files deeper than the first 500 entries on very
  large caches. Not a scaling problem in the traditional sense, but a correctness
  limit at scale.

---

## Dependencies at Risk

**`questionary` used for `--yes` confirm prompts in `execute_plan`:**
- File: `sccs/doctor/installer.py:828-835`
- Risk: `questionary` is a third-party TUI library. If stdin is not a TTY
  (e.g. CI pipe, `echo y | sccs doctor install`), `questionary.confirm(...).ask()`
  returns `None`, which `bool(None)` coerces to `False` — silently skipping all
  actions. The `KeyboardInterrupt` / `EOFError` catch handles hard breaks but
  not the `None` case explicitly.
- Impact: Running `sccs doctor install` in CI without `--yes` produces zero
  executed actions with no error, which looks like success.
- Migration plan: Add an explicit `None` check after `.ask()` and emit a
  warning when stdin appears non-interactive; or replace with a simpler
  `input()` fallback guarded by `sys.stdin.isatty()`.

---

## Missing Critical Features

**No `StatuslineDetector` in `sccs doctor`:**
- Problem: `sccs doctor check` does not verify that `~/.claude/settings.json`
  contains a valid `statusLine` entry or that the referenced script exists. The
  Homebrew Node upgrade scenario (identified 2026-05-11) can silently break the
  statusline with no doctor signal.
- Blocks: Users on macOS who upgrade Node via Homebrew have no automated way to
  detect or repair a broken statusline short of re-running `sccs doctor install`.
- Related files: `sccs/config/defaults.py:186-207`, `sccs/doctor/defaults.py`
  (no statusLine spec), `sccs/doctor/detectors.py` (no StatuslineDetector class)

**`sccs doctor` does not check `get-shit-done-cc` output validity:**
- Problem: `get-shit-done-cc` is detected via state file only (`detect_via_state:
  True`, `sccs/doctor/defaults.py:45`). There is no check that the tool's output
  (the statusline patch it applies to `settings.json`) is still present and
  correct after a Node upgrade or a manual `settings.json` edit.
- Blocks: Silent regression after any external mutation of `~/.claude/settings.json`.

---

## Test Coverage Gaps

**`ClaudeMarketplaceDetector` format-change regression:**
- What's not tested: No fixture covers a changed `claude plugin marketplace list`
  output format (e.g. a future CLI that drops the `❯` prefix). The current tests
  validate the happy path but not the fallback parser independently.
- Files: `tests/` (no `test_doctor_marketplace.py` visible from grep)
- Risk: A Claude CLI update silently breaks marketplace detection.
- Priority: Medium

**`execute_plan` non-TTY / `questionary` returns `None`:**
- What's not tested: The `bool(answer)` coercion at
  `sccs/doctor/installer.py:835` when `answer is None`.
- Risk: CI invocations appear to succeed while executing nothing.
- Priority: High

**`_sync_bundled_skill` on Windows:**
- What's not tested: `shutil.copytree` behaviour when `target` already exists
  on Windows (case-insensitive filesystem, locked files from a running process).
- Files: `sccs/doctor/installer.py:560-582`
- Risk: Silent overwrite failure on Windows leaving a partial skill directory.
- Priority: Low (Windows support is secondary)

**`settings_ensure` `platform_overrides` overwrite path:**
- What's not tested: A settings.json that already contains `statusLine` on
  Windows is overwritten by the platform override. `keys_overridden` is populated
  but not asserted in tests.
- Files: `sccs/sync/settings.py:96-101`
- Risk: Silent data loss of user-customised statusLine on Windows.
- Priority: Medium

---

*Concerns audit: 2026-05-11*
