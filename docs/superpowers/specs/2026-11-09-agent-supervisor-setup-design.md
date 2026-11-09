# Agent supervisor setup: configure the multi-CLI agents from sccs

**Date:** 2026-11-09
**Target release:** 2.73.0
**Status:** builder check done, awaiting the Captain's approval

## Intent

The Captain works with Claude Code as the **supervisor**: one interactive Claude
session (usually inside a Herdr window) that delegates reviews, second opinions and
bounded analyses to other AI CLIs through thin **wrapper subagents** in
`~/.claude/agents/`, and then verifies every returned finding against the code
itself. As of 09.11.2026 this setup exists and works, but it was built by hand:

- `antigravity-worker` → Antigravity CLI (`agy -p`), always a Gemini model,
  read-only via `--mode plan` plus a command allowlist, material inline.
- `opencode-worker` → OpenCode (`opencode run --agent claude-ro`), default Kimi via
  OpenRouter, read-only via an inline agent definition in `OPENCODE_CONFIG_CONTENT`.
- Codex → the foreign-maintained plugin `codex@openai-codex` (`codex:codex-rescue`,
  `/codex:review`), read-only directly via `codex exec -s read-only`.

Changing a model, adding a wrapper for another tool, checking whether every tool is
installed and logged in, or keeping the wrappers out of the `sync-all` export all mean
editing Markdown, JSON and YAML by hand and remembering a list of traps. The goal is
to make that **comfortable and safe inside sccs**, for shell-literate AI experts.

**Decided by the Captain:**

- It lives in **sccs**. Herdr is only the window the work later runs in; no Herdr mod,
  no configuration in Herdr.
- It is **configuration only**. It never starts, dispatches or monitors agent work.
- **No CAO.** The supervisor pattern is Claude Code plus wrapper subagents.
- Tools in scope: **Claude Code, Codex, OpenCode, Pi, Antigravity CLI**.
- "Agents" means the interplay of all defined agents: which tool, which model,
  read-only or not, and how the supervisor uses them.
- UI: a **full-screen terminal UI**, layout **variant C** (see below).
- Two pieces of documentation are part of the deliverable: **how to use it at work**
  (start Claude, task it to work with the agents) and **the approach** (why it is
  built this way).
- The two existing hand-written wrappers are **adopted once** (see "Adoption").
- Wrapper templates for **Antigravity, OpenCode and Codex**. Pi is shown as a tool
  only, without a template, until it is installed and tested.
- **Textual is a regular dependency**, always installed.

## Goals

1. Show the five tools at a glance: installed or not, version, login state, default
   model, and where its config lives.
2. Show Claude Code's supervisor role: session model, agent folder, and which agents
   it can delegate to.
3. Show every delegating agent with its tool, model and mode (read-only / writes), and
   whether its tool is usable right now.
4. Change the model of an sccs-managed wrapper by picking from the tool's real model
   list.
5. Create a new wrapper for a supported tool from a bundled template (read-only by
   default).
6. Keep wrappers out of the `sync-all` export (`opencode.exclude`, `pi.exclude`,
   `codex.exclude`) automatically, and show that state.
7. Everything the TUI does is also available as plain CLI commands with `--json`
   (Core-First, like `status`, `doctor check`).
8. The usage guide and the approach document, reachable from the TUI (`?`).

## Non-goals

- Starting, dispatching, scheduling or watching agent work. That happens in Claude
  Code, inside Herdr.
- Installing or updating the CLIs. That is `sccs doctor`; the TUI points there.
- Logging in. Logins are interactive in each tool; the TUI shows the command to run.
- Editing foreign-maintained agents or plugins (`codex:*` plugin agents, `gsd-*`,
  `superpowers:` …). They are shown read-only, marked as plugin.
- CAO profiles and Herdr templates.
- Cost tracking. A wrapper that costs credit is marked, nothing more.

## Anti-goals (a failure even if it technically works)

- A wrapper generated as write-capable without the user explicitly choosing that.
- A wrapper whose generated shell command can be altered through a model name or any
  other field (the Haiku wrapper runs that command verbatim via Bash).
- `antigravity-worker` (or any Gemini wrapper) ending up on a `claude-*` or `gpt-*`
  model — the point is a second model family.
- Overwriting a wrapper the user edited by hand without asking.
- Touching the nono-managed block in `~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md`.
- Showing secrets: auth files are read for presence only, never displayed.
- Inventing a value it cannot determine (same rule as `sccs capacity`: `unknown` is a
  valid, displayed state).

## Main screen (variant C, chosen by the Captain)

One screen: the supervisor in the header line, one row per delegating agent below,
each row carrying the state of its tool, so a tool problem shows up at the agent it
breaks. Tools without an agent appear as a dimmed `(frei)` row. Mockup:

```
 sccs agents   Supervisor: Claude Code ✓ opus · ~/.claude/agents
─────────────────────────────────────────────────────────────────────
 Agent               Werkzeug          Modell                  Modus
 antigravity-worker  agy 1.5.3 ✓       gemini-4-argon-high     lesen
 opencode-worker     opencode 1.19 ✓   ~moonshotai/kimi-latest lesen  €
 codex:codex-rescue  codex 0.167 ✓     gpt-6.1-terra           Plugin
 (frei)              pi fehlt          –                       –
─────────────────────────────────────────────────────────────────────
 Read-only über --mode plan + Allowlist · Material inline · Export: aus
 ⏎ Bearbeiten  m Modell  n Neuer Agent  w Werkzeuge  ? Anleitung  q Ende
```

- The footer line explains the selected row (how read-only is enforced, export state).
- `w` opens a tools view (version, login, default model, config path, install hint
  pointing at `sccs doctor`).
- `?` opens the usage guide and the approach document inside the TUI.
- *My call:* UI text is **English**, like all sccs CLI output today; the mockup is
  German only because the conversation was. The usage guide is bilingual (below).

## Facts the builder needs (measured on the Captain's Mac, 09.11.2026)

| Tool | Binary / version | Models from | Notes |
|---|---|---|---|
| Claude Code | `claude` | aliases `haiku`/`sonnet`/`opus`/`fable`; session default in `~/.claude/settings.json` `"model"` (currently `opus`) | Supervisor; agents in `~/.claude/agents/*.md` (frontmatter `name`, `description`, `tools`, `model`) |
| Codex | `codex` 0.167.0 | `~/.codex/config.toml` `model` (currently `gpt-6.1-terra`) | No model-list command known; read-only via `codex exec -s read-only --ephemeral`; plugin agents are foreign |
| OpenCode | `opencode` 1.19.5 | `opencode models` (`provider/model`, OpenRouter 362 + 11 free `opencode/*`) | Free `opencode/*` models: unclear data policy → warn |
| Antigravity | `agy` 1.5.3 | `agy models </dev/null` | Gemini-only rule for wrappers; headless denies all commands outside the allowlist |
| Pi | **not on PATH** | `~/.pi/agent/models.json` exists | `~/.pi/agent/bin` holds only `fd`; show as "nicht installiert", config present |

All model listings are subprocesses → through `sccs/doctor/runner.py`, with
`stdin=DEVNULL` and a timeout; results cached for the TUI session.

## How it is built (decided parts and my calls)

**Core module, then CLI, then TUI.** A new package (my call: `sccs/supervisor/`)
holds detection and the wrapper model; the CLI exposes it; the TUI only calls the
core. Proposed commands (my call on naming — see open questions):

```
sccs agents                 # opens the TUI
sccs agents list [--json]   # tools + agents as in the main screen
sccs agents tools [--json]  # tool detail
sccs agents models <tool> [--json]
sccs agents set-model <agent> <model>
sccs agents new <tool> <name> [--model M]
```

**Wrapper templates.** Three bundled templates: `agy` and `opencode` are the two
existing wrappers turned into templates (proven 09.11.2026); `codex` is new and
follows the same shape with `codex exec -s read-only --ephemeral -o <file> "<prompt>"`
(proven as a direct call on 09.11.2026, not yet as a wrapper — the builder tests it
end to end once). The Codex wrapper stands next to the foreign `codex:codex-rescue`
plugin agent, which stays read-only in the list. No Pi template: `sccs agents new pi`
fails with a hint that Pi has no tested template yet.

A managed file carries a marker in its frontmatter (Claude Code ignores unknown
fields), *my call on the shape:*

```yaml
sccs:
  managed: true
  template: agy            # agy | opencode | codex | adopted
  template_version: 1
  hash: <sha256>
```

*My call on the hash:* sha256 over the whole file body (below the frontmatter) with
the CLI model token replaced by a fixed placeholder. So a model change never looks
like a hand edit, and any other edit does.

**Which model is edited (my call).** "Model" in the UI is the **CLI model** inside
the Bash command (`--model gemini-…`, `-m openrouter/…`, Codex `-m …`). The wrapper's
own frontmatter `model: haiku` is fixed and not offered: the wrapper only forwards.
`set-model` is a **surgical edit** of the default model token in the command line,
then the hash is recomputed — never a re-render, so description and prompt text
survive. The Antigravity template keeps its second, short-question variant
(`gemini-3.8-flash-medium` with shorter timeouts) as prose; only the default model is
editable.

**Adoption (decided by the Captain).** Hand-written agents whose body matches a
template's command shape (`agy -p … --mode plan --settings "$AGY_RO"`,
`opencode run --agent claude-ro …`) are offered for adoption once: sccs asks, then
writes the marker with `template: adopted` and the hash of the current body, and adds
the name to the excludes if missing. The body is left as it is. After that, model
changes work as above. Agents that match no template shape are listed and never
written.

**Re-render.** Only on explicit request for a file created by `new`; if the hash no
longer matches, sccs asks before overwriting. Adopted files are never re-rendered.

**Model names are validated** before they are written: conservative pattern
`^[A-Za-z0-9._:/~][A-Za-z0-9._:/~-]*$` (no leading `-`, so it cannot be read as an
option; no shell metacharacters). The Gemini template additionally rejects anything
not starting with `gemini-`. If the tool's model list can be read, the model must be
in it. *My call:* if the list cannot be read (offline, logged out, timeout), a
pattern-valid model is accepted with a warning and shown as `unverified`. Codex has no
known list command: its source is the pattern plus the `model` in `~/.codex/config.toml`
as the suggested default.

**Read-only by default.** Templates embed the proven read-only mechanism per tool
(agy `--mode plan` + `AGY_RO`; OpenCode `claude-ro` inline agent; Codex
`-s read-only`). A write-capable variant is out of scope for this release.

**Export exclusion.** Creating or adopting a wrapper adds its **agent name** (no
`.md`, as in today's config) to `opencode.exclude`, `pi.exclude` and `codex.exclude`
in `config.yaml`, idempotently, via the existing config save path. config.yaml travels
through the sync repo — this only adds exclude entries, never runnable steps, so it
stays inside the trust ceilings. The main screen shows `Export: aus` when all three
lists contain the name.

**Dependencies.** Textual is a new regular dependency (decided by the Captain),
pinned like the others, `uv lock` afterwards; pip-audit must stay green. The `--json`
CLI must work without importing it (lazy import).

**Sync.** `~/.claude/agents` is the synced `claude_agents` category, so wrappers travel
to other hosts where a tool may be missing — that is exactly what the per-row tool
state shows.

## Documentation (part of the deliverable)

Bilingual DE/EN in one file, like the other `docs/usage/*.md`:

1. **`docs/usage/agents.md` — using it at work.** Configure with `sccs agents`; open a
   Herdr window; start `claude` in the project; example supervisor tasks
   ("Lass den Diff von Codex, Gemini und Kimi prüfen und gleiche die Befunde am Code
   ab", "zweite Meinung von Gemini zu diesem Entwurf"); how to tell a worker is
   running, done or stuck (background notifications, timeouts of 900 s); the traps:
   Codex' own sandbox vs. the nono rule, Gemini needs the material inline, OpenCode
   costs OpenRouter credit, a new agent needs a Claude Code restart. Every snippet the
   user types is **fish syntax**.
2. **The approach** (my call: a section in `docs/architecture.md`, linked from
   `agents.md`): why Claude is the supervisor, why thin Haiku wrappers with only
   Bash+Read, why not CAO, why reviewers are read-only, why a Gemini reviewer never
   falls back to a Claude model, why the supervisor verifies every finding itself.

Also: `docs/usage/cli-reference.md` and `--help` texts, `README.md` command list,
`RELEASE_NOTES.md`, maintainer-notes section for the new trust rules, version bump
plus `uv lock`.

## Testing

- Detection with fake binaries on a temporary PATH (CI runs on Linux; no macOS paths
  assumed).
- Template rendering: golden files; model validation rejects shell metacharacters,
  a leading `-`, non-Gemini models for the Gemini template, models absent from a
  readable list; an unreadable list yields `unverified`, not a refusal.
- `set-model` changes only the model token and keeps the hash valid; any other edit
  invalidates it.
- Adoption: the two real wrapper shapes are recognised (fixtures copied from them),
  the body stays byte-identical, only the frontmatter marker is added.
- Hand-edited managed file → overwrite asks; unmanaged file → never written.
- `new pi` fails with a hint.
- Exclude entries added once, idempotent.
- `--json` output shape; TUI via Textual's test pilot for the main flows (list,
  set model, new agent). CLI assertions strip ANSI.

## Left to the builder

Internal structure of the package and the TUI widgets, caching, exact key bindings
beyond the mockup, the login-state heuristics per tool (with `unknown` as fallback),
and the wording of the docs within the content listed above.
