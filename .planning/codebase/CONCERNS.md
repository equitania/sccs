# Codebase Concerns

**Analysis Date:** 2026-05-26

---

## Resolution History (v2.29.1 – v2.32.1)

The following concerns flagged in the 2026-05-11 audit are now **RESOLVED**:

| Concern | Resolution | Version |
|---------|------------|---------|
| No `StatuslineDetector` in doctor | `StatusLineDetector` added to `sccs/doctor/detectors.py`; stale Cellar auto-fix wired into install/update/optimize | v2.29.0 |
| Config loader dropping user `doctor:` overrides | `_merge_with_defaults` in `sccs/config/loader.py:289-294` now passes `doctor` block through verbatim | v2.29.1 |
| No `get-shit-done-cc` output validity check | `StatusLineDetector` validates the `statusLine.command` key after every GSD run; `smart_required` logic ensures it only fires when the statusline category is enabled | v2.29.0 |
| Foreign plugin / MCP drift invisible | `ForeignPluginDetector`, `MCPServerDetector`, `get_foreign_plugins`, `get_foreign_servers` added; surfaced in `sccs doctor optimize` | v2.30.0 |
| `settings.json` hook re-injection by upstream tools | `SettingsHookDetector` + `_settings_hook_cleanup_actions`; runs last in every doctor pass | v2.31.0 |
| No protection for GSD hooks against `disallowed_hooks` stripping | `protected_hooks` guard added to `DoctorConfig`; `gsd-` in `DEFAULT_PROTECTED_HOOKS`; protection wins over removal | v2.32.0 |
| Linux system-npm EACCES on `<prefix>/bin` | `npm-bin-global` `PermissionCheckSpec` added; gates the npx install on bin-dir writability, not just lib-dir | v2.32.1 |
| Misleading `chown` advice for system npm prefixes | `_npm_global_fix_block` suppresses Option B (sudo chown) for any npm prefix outside `$HOME` | v2.32.1 |
| `execute_plan` non-TTY CI invocations failing silently in some statusline CI path | Linux CI idempotency test patched to tolerate platform-dependent `missing_binary` state | v2.32.1 |
| `_validate_safe_name` pattern not applied to plugin argv elements | `PluginSpec._validate_name`, `._validate_marketplace`, `._validate_source` validators added in `sccs/doctor/schema.py:48-68` | v2.29+ |

---

## Tech Debt (OPEN)

**`config: DoctorConfig` parameter silently unused in `build_install_plan` / `build_update_plan`:**
- Files: `sccs/doctor/installer.py:1116`, `sccs/doctor/installer.py:1167`
- Issue: Both plan-builder functions accept `config` as first argument but annotate it `# noqa: ARG001`. The parameter exists for API symmetry with `build_optimize_plan` but has zero runtime effect. Callers passing per-user overrides (e.g. `min_node_major`) into these functions get silently ignored.
- Impact: Future callers expecting config-driven plan customisation will be surprised. The `min_node_major` override in `~/.config/sccs/config.yaml` is only consumed upstream in the CLI, not inside the planner.
- Fix: Either remove the parameter and update call sites, or thread `config.min_node_major` into `_node_action`.

**`_collect_doctor_statuses` function has no type annotations:**
- File: `sccs/cli.py:1511`
- Issue: `doctor_cfg` and `state_manager` parameters are untyped (`Any`). The return type is `dict` (not typed). `mypy` cannot catch callers passing the wrong config type or accessing missing keys.
- Impact: Low today; becomes a maintenance trap as the dict grows more keys.
- Fix: Annotate with `DoctorConfig` and `DoctorStateManager | None`; return a `TypedDict`.

**`NodeSource 20.x` hardcoded in Linux install hint:**
- File: `sccs/doctor/defaults.py:220`
- Issue: `manual_block` contains the literal string `setup_20.x`. `MIN_NODE_MAJOR = 20` is defined three lines above (line 19) but the manual block is not derived from it.
- Impact: A future `MIN_NODE_MAJOR = 22` bump without updating the manual text gives users a working-but-outdated install command.
- Fix: Build the `manual_block` string dynamically: `f"curl -fsSL https://deb.nodesource.com/setup_{MIN_NODE_MAJOR}.x | sudo -E bash -\nsudo apt-get install -y nodejs"`.

**`~/gitbase/sccs-sync` hardcoded as default repository path:**
- Files: `sccs/config/defaults.py:10`, `sccs/cli.py:572`, `sccs/cli.py:581`, `sccs/config/defaults.py:460`
- Issue: The default repo path assumes the Equitania/author development tree (`~/gitbase/sccs-sync`). First-run experience for other users requires an immediate override.
- Impact: Cosmetic for existing users; confusing for new installs. The `config init` prompt (line 572) uses this as the default suggestion.
- Fix: Low priority — the `config init` flow prompts the user and replaces the string. Document prominently in README that the path must be changed on first init.

---

## Known Bugs / Residual Risks (OPEN)

**`is_multi_user` heuristic may miss the second foreign uid on large caches:**
- File: `sccs/doctor/detectors.py:234`, `sccs/doctor/detectors.py:1083`
- Symptoms: On a ≥3-user Debian box with a large `~/.npm` cache (>500 entries from a single large package), the 500-entry scan cap (`_MAX_PATHS_SCANNED = 500`) may exhaust before encountering the second foreign uid. This causes `is_multi_user` to return `False`, and Option B (`sudo chown -R`) is shown in the manual block when it should be suppressed.
- Trigger: Requires `≥2 non-root foreign uids` AND a very large npm cache where both uids' entries are spread beyond the first 500 paths.
- Files: `sccs/doctor/detectors.py:41`, `sccs/doctor/detectors.py:1060-1083`
- Workaround: None automatic; user must manually choose the user-local prefix option.

**`_sync_bundled_skill` calls `npm root -g` at execute-time, separate from `PermissionDetector`:**
- Files: `sccs/doctor/installer.py:727`, `sccs/doctor/detectors.py:574`
- Issue: `npm root -g` is called once by `_resolve_npm_root_global` during detection, and again inside `_sync_bundled_skill` at plan execution. On machines where `npm` is slow (nvm shims, NFS mounts) this adds measurable latency.
- Impact: Performance — two `npm` subprocess calls per doctor pass when a bundled skill needs copying. Not a correctness issue.
- Fix: Resolve once in the CLI entry point and inject the resolved path into the plan or directly into `BundledSkillSpec` at detection time.

---

## Security Considerations (OPEN)

**`settings_ensure` `platform_overrides` silently overwrites user-customised keys:**
- File: `sccs/sync/settings.py:96-101`
- Risk: A user who has manually customised `statusLine` in `~/.claude/settings.json` on Windows will have their value replaced on every `sccs sync` run that touches the `claude_statusline` category. The backup (`backup_before_modify: true`) prevents data loss but the overwrite produces no diff in the terminal.
- Current mitigation: `keys_overridden` is tracked in `SettingsEnsureResult` (line 21) but is never consumed by the sync engine or printed to the console. The backup exists on disk.
- Recommendation: Surface `keys_overridden` in sync console output. Currently `keys_overridden` is populated in `sccs/sync/settings.py` but not passed up through `sccs/sync/category.py` or `sccs/sync/engine.py` to the Rich output.

**`claude_memories` category disabled by default — no content warning at enable time:**
- File: `sccs/config/defaults.py:144-158`
- Risk: If a user enables this category, all Claude memory files (including those that may capture API keys or passwords mentioned in conversation) are synced to the git repository verbatim. The comment `"May contain sensitive conversation context"` is the only protection.
- Current mitigation: Disabled by default. Category is hidden from `sccs categories` by default.
- Recommendation: Add a prominent warning when a user enables `claude_memories` via `sccs categories enable claude_memories` or `sccs config upgrade`.

**`edit_in_editor` and `config_edit` accept `$EDITOR` without path validation:**
- Files: `sccs/output/merge.py:221`, `sccs/cli.py:608`
- Risk: The editor binary is taken directly from `$EDITOR` / `$VISUAL` and passed as `argv[0]` to `subprocess.run`. Unlike `sccs/doctor/runner.py`, neither call site validates the editor name against `_SAFE_HEAD_PATTERN`. A malicious `$EDITOR` value such as `rm -rf` or a path to a rogue binary would be executed.
- Threat model: User-controlled environment variable — low practical risk on a personal machine, but the inconsistency with the explicit safety contract in `runner.py` is noteworthy.
- Fix: Apply a `shutil.which` existence check (already done in `merge.py:231`) and optionally reject values starting with `-` or containing shell metacharacters.

---

## Performance Bottlenecks (OPEN)

**`PermissionDetector._check` uses `rglob("*")` capped at 500 entries:**
- File: `sccs/doctor/detectors.py:1081`
- Problem: `path.rglob("*")` on `~/.npm` with thousands of cached packages iterates the full subtree until the 500-entry cap is hit. On a cold npm cache the first 500 entries may all be from a single large package.
- Impact: `sccs doctor check` can feel slow on developer machines with large caches; the multi-user heuristic may give misleading results (see Known Bugs above).
- Improvement path: Replace `rglob("*")` with `os.scandir` for the top two directory levels only (root + one level down), which covers the typical foreign-ownership pattern without descending into deep package trees.

---

## Fragile Areas (OPEN)

**`ClaudeMarketplaceDetector._parse_registered` regex — format-dependent:**
- File: `sccs/doctor/detectors.py:492-525`
- Why fragile: The parser relies on `claude plugin marketplace list` emitting `❯ <name>` header lines. The Claude CLI has changed output format before. A format change would cause all marketplaces to appear unregistered, triggering spurious `blocks_downstream` manual blocks that prevent every plugin install.
- The secondary fallback (`Name: <name>` lines) partially mitigates this but does not cover all possible future formats.
- Safe modification: Add a unit test fixture for the current format and keep the fallback parser updated alongside any Claude CLI version bumps.

**`ClaudePluginDetector._detect_plugin` regex — locale-sensitive `\w`:**
- File: `sccs/doctor/detectors.py:325-329`
- The negative lookbehind `(?<![\w\-])` uses `\w` which is locale-dependent in Python's `re` module. A plugin name containing non-ASCII characters could produce unexpected match results.
- Impact: Low — current plugin names are ASCII only. Risk increases if the marketplace ever ships plugins with Unicode names.

**`StatusLineDetector` auto-fix covers only Apple Silicon (`/opt/homebrew`) Cellar paths:**
- File: `sccs/doctor/detectors.py:683-685`
- The stale-Cellar regex (`_STATUS_LINE_CELLAR_RE`) matches only `/opt/homebrew/Cellar/...`. Intel Homebrew (`/usr/local/Cellar/...`) and Linuxbrew are explicitly deferred per the inline comment: "Homebrew (`/usr/local/Cellar/...`) and Linuxbrew are deferred to a future phase per CONTEXT.md D2."
- Impact: Users on Intel Macs or Linux running Linuxbrew will see `stale_cellar` flagged as `missing_binary` (a less informative state), and the auto-rewrite action will not fire for their path shape.
- Fix: Extend `_STATUS_LINE_CELLAR_RE` to cover `/usr/local/Cellar/...` (Intel Homebrew) and a similar pattern for Linuxbrew.

**`settings_ensure` silently upgrades old user configs with bundled `platform_overrides`:**
- File: `sccs/sync/category.py:27-43`
- `_resolve_effective_settings_ensure` silently merges the bundled `platform_overrides` into any user config that predates v2.20.0. This is intentional but means old user configs are quietly upgraded on every sync without explicit acknowledgement.
- Safe modification: The logic is correct as implemented. Document this merge behaviour in `sccs config upgrade` output so users understand why their settings are being written.

**Windows `powershell_profile` category assumes `~/Documents/PowerShell`:**
- File: `sccs/config/defaults.py:288-308`
- The comment at line 285-286 documents the OneDrive edge case: `~/OneDrive/Documents/PowerShell` is the real path on machines with OneDrive folder redirection enabled (common Windows default). Only a code comment warns users to override `local_path`.
- Impact: Silent sync failure (no files found) or incorrect files synced on OneDrive-enabled machines.
- Fix: At category scan time, check both `~/Documents/PowerShell` and `~/OneDrive/Documents/PowerShell`; use whichever exists, or surface a warning when neither is found.

---

## Scaling Limits

**`_MAX_PATHS_SCANNED = 500` in `PermissionDetector`:**
- File: `sccs/doctor/detectors.py:41`
- Current capacity: scans up to 500 entries per checked path.
- Limit: Misses foreign-owned files deeper than the first 500 entries on very large caches. Not a traditional scaling problem, but a correctness limit at scale.
- Note: The `npm-bin-global` check (added v2.32.1) uses a simple writability probe on a single path and is not affected by this cap.

---

## Dependencies at Risk

**`questionary` confirm prompt returns `None` on non-TTY stdin:**
- File: `sccs/doctor/installer.py:1329-1332`
- Risk: When stdin is not a TTY (CI pipe, `echo y | sccs doctor install`), `questionary.confirm(...).ask()` returns `None`. The current guard is `except (KeyboardInterrupt, EOFError): return False` — `None` is not caught, so `bool(None)` coerces to `False`, silently skipping all actions with no error message.
- Impact: Running `sccs doctor install` in CI without `--yes` produces zero executed actions, which looks like success.
- Mitigation: The `--yes` flag is the documented CI solution and its use is enforced in the `doctor_install` command docs. The silent-`None` path is only reached by unusual invocations.
- Fix: Add an explicit `None` check in `_confirm`: emit a warning and return `False` when `answer is None` and `not assume_yes`.

---

## Test Coverage Gaps (OPEN)

**Doctor CLI commands (`doctor check`, `install`, `update`, `optimize`) have zero CLI-level tests:**
- What's not tested: `test_cli.py` contains no tests for any `doctor` subcommand. The unit tests in `test_doctor.py` test individual detectors/planners/executors but the CLI wiring (`_collect_doctor_statuses`, `_load_doctor_config`, the Click command handlers) is untested at the integration level.
- Files: `tests/test_cli.py` (no doctor tests), `sccs/cli.py:1511-1805`
- Risk: A regression in how the CLI assembles detector results, applies `--yes`, or prints the report could go undetected.
- Priority: High

**`questionary` `None` return in non-TTY `_confirm`:**
- What's not tested: The `bool(None)` coercion path in `sccs/doctor/installer.py:1332` when `questionary.confirm().ask()` returns `None` (non-TTY stdin, no `--yes`).
- Risk: CI invocations appear to succeed while executing nothing.
- Priority: High

**`ClaudeMarketplaceDetector` format-change regression:**
- What's not tested: No fixture covers a changed `claude plugin marketplace list` output format (e.g. future CLI that drops the `❯` prefix). Current tests validate the happy path but not the fallback parser path independently.
- Files: `tests/test_doctor.py` (tests `_parse_registered` but not the `❯`-less format)
- Risk: A Claude CLI update silently breaks marketplace detection.
- Priority: Medium

**`settings_ensure` `keys_overridden` is never asserted:**
- What's not tested: A settings.json that already contains `statusLine` on Windows being overwritten by the platform override. `keys_overridden` is populated but not asserted in any test, and the console output path that would surface it does not exist.
- Files: `sccs/sync/settings.py:96-101`, `tests/test_settings.py`
- Risk: Silent data loss of user-customised statusLine on Windows; no test guards the contract.
- Priority: Medium

**Intel Homebrew / Linuxbrew stale-Cellar auto-fix:**
- What's not tested: `StatusLineDetector` stale-Cellar detection for `/usr/local/Cellar/...` paths (Intel Mac). The fix regex only covers `/opt/homebrew/Cellar/...`.
- Files: `sccs/doctor/detectors.py:683-685`, `tests/test_doctor.py`
- Risk: Intel Mac users hit `missing_binary` instead of `stale_cellar` with no auto-repair.
- Priority: Low (Apple Silicon is the dominant case)

**`_sync_bundled_skill` on Windows:**
- What's not tested: `shutil.copytree` behaviour when `target` already exists on Windows (case-insensitive filesystem, locked files from a running process).
- Files: `sccs/doctor/installer.py:735-737`
- Risk: Silent overwrite failure on Windows leaving a partial skill directory.
- Priority: Low (Windows support is secondary)

**Coverage baseline still at 66% (target 80%):**
- File: `pyproject.toml:91-94`
- The `fail_under = 66` comment explicitly names `sccs/cli.py` and `sccs/transfer/ui.py` as the weakest areas. `cli.py` is 1,811 lines with 41 functions; only 25 test functions exist in `test_cli.py`, none covering any `doctor` subcommand.
- Priority: Ongoing — raise floor incrementally as gaps close.

---

*Concerns audit: 2026-05-26*
