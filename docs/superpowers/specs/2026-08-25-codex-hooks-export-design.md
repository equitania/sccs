# Codex Hooks Export — Design (v2.59.0)

**Date:** 25.08.2026
**Status:** approved, ready for implementation planning
**Scope:** one-way export of Claude Code hook entries into the OpenAI Codex CLI

## Problem

SCCS exports skills, agents and commands to Codex (v2.53.0). Hooks are the one
artefact family still missing, and Codex 0.149.1 supports a hook system whose
configuration format is close enough to Claude Code's that a mechanical export
is possible.

Codex ships its own one-time `/import` for Claude Code. This export is the
*repeatable* path — same relationship as the other three families.

## Verified facts

Everything below was checked against the installed CLI (codex 0.149.1) and the
official documentation on 25.08.2026, not inferred from the shape of the code.

### Target file

`~/.codex/hooks.json`. **Not** `~/.codex/hooks/hooks.json` — that path is the
plugin-bundled location, resolved relative to a plugin root.

Codex also accepts inline `[hooks]` tables in `config.toml`. If one config layer
contains both, Codex merges them and warns at startup. We therefore write
`hooks.json` only, and never touch `config.toml`.

### Target format

Structurally near-identical to Claude Code's `hooks` block:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "python3 \"$HOME/.claude/hooks/quality-gate.py\"" }
        ]
      }
    ]
  }
}
```

Codex-only handler fields: `async`, `statusMessage`, and a second handler type
`mcp_tool`. `timeout` is in seconds on both sides and defaults to 600 in Codex.

### Event coverage

Ten event names exist on both sides:

| Event | Claude | Codex | Exported |
| --- | --- | --- | --- |
| `PreToolUse` | yes | yes | yes |
| `PostToolUse` | yes | yes | yes |
| `PermissionRequest` | yes | yes | yes |
| `PreCompact` | yes | yes | yes |
| `SessionStart` | yes | yes | yes |
| `SessionEnd` | yes | yes | yes |
| `SubagentStart` | yes | yes | yes |
| `SubagentStop` | yes | yes | yes |
| `UserPromptSubmit` | yes | yes | yes |
| `Stop` | yes | yes | yes |
| `PostToolUseFailure` | yes | **no** | dropped |
| `PostToolBatch` | yes | no | dropped |
| `PermissionDenied` | yes | no | dropped |
| `Setup` | yes | no | dropped |
| `UserPromptExpansion` | yes | no | dropped |
| `StopFailure` | yes | no | dropped |
| `Notification` | yes | no | dropped |
| `FileChanged` | yes | no | dropped |
| `Elicitation` | yes | no | dropped |
| `PostCompact` | no | yes | n/a (no source) |

`PostToolUseFailure` is a real, documented Claude Code event — it is dropped
because Codex lacks it, not because it is invalid.

A shared name does not guarantee identical payloads. Both tools send a JSON
object on stdin with `session_id`, `cwd`, `hook_event_name` and `permission_mode`,
but each adds its own fields (Codex: `turn_id`, `model`). A hook script reading
only the shared fields ports cleanly; one depending on Claude-specific fields may
misbehave. This is the user's judgement to make, so the export states it in the
docs rather than trying to detect it.

### Handler types

Claude Code supports `command`, `http`, `prompt` and `agent`. Codex supports
`command` and `mcp_tool`. **Only `command` handlers are exportable.** A handler
of any other type is dropped with a warning. A `matcher` group whose handlers are
all dropped produces no group at all.

### Tool coverage inside matchers

Codex fires tool events for `Bash`, `apply_patch` (matcher aliases `Edit` and
`Write`), and MCP tool names. Claude tool names outside that set — `Read`,
`Grep`, `Glob`, `Task`, `WebFetch`, `WebSearch`, and others — never match in
Codex. Matchers are exported **verbatim** and the unreachable parts are named in
a warning (see Decision 3).

`SessionStart` matchers differ too: Claude allows `fork`, Codex does not.

### Trust flow — the constraint that shapes the design

> "Codex records trust against the hook's current hash, so new or changed hooks
> are marked for review and skipped until trusted."

An exported hook does not run until reviewed via `/hooks` in the Codex CLI. Two
consequences:

1. The export must tell the user to run `/hooks`, or they will conclude the
   export silently failed.
2. **Serialization must be byte-stable.** A re-export that changes nothing
   semantically must produce a byte-identical file. Otherwise the hash changes
   and every export forces a fresh trust review. This is a hard requirement with
   a dedicated test, not a nicety.

## Decisions

Three questions were put to the owner; the answers below are settled.

### Decision 1 — hook scripts stay where they are

Hook commands keep pointing at `~/.claude/hooks/`. Scripts are **not** copied
into `~/.codex/`, and commands are **not** rewritten.

One script, one source of truth: a fix applies to both tools at once, and there
is no second copy to drift. The trade-off is that Codex depends on
`~/.claude/hooks/` remaining present, which is true on any machine running both.

Rejected: copying scripts (duplicate state, needs a new sync category) and a
`--copy-scripts` flag (two ownership models, double the tests, no demonstrated
need).

### Decision 2 — merge with state tracking

`~/.codex/hooks.json` belongs to the user. SCCS records which entries it wrote
and replaces only those.

- **Key:** the triple `(event, matcher, command)`. Naturally stable, no synthetic
  id, and nothing artificial written into the target document.
- **State file:** `~/.config/sccs/.codex_hooks_state.yaml`, alongside
  `.profile_state.yaml` and `.doctor_state.yaml`.
- **Foreign entries** — anything not in the state — are preserved untouched.
- **Deletion propagates:** a Claude hook removed from `settings.json` is removed
  from `hooks.json` on the next export, because the state still remembers it.
- **Ordering within an event is fixed:** foreign groups keep their original
  relative order and come first; managed groups follow, in source order. Without
  a rule here, interleaving would depend on dict iteration and break byte
  stability — the trust hash would churn on every export.

**Known limitation, documented rather than solved.** The key includes `command`,
so editing a managed entry *inside Codex* changes its key. SCCS then sees the
edited entry as foreign (it survives) and re-creates the original from
`settings.json` — leaving two entries. The rule for users is therefore: edit
hooks in Claude Code, re-export, never patch a managed entry in `hooks.json`.
Detecting this properly would need a marker in the target document, which the
Codex schema has no room for; a heuristic match would risk clobbering genuinely
foreign entries. The docs state the rule, `export-hooks` warns when the state
lists a key it cannot find in the target, and that is where it stops.

This mirrors `ProfileRecord.original_hook_events`, which already solves the same
problem for `settings.json`.

Rejected: owning the whole file (destroys hooks authored directly in Codex) and
create-only (no repeatable reconciliation, which is the entire point).

### Decision 3 — translate strictly, warn loudly

- Events Codex lacks: **dropped**, with a warning naming the event.
- Handler types other than `command`: **dropped**, with a warning.
- Matchers: exported **verbatim**, with a warning listing the parts that cannot
  fire in Codex.

Nothing is silently reinterpreted. Verbatim matchers also mean the export grows
with Codex: when its tool coverage widens, existing entries start matching
without SCCS having to reissue them.

Rejected: rewriting matchers down to Codex's current tool set (SCCS editing the
user's regexes, freezing today's coverage, and awkward cases like `^apply_patch$`
or `mcp__.*`) and mapping `PostToolUseFailure` onto `PostToolUse` (Codex's
`PostToolUse` does fire after non-zero Bash exits, but also after every success —
a silent behaviour change).

## Architecture

Two new modules, following the split the Codex integration already uses:

```
sccs/convert/claude_to_codex_hooks.py   pure translation, no I/O
sccs/integrations/codex_hooks.py        read, merge, write
```

`codex_hooks.py` sits **beside** `codex.py` rather than inside it: that file is
already ~500 lines, and hooks follow a merge pattern rather than the
file-per-artefact pattern of the other three families.

### `convert/claude_to_codex_hooks.py`

| Function | Purpose |
| --- | --- |
| `CODEX_HOOK_EVENTS` | frozenset of the ten exportable event names |
| `UNREACHABLE_TOOL_TOKENS` | Claude tool names that never match in Codex |
| `convert_hook_entry(event, entry)` | one `{matcher, hooks[]}` group → `(codex_group_or_None, warnings)` |
| `convert_hooks_block(hooks)` | the whole `hooks` block → `(codex_hooks, warnings_by_event)` |
| `matcher_warnings(matcher)` | names the unreachable alternatives in a matcher |

Pure functions over dicts. No file access, no config lookups — the same contract
as `claude_to_codex.py`.

### `integrations/codex_hooks.py`

| Piece | Purpose |
| --- | --- |
| `CodexHookGap` | one entry to add, update or remove, with its warnings |
| `CodexHooksDetector.get_gaps()` | compares converted source against the target file plus state |
| `merge_hooks(existing, managed, state)` | pure merge; returns the new document and the new state |
| `export_hooks_to_codex(gaps, *, dry_run, ...)` | writes atomically, updates state |
| `CodexHooksStateManager` | loads/saves `.codex_hooks_state.yaml` |

`merge_hooks` is deliberately pure so the merge semantics can be tested without
touching the filesystem.

### Data flow

```
~/.claude/settings.json
        │  hooks block
        ▼
convert_hooks_block()  ──► warnings (dropped events, dropped types, dead matchers)
        │  managed entries
        ▼
merge_hooks(existing hooks.json, managed, state) ──► new document + new state
        │
        ▼
atomic_write(~/.codex/hooks.json, mode=0o600)
        │
        ▼
CodexHooksStateManager.save()
```

Reading `settings.json` reuses the existing helpers in `sync/settings.py`.

### Serialization

Byte-stability rules, all enforced by one test:

- events sorted alphabetically
- within each event: foreign groups first in their original relative order, then managed groups in source order (see Decision 2)
- fixed key order: `matcher`, then `hooks`; inside a handler `type`, `command`,
  `timeout`
- `json.dumps(..., indent=2, ensure_ascii=False)` plus one trailing newline
- an empty result writes `{"hooks": {}}` rather than deleting the file — the file
  may hold foreign entries, and deleting it is never this tool's call
- `atomic_write` with mode `0o600`, matching the settings.json sync

### CLI

```
sccs integrations codex export-hooks [-n/--dry-run] [--overwrite/--no-overwrite]
```

`codex status` gains a hooks line: how many entries would be added, updated or
removed.

**Not part of `export-all`.** Skills and agents are text a model reads; hooks
execute code on every tool call. That risk class belongs behind a deliberate
command, not inside a convenience wrapper. The `export-all` help text points at
`export-hooks` so the omission is visible rather than surprising.

On success the output ends with a pointer to `/hooks` in the Codex CLI, because
of the trust flow.

### Error handling

| Situation | Behaviour |
| --- | --- |
| Codex not installed | exit 1, "Codex is not installed", as the other export commands |
| `~/.claude/settings.json` missing or unreadable | error, no write |
| `hooks.json` is not a JSON object | error naming the file, no write — never silently overwrite |
| `hooks.json` holds a non-object under `hooks` | same |
| state file missing | treated as empty: nothing is claimed as managed, nothing foreign is touched |
| state file corrupt | warn and treat as empty (safe: worst case a stale managed entry lingers) |
| no `hooks` block in settings.json | success, "no hooks to export" |

The rule behind the table: SCCS never destroys what it did not write, and prefers
a loud refusal to a silent overwrite.

## Testing

New file `tests/test_codex_hooks.py`:

**Translation** — every event in the shared set survives; every Claude-only event
is dropped with a warning naming it; `http`/`prompt`/`agent` handlers are dropped;
a group whose handlers all drop produces no group; matcher warnings name exactly
the unreachable alternatives; a matcher that is entirely reachable warns not at
all.

**Merge** — foreign entries survive an export; a removed Claude hook is removed
from the target; a foreign entry that happens to share a key with a managed one
is not double-written; an empty state claims nothing; foreign groups keep their
relative order and precede managed ones; a state key missing from the target
produces a warning rather than a silent re-add.

**Byte-stability** — exporting twice with no source change leaves the file
byte-identical (the trust-hash requirement); key order is fixed regardless of
input order.

**Safety** — a `hooks.json` containing a JSON array, a string, or invalid JSON is
refused without a write; a corrupt state file degrades to empty.

**Real-world fixtures** — the owner's actual five entries, asserting the expected
verdicts: `quality-gate.py` exported clean; `nono-hook.sh` dropped
(`PostToolUseFailure`); `suggest-compact.py` exported with a matcher warning for
`Read`, `Grep`, `Glob`; `discover-skills.py` and `cost-tracker.py` exported clean;
`context-mode-cache-heal.mjs` exported with an absolute-path warning.

**CLI** — dry run writes nothing; not-installed exits 1; the `/hooks` pointer
appears on success.

## Out of scope

- Reverse direction (Codex → Claude). The integration is one-way by design.
- `config.toml` inline `[hooks]`. One representation per layer.
- Project-level `.codex/hooks.json`. User level only, as with the other exports.
- Rewriting or validating hook commands. SCCS writes them; Codex's trust flow is
  the security boundary, and it is a better one than any check we could add.
- MCP tool hooks (`type: "mcp_tool"`). Nothing in Claude Code maps onto it.

## Documentation

`docs/usage/codex.md` (DE + EN) gains a hooks section: what transfers, what does
not and why, the trust flow with `/hooks`, and why `export-all` leaves hooks out.
`usage/AGENT.md` gains the command and a guardrail line. `README.md` gets the
feature bullet, `CLAUDE.md` a key-feature entry.
