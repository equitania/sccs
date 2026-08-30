# CAO Agent Profiles

Agent profiles for the [CLI Agent Orchestrator](https://github.com/awslabs/cli-agent-orchestrator)
covering the Equitania four-CLI fleet: Claude Code, Codex, OpenCode and
Antigravity.

All shell snippets below are **Fish**.

## The fleet

| Profile | Provider | Model | Role | Purpose |
|---|---|---|---|---|
| `eq_supervisor` | `claude_code` | `claude-opus-5` | supervisor | Decompose, route, synthesize, decide |
| `eq_claude_analyst` | `claude_code` | `claude-sonnet-5` | reviewer | Odoo `eq_*`, FastReport, Rust TUIs, wide-context work |
| `eq_codex_analyst` | `codex` | `gpt-5.6-terra` | reviewer | Bounded tasks: test gaps, bug reproduction, Python CLI |
| `eq_antigravity_reviewer` | `antigravity_cli` | `gemini-3.1-pro-high` | reviewer | Independent second opinion on a Google model |
| `eq_opencode_analyst` | `opencode_cli` | provider default | reviewer | Skill-driven specialist analysis |
| `eq_image_smith` | `codex` | `gpt-5.6-terra` | developer | Image production against the included plan quota |

## Current wave: read-only

Every worker except `eq_image_smith` carries `role: reviewer`, which CAO maps to
a read-only tool set (`@builtin`, `fs_read`, `fs_list`, `@cao-mcp-server`). The
restriction is structural, not merely requested — workers deliver findings and
recommendations, the human applies changes.

`eq_image_smith` writes, because producing an image means producing a file. Its
boundary is narrow and stated in the profile: `~/Downloads` and `~/temp` only,
never a repository.

## Installing

CAO needs the tmux backend, because Antigravity requires it:

```fish
cao config set terminal.backend tmux
```

Then install each profile. The `--provider` flag wins over the profile's
`provider:` key, so pass it explicitly:

```fish
cao install ./agents/eq_supervisor.md            --provider claude_code
cao install ./agents/eq_claude_analyst.md        --provider claude_code
cao install ./agents/eq_codex_analyst.md         --provider codex
cao install ./agents/eq_antigravity_reviewer.md  --provider antigravity_cli
cao install ./agents/eq_opencode_analyst.md      --provider opencode_cli
cao install ./agents/eq_image_smith.md           --provider codex
```

Verify:

```fish
cao profile list
```

**OpenCode caveat:** its permissions are baked into the installed agent
configuration at install time, and a later `cao launch --yolo` does not lift
them. Changing `allowedTools` in `eq_opencode_analyst.md` therefore requires a
reinstall to take effect.

## Operational traps

Four of these cost an hour of diagnosis on 30.08.2026. None are documented
upstream; all four bite again on a fresh machine.

**1. CAO assumes a POSIX shell — fish breaks it.** Before launching Claude Code,
CAO prefixes the command with `unset $(env | sed ...)` to scrub `CLAUDE_*`
variables (`providers/claude_code.py`). Fish has no `unset`, so the prefix dies,
Claude starts anyway, the workspace-trust dialog appears, and CAO's auto-accept
sends a bare Enter — which selects **"No, exit"** in Claude Code 2.1.251. The
symptom is `Claude Code initialization timed out`, which points nowhere near the
cause. Fix:

```fish
echo 'set-option -g default-shell /bin/bash' >> ~/.tmux.conf
tmux set-option -g default-shell /bin/bash    # for the running server
```

With that in place, a worker reaches `idle` in about two seconds.

**2. `cao launch "<task>"` only delivers the task with `--headless`.** Without
the flag CAO attaches you to the tmux session and discards the message argument
silently — `if not headless: attach_session()` / `elif message: POST /input`.
Every example that omits `--headless` while expecting the agent to work is
wrong.

**3. `cao shutdown` requires `--all` or `--session`.**

**4. Do not name the server's own tmux session `cao-*`.** CAO claims that
namespace, lists such a session as one of its own, and `cao shutdown --all`
would kill the very server it needs. Use a neutral name:

```fish
tmux new-session -d -s orchestrator 'cao-server --terminal tmux'
```

`cao-server` has no daemon mode, so it needs a session of its own either way.

**Reading results.** The output `cao launch --headless` prints is scraped from a
repainting TUI and often arrives torn. The reliable reads are
`cao session status <session>` and `tmux capture-pane -p -t <session>`.

## The web UI is missing from the PyPI wheel

`http://127.0.0.1:9889/` answers `{"detail":"Not Found"}` instead of the
dashboard, and `cao tui` reports a missing binary. Neither is a local
misconfiguration: the published wheel ships without the compiled frontend and
without the Rust TUI binary (awslabs/cli-agent-orchestrator#610). The backend is
complete — 71 REST endpoints including `/sessions`, `/terminals/{id}` and an
`/events` stream — only the shipped viewer is absent.

Their own `pyproject.toml` declares `src/cli_agent_orchestrator/web_ui/**` as
package data and vite's `outDir` points exactly there, so the wheel is simply
built without running `npm run build` first. Building it locally therefore
produces the intended dashboard, not a workaround:

```fish
git clone --depth 1 --branch v2.5.0 https://github.com/awslabs/cli-agent-orchestrator.git ~/gitbase/cli-agent-orchestrator
bash agents/cao-restore-webui.sh
```

Then restart the server and open <http://127.0.0.1:9889>. Re-run the script
after every `cao update` — an upgrade replaces the package and removes the
assets again. Match the checkout tag to `cao --version`; the script warns when
they diverge.

## Capacity-aware routing

The supervisor consults `sccs capacity --json` before its first delegation and
again before any delegation to Codex or Antigravity. That command reports
remaining plan quota per provider and derives three decisions — which agent gets
image work, who is the independent reviewer, and whether parallel workers are
affordable. See [`docs/usage/capacity.md`](../docs/usage/capacity.md).

The rule most easily got wrong, and the reason it lives in code rather than in a
prompt: **when the Gemini quota is tight, the fallback reviewer is Codex — never
Antigravity switched to a Claude model.** Antigravity resells Claude and GPT
models from a separate quota pool, so the switch looks available. Taking it
turns cross-provider review into Anthropic reviewing Anthropic.

## Model names

Model identifiers drift. Re-check before assuming a profile is still valid:

```fish
agy models                 # Antigravity: use the slug, not the display name
codex debug models         # Codex: raw model catalogue as JSON
```

Codex also caches a machine-readable catalogue at `~/.codex/models_cache.json`.
