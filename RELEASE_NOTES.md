# Release Notes

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
