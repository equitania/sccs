# `sccs capacity` — remaining plan quota per agent CLI

Reports how much plan quota Claude Code and Antigravity have left, and
derives the routing decisions an orchestrator makes from it. Written for a
supervising agent deciding which worker to delegate to, but equally readable at
the terminal.

```fish
sccs capacity              # Rich table + routing advice
sccs capacity --json       # one line of JSON for a supervisor or a GUI
sccs capacity --offline    # skip every probe that makes a network call
```

## Why this exists

Delegating to a worker whose weekly window is exhausted wastes a round trip and
a supervisor turn. The metered CLI exposes its quota, but only from inside an
interactive session (`/usage` in Antigravity), which is exactly where an
orchestrator cannot reach. This command gets at the same numbers from outside.

## The sources differ in trustworthiness

The `source` field is part of the payload on purpose — a caller must be able to
tell a live reading from a cached one before it routes real work.

| Provider | `source` | How it is obtained | Caveat |
|---|---|---|---|
| `antigravity` | `live` | `agy -p "/usage"` — `agy` has no `usage` subcommand, but print mode expands slash commands | Costs one tiny request against your account; skipped by `--offline` |
| `claude_code` | `assumed` | Nothing to read | Claude Code keeps no on-disk quota cache and `/usage` is interactive only. **No numbers are invented**; it is reported as the fallback reserve |

## Windows and scopes

Providers may disagree on which half of the fraction they report (used or
remaining), so every `QuotaWindow` carries both and derives whichever is
missing. A window whose `resets_at` has already
passed is marked `expired` and treated as 100 % free: the snapshot describes a
window that has since rolled over.

Scopes are a list rather than a flat field because **Antigravity bills Gemini
models separately from the Claude and GPT models it resells**. That distinction
is load-bearing for routing (see below), not cosmetic.

## Routing advice

`routing` is derived in code rather than left to a prompt, so it is testable and
identical on every host:

- **`image_generation`** — `antigravity` → `paid-api`. The Antigravity plan
  includes image generation (through Gemini), so the billed API is the last
  resort, never the first. Diagrams are excluded by convention: they belong in Graphviz or
  Mermaid, not in an image model, because generated labels are unreliable.
- **`independent_reviewer`** — `antigravity` → `none`. Antigravity earns the
  reviewer slot *because a Google model is behind it*. When the Gemini quota is
  tight there is **no independent reviewer — Antigravity running a Claude model
  does not count**, because that would make Anthropic review its own work and
  defeat the point of cross-provider review. The report says so explicitly in
  `constraints`.
- **`parallel_workers_ok`** — false when any weekly window is below 20 %.
  Parallel workers are what burns a weekly budget.
- **`constraints`** — human-readable notes a supervisor can quote back to the
  user, including reset times.

A quota below **20 % remaining** counts as tight
(`sccs.capacity.schema.LOW_REMAINING_PERCENT`). Missing data is deliberately
*not* the same as exhausted: an unreadable quota still routes work to that
provider, because treating "unknown" as "empty" would push paid work onto the
billed API for no reason.

## JSON shape

```json
{
  "generated_at": "2026-08-30T12:00:00Z",
  "providers": [
    {
      "provider": "antigravity",
      "installed": true,
      "source": "live",
      "observed_at": "2026-08-30T12:00:00Z",
      "scopes": [
        {
          "name": "Gemini Models",
          "windows": [
            {
              "name": "weekly",
              "window_minutes": 10080,
              "remaining_percent": 99.0,
              "used_percent": 1.0,
              "resets_at": "2026-09-06T08:01:34Z",
              "resets_in_minutes": 10200,
              "expired": false
            }
          ]
        }
      ],
      "note": null,
      "error": null
    }
  ],
  "routing": {
    "image_generation": "antigravity",
    "independent_reviewer": "antigravity",
    "parallel_workers_ok": true,
    "constraints": []
  }
}
```

Every probe degrades rather than raises: a missing binary, an unparsable table
or a timeout yields `source: "unavailable"` plus an `error` string, and the
report still answers.
