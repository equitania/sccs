# Release Notes

## Version 2.55.0 (07.08.2026)

### Fixed (transfer carries only your own artefacts)

- **`sccs export` no longer offers or ships doctor-managed items.** The selection list for `claude_skills` showed 141 entries on a normal host, of which 71 were not the user's work at all: the ~70 `gsd-*` skills dropped by `npx @opengsd/gsd-core` plus the npm-managed `playwright-cli`. Same picture for `claude_agents` (41 → 7) and `claude_hooks` (28 → 5). Exporting them is pointless — the receiving machine reproduces them at the *then-current* version with its own `sccs doctor install`, so the archive only ever carried a snapshot destined to go stale.
- **Root cause**: `SyncEngine` merges `get_doctor_managed_excludes(config.doctor)` into its effective exclude list (`sync/engine.py`), which is why the Git repository stays clean. `Exporter` read the raw `config.global_exclude` and never consulted that registry. It now mirrors the engine via `Exporter.effective_global_exclude`, so sync, export and the OpenCode/Pi/Codex exports all filter through the single registry in `sccs/doctor/managed.py`.
- **Scope of the filter is the item, not its contents**: `_add_directory_to_zip` deliberately keeps using the raw `global_exclude`. A reference file named `gsd-notes.md` inside one of your own skills stays in the archive — only whole doctor-managed items disappear.
- User-supplied `doctor.managed_excludes` patterns from `config.yaml` apply to the export as well, so additional vendor-installed artefacts can be filtered without a code change.
- **`sccs import` is symmetric.** Filtering only the export would have left the other direction open: every archive written *before* this release still carries those items, and importing them writes a frozen snapshot next to whatever `sccs doctor install` maintains — which the sync engine then ignores, so the drift never surfaces again. `Importer` now takes the same registry and drops managed items from the selection UI (`importable_manifest()`), from `--all` and from an explicit parsed selection alike. Measured against a real pre-fix archive: 327 items in the ZIP, 198 written, 129 skipped.
  - The archive **summary keeps reporting the raw manifest** — it states what the ZIP contains, not what SCCS is willing to write. The skipped count is printed separately, with the `--include-managed` hint.
  - A category left empty by the filter is dropped from the picker instead of showing as an empty group; an archive consisting *only* of managed items exits cleanly with "nothing to import" rather than an empty checkbox list.

### Added

- **`sccs export --include-managed` / `sccs import --include-managed`** — escape hatch that disables the filter for a single run and restores the pre-2.55.0 behaviour (e.g. seeding an air-gapped machine that cannot run `sccs doctor install`).

### Tests

- `tests/test_transfer.py`: new `TestExporterManagedExcludes` (5) — managed items absent from the scan, `include_managed=True` restores them, end-to-end absence from the ZIP payload, inner files named `gsd-*` survive, user `doctor.managed_excludes` honoured.
- `tests/test_transfer.py`: new `TestImporterManagedExcludes` (7) — `--all` and parsed selections both drop managed items, escape hatch restores them, raw manifest still reports the full archive while `importable_manifest()` does not, categories emptied by the filter disappear, end-to-end nothing managed lands on disk, user `doctor.managed_excludes` honoured.
- Two CLI tests asserting `export --all` / `import --all` omit them and `--include-managed` keeps them. 1366 total; ruff/format/mypy clean.

## Version 2.54.0 (26.07.2026)

### Added (doctor baseline)
- **Two Anthropic-authored plugins joined the doctor baseline** (`DEFAULT_CLAUDE_PLUGINS` in `sccs/doctor/defaults.py`), so `doctor check` reports them, `doctor install` installs them and `doctor update` keeps them current on every host:
  - **`claude-security@claude-plugins-official`** — deep vulnerability scanning of your own code, run inside the session at a chosen effort level. Entered as a *required* plugin rather than `allowlist_only`: a security scanner only helps if it is present everywhere, not just wherever it happened to be installed first.
  - **`claude-md-management@claude-plugins-official`** — audits and maintains `CLAUDE.md` files. Relevant on every host: a global `~/.claude/CLAUDE.md` plus one per project drift independently.
- **Scope note** (why this matters in practice): installing a plugin with `/plugin install` from inside a project writes `<project>/.claude/settings.json` — **project scope**, which does not travel to other projects or machines. `doctor install` issues a plain `claude plugin install <name>@<marketplace>`, i.e. **user scope** — the correct home for a doctor-managed baseline. A plugin that only exists at project scope will therefore show up as `MISSING` everywhere else, which is exactly the drift the doctor is meant to catch.

### Tests
- `tests/test_doctor.py`: `TestDefaultPluginBaseline` — asserts both new plugins are present in the defaults, are required (not `allowlist_only`), resolve to the official marketplace, and that the baseline carries no duplicate `name@marketplace` pairs.

## Version 2.53.0 (16.07.2026)

### Added (OpenAI Codex integration)
- **New `sccs integrations codex` sub-group** exports Claude Code artefacts one-way into the [OpenAI Codex CLI](https://developers.openai.com/codex/): `status`, `export-skills`, `export-agents`, `export-commands`, `export-all` (all with `-n/--dry-run`, `--overwrite/--no-overwrite` and selective `-s`/`-a`/`-c`). Doctor-managed artefacts (`gsd-*`, `playwright-cli`) are excluded by default; extend via `codex.exclude`, bypass per run with explicit name selection.
  - **Skills → `~/.agents/skills/<name>/` (verbatim)**: Codex reads skills in the open agentskills.io standard — the `SKILL.md` format is identical to Claude Code, so the whole directory is copied via `safe_copy` (symlink-rejecting), no conversion. Note the target: Codex's *user* skills live in `~/.agents/skills/`, NOT `~/.codex/skills/` (reserved for OpenAI-bundled system skills).
  - **Agents → `~/.codex/agents/<name>.toml`**: Markdown+frontmatter is converted to a Codex agent TOML file (`name`/`description`/`developer_instructions` = body). The Claude model alias maps to a Codex model **plus `model_reasoning_effort`** (opus→high, sonnet→medium, haiku→low); a `tools:` allowlist containing only read-only tools becomes `sandbox_mode = "read-only"`, anything else is dropped with ONE collected warning (Codex governs access via sandbox/approval policy, not per tool). The bundled model map is a static offline default (Codex has no discovery command) — override via `codex.model_map`/`extra_model_map`/`reasoning_effort_map`.
  - **Commands → wrapped as Codex skills** (`~/.agents/skills/<name>/SKILL.md`): Codex custom prompts (`~/.codex/prompts/`) are officially deprecated; skills are the documented migration target. Body stays verbatim; `$ARGUMENTS`/`$1` placeholders and dropped frontmatter fields produce warnings. **Collision protection**: a command whose name is claimed by a real skill (a Claude skill of the same name, or an on-disk skill directory carrying more than the wrapped SKILL.md) is never written — the skill wins, the command is skipped with a warning; previously wrapped commands stay idempotently re-exportable.
  - New hand-rolled minimal TOML emitter `sccs/convert/toml_write.py` (strings only — the one shape we emit; multi-line literal `'''` blocks preferred, escaped `"""` fallback). No runtime dependency added; every emitted document is round-trip-verified through a real TOML parser in the tests (dev-only `tomli` for Python 3.10).
  - New modules `sccs/convert/claude_to_codex.py` (pure conversion rules) and `sccs/integrations/codex.py` (`CodexDetector` + writers, hybrid of the Pi verbatim-copy and OpenCode converted-content patterns). New optional `CodexConfig` block (`base_dir`, `skills_dir`, `model_map`, `extra_model_map`, `reasoning_effort_map`, `exclude`) — backwards-compatible. `integrations status` gained a Codex section. Out of scope for v1 (deliberate): MCP merge into `~/.codex/config.toml`, CLAUDE.md → AGENTS.md.
  - New bilingual doc `docs/usage/codex.md`; README, CLI reference and the agent capability card updated.

### Fixed
- **`pi:` config block was silently dropped by the loader**: `_merge_with_defaults` had no passthrough branch for `pi` (unlike `doctor`/`opencode`), so `pi.base_dir`/`pi.exclude` overrides in `config.yaml` never reached the Pydantic model and the bundled defaults always won. Added the passthrough (plus the equivalent branch for the new `codex` block) with regression tests.

### Tests
- New `tests/test_codex_convert.py` (37 — model/tool mapping, command wrapping, TOML emitter round-trips incl. `'''`-runs, quotes/backslashes, CRLF, unicode), `tests/test_codex_detector.py` (16 — install marker, skill/agent/command gaps, collisions, re-export idempotency), `tests/test_codex_export.py` (12 — dir copy, TOML/SKILL.md materialisation, dry-run, overwrite, collision never writes), `tests/test_codex_config.py` (8 — CodexConfig defaults/overrides, loader passthrough incl. `pi` regression), `tests/test_codex_cli.py` (5 — help, not-installed exits, dry-run happy path). Suite now at **1347 passing**.

## Version 2.52.1 (15.07.2026)

### Changed (zsh activation UX)
- **Ready copy-paste one-liner instead of prose instructions** for activating the generated zsh profile. The hard rule stays untouched — SCCS never edits `~/.zshrc` itself — but everywhere the user was told to "add `source ~/.config/zsh/zshrc` to your ~/.zshrc" they now get a ready, idempotent one-liner: `grep -qxF 'source ~/.config/zsh/zshrc' ~/.zshrc 2>/dev/null || echo 'source ~/.config/zsh/zshrc' >> ~/.zshrc` (exact-line match — re-running never duplicates; `>>` creates a missing `~/.zshrc`). Single source of truth is the new `ACTIVATION_ONE_LINER` constant in `sccs/convert/zsh_templates.py`, used by the CLI success output of `sccs convert fish-to-zsh`, the generated `zshrc` header comment and the generated `README.md` (activation section + target-machine note). Docs updated accordingly (`docs/usage/platforms.md` DE+EN, `usage/AGENT.md`, `README.md`).

### Tests
- `tests/test_convert_zsh.py`: new assertions that the `grep -qxF` one-liner appears in the generated `zshrc` header, the generated `README.md` and the (ANSI-stripped) CLI success output.

## Version 2.52.0 (14.07.2026)

### Added (Fish → Zsh conversion)
- **New `sccs convert fish-to-zsh` command** generates a native zsh profile from the fish configuration — so all fish-defined aliases, env vars and functions are available on machines without fish (e.g. a stock macOS zsh). Options mirror `fish-to-pwsh` (`--src`, `--dst`, `--force`, `-n/--dry-run`, `--conveniences/--no-conveniences`); default destination is `<repo>/.config/zsh/` with an entry point `zshrc` that sources `conf.d/*.zsh` (sorted) and `functions/*.zsh`. Activation is a one-time manual `source ~/.config/zsh/zshrc` line in `~/.zshrc` — SCCS never edits `~/.zshrc` itself (the CLI prints the hint).
- **Best-effort block translator** (`sccs/convert/zsh_block.py`) — unlike the PowerShell converter, fish function bodies and control flow ARE translated: `function/end` → `name() { }` (incl. `-d` description and `-a/--argument-names` → `local x="$1"`), `if/else if/else` → `if/elif/else/fi`, `for`/`while` → `do/done`, `switch/case` → `case/esac`, `begin/end` → `{ }`, `set -l/-g/-gx/-e/-q` → `local`/`typeset -g`/`export`/`unset`/`[[ -v ]]`, `command -q` → `command -v >/dev/null`, `status is-interactive` → `[[ -o interactive ]]`, `and`/`or` continuation lines, `$argv`→`"$@"`, `$argv[N]`→`$N`, `(count $argv)`→`$#`, `$status`→`$?`, `(cmd)`→`$(cmd)`. Bare `~` tokens expand to `$HOME` (fish expands unquoted tildes; the zsh output lands inside double quotes where `~` would stay literal).
  - **Hard promise: never emit syntactically broken zsh.** Untranslatable fish builtins (`string`, `math`, `argparse`, `set -U`, `psub`, event handlers) stay as `# fish-untranslated:` comments; files exceeding a 30 % untranslatable threshold, unbalanced block structures, or event-handler functions fall back to fully commented stubs with a warning. A `zsh -n` syntax gate over every generated file is part of the test suite.
- **Line rules** (`sccs/convert/zsh_rules.py`) share the regex patterns with the PowerShell rules and add the fish space-form `alias name 'value'`: `alias` → `alias name='value'` (verbatim — zsh aliases carry arguments natively, no function wrapping needed), `set -gx` → `export VAR="value"`, `fish_add_path` → duplicate-aware `[[ ":$PATH:" != *":DIR:"* ]] && export PATH=...` prepend, `abbr` → `alias`.
- **Platform files are converted, not skipped** (divergence from `fish-to-pwsh`): `*.macos.fish` / `*.linux.fish` are translated and wrapped in a `[[ "$(uname)" == "Darwin"|"Linux" ]]` guard, so one generated profile is safe on both platforms. Secret guards (`*secret*`, `*token*`, `*credential*`, `*password*`), `*.local.fish`, `fish_history` and `fish_variables` remain excluded.
- **Minimal conveniences block** `conf.d/95-conveniences.zsh` (opt-out via `--no-conveniences`): only what zsh genuinely lacks — `..`/`...`/`....` navigation aliases and `mkcd`. The converted `ll`/`ls` aliases work natively in zsh, so no override layer like the PowerShell variant is needed.
- **New disabled-by-default sync category `zsh_config`** (`~/.config/zsh` ↔ `.config/zsh`, platforms macos/linux; includes `zshrc`, `conf.d/*.zsh`, `functions/*.zsh`, `README.md`; excludes `*.local.zsh`, `*secret*`, `*.bak`, `*credential*`). Adopt via `sccs config upgrade` or `sccs sync --migrate`, enable with `sccs categories enable zsh_config`.

### Tests
- New `tests/test_convert_zsh.py` (77 tests): line rules, fish-token rewrites, expression translation, block translator (incl. nesting, stub fallbacks, unbalanced structures), uname guards, directory conversion (secrets skip, dry-run, 0600 `.bak`, README preservation), CLI wiring, and a `zsh -n` syntax-validity gate (skipped when zsh is absent, e.g. on CI runners without zsh). Suite now at **1257 passing**.

## Version 2.51.0 (14.07.2026)

### Added (Self-serve capability card)
- **New `sccs capability-card` command** prints the agent capability card (`usage/AGENT.md`) as raw Markdown to stdout — the primary self-description surface for LLMs/agents that want to *use* the tool without repo or website access. Output goes through `click.echo` (never the Rich `Console`) so the Markdown arrives byte-for-byte; no options.
  - **Live version injection**: `_CARD_VERSION_RE` rewrites the card's `**Version:** X.Y.Z` header line to the running `__version__` at print time, so the header can never go stale.
  - **Bundling & fallback**: the card is force-included into the wheel (`[tool.hatch.build.targets.wheel.force-include]` → `sccs/data/AGENT.md`). `_find_capability_card()` resolves bundled package data first, then falls back to the repo `usage/AGENT.md` for editable installs, then a clean `SystemExit(1)` error.
  - The card itself was refreshed: added the `**Self-serve:**` header bullet and a `capability-card` table row, corrected the now-outdated "Machine-readable outputs: None" section to document the v2.50.0 `--json` layer, and tagged the `--json`/`--repo-path` flags onto the relevant command rows.

### Added (Export/Import pre-selection prompt)
- **The interactive two-stage export/import now asks, per detail view, whether items start all-selected or all-deselected.** For any group with more than `SMALL_GROUP_THRESHOLD` (5) items, `prompt_default_checked()` shows a two-option `questionary.select` before the item checkbox — "All pre-selected" (legacy behaviour, default) or "None pre-selected". This lets a user pick just a few items without deselecting every other entry.
  - Implementation threads a `default_checked` flag through `_build_group_item_choices()` / `_build_import_item_choices()` in `sccs/transfer/ui.py`, replacing the previously hard-coded `checked=True`. Applies to both `sccs export` and `sccs import`. Stage-1 group selection and the ≤5-item auto-include path are unchanged.

### Tests
- New `tests/test_cli_capability_card.py` (prints card, live-version injection, command surface, `--help` listing, missing-card error path, stale-version replacement).
- `tests/test_transfer_ui.py` extended: `prompt_default_checked` behaviour (True/False/Ctrl-C), builder `default_checked` state, and an export flow where "None pre-selected" + no toggle yields an empty selection.

## Version 2.50.0 (11.07.2026)

### Added (Machine-readable `--json` output layer)
- **Core-First commands now emit clean, single-line JSON for GUI/automation consumption.** New module `sccs/output/json_emit.py` (`to_jsonable` / `emit_json` / `emit_json_error`) recursively serializes the *existing* result objects — Pydantic models via `model_dump(mode="json")`, dataclasses via declared fields (computed `@property` values are intentionally excluded), enums→`.value`, `Path`→`str`. Driver: a native Tauri desktop GUI (`sccs-gui`) that wraps the CLI as a subprocess needs structured output instead of scraping Rich tables.
  - **Critical design constraint**: the Rich `Console` defaults to `colored=True` → `force_terminal=True`, so it emits ANSI escapes even when stdout is piped. Every `--json` path therefore bypasses `Console` entirely and writes through `click.echo`, taking an `if output_json:` branch *before* any Rich render call.
- **`--json` added to**: `status`, `categories list`, `config show`, `config validate`, `sync` (incl. `--dry-run`), `diff`, `doctor check`, `doctor install`, `doctor update`. Each returns the underlying `CategoryStatus` / `SccsConfig` / `SyncResult` / `DiffResult` / doctor status collection / `ExecuteResult` verbatim.
  - `sync --json` reports `{dry_run, committed, pushed, docs_generated, result}`; `diff --json` routes `show_diff()` to a throwaway sink and emits raw `diff_lines` + a convenience `diff_text`; `doctor install|update --json` force `assume_yes` and route `execute_plan`'s manual-block prints to a no-op so stdout stays pure JSON.
- **New `sccs config init --repo-path PATH` flag** makes config bootstrap non-interactive (bypasses the blocking `click.prompt`) — required for a GUI's first-run flow; pairs with `--json` to confirm the written path.
- 17 new tests (`tests/test_cli_json.py`) assert every path parses via `json.loads` with zero ANSI leakage; suite now at **1168 passing**. `ruff`, `mypy sccs/`, `bandit -ll` and the hatchling wheel build are clean.

## Version 2.49.0 (10.07.2026)

### Added (Doctor — GSD scope-boundary auto-patch)
- **`sccs doctor install|update|optimize` now auto-patches externally-delivered GSD prompts.** New module `sccs/doctor/scope_patch.py` prepends a **SCOPE BOUNDARY** directive to any `gsd-*` skill/agent/command whose body runs an unbounded `find .` / `grep -r <relpath>` scan not pinned to the git project root — the same bug class that made `/project-audit` scan sibling projects in a monorepo. GSD is delivered verbatim via `npx @opengsd/gsd-core` and cannot be fixed upstream, so we patch the files *after* every (re)install, before they are used.
  - Strategy is **directive-prepend only** — vendor shell snippets are left untouched, so an isolated snippet with an undefined `$PROJECT_ROOT` can never break.
  - **Idempotent**: a versioned sentinel (`<!-- sccs:scope-boundary v1 -->`) guards against double-patching; a GSD reinstall overwrites the file, and the next doctor run re-applies the directive. Original file permissions are preserved.
- **New `NpxToolSpec.patch_scope_boundary` flag** (default `False`, `True` for `@opengsd/gsd-core`) gates the new `_gsd_patch_action`, wired into both `_npx_install_actions` and `_npx_update_actions` (mirrors the existing `_bundled_skill_action` follow-up pattern).
- 12 new tests (`TestScopePatch`); suite now at **1151 passing**. `ruff`, `mypy sccs/` and the hatchling wheel build are clean.

## Version 2.48.0 (10.07.2026)

### Changed (Project-Audit Follow-up — maintainability hardening)
- **Refactored oversized functions identified in the project audit.** Four functions exceeded 150 lines and were split into focused helpers:
  - `sccs/cli.py:sync()` → `_handle_remote_status()`, `_build_conflict_resolver()`, `_resolve_with_editor()`, `_finish_sync()`.
  - `sccs/doctor/detectors.py:StatusLineDetector._evaluate()` → `_load_settings()`, `_read_statusline()`, `_evaluate_command()`, `_check_stale_cellar()`, `_check_binary()`, `_check_script()`.
  - `sccs/doctor/reporter.py:render_doctor_report()` → `_print_node_hint()`, `_print_pwsh_hint()`, `_print_permission_remediation()`, `_print_orphan_remediation()`, `_print_winget_path_remediation()`.
  - `sccs/sync/actions.py:determine_action()` → `_action_local_only()`, `_action_repo_only()`, `_action_both_exist()`, `_action_both_changed()`.
  No behavior changed; test suite remains green (1139 tests).
- **Removed all remaining `# type: ignore` comments.** Typed `resolve_conflict()` and `interactive_export_selection()` correctly; updated call sites in `sccs/cli.py`, `sccs/sync/category.py`, `sccs/sync/engine.py` and `tests/test_transfer_ui.py`. `mypy sccs/` now reports 0 issues.
- **Replaced production `assert` statements with explicit runtime checks.** Replaced three defensive assertions in `sccs/doctor/detectors.py` and `sccs/doctor/installer.py` (×2) with proper `if ...: raise ValueError(...)` checks so builds under `-O` / `PYTHONOPTIMIZE=1` do not silently drop validation.
- **Hardened external editor invocations.** New `validate_editor()` in `sccs/doctor/runner.py` verifies that an editor executable exists on PATH before `sccs config edit` or the merge editor attempt to spawn it; missing editors now surface a clear error instead of failing inside `subprocess`.

### Notes
- This release is pure maintainability / audit-close-out: no new user-facing commands, no new config options, no behavior changes. 1139 tests passing; `ruff check`, `ruff format --check`, `mypy sccs/` and `bandit -ll` clean; hatchling wheel build verified.


## Version 2.47.0 (09.07.2026)

### Fixed (OpenCode agent export — tool permissions were fully broken)
- **`export-agents` produced a wall of `tool 'Read,' has no OpenCode permission mapping — skipped` warnings and exported agents with NO tool restrictions.** Root cause: `_split_allowed_tools` split only on whitespace, but real Claude Code agent frontmatter is **comma-separated** (`tools: Read, Write, Edit, Bash`) — so every token kept a trailing comma (`Read,`), matched nothing, and the `permission` block came out empty. The splitter now splits on commas *and* whitespace.
- **The permission key table was wrong and incomplete.** It mapped only `read/write/edit/webfetch`, but OpenCode's `write` permission key does not exist (it's `edit`, which gates write+edit+apply_patch), and `glob/grep/list/websearch/skill/task/question` were missing entirely — so even without the comma bug most tools warned. The table is now complete and correct per opencode.ai/docs/agents (`Write`/`Edit`→`edit`, `Agent`/`Task`→`task`, `AskUserQuestion`→`question`, `Skill`→`skill`, etc.), and MCP tools map to OpenCode's wildcard keys (`mcp__context7__*` → `context7_*`).

### Changed
- **Tool allowlists are now reproduced faithfully.** Claude's `tools:` is a positive allowlist (only those tools). The export now emits `permission: {"*": "deny", …grants}` — OpenCode resolves most-specific-wins, so a read-only agent (e.g. `security-auditor`) is genuinely read-only in OpenCode instead of getting a meaningless grants-only block. This makes the export actually useful; the old "converted to grants only / not auto-denied" caveat is gone (no longer lossy). Verified end-to-end against a live OpenCode 1.17.15 (`opencode agent list` reads the exported agent and resolves its permission block).
- **Much quieter output.** Unmappable tools collapse into one summary warning per agent instead of one per tool. For commands, cosmetic `tags` are dropped silently and `allowed-tools` yields a single soft note (commands inherit tool access from their agent).

### Notes
- Triggered by a real `export-agents` run that surfaced the wall of warnings. Findings verified against the code, the official OpenCode docs, and a binary/string analysis of the installed OpenCode. Tests: comma-separated parsing regression, the full extended key table, catch-all-deny faithfulness, MCP wildcard mapping, and command noise reduction — 1139 total. `ruff`/`mypy`/`bandit -ll` clean.

## Version 2.46.0 (09.07.2026)

### Changed (OpenCode integration — deep review against the current version)
- **Skills honesty — the invented `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS` flag is gone.** A deep re-review against a live OpenCode install (**1.17.15**) and the official docs found that this env var does not exist in current OpenCode — the `reads_claude_skills` detector flag was never set by the CLI (always hardcoded `True`), so the "verification" was fiction. Removed the `disable_claude_skills` constructor param, the `reads_claude_skills` field, and the misleading comment/doc line. `sccs integrations opencode status` and `sccs integrations status` now state the plain fact: **OpenCode reads `~/.claude/skills/` natively (since v1.16, Jun 2026) — nothing to export** (new `SKILLS_NATIVE_NOTE` constant). The `SKILL.md` format is identical, so skills stay strictly zero-touch.
- **Concept documented: "skills-first, agents-as-subagents".** `docs/usage/opencode.md` (DE+EN) now leads with OpenCode's own mental model — *"Commands are what to do, skills are how to do it, agents are who does it"* (coexistence, not deprecation). Skills are the low-friction focus (native read, no SCCS action); agents map to `mode: subagent`; commands are thinly converted.
- **Command conversion completed.** `convert_command_frontmatter` now passes through the OpenCode-native `agent` and `subtask` fields when present in the Claude frontmatter (previously only `description`+`model` were emitted, despite the docstring claiming otherwise). `tags`/`allowed-tools` are still dropped with a warning.
- **Model-map fallback de-staled.** `DEFAULT_OPENCODE_MODEL_MAP` is now clearly documented as an offline last-resort only — the normal export path resolves models live via `resolve_model_map()` / `opencode models` (which returns the real provider prefix, e.g. `openrouter/anthropic/claude-sonnet-4.5`, not a hardcoded bare `anthropic/`). No behavior forced; the guidance points users at `opencode map-models`.

### Verified as still correct (no change needed)
- **Singular vs plural directories:** SCCS writes to `agent/`/`command/`; the OpenCode loader globs `{agent,agents}`/`{command,commands}`, so both are valid. Confirmed empirically — `opencode agent list` on 1.17.15 picks up an agent written to the singular `.opencode/agent/`.
- **MCP merge** (`mcp` block, `type: local/remote`, `command` array, `environment`, `headers`, `enabled`) matches current docs; `cwd` for local servers already supported.
- **`permission` over deprecated `tools:`** — SCCS already emits the modern shape.

### Notes
- Findings from a deep review (2 agents: SCCS-code map + live OpenCode research) plus binary/string analysis of the installed OpenCode (project renamed sst → anomalyco; docs at opencode.ai). Tests: `reads_claude_skills` toggle tests replaced with a constant-note test; new `agent`/`subtask` passthrough tests — 1132 total. `ruff`/`mypy`/`bandit -ll` clean, coverage floor 82 held. Live `sccs integrations opencode status` verified against 1.17.15.

## Version 2.45.3 (09.07.2026)

### Fixed (security hardening — project audit follow-up)
- **HIGH: `sccs export` no longer dereferences symlinks into the ZIP archive.** A planted symlink inside a synced directory (e.g. `~/.claude/skills/<x>/SKILL.md -> ~/.ssh/id_ed25519`) was silently followed by `zipfile.write()`/`os.walk()`, embedding the *target file's contents* in the portable export — the exact archive users hand to a colleague or move to a new machine, turning a local symlink plant into cross-machine secret exfiltration. Symlink items are now dropped at scan time (`scan_available_items`, so they never reach the selection UI or the manifest), and the ZIP writer itself skips symlinked files/directories as defence-in-depth (`_add_category_to_zip`/`_add_directory_to_zip`, with a warning log). This aligns the exporter with the rest of the codebase, which already refused symlinks everywhere (`safe_copy`, importer zip-entry rejection, Pi/OpenCode exports). Verified end-to-end: a real `sccs export` with a planted symlink logs the skip and the archive contains neither the entry nor the target's contents.
- **`settings.json.bak-*` backups are now written 0600 + atomically.** All three doctor mutators (statusline stale-cellar fix, missing-script fix, hook sanitiser) hardened the *primary* `settings.json` with `atomic_write(mode=0o600)` ("may hold MCP tokens") but wrote the backup — same content, same tokens — via plain `write_text()`, inheriting the process umask (often 0644) and persisting indefinitely. New shared helper `_write_settings_backup()` routes all three through `atomic_write(…, mode=0o600)`.
- **Allowlist validators added for `NpxToolSpec.npm_package` and `CliToolSpec.winget_id`.** Every other subprocess-bound spec field was validated against `_SAFE_NAME_PATTERN`; these two (added in v2.42.0/v2.43.0) were not, so a `-`-prefixed config value became an injected flag to `npm view` (e.g. `--registry=<evil-url>`) or `winget list`. Not OS command injection (shell=False holds), but a gap against the doctor's allowlist-everything policy. Scoped npm names (`@opengsd/gsd-core`) and dotted winget ids (`Microsoft.Coreutils`) still validate.
- **Robustness: remaining non-atomic config writers now use `atomic_write`.** `claude_desktop_config.json` (trust-repo), the fish-to-pwsh `.bak` backup (0600 — shell profiles can carry exported secrets), and `config.yaml` (`save_config`/`ensure_config_exists`) no longer risk a truncated file on crash mid-write.
- **Dependency hygiene:** `mypy` dev-dependency capped `<2.0.0` — mypy 2.0 (May 2026) changes default behavior (`--local-partial-types`, `--strict-bytes`, PEP 688), so the 2.x upgrade must be a deliberate, tested step instead of a silent `uv lock --upgrade` side effect. `uv.lock` refreshed (was stale at 2.45.1).

### Notes
- Findings from a full project audit (three parallel agents: structure/config, security, dependencies). All previously fixed areas re-verified as holding (runner allowlist, zip-slip guard, git argument validation, atomic settings writes, merge-buffer perms, GSD orphan-move safety). Runtime dependencies all current; rich cap fix from v2.36.1 confirmed. New tests: `tests/test_exporter_security.py` (6), backup-perms tests in `test_doctor.py`, spec-validator tests, converter backup-mode test — 1130 total. `ruff`/`mypy`/`bandit -ll` clean, coverage 83.7% (floor 82). Audit recommendation recorded for later: add a Windows CI runner (extensive Windows-specific code paths are currently only tested on Linux).

## Version 2.45.2 (30.06.2026)

### Fixed
- **CI: `test_cli_no_conveniences_flag` no longer fails under colorized output.** The test asserted the raw substring `skipped (--no-conveniences)` against the CLI output, but Rich colorizes in CI (GitHub Actions sets `FORCE_COLOR`) and wraps the parentheses in ANSI bold codes, so the literal match failed (it passed locally where the piped output is uncolored). The assertion now strips ANSI via the existing `_ANSI_RE` first, matching the other CLI-output tests in the file. Test-only change — no runtime behavior affected (the v2.45.0 conveniences feature and v2.45.1 Chocolatey hint are unchanged).

## Version 2.45.1 (30.06.2026)

### Changed
- **`sccs doctor` now recommends Chocolatey (not winget) for installing Node.js on Windows.** The Windows Node.js install hint was a runnable `winget install OpenJS.NodeJS`; it is now a print-only Chocolatey recipe (`runnable=False`, mirroring the Linux NodeSource block) because bootstrapping Chocolatey requires an *elevated* PowerShell that SCCS must never spawn on the user's behalf. Both `doctor check` and `doctor install` print, below the table:

  ```text
  powershell -c "irm https://community.chocolatey.org/install.ps1 | iex"
  choco install nodejs
  ```

  `choco install nodejs` installs the latest Node (no hard-pinned version that would age in the codebase). winget was removed entirely for Windows Node; macOS (`brew install node`) and Linux (NodeSource) are unchanged. The PowerShell 7 check added in 2.45.0 still uses winget for `Microsoft.PowerShell` — that is unrelated and unchanged.

### Notes
- Test `test_current_node_passes` updated to assert the Chocolatey block; `docs/usage/doctor.md` (DE + EN) updated. `ruff`/`mypy` clean, build OK. Full suite runs on Linux CI.

## Version 2.45.0 (30.06.2026)

### Added
- **`sccs convert fish-to-pwsh` now ships Fish-style comfort shortcuts (`conf.d/95-conveniences.ps1`).** The converter writes a curated, PowerShell-native block with the shortcuts you're used to from Fish: `ll`/`la`/`l` listing (preferring `eza` → `lsd` → native `Get-ChildItem`), navigation `..`/`...`/`....` (type `..` instead of `cd ..` — PowerShell has no built-in for it), plus the small Unix helpers `which`, `touch` and `mkcd`. The file's `95-` prefix makes it load **last** in `conf.d/`, so it intentionally wins over the auto-converted `ls`/`ll`. (Why this matters: a typical Fish config defines `ll` inside an `if command -q uu-ls … else … end` block; the converter only understands `function/end` blocks, so it converts *both* branches and the `else` branch — `ll = ls -alhFG` — wins, which is broken on Windows where `ls` is `Get-ChildItem` and `-alhFG` is rejected.) Opt out with `sccs convert fish-to-pwsh --no-conveniences`; the summary reports `Conveniences: enabled (95-conveniences.ps1)` or `skipped`.
- **`sccs doctor check` verifies PowerShell 7+ on Windows and suggests a winget install/upgrade.** Modelled on the existing Node check: on Windows the report adds a `PowerShell 7+ (pwsh)` row (`OK`/`OUTDATED`/`MISSING`) by probing `pwsh --version` against a minimum major of 7 (the modern, cross-platform shell that consumes the converted profile — not the legacy Windows PowerShell 5.1). When `pwsh` is missing or older than 7.x, the report prints `winget install --id Microsoft.PowerShell` (or `winget upgrade …`) below the table. It is **a suggestion only** — SCCS never installs/upgrades PowerShell itself — and a missing/outdated `pwsh` does **not** flip the exit code (informational, CI-friendly). On macOS/Linux the row is hidden entirely and no subprocess is spawned.

### Notes
- New tests: `TestConveniences` (convert), `TestPowerShellDetector` + `TestPowerShellReporter` (doctor). `ruff` format/lint clean, `mypy` clean (56 files), build OK. Behaviour verified directly on macOS (convert dry-run shows the conveniences line; `doctor check` hides the pwsh row off Windows; a simulated Windows render shows the row + winget block for missing/outdated/ok). Full suite runs on Linux CI (platform-independent change).

## Version 2.44.0 (30.06.2026)

### Changed
- **`sccs sync` no longer proactively offers new default categories — the prompt is now opt-in.** Previously `sccs sync` would interrupt with "New categories available (3) … Add all 3 categories at once?" whenever the default config gained optional integrations (currently the three `opencode_*` categories, plus Pi) that the user's config was missing. Those integrations aren't for everyone, so the prompt should only appear on explicit request. The `--no-migrate` opt-out flag is replaced by a `--migrate/--no-migrate` boolean pair defaulting to **off**: a plain `sccs sync` (and any non-TTY/CI run) is now completely silent — no prompt, no notice. To adopt newly available categories, use the dedicated `sccs config upgrade` (unchanged) or pass `sccs sync --migrate`. `--no-migrate` stays valid as a no-op (backwards compatible). `_run_migration_check`'s early-exit is inverted (`if not migrate: return`); the `declined_categories` state logic is untouched and still applies under `--migrate`/`config upgrade`.

### Notes
- Tests flipped from opt-out to opt-in, plus a new "default sync is silent about new categories" assertion. `ruff` format/lint clean, build OK. Full suite verified on Linux CI (platform-independent change).

## Version 2.43.2 (26.06.2026)

### Fixed
- **Windows: `path: npm-prefix-bin` no longer reports a false MISSING, and its PATH-fix block is PowerShell.** Two bugs on the same doctor row. (1) `_resolve_npm_prefix_bin()` always appended `/bin`, but on Windows npm puts global executables **directly in the prefix** (`C:\Users\…\AppData\Roaming\npm\playwright-cli.CMD` — no `bin\` subdir), so the check pointed at a non-existent directory and stayed MISSING even when the real dir was on PATH. It now returns the prefix itself on Windows (`<prefix>/bin` stays on Unix); a `is_windows` parameter makes it testable. (2) `_path_prefix_actions` only emitted `fish_add_path` / `~/.bashrc` / `~/.zshrc` snippets — useless in PowerShell. On Windows it now emits a PowerShell block (persistent User PATH via `[Environment]::SetEnvironmentVariable('Path', …, 'User')`, idempotent, plus the temporary `$env:Path` form). Non-Windows output is unchanged. Print-only — SCCS never edits the environment itself.

## Version 2.43.1 (26.06.2026)

### Fixed
- **Windows: `npm`/`npx` (`.cmd` wrappers) are now launchable via subprocess.** On Windows `npm`/`npx` are batch wrappers (`npm.cmd`/`npx.cmd`), not real `.exe` files; `subprocess.run(shell=False)` → CreateProcess cannot launch a `.cmd`/`.bat` directly and raised `FileNotFoundError`. This broke `sccs doctor install` (`Command not found: npx` / `npm` for gsd-core and playwright-cli) **and** every npm-querying detector (`npm config get prefix`, `npm root -g`), which falsely reported "npm not on PATH". New `_resolve_exec_command()` in `runner.py` resolves the wrapper via `shutil.which` and, on Windows for a `.cmd`/`.bat` target, launches it shell-free through `cmd.exe /c <resolved-path> <args>` (the HARD RULE "never `shell=True`" stays intact; a metacharacter guard `& | < > ^ % " ( ) !` + CR/LF refuses any injection-bearing argument). Real `.exe` targets and every non-Windows platform are returned untouched (no-op), and error messages still name the original command (`Command not found: npm`).

### Notes
- 12 new tests across the two fixes (`.cmd` resolution 7, npm-prefix-bin/PowerShell 5); 1102 total. `ruff` / `mypy` clean. Verified on macOS: `_resolve_exec_command` rewrites only Windows `.cmd` targets; `_resolve_npm_prefix_bin(is_windows=True)` drops the `bin` suffix; the Windows PATH block contains `SetEnvironmentVariable`/`$env:Path` and no shell snippets.

## Version 2.43.0 (26.06.2026)

### Added
- **`sccs doctor` detects + helps install optional shell CLI tools (zoxide, Microsoft Coreutils).** New opt-in category modelled on the npx-tool checks. Enable it by listing built-in preset names in `~/.config/sccs/config.yaml`: `doctor: { cli_tools: [zoxide, coreutils] }` (empty by default → no extra rows, so macOS/Linux users never see surprise output). **zoxide** (smart `cd`) is checked on all platforms (winget on Windows, `brew install zoxide` on macOS, the official install script on Linux); **Microsoft Coreutils** (`Microsoft.Coreutils`, the Rust uutils port of `cat`/`grep`/`wc`/`cut`/`xargs`/…) is Windows-only — it gives PowerShell the same native UNIX commands as Linux/macOS/WSL. Detection: `shutil.which(detect_command)` decides "on PATH"; on Windows a `winget list --id <id>` fallback is the **authoritative** install check (independent of PATH — it distinguishes "installed but not on PATH", the WinGet-Links trap, from "missing"). Three states render as `OK` (on PATH), yellow "installed, not on PATH" (+ a copy-paste PowerShell PATH snippet below the table), or blue "not installed (optional)". **Informational only** — a missing tool is never red MISSING and never flips the exit code (`has_problems` is unchanged → CI-friendly). `sccs doctor install` offers `winget install` / `brew install` behind a confirm prompt; SCCS never edits the user's PATH/profile itself (consistent with the existing npm PATH-prefix block). New `CliToolSpec` + `DoctorConfig.cli_tools`/`extra_cli_tools`/`effective_cli_tools()`, `BUILTIN_CLI_TOOLS`, `CliToolStatus`/`CliToolDetector`, `run_winget_list`, `_cli_tool_install_actions`/`_winget_links_path_block`, `_cli_tool_row`. `winget` already passed the runner allowlist (no security change); `NodeInstallSpec` is reused as the per-platform install recipe. Note: zoxide additionally needs `zoxide init <shell>` in the shell profile for the `z` command — intentionally out of scope (the doctor only ensures the binary, it never mutates profiles).
- **`sccs doctor check` now shows the Node.js install/upgrade command inline.** Previously a missing/outdated Node only produced a table row ("need >= 22.x"); the actual NodeSource/brew/winget command appeared only under `doctor install`. The report now renders the platform-specific install block below the table (Linux NodeSource two-liner rendered line-by-line, macOS `brew install node`, Windows `winget install OpenJS.NodeJS`), so the copy-pasteable fix is right there.

### Fixed
- **Windows crash: subprocess wrappers now force UTF-8 decoding.** On Windows (cp1252 locale, Python 3.14) `sccs doctor check` crashed in the subprocess reader thread (`UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d`): `subprocess.run(text=True)` without an explicit `encoding=` decodes with the OS code page, and `claude plugin list` / `npm` emit UTF-8 bytes (box-drawing glyphs, emoji). The fallout was not cosmetic — the truncated stdout made the doctor report installed plugins as falsely MISSING. Both capturing wrappers (`doctor/runner.py:_run`, `git/operations.py:_run_git`) now pass `encoding="utf-8", errors="replace"` → deterministic across platforms and tolerant of odd bytes.

### Notes
- 24 new tests across the three increments (cli-tools 18, node-hint 4, UTF-8 regression 2); 1090 total. `ruff` / `mypy` clean. zoxide install verified on macOS (`tool: zoxide  OK`); Coreutils row correctly skipped off-Windows.

## Version 2.42.0 (26.06.2026)

### Added
- **`sccs doctor check` now flags available updates.** Previously `doctor check` showed only the *installed* version of an npx tool or plugin and marked everything `OK` — even when a newer version existed upstream (the driver: gsd-core 1.5.0→1.6.0 and context-mode 1.0.162→1.0.166 were only noticed via GSD's own UI). `doctor check` now checks **live** whether the doctor-managed npx tools **and** Claude plugins have a newer version and renders them as `OUTDATED` plus an "Updates available — run `sccs doctor update`" hint line. **Exit code is unchanged** — an available update is informational, not a failure, so it never flips `doctor check` to exit 1 (`has_problems` deliberately ignores updates → CI-friendly). Latest-version sources: npx tools via `npm view <npm_package> version` (read-only registry query); plugins via the live-refreshed marketplace manifest (`claude plugin marketplace update <name>` → `<installLocation>/.claude-plugin/marketplace.json`). New `NpxToolSpec.npm_package` field marks which tools npm is the source of truth for (only `@opengsd/gsd-core`; the brew-managed `playwright-cli` is intentionally left unchecked). New `latest_version` / `update_available` fields on `NpxToolStatus` and `PluginStatus`; a dependency-free semver comparator (`_parse_version` / `_version_gt`) that returns `False` conservatively on any unparsable/`None` value so a network failure never raises a false "update available". `allowlist_only` plugins (the LSPs) are never update-checked, consistent with the install/marketplace passes. New CLI flag `sccs doctor check --update-check/--no-update-check` (default on; `--no-update-check` keeps the report fully offline and fast).

### Changed
- New runner helpers `run_npm_view_version` / `run_claude_marketplace_update` (both best-effort, swallow failures); both `ClaudePluginDetector.get_statuses` and `NpxToolDetector.get_statuses` gained a `check_updates=` keyword (default `False`, so `install`/`update`/`optimize` — which refresh blindly anyway — pay no network cost). The reporter's `_OUTDATED` row style (defined since v2.33.0 but never used) is now emitted for outdated npx tools and plugins, alongside a new `has_updates()` helper.

### Notes
- 26 new tests (`TestVersionComparison`, `TestRunNpmViewVersion`, `TestNpxUpdateDetection`, `TestPluginUpdateDetection`, `TestMarketplaceManifestReaders`, `TestUpdateReporting`); 1066 total. `ruff` / `mypy` clean. Verified live on macOS: an artificially down-rev'd `~/.claude/gsd-core/VERSION` produced the `OUTDATED` row + hint at exit 0; `--no-update-check` stayed offline.

## Version 2.41.0 (21.06.2026)

### Added
- **Pi integration (`sccs integrations pi`).** Export Claude Code artefacts one-way to [Pi](https://pi.dev) (`@earendil-works/pi-coding-agent`). Pi loads `SKILL.md` folders with the *same* frontmatter format Claude Code uses, so the export is a **verbatim copy** — no frontmatter conversion and no model mapping (unlike OpenCode). Mapping: Claude **skills** `~/.claude/skills/<name>/` → `~/.pi/agent/skills/<name>/` (whole directory, incl. `references/`/`scripts/`); Claude **agents** `~/.claude/agents/<name>.md` → `~/.pi/agent/skills/<name>.md` (Pi has no subagent concept, so agents land as individual root-`.md` skills); Claude **commands** `~/.claude/commands/<name>.md` → `~/.pi/agent/prompts/<name>.md` (prompt templates). New `PiDetector` + `export_skills_to_pi` / `export_agents_to_pi` / `export_commands_to_pi` in `sccs/integrations/pi.py`, reusing `safe_copy` (file **and** directory, symlink-rejecting) and `quick_compare` for outdated-detection. CLI sub-group `pi status` / `export-skills` / `export-agents` / `export-commands` / `export-all`, all with `--dry-run` / `--overwrite` / name-selection. Doctor-managed artefacts (`gsd-*`, `playwright-cli` — the same managed registry the sync engine honours) are excluded by default; extend via `pi.exclude`, override per-run with an explicit `-s`/`-a`/`-c` selection. `integrations status` now reports the Pi install and its export gaps. New `PiConfig` block (`base_dir`, `exclude`) is fully optional/backwards-compatible → [docs/usage/pi.md](docs/usage/pi.md).

### Notes
- 23 new tests (`tests/test_pi_detector.py`, `tests/test_pi_export.py`); `ruff`/`mypy` clean. Existing `test_integrations_status_no_integrations` extended to mock the new `PiDetector`.

## Version 2.40.0 (20.06.2026)

### Changed
- **Doctor's bundled GSD tool moved from the now-deprecated `@opengsd/get-shit-done-redux` to `@opengsd/gsd-core`.** GSD relocated again: the redux npm package is deprecated (`"Renamed to @opengsd/gsd-core — reinstall: npx @opengsd/gsd-core@latest"`) and the active line is `@opengsd/gsd-core` (repo `open-gsd/gsd-core`, latest 1.5.0). `DEFAULT_NPX_TOOLS` now invokes `npx -y @opengsd/gsd-core --claude --global --force-statusline` (flag compatibility verified against the v1.5.0 `bin/install.js`). The `version_file` moved with it (`~/.claude/get-shit-done/VERSION` → `~/.claude/gsd-core/VERSION`; the package no longer ships a `get-shit-done/` dir, only `gsd-core/`). `DEFAULT_MANAGED_PATTERNS` key and `NpxToolSpec.name` updated in lockstep so the `gsd-*` sync-exclude, protected-hooks and statusline auto-fix keep matching. The doctor state marker (argv hash) self-invalidates on the package-name change, triggering a one-time reinstall onto gsd-core — no manual migration.
- **`MIN_NODE_MAJOR` bumped 20 → 22.** gsd-core requires Node ≥22 (`engines: node>=22, npm>=10`). The schema default (`DoctorConfig.min_node_major`), the bundled config default and the Linux NodeSource install hint follow (the hint is now derived from `MIN_NODE_MAJOR`, so it prints `setup_22.x` and stays in sync with future bumps).

### Added
- **Orphan cleanup for stale doctor-managed GSD artefacts.** gsd-core's own legacy cleanup only prunes stale `hooks/` and `commands/` — orphaned `gsd-*` **skills** and **agents** from the superseded redux package pile up untouched. New `GsdOrphanDetector` uses the tool's install manifest (`~/.claude/gsd-file-manifest.json`) as the single source of truth: any on-disk `gsd-*` artefact under the configured scan dirs that the **fresh** manifest does not reference is an orphan (as is the old `~/.claude/get-shit-done/` directory once migration is complete). `sccs doctor check` reports orphans read-only below the table; `install`/`update`/`optimize` queue a cleanup action that **moves** (never hard-deletes) each orphan into `~/.config/sccs/gsd-orphans-backup-<timestamp>/` — per-action confirm (default No; `--yes` overrides), reversible, idempotent, and a no-op on a clean host. The action runs after the npx (re)install rewrites the manifest and re-detects against it, so it reflects the new package's exact file set. New `NpxToolSpec` fields `managed_file_manifest` / `managed_scan_dirs` / `managed_legacy_dirs` drive it; the plan builders take pre-computed `gsd_orphans` (no filesystem I/O in the builder, so plan-building stays test-isolated).

### Notes
- 1017 tests (18 new in `tests/test_doctor_orphans.py`); `ruff`/`mypy`/`bandit` clean, coverage 83.9% (floor 82).

## Version 2.39.1 (17.06.2026)

### Added
- **AI Capability Card (`usage/AGENT.md`).** A dense, English, machine-skimmable reference for an LLM/agent that wants to *use* the `sccs` CLI — every command, flag, recipe and guardrail in one file. The command table is extracted **deterministically** by introspecting `sccs.cli:cli` (28 runnable commands; completeness gate green), while recipes, guardrails and the capability summary are synthesized from `docs/usage/*.md`. Lives under `usage/AGENT.md`, kept separate from the bilingual human docs in `docs/usage/`. Regenerate the table after any CLI change via `scripts/introspect_cli.py --import sccs.cli:cli --root-name sccs`.

### Notes
- Documentation-only release — no code change. 999 tests unchanged; `ruff format` clean, build OK.

## Version 2.39.0 (15.06.2026)

### Added
- **OpenCode export now skips doctor-managed (`gsd-*`) agents/commands by default.** Real driver: `sccs integrations opencode status` listed all 40 `~/.claude/agents/*.md` — 33 of them the `gsd-*` agents installed by the *get-shit-done* plugin (`@opengsd/get-shit-done-redux`), which the user never wants to export. The export now reuses the **same managed-exclude registry the sync engine already honours** (`get_doctor_managed_excludes(config.doctor)` → `gsd-*`, `playwright-cli`), so plugin-managed artefacts are filtered out of status, `export-agents` and `export-commands` out of the box. Your own agents/commands are unaffected. (Skills were never exported — OpenCode reads `~/.claude/skills/` natively.)
- **New optional `opencode.exclude`** config field (`OpenCodeConfig.exclude`): extra glob patterns (matched against the artefact basename) stacked on top of the doctor-managed defaults, for dropping your own additional artefacts from the export.
- **Explicit selection overrides the exclude.** Passing `-a <agent>` / `-c <command>` bypasses the default exclude for that run, so a specifically-named managed artefact (e.g. `-a gsd-debugger`) still exports.

### Changed
- `OpenCodeDetector.get_agent_gaps` / `get_command_gaps` (and `_gaps_for`) gained an `exclude_patterns` parameter, matched via the existing `matches_any_pattern` helper at the same filter stage as the `_`/`.local.md`/symlink skips. New `_resolve_opencode_excludes()` CLI helper combines doctor-managed + user patterns (falls back to bundled `DoctorConfig()` defaults when no config file exists, so `gsd-*` stays excluded out of the box).

### Tests
- 8 new tests: detector-level exclude (glob filtering for agents + commands, no-pattern passthrough, stacked custom patterns) and CLI (`_resolve_opencode_excludes` default + user-stack, `-a` override bypasses the exclude). 999 tests total; coverage floor 82 held. `ruff` + `mypy` clean.

## Version 2.38.0 (15.06.2026)

### Added
- **Dynamic, configurable model mapping for OpenCode export.** The hardcoded `MODEL_MAP` (guessed `anthropic/...` ids) is now the last-resort fallback only. Model resolution is layered, per Claude alias (lowest → highest precedence):
  1. **Static default** `DEFAULT_OPENCODE_MODEL_MAP` (the old map; used offline / when no provider is authenticated).
  2. **Live discovery + family match** — `opencode models` (via the hardened doctor runner) is queried and the CC tier (`sonnet`/`opus`/`haiku`) is matched against the models the install *actually offers*; `preferred_providers` (default `["anthropic"]`, configurable) wins, ambiguity is warned. So we map to a model that really exists instead of guessing.
  3. **Explicit config map** `opencode.model_map` / `extra_model_map` from `~/.config/sccs/config.yaml` — pins specific aliases.
- **`sccs integrations opencode map-models`** — interactive setup: lists the Claude model aliases your agents/commands actually use plus the models your OpenCode install offers, lets you assign each (questionary, family-match pre-selected), and persists the result to `opencode.model_map` (raw-edit + backup; only that key is touched). `--dry-run` previews without writing.
- **New `opencode:` config block** (`OpenCodeConfig`: `model_map`, `extra_model_map`, `preferred_providers`) on `SccsConfig`, fully optional and backwards-compatible (default_factory). Loader passes the block through verbatim in `_merge_with_defaults` (same fix shape as the v2.29.1 `doctor:` regression). New `save_opencode_model_map()` in `config/loader.py`.
- **`map_model()` now takes an injected `model_map`** (default = static), and `convert_agent_frontmatter` / `convert_command_frontmatter` thread it through; `export-agents` / `export-commands` build the resolved map once per run via `resolve_model_map(config)`. New pure helper `match_models()` (family-match heuristic, isolated-testable) and `list_opencode_models()` / `resolve_model_map()` in `integrations/opencode.py`; `run_opencode_models()` in `doctor/runner.py`.

### Tests
- 30 new tests (`tests/test_opencode_models.py` + `match_models`/injection cases + a `map-models` CLI block). 991 tests total; coverage 83.7% (floor 82). End-to-end verified against live OpenCode 1.17.7: `map-models` lists models, `export-agents` resolves through the layered map and falls back to static when no Anthropic provider is authenticated.

## Version 2.37.0 (15.06.2026)

### Added
- **OpenCode integration — share Claude Code artefacts with OpenCode (opencode.ai).** New `sccs integrations opencode` sub-group materialises Claude artefacts into the OpenCode formats. Direction is **one-way** (Claude is the source of truth). Three stages, by compatibility:
  - **Skills + Rules — zero conversion.** OpenCode reads `~/.claude/skills/<name>/SKILL.md` and `CLAUDE.md` natively (verified on OpenCode 1.17.7; toggle via `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`). Nothing to export — `sccs integrations opencode status` just surfaces this.
  - **Agents + Commands — frontmatter conversion.** `export-agents` / `export-commands` convert CC frontmatter to the OpenCode shape and write into `~/.config/opencode/agent/` and `command/` (singular dirs; the plural alias also works). Transforms: drop `name` (OpenCode derives it from the filename), map the model alias (`sonnet` → `anthropic/claude-sonnet-4-5`, with pass-through + warning on unknown ids), `mode: subagent`, and `allowed-tools` → an OpenCode `permission` object (`Bash(git:*)` → `bash: {"git *": allow}`). Commands drop CC-only `tags`/`allowed-tools` with a warning.
  - **MCP — config merge.** `merge-mcp` reads `mcpServers` from `~/.claude/settings.json`, transforms each entry (`command`+`args` → single argv array, `env` → `environment`, explicit `type: local|remote`, `enabled: true`) and merges it into the `mcp` block of `opencode.json` (JSONC-comment-tolerant reader). Existing OpenCode entries are preserved unless `--overwrite`; a timestamped backup is written first.
- **Three new (disabled-by-default, macos/linux) sync categories** — `opencode_agents`, `opencode_commands`, `opencode_skills` (`local_to_repo`) — so the materialised OpenCode artefacts can also flow into the sync repo. `opencode_skills` is only for maintaining a *separate* OpenCode skill set; most users rely on the native `~/.claude/skills` read.
- New modules: `convert/frontmatter.py` (dependency-free YAML-frontmatter parse/render), `convert/claude_to_opencode.py` (pure transform logic + `MODEL_MAP`), `integrations/opencode.py` (`OpenCodeDetector`, gap detection, writers, MCP merge). All `__init__` exports updated. `integrations status` gained an OpenCode section.

### Tests
- 71 new tests across `tests/test_opencode_convert.py`, `tests/test_opencode_detector.py`, `tests/test_opencode_mcp.py` and a `TestOpenCodeCli` block in `tests/test_cli.py`. 961 tests total; coverage 83.7% (floor 82). End-to-end verified against a live OpenCode 1.17.7 install — a converted agent loads as `python-toolsmith (subagent)`.

## Version 2.36.1 (07.06.2026)

### Fixed
- **Dependency hygiene (project audit follow-up).** The `rich` upper bound was an off-by-one (`<15.0.0`) that blocked the current stable release — widened to `<16.0.0` so fresh installs resolve up to 15.x. `uv.lock` was stale at `2.33.1` across three releases — regenerated to `2.36.1`.
- **`settings.json` writes now pass an explicit `mode=0o600`.** `atomic_write()` gained an optional `mode=` parameter; the sensitive settings.json writers (doctor statusline auto-fix, hook sanitiser, settings sync) set it explicitly. Note: this is defence-in-depth, not a bugfix — `os.replace` is `rename(2)`, so the target already inherits the temp file's `0600` perms (mkstemp default); the audit finding M-1 ("settings.json left world-readable") was a false positive, verified by regression test. Docstrings/comments corrected.

### Changed
- **Test coverage raised from ~73% to ~83%.** The coverage floor in `pyproject.toml` (single source of truth) went `70 → 82`. Newly covered: `output/merge.py` (36%→94%), `sync/engine.py` (65%→96%), `cli.py` (32%→75%, via CliRunner across every command group), and `transfer/ui.py` (42%→100%, questionary prompts mocked). 890 tests total.
- **CLAUDE.md architecture diagram synced with the real source tree** (added `doctor/`, `transfer/`, `integrations/`, `convert/`, `docs/` and the missing per-module files).

## Version 2.36.0 (29.05.2026)

### Added
- **`doctor check` now shows a Version column for plugins and npx tools.** The table gained a dedicated `Version` column so you can verify the whole list at a glance (e.g. confirm redux runs `v1.1.0`, not the frozen old package). Plugin versions are **zero-cost**: the `Version:` line already sits in the `claude plugin list` output and was previously parsed only for `Scope:` — a second regex (`_extract_version_from_block`) surfaces it. npx-tool versions come from two new declarative `NpxToolSpec` fields: `version_file` (a tilde-path whose first line is the version — `@opengsd/get-shit-done-redux` → `~/.claude/get-shit-done/VERSION`, zero subprocess) and `version_args` (e.g. `playwright-cli --version`, one cheap call, output scanned for the first semver token). Any lookup failure leaves the column blank — never breaks the check. New fields `PluginStatus.version` / `NpxToolStatus.version`; all reporter row functions return a 4-tuple `(Component, Status, Version, Detail)`.
- **Plugin source in the Detail column.** When a `PluginSpec` declares a `marketplace_source` (the upstream repo, e.g. `mksglu/context-mode`), it now appears in the row detail; the marketplace itself was already visible in the `name@marketplace` component label.

### Changed
- **PATH manual block now explains how to make the entry permanent.** Previously the `npm global bin not on $PATH` block only printed the **temporary** commands (`set -gx PATH …` / `export PATH=…`), which vanish with the shell session — users had to re-enter them after every new shell. The block (and the Option-A snippet in `_npm_global_fix_block`) now lead with permanent instructions: `fish_add_path <dir>` (Fish 3.2+, idempotent) and `echo 'export PATH="<dir>:$PATH"' >> ~/.bashrc` / `~/.zshrc`, with the temporary form kept below. SCCS still never mutates rc files — it only prints the guidance.

### Tests
- 13 new tests (`TestVersionAndSourceReporting`): plugin-version parse (present/absent/no-bleed-across-blocks), npx `version_file`/`version_args` resolution + failure tolerance, reporter Version column + marketplace_source suffix, permanent-PATH block contents, and defaults declaring the version sources. Existing reporter row-unpacking tests updated to the 4-tuple shape.

## Version 2.35.0 (29.05.2026)

### Added
- **`sccs doctor` now auto-fixes the GSD statusline rename (`missing_script`).** GSD renamed its statusline hook `hooks/statusline.js` → `hooks/gsd-statusline.js` during the get-shit-done-redux move. A `statusLine.command` still pointing at the old name left the statusline dead, and `StatusLineDetector` only *reported* it (`missing_script`) while `_status_line_actions` printed a manual block. Doctor now offers an in-process auto-fix — modelled exactly on the existing `stale_cellar` rewrite: regex-rewrite on the raw command (quoting preserved), timestamped `.bak-YYYYMMDD-HHMMSS` backup, then `atomic_write`. New `StatusLineCheckSpec.auto_fix_stale_script` flag (default `True`). The settings.json rewrite stays `auto_confirm=False`, so the user is still prompted (delete-safety convention; `--yes` overrides).
- **Deliberately narrow scope.** The rewrite fires *only* for the `hooks/`-prefixed `statusline.js` → `gsd-statusline.js` rename (mirrors upstream redux #330's guard against third-party `statusline.js` scripts) and *only* when the new `gsd-statusline.js` exists on disk. Every other `missing_script` case (foreign scripts, new script absent) keeps the existing manual block — no guessing where to rewrite. New helper `_rewrite_stale_gsd_script_command` (`sccs/doctor/installer.py`).

### Tests
- 4 new tests in `tests/test_doctor.py` (`TestStatusLineAutoFix`): rewrite + backup + key preservation, no-fix-when-new-script-absent, foreign-script-stays-manual (scope guard), and idempotency.

## Version 2.34.0 (29.05.2026)

### Changed
- **Doctor's bundled GSD tool moved from the deprecated `get-shit-done-cc` npm package to `@opengsd/get-shit-done-redux`.** GSD officially relocated: the upstream `gsd-build/get-shit-done` README now reads *"GSD Has Moved … continues as GSD Redux in open-gsd/get-shit-done-redux"*, and the old `get-shit-done-cc` package is marked deprecated on npm (frozen at v1.42.3, 16.05.2026). The active line is `@opengsd/get-shit-done-redux` (releases from 22.05.2026). Its versioning reset (1.42.3 → 1.x) makes the number look lower, but it is the current, maintained package. Real driver: on a host where the user already runs redux, `sccs doctor update` was overwriting the install with the stale `get-shit-done-cc` tree, after which GSD's own update-banner hook reported "GSD update available — run /gsd-update". `DEFAULT_NPX_TOOLS` in `sccs/doctor/defaults.py` now invokes `npx -y @opengsd/get-shit-done-redux --claude --global --force-statusline` (flag compatibility verified against the redux `bin/install.js`). The `DEFAULT_MANAGED_PATTERNS` key in `sccs/doctor/managed.py` and the `NpxToolSpec.name` are updated in lockstep so the `gsd-*` sync-exclude and hook-protection keep matching.
- **State-marker invalidation triggers a one-time reinstall onto the active package.** The `detect_via_state` marker carries a hash of the invocation argv (v2.21.1); changing the package name invalidates the stored marker, so the next `sccs doctor check/install/update` reports the tool as missing and reinstalls it via redux — no manual migration needed.

## Version 2.33.2 (28.05.2026)

### Fixed
- **`sccs doctor check` no longer recommends `sudo chown -R /usr/bin`.** Linux real-session bug (uid 1000, system npm at `/usr`): the reporter's "Permission issues — run manually" block printed a one-line chown targeting `/usr/bin`, which would brick the system. The installer had the safe `_npm_global_fix_block` (Option-A user-local prefix) since v2.32.1, but the reporter rendered `PermissionStatus.fix_command` directly and bypassed the guard. `fix_command` now returns `None` when the path is outside `$HOME` (chown unsafe AND incomplete) or owned by ≥2 distinct non-root users (chown would destroy other users' installs); the reporter delegates to `_npm_global_fix_block` for these npm-root/bin-global cases, so `check` and `install` finally agree.
- **Shared helper `is_home_path`** extracted from `installer.py` into `sccs/doctor/_paths.py` so `detectors.py` can reuse it without creating an import cycle.

### Changed
- **`npm bin -g` label renamed to `npm prefix bin`** (display only — the resolver still uses `npm config get prefix`/bin). npm 9+ removed the `npm bin` subcommand, so a user copying the old label from the doctor table would hit `Unknown command 'bin'`. The component identifier follows (`perm:npm prefix bin`), and the cascade-skip messages now read `depends on perm:npm prefix bin`.

### Added
- **Post-fix `restart your shell` hint** appended to every branch of `_npm_global_fix_block`. After `npm config set prefix ~/.npm-global` + PATH export, the *running* doctor process still sees the old `$PATH`, so the next `sccs doctor check` would mislead the user into thinking the fix didn't take. The hint explains the shell-reload requirement once, visible from both the reporter and installer paths.

### Tests
- 6 new tests in `tests/test_doctor.py`: `TestFixCommandSafetyGuards` (None for system/multi-user, present for in-$HOME single-user), `TestReporterSafeFixForSystemPrefix` (no `sudo chown 1000:1000 /usr/bin`, Option A appears, reload hint present, multi-user branch safe), `TestNpmBinLabelRename` (defaults expose new label).
- 3 existing tests updated to monkeypatch `Path.home()` so chown-branch assertions still fire under the new home-only guard.

## Version 2.33.1 (26.05.2026)

### Changed
- **`bandit` is now wired into CI and pre-commit** instead of being a declared-but-unused dev dependency. The lint job runs `bandit -r sccs/ -ll` (medium+ severity gate) and a local pre-commit hook mirrors it. The scan is clean: 0 medium/high findings — the 9 low results are the deliberate, list-arg `subprocess` calls that the runtime/git allowlist validators already guard.
- **Coverage floor unified to a single source of truth.** CI no longer passes `--cov-fail-under`; the threshold lives solely in `pyproject.toml [tool.coverage.report]`, raised `66 → 70` (actual coverage ~72%, floor a notch below to absorb Linux-CI vs macOS variance). Target remains 80%.

### Fixed
- **Editor merge buffer hardened (security audit LOW).** `output/merge.py` now `chmod 0600`s the `NamedTemporaryFile` conflict-edit buffer explicitly. POSIX defaults to `0600` already, but the buffer can hold MCP tokens or shell config, so the guarantee is made explicit and platform-independent — matching the `atomic_write` hardening from 2.32.2.

## Version 2.33.0 (26.05.2026)

### Added
- **`PluginSpec.allowlist_only` field.** Marks a plugin entry as *foreign-drift allowlist only*: it keeps an installed plugin off `optimize --strict`'s removal list **without** being install-/marketplace-checked. Such entries produce no MISSING/OUTDATED row and no marketplace-registration block, but still count toward foreign-drift coverage via `effective_plugins()`. New resolver `DoctorConfig.checkable_plugins()` returns the install-check list (excludes `allowlist_only`); `effective_plugins()` is unchanged (full list, used only for foreign-drift detection).

### Fixed
- **`check` → `update` → `check` now converges for managed-but-not-installed plugins.** Root cause: the v2.32.0 entries added purely as a foreign-drift allowlist (the 5 LSP plugins `gopls-lsp`/`pyright-lsp`/`rust-analyzer-lsp`/`swift-lsp`/`typescript-lsp` and the second `frontend-design@claude-code-plugins` copy) were install-checked like real targets. Three non-converging symptoms, all fixed by tagging them `allowlist_only=True`:
  - **LSP plugins showed red MISSING** on hosts that don't use them (e.g. a headless Linux server running only Claude). They now produce no row.
  - **`frontend-design@claude-code-plugins` showed perpetual OUTDATED.** It is detected as `alternative` (installed under `claude-plugins-official`) and could never converge (the plugin never appears under `claude-code-plugins`, whose marketplace can't be registered). It now produces no row.
  - **`claude-code-plugins` marketplace emitted an unresolvable manual block** ("not registered — no marketplace_source"; `claude plugin marketplace add claude-code-plugins` fails with "Invalid marketplace source format"). The marketplace is no longer derived, because `ClaudeMarketplaceDetector` is now fed `checkable_plugins()` — and the only entry referencing it is `allowlist_only`.
- **`alternative` detection no longer mislabelled as OUTDATED.** A plugin installed under a different marketplace than configured is reported as blue **INFO** "installed via <marketplace>", not yellow OUTDATED. `claude plugin` exposes no update-available signal (`update_available` is always `None`), so OUTDATED nagged forever with no fix path. The `sccs status` inline summary likewise dims the "alt marketplace" counter (informational, not a problem).

### Tests
- 13 new tests in `tests/test_doctor.py`: `TestPluginSpecAllowlistOnly` (default/accept/loader-roundtrip), `TestCheckablePlugins` (filter vs full list; defaults' LSPs + 2nd frontend-design excluded), `TestAllowlistOnlyNotForeign` (regression: installed allowlist_only plugin never flagged foreign), `TestAllowlistOnlyNoMarketplaceBlock` (`claude-code-plugins` absent from marketplace statuses), `TestAlternativeReportedAsInfo` (alternative → INFO, not OUTDATED).

## Version 2.32.2 (26.05.2026)

### Fixed
- **Non-atomic `settings.json` rewrites (security review MEDIUM-2).** Both doctor mutators — the statusline stale-Cellar auto-fix (`_status_line_actions._fix`) and the disallowed-hook sanitiser (`_settings_hook_cleanup_actions`) — wrote the file with a plain `p.write_text(json.dumps(...))`. A crash or disk-full mid-write could leave the user's `settings.json` truncated; recovery from the timestamped `.bak` was manual. Both now route through the existing `sccs.utils.paths.atomic_write` (temp file + `os.replace`), so the rewrite is all-or-nothing. Bonus: `mkstemp` creates the temp file `0600`, so the rewritten `settings.json` — which may hold MCP-server tokens — is no longer left group/world-readable on multi-user hosts.

### Changed
- **`uv.lock` refreshed.** The committed lock still referenced sccs `2.31.0`, stale since the v2.32.x releases; regenerated to pin the current `2.32.2` and present dependency set. (The lock was already tracked — pinning all 41 packages with hashes — so no supply-chain gap existed; this is housekeeping only.)

### Tests
- `TestSettingsHookCleanupAction::test_action_writes_settings_atomically` — regression guard: asserts no `.tmp` leftovers remain after the rewrite and (POSIX only) the file ends up `0600`, preventing a silent revert to `p.write_text()`.

## Version 2.32.1 (25.05.2026)

### Fixed
- **Linux system-npm permission gap (`npm-bin-global` check).** On a system-wide npm install, `npm root -g` is `/usr/lib/node_modules` (lib) but `npm install -g` ALSO symlinks the CLI binary into `<prefix>/bin` (e.g. `/usr/bin`). The doctor only gated installs on the lib dir, so after `sudo chown -R <uid> /usr/lib/node_modules` the permission check passed but `npm install -g @playwright/cli@latest` still died with `EACCES` on the `/usr/bin/playwright-cli` symlink. A new `npm-bin-global` permission check (resolved via `<npm config get prefix>/bin`, simple writability — never recursively scanned or chowned) now gates the npx install on the bin dir too, so the failure is surfaced as a manual block before the install runs instead of as a raw npm crash.
- **Misleading chown advice for system npm prefixes.** The npm-permission manual block offered Option B (`sudo chown` of the global root) even when the prefix was a system directory (`/usr`). Chowning `/usr/lib/node_modules` alone is the trap that caused the incident — it leaves `/usr/bin` root-owned — and chowning `/usr/bin` is dangerous. Option B is now suppressed for any npm dir outside `$HOME` (joining the existing multi-user suppression); only the user-local prefix (`~/.npm-global`, which relocates BOTH lib and bin under home) is recommended, with an explicit system-dir warning. `_npm_root_global_fix_block` → `_npm_global_fix_block` (now also handles the bin dir).
- **CI red on Linux since v2.29.0.** `TestStatusLineAutoFix::test_auto_fix_idempotent_for_cellar` asserted the second detector pass produced zero actions, but the stale-Cellar auto-fix rewrites the command to `/opt/homebrew/bin/node` — which only exists on macOS Homebrew hosts. On Linux CI that path is missing, so the second pass correctly emitted a `missing_binary` manual block, failing the assertion. The test now asserts the idempotency invariant precisely: no auto-fix (in-process `python_callable` action) is re-triggered, tolerating a platform-dependent `missing_binary` block.

### Tests
- 8 new tests in `tests/test_doctor.py` (`TestNpmBinGlobalPermission`): default check present, skipped when npm missing, unwritable → not ok, writable/nonexistent → ok, system-path block recommends user prefix only, failing bin check gates the npx install. Plus `TestNpmRootGlobalPermission::test_system_npm_root_suppresses_chown_option` and a renamed home-relative two-option test. The multi-user tests adopt the `_npm_global_fix_block` name.

## Version 2.32.0 (25.05.2026)

### Added
- **GSD-hook protection (`doctor.protected_hooks`).** Hard guard that the settings.json sanitiser must never strip a protected hook, even when a `disallowed_hooks` pattern would match it — protection wins over removal. Real driver: the v2.31.0 sanitiser was built to fight GSD's settings.json re-injection, but GSD (`get-shit-done-cc`) hooks must be **preserved** — removing them breaks the plugin. `DEFAULT_PROTECTED_HOOKS = ["gsd-"]` (mirrors the `managed.py` `gsd-*` convention) so GSD hooks survive every doctor pass out of the box. `SettingsHookDetector.get_violations(disallowed, *, protected=...)` skips any command containing a protected substring. Override via `doctor.protected_hooks:`; pass `[]` to disable protection entirely.
- **`auto_confirm` on safe maintenance actions.** `sccs doctor update` / `optimize` now run plugin install/update, npx-tool refresh (incl. GSD), marketplace add/update, and bundled-skill / browser post-install steps **without per-action confirm prompts** — installed plugins stay current unattended, replacing GSD's sluggish built-in update. Destructive actions (foreign plugin/MCP `uninstall`, settings.json hook removal, statusline rewrite) keep `auto_confirm=False` and still prompt every time; `--yes` remains the blanket override. New `DoctorAction.auto_confirm` field; `execute_plan` honours `assume_yes or action.auto_confirm`.

### Changed
- **`DEFAULT_CLAUDE_PLUGINS` rewritten to the canonical official-ecosystem allowlist.** Dropped `claude-mem` (superseded by Claude Code's native auto-memory). Added the official language-server plugins (`gopls-lsp`, `pyright-lsp`, `rust-analyzer-lsp`, `swift-lsp`, `typescript-lsp` @claude-plugins-official), `superpowers-developing-for-claude-code@superpowers-marketplace` (source `obra/superpowers-marketplace`), and a second `frontend-design@claude-code-plugins` entry so a locally-disabled copy is not flagged foreign. `optimize --strict` no longer queues these legitimate plugins for removal; `claude-mem` is now correctly flagged as foreign if still installed.

### Tests
- 9 new tests in `tests/test_doctor.py`:
  - `TestSettingsHookDetector` (3): protected hook never reported, protection is selective (non-protected siblings still surface), counter-check without protection.
  - `TestForeignPluginDetection` (2): real-host snapshot flags nothing foreign against defaults; stray `claude-mem` flagged foreign.
  - `TestExecutePlan` (2): `auto_confirm=True` runs without prompting questionary; `auto_confirm=False` still prompts and a declined uninstall is skipped while the auto update runs.
  - `TestDoctorConfigProtectedHooks` (3): default protects `gsd-`, explicit `[]` disables protection, override survives loader merge.
- `_make_status_set` gained an optional `specs=` parameter so plugin-plan tests decouple from the defaults (4 `claude-mem` fixtures migrated to injected synthetic specs).

## Version 2.31.0 (24.05.2026)

### Added
- **Settings.json hook sanitisation after every doctor pass.** Real driver: `npx get-shit-done-cc --claude --global --force-statusline` (one of doctor's bundled npx tools) overwrites `~/.claude/settings.json` on every run, re-injecting hooks the user had explicitly removed in a setup audit — concretely `gsd-read-guard.js`, which a v2.30.0 audit had stripped from the PreToolUse stack. Each `sccs doctor optimize` then silently put it back. The new `doctor.disallowed_hooks:` list takes substring patterns matched against every `hooks[event][i].hooks[j].command` entry; `build_install_plan`, `build_update_plan`, and `build_optimize_plan` queue a final sanitiser action that rewrites settings.json without the offending entries (with timestamped `.bak-YYYYMMDD-HHMMSS` backup). Sanitiser runs LAST so it picks up violations re-injected by upstream actions. Idempotent: a second pass over a clean file emits no action.
- **`SettingsHookDetector`** parses `~/.claude/settings.json` and returns a `SettingsHookViolation` per matching hook entry, carrying the event name (`PreToolUse`/`PostToolUse`/…), matcher string, full command, and which pattern matched. Defensive: missing file, malformed JSON, or absent `hooks` block all return `[]` without raising.
- **`_settings_hook_cleanup_actions`** builds a single `DoctorAction` with a `python_callable` closure (same pattern as v2.29.0's statusline auto-fix). Removal rules: (1) hooks matching any disallowed pattern are deleted, (2) outer entries whose inner `hooks:` list ends up empty are dropped, (3) event keys with no remaining entries are dropped. Eliminates the dead `{matcher: …, hooks: []}` accumulation that would otherwise grow on every run.
- **`DoctorConfig.disallowed_hooks` field** + `effective_disallowed_hooks()` resolver. `DEFAULT_DISALLOWED_HOOKS` is intentionally empty: the bundled distribution makes no judgements about user hook setups. Opt in via `~/.config/sccs/config.yaml`:
  ```yaml
  doctor:
    disallowed_hooks:
      - gsd-read-guard.js
  ```

### Tests
- 15 new tests across 3 classes in `tests/test_doctor.py`:
  - `TestSettingsHookDetector` (7): finds match in nested hook, finds match in multi-hook entry, empty disallowed → no violations, missing settings file → no violations, malformed JSON → no violations, no `hooks` block → no violations, multiple patterns matching same command report only once.
  - `TestSettingsHookCleanupAction` (6): no violations → no action, action removes matching hook entry and keeps siblings, action drops empty outer entry, action drops empty event key, action writes timestamped backup, action is idempotent.
  - `TestDoctorConfigDisallowedHooks` (2): override survives `_merge_with_defaults`, default is empty.

## Version 2.30.0 (24.05.2026)

### Added
- **`sccs doctor optimize` sub-command** — one-shot optimisation pass that combines `build_install_plan` + `build_update_plan` (install missing, update everything installed) AND surfaces drift between the user's spec and the locally installed reality. Without `--strict`, drift appears as a manual_block warning per category (`foreign-plugins:summary`, `foreign-mcp:summary`) — visible but not removed. With `--strict`, every foreign plugin gets a `claude plugin uninstall <name>@<marketplace> [--scope <scope>]` action and every foreign MCP server gets `claude mcp remove <name> -s user`, each behind its own confirm prompt (default: No). Real driver: a setup audit on macOS removed `claude-mem` from `doctor.plugins:`, but the plugin stayed physically installed on Linux until the user manually ran `claude plugin uninstall`. Without `--strict`, repeated `doctor check`/`update` ignored the entry; the new optimize command makes drift visible in the install/update pipeline and offers explicit removal with `--strict`.
- **Foreign-plugin detector** (`ClaudePluginDetector.get_foreign_plugins`, `ForeignPluginStatus`). Parses every `❯ <name>@<marketplace>` header in `claude plugin list` and filters against the user's spec. Marketplace-aware: a spec entry for `frontend-design@A` does NOT excuse an installed `frontend-design@B` — the user wanted exactly @A. A bare spec entry (marketplace=None) excuses every installed copy under any source. Scope is extracted from the metadata block so uninstall actions forward the correct `--scope` value (mirrors the v2.21.0 fix for `claude plugin update`).
- **MCP-server detector + spec** (`MCPServerDetector`, `MCPServerSpec`, `MCPServerStatus`, `ForeignMCPServerStatus`). Parses `claude mcp list` (split on `: ` to preserve server names containing colons, e.g. `plugin:context-mode:context-mode`). Two filter layers: (1) exact name match against `doctor.mcp_servers:`, (2) fnmatch glob against `doctor.ignored_mcp_patterns:`. Default ignored patterns (`DEFAULT_IGNORED_MCP_PATTERNS`) skip `claude.ai *` OAuth services (Gmail/Calendar/Drive) and `plugin:*` plugin-internal MCPs out of the box so first-run doctor optimize on a fresh install does not flag system-supplied entries as foreign.
- **`doctor.mcp_servers` / `extra_mcp_servers` / `ignored_mcp_patterns`** fields on `DoctorConfig`, each with its own `effective_*()` resolver — same override/extras pattern as `doctor.plugins`. `DEFAULT_MCP_SERVERS` is intentionally empty: users with custom MCP integrations they want to own add them here.
- **`sccs_config` sync category** in `DEFAULT_CONFIG` (well, the user's own config — bundled defaults remain unchanged). Bidirectional sync of `~/.config/sccs/config.yaml` itself across hosts, with `conflict_resolution: local` so the most recently edited host wins. Cross-platform: `repository.path` is `~`-relative, resolved by `Path.home()` via `expand_path`, identical on macOS/Linux/Windows when the repo lives under `~/gitbase/sccs-sync` on each box. Closes the gap where doctor overrides made on one machine did not propagate.

### Tests
- 18 new tests across 5 classes in `tests/test_doctor.py`:
  - `TestForeignPluginDetection` (6): empty-spec-is-all-foreign, exact-match excludes, marketplace mismatch still counts, bare-spec covers all marketplaces, scope extraction, empty output → no foreign.
  - `TestMCPServerDetector` (8): colons in names survive (regression for the `plugin:context-mode:context-mode` parser), spaces in names survive (regression for `claude.ai Gmail`), banner skipping, default-ignored-patterns work, spec-match excludes, empty-ignored-patterns flags everything, spec status marks missing, empty output.
  - `TestMCPServerSpecValidation` (3): unsafe characters rejected, colons + dots + spaces accepted, scope validation.
  - `TestBuildOptimizePlan` (5): non-strict emits warning-block for foreign plugins, strict queues uninstall with `--scope`, strict queues `claude mcp remove`, non-strict emits warning-block for foreign MCP servers, empty state → empty plan.
  - `TestDoctorConfigLoaderPreservesMCPOverride` (1): regression cover for `doctor.mcp_servers` and `doctor.ignored_mcp_patterns` surviving `_merge_with_defaults` — same bug class as v2.29.1's `doctor.plugins`.

## Version 2.29.1 (24.05.2026)

### Fixed
- **Config loader silently dropped user-supplied `doctor:` overrides.** `_merge_with_defaults()` in `sccs/config/loader.py` had merge branches for every top-level `SccsConfig` field except `doctor`. A user that added a `doctor:` block to `~/.config/sccs/config.yaml` (e.g. to remove a plugin from `DEFAULT_CLAUDE_PLUGINS` by setting `doctor.plugins:` to a smaller list) saw the entire block disappear before Pydantic validation, so every DoctorConfig field fell back to its bundled default. Real-world impact: after a setup audit removed `claude-mem` from a user's Claude Code install, the user's `doctor.plugins:` override could not actually prevent `sccs doctor install/update` from reinstalling it. The loader now passes the user's `doctor:` block through verbatim — `DoctorConfig` already handles partial overrides via its own field defaults, so no merge gymnastics are needed at the loader layer.

### Tests
- `test_load_config_preserves_doctor_override` in `tests/test_config.py::TestConfigLoader` writes a sample config with `doctor.min_node_major` and `doctor.plugins` set, reloads it, and asserts both values survive the loader pipeline.

## Version 2.29.0 (11.05.2026)

### Added
- **Doctor statusline detector** (`StatusLineDetector`, `StatusLineCheckSpec`, `StatusLineStatus`) inspects `~/.claude/settings.json` → `statusLine.command` and classifies it into seven states: `ok`, `missing`, `missing_binary`, `missing_script`, `stale_cellar`, `opaque`, `no_settings_file`. Real-world incident (2026-05-11): the user's settings.json contained a hardcoded `/opt/homebrew/Cellar/node/25.9.0_3/bin/node`; Homebrew bumped Node to 26.0.0 and pruned the old Cellar directory, so the statusline silently disappeared. `sccs doctor check` was all-green because nothing inspected settings.json. The new detector catches the stale Cellar path AND surfaces missing binaries/scripts.
- **Auto-fix for stale Apple-Silicon Homebrew Cellar paths.** `_status_line_actions` emits a `python_callable` action that, after confirmation, rewrites `/opt/homebrew/Cellar/<pkg>/<version>/bin/<binary>` segments to the stable `/opt/homebrew/bin/<binary>` symlink Homebrew maintains across upgrades. The fix writes a timestamped backup (`settings.json.bak-YYYYMMDD-HHMMSS`) before any mutation; subsequent doctor runs return zero auto-fix actions because the Cellar marker is gone (idempotent at the action layer).
- **`required_mode` field** on `StatusLineCheckSpec` with values `always`, `never`, and `smart` (default). `smart` mode treats a missing `statusLine` key as a FAIL only when (1) the `claude_statusline` sync category is enabled in `~/.config/sccs/config.yaml` AND (2) at least one statusline script exists in `~/.claude/` (`statusline.sh`/`.py`/`.ps1`/`.fish` or `hooks/gsd-statusline.js`). Users who never asked for a statusline are not nagged; users who clearly configured one but lost the key get a clear FAIL.
- **`opaque` state** for command shapes the detector cannot safely verify — pipelines (`|`), conditional chains (`&&`/`||`), command substitution (`$(...)`/backticks), or env-var prefixes (`FOO=bar node ...`). Reporter renders these as a blue `INFO` row with detail "custom command shape, not checked"; no false positives for power-users with intentional setups.
- **Reporter additions:** new `statusline: <identifier>` row in `sccs doctor check`, plus `STALE` (yellow) and `INFO` (blue) status icons. `has_problems()` flips on statusline issues so the doctor exit code is 1 when an actionable issue exists. `render_inline_summary()` (used by `sccs status`) prints `statusline issues: N` when present.

### Tests
- 13 new tests in `tests/test_doctor.py` across 2 classes:
  - `TestStatusLineDetector` (10): `no_settings_file`, `missing` key with `required=never|always`, `smart`-mode requires both sync-category enablement AND script presence, `ok` for binary-on-PATH plus existing script, `missing_binary` for unresolvable token, `missing_script` for absent script path, `stale_cellar` for non-existent Cellar version directory, `opaque` for pipelines and env-prefix commands.
  - `TestStatusLineAutoFix` (3): auto-fix rewrites the Cellar path to `/opt/homebrew/bin/X` and preserves every other settings.json key; auto-fix is idempotent (no second action emitted after the first run); `missing_binary` emits a print-only manual block (no `python_callable`) because the right fix depends on user intent.

## Version 2.28.1 (06.05.2026)

### Added
- **Marketplace-existence detector** (`ClaudeMarketplaceDetector`) reads `claude plugin marketplace list` and reports per-marketplace `registered`/`missing` status. Real failure mode (Debian 13 multi-user terminal server, 2026-05-06): `claude-plugins-official` was not registered locally, so every `claude plugin install <name>@claude-plugins-official` died with "Plugin not found in marketplace …" — a different mode from the stale-cache one v2.28.0 covers via `marketplace update`. The auto-`update` path cannot help here: you cannot UPDATE a marketplace that does not exist; you must ADD it.
- **`_marketplace_missing_actions`** emits a `manual_block` (`blocks_downstream=True`, component `plugin-marketplace:<name>:exists`) per missing marketplace with a copy-paste `claude plugin marketplace add <owner/repo>` snippet — using the `marketplace_source` from the user's `PluginSpec` when available, or otherwise pointing the user at `~/.config/sccs/config.yaml` to add one. Plugin installs whose marketplace is missing now list this component as a dependency, so the cascade engine reports them as `⊘ skipped` instead of queuing three guaranteed-failed `claude plugin install` subprocesses (the exact symptom from the Debian session).
- **Multi-user-aware `_npm_root_global_fix_block`.** Real failure mode: `/usr/local/lib/node_modules/` on a multi-user terminal server held packages from several non-root users (bun, @fission-ai). Recommending `sudo chown -R <me>:<me>` would have silently destroyed those installs. `PermissionStatus` now collects every distinct foreign uid during the recursive scan; `is_multi_user` is True when ≥2 distinct non-root uids own the tree. The fix-block then suppresses Option B (`sudo chown`) entirely, lists the offending uids, and shows Option A (user-local prefix) as the only safe path with a "DO NOT use chown" warning.
- **Reporter:** new `marketplace: <name>` rows in `sccs doctor check` between Claude CLI and plugin rows; `has_problems()` flips on missing marketplaces so the doctor exit code is 1.

### Tests
- 14 new tests in `tests/test_doctor.py` across 3 classes:
  - `TestClaudeMarketplaceDetector` (4): registered marketplace, missing marketplace, claude-CLI-missing skip, no-marketplace-in-specs returns empty.
  - `TestPluginInstallSkipsWhenMarketplaceMissing` (5): install gains `plugin-marketplace:<name>:exists` dependency when missing; install has no extra dep when registered (and the marketplace-update step IS queued); manual block surfaces `marketplace add <suggestion>` when source is known and the config-file pointer otherwise; end-to-end install plan with three plugins on a missing marketplace yields three skipped rows + one printed manual block + zero subprocess calls.
  - `TestMultiUserPermission` (5): `is_multi_user` True for ≥2 non-root uids; root-only and single-foreign-user are NOT multi-user; multi-user block suppresses Option B (no runnable `chown` command remains) and lists the foreign uids; single-admin block keeps both options unchanged.

## Version 2.28.0 (06.05.2026)

### Added
- **Doctor cascade-resilience: failed and blocked components now fence off downstream actions.** Real-world Debian 13 incident: `sccs doctor install --yes` printed a manual block for the `npm root -g` permission issue, then ran the npm install anyway, which died with `EACCES`, after which `playwright-cli install-browser chromium`/`firefox` and the bundled-skill copy each failed with their own redundant errors — five identical-root-cause failures stacked on top of one another. v2.28.0 turns that pile into one `[manual]` block plus four quiet `⊘ skipped` rows, each citing the blocking component (`depends on perm:npm root -g` / `depends on npx:playwright-cli`) so users can trace cause without reading subprocess output.
- **`DoctorAction` gains three cascade-engine fields:** `blocks_downstream` marks manual blocks that should fence off subsequent actions citing the same `component`; `depends_on_components` lists components whose failure or block turns this action into a `skipped` outcome; `soft_fail` downgrades `DoctorError` to a yellow `warned` row so opportunistic steps (marketplace refreshes) cannot fail the whole pass.
- **Auto-marketplace-update before plugin installs.** Real failure mode: `claude plugin install skill-creator@claude-plugins-official` died with `Plugin not found in marketplace` because the local marketplace cache was stale; the CLI's own remediation hint is `try claude plugin marketplace update claude-plugins-official`. v2.28.0 queues exactly that step (deduplicated per marketplace) before the first install of any plugin spec that has a `marketplace` but no explicit `marketplace_source`. The update is `soft_fail=True`: a network blip warns but does not block the install retry.
- **New `PathPrefixCheckSpec` + `PathPrefixDetector`** verify that `<npm config get prefix>/bin` is on `$PATH`. Triggered by the Debian 13 follow-up: `npm config set prefix ~/.npm-global` fixed the EACCES block, but `~/.npm-global/bin` wasn't on `$PATH` for the current shell — so `npm install -g @playwright/cli` succeeded yet every `playwright-cli install-browser …` died with `Command not found`. The detector emits a manual block with bash/zsh/fish snippets and a "start a new shell, then re-run" instruction; the block is `blocks_downstream=True` so post-install browser fetches and the bundled-skill sync are reported as `skipped`, not failed.
- **`_diagnose_hint()` adds one-line guidance** to common stderr signatures: stale-marketplace → "marketplace update is queued automatically in v2.28.0", `EACCES on node_modules` → "see the manual block above, pick Option A or B", `command not found / spawn ENOENT` → "confirm `$(npm config get prefix)/bin` is in `$PATH` and reload your shell".
- **Reporter:** new `path: npm-prefix-bin` row in `sccs doctor check`; new yellow `Warnings:` bucket in `sccs doctor install` output for soft-failed steps; skipped rows now render as `⊘ <label> — depends on <component>` so the cascade chain is visible at a glance.

### Tests
- 17 new tests in `tests/test_doctor.py` across 6 classes:
  - `TestCascadeSkip` (2): dependency failure cascades cleanly into `skipped`; success allows downstream to run normally.
  - `TestManualBlockBlocksDownstream` (2): `blocks_downstream=True` fences `--yes` flow; legacy `blocks_downstream=False` does not break existing call-sites.
  - `TestNpxInstallCascade` (2): `_npx_install_actions` wires post-install + bundled-skill to depend on the install component; failed install yields one failure + N skipped (no spurious "command not found").
  - `TestMarketplaceUpdateBeforePluginInstall` (3): one update step per marketplace dedup'd; explicit `marketplace_source` skips auto-update; soft-fail update with successful install renders as `warned` + `executed`.
  - `TestNpmPrefixInPathDetection` (4): in-PATH OK, missing-from-PATH not-OK, npm-missing skip, end-to-end install plan renders manual block + skips post-install fetches.
  - `TestDiagnoseHint` (4): three known signatures map to actionable hints; unknown errors return `None`.

## Version 2.27.1 (05.05.2026)

### Fixed
- **Manual block for `npm-root-global` permission issues now pre-creates `~/.npm-global/lib` and `~/.npm-global/bin`.** Real-world Debian 13 follow-up: after `npm config set prefix ~/.npm-global` (the recommended Option A from v2.27.0) the next `npx -y get-shit-done-cc …` died with `ENOENT: lstat '/home/user/.npm-global/lib'` because npx lstats the directory *before* any `npm install -g` would have created it. Pre-creating both subdirs in the manual block eliminates the stumbling block on a fresh prefix relocation.

## Version 2.27.0 (05.05.2026)

### Added
- **`sccs doctor` now detects an unwritable `npm root -g` directory and surfaces a two-option fix block before the npm install action runs.** Real-world Debian 13 incident: a system-wide Node.js install puts the global root at `/usr/lib/node_modules/` (root-owned), so `npm install -g @playwright/cli@latest` dies with `EACCES: permission denied, mkdir '/usr/lib/node_modules/@playwright'`. The follow-up actions (`install-browser chromium`, `install-browser firefox`, bundled-skill copy from the same root) all fail downstream. Doctor now catches the bad permission *before* npm gets called.
- **New `PermissionCheckSpec.path_kind` field** with values `"literal"` (default, existing behaviour) and `"npm-root-global"` (resolved at check-time via `npm root -g`). Default permission checks gain a fourth entry that uses the new kind.
- **Two-option manual block in `_permission_actions`** for `npm-root-global` issues:
  - **Option A (recommended):** user-local prefix — `mkdir -p ~/.npm-global; npm config set prefix ~/.npm-global` plus PATH snippets for both bash/zsh and fish. No sudo, survives `apt install nodejs` cleanly.
  - **Option B (alternative):** `sudo chown -R UID:GID /usr/lib/node_modules` — quicker but reverts on system upgrades.
- **`_resolve_npm_root_global()`** helper (`sccs/doctor/detectors.py`) reuses the existing `runner._run` machinery (timeout 15s, stdin=DEVNULL hardening from v2.22.1, no shell). Returns `None` when npm is missing → detector emits a `skipped_reason` instead of crashing.
- **Reporter:** the new check shows up as a regular `perm: npm root -g` row in `sccs doctor check`, identical UX to the existing `~/.npm` / `~/.claude` / `~/.config/sccs` rows.

### Tests
- 8 new tests in `tests/test_doctor.py` across 2 classes: `TestNpmRootGlobalPermission` (5: default presence, npm-missing skip, user-writable OK, root-owned manual block with both options, regression guard for literal paths) and `TestResolveNpmRootGlobal` (3: missing npm, happy path, empty stdout).

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
