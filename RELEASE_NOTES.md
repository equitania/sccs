# Release Notes

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
