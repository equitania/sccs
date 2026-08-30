# AGENTS.md

Guidance for the Codex CLI when working in this repository.

> **Read this first.** "Claude" is this project's *subject matter*, not a
> stand-in for whichever agent is reading. SCCS synchronizes **Claude Code**
> files — `~/.claude/skills`, `~/.claude/settings.json`, `~/.claude/hooks` — and
> exports some of them to other agent CLIs, Codex among them. Renaming Claude to
> Codex anywhere in this repo breaks the meaning of the code. A previous
> machine-translated version of this file did exactly that and claimed SCCS
> merged `~/.Codex/settings.json`, which is not a path that exists.

## Project overview

**sccs** (SkillsCommandsConfigsSync) is a YAML-configured bidirectional
synchronization tool for Claude Code artefacts and optional shell
configurations, distributed on PyPI.

**Version**: 2.60.0

Two halves worth separating in your head:

- **Sync** (bidirectional, stateful): categories defined in `config.yaml` move
  files between `~/.claude/...` and a Git repository, with conflict detection
  and a state file recording content hashes.
- **Integrations and converters** (one-way, stateless except where noted):
  export Claude artefacts to Antigravity, Claude Desktop, OpenCode, Pi and
  Codex; convert fish config to PowerShell and zsh.

## Repository layout

```
sccs/
├── cli.py                # Click command groups — the largest file
├── config/               # Pydantic schema, YAML loader, defaults, migration
├── sync/                 # SyncItem, actions, state, category handler, engine
├── doctor/               # Plugin/npx health checks, profiles, statusline, scope patch
├── transfer/             # ZIP export/import (zip-slip and symlink rejection)
├── integrations/         # Antigravity, Claude Desktop, OpenCode, Pi, Codex
├── convert/              # fish→PowerShell, fish→zsh, Claude→Codex (agents, hooks)
├── capacity/             # Plan-quota probes and routing advice (v2.60.0)
├── output/               # Rich console, diff display, JSON emitters
├── git/                  # Validated git operations, divergence resolver
└── utils/                # atomic_write, hashing, logging, platform helpers

docs/usage/               # User-facing guides, German and English
tests/                    # 25 files; test_doctor.py and test_capacity.py are largest
```

## Commands

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

pytest -q                       # full suite, quiet (it is large)
pytest tests/test_capacity.py   # single file
ruff check sccs/ tests/
ruff format sccs/ tests/
mypy sccs/
```

Use **UV**, never bare `pip`. `pyproject.toml` is the single source of truth for
dependencies — do not create a `requirements.txt`.

## Things that will bite you

**Tests run on Linux in CI.** No macOS paths, no assumption that any agent CLI
exists on the machine. Every probe and detector is exercised through injected
fakes for exactly this reason. Assertions against CLI output must strip ANSI —
CI colorizes, a local pipe does not.

**The user's shell is fish, everywhere.** Any snippet a human is meant to paste
must be fish syntax: `set VAR value`, not `VAR=value`; `set -x` for exports; no
heredocs, no here-strings. Scripts with a `#!/usr/bin/env bash` shebang are
exempt — the rule is about who types the line.

**Version bumps touch four files.** `pyproject.toml`, `sccs/__init__.py`, the
`**Version**` line in `CLAUDE.md` and this file. Then run `uv lock`, or the lock
file goes stale — a recurring miss. Add a `RELEASE_NOTES.md` section with the
date taken from the environment, never copied from a document.

**Commit prefixes** are `[ADD]`, `[CHG]`, `[FIX]`. Never commit or push unless
asked.

**UTF-8 throughout.** German umlauts and typographic quotes must survive; in
generated German documents quotation marks are the proper pair „…“ — an ASCII
`"` as the closing half breaks the Typst PDF export.

## Subsystem notes that are not obvious from the code

**Doctor-managed items are excluded from sync.** `gsd-*` skills and
`playwright-cli` are installed and updated by `sccs doctor`, so the sync engine,
the ZIP exporter and the importer all filter them out. Reintroducing them into a
selection list would let a stale archive overwrite a live install.

**The Codex hooks export tracks ownership rather than owning the file.**
`~/.codex/hooks.json` is hand-editable, so every entry SCCS writes is keyed on
`(event, matcher, command)` in `~/.config/sccs/.codex_hooks_state.yaml`, and
only keys in that state are ever touched. Serialization is byte-stable on
purpose: Codex hashes each definition for its trust record, so incidental key
reordering would drag the user back through `/hooks` on every export. The
command is deliberately **not** part of `export-all` — hooks execute code on
every matching tool call.

**Two frontmatter parsers exist and must stay different.**
`parse_frontmatter()` returns an unparsable block as part of the body, which is
what `doctor/scope_patch.py` needs to round-trip a `gsd-*` prompt safely.
`parse_frontmatter_ex()` strips it and names the error, which is what the
converters need so they do not emit two stacked frontmatter blocks. The
triggering case is ordinary: `argument-hint: [a] [b...]` is documented Claude
Code syntax and invalid YAML.

**Codex has no model-discovery command**, so `DEFAULT_CODEX_MODEL_MAP` is
static. Re-check it against `~/.codex/models_cache.json` or `codex debug
models`. Policy, enforced by a test: all three Claude tier aliases map to one
current top model family and differ only in `model_reasoning_effort` — never map
a tier onto an older generation's mini model.

**`sccs capacity` reports provenance, not just numbers.** Codex quota comes from
a session rollout file (`session-cache`, possibly stale), Antigravity from a
live `agy -p "/usage"` call, Claude Code is `assumed` because it caches nothing
on disk. `unknown` is deliberately distinct from `tight`: missing data is not
evidence of exhaustion. The routing rule most easily got wrong lives in code,
not in a prompt — when the Gemini pool is tight the fallback reviewer is
**Codex, never Antigravity switched to a Claude model**, which would make
Anthropic review its own work.

## Configuration and state

Config lives at `~/.config/sccs/config.yaml` (override with `SCCS_CONFIG`).
State files sit beside it: `.sync_state.yaml`, `.doctor_state.yaml`,
`.profile_state.yaml`, `.codex_hooks_state.yaml`.

Core commands accept `--json` for GUI and automation consumption — emitted as a
single line via `click.echo`, never through the ANSI-forcing Rich console. See
`sccs/output/json_emit.py`.

## Further reading

- `CLAUDE.md` — the same ground with the full per-release feature archaeology
- `RELEASE_NOTES.md` — why each change was made, in prose
- `docs/usage/` — user-facing guides, including `capacity.md` and `codex.md`
