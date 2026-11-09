# Working with agents from several providers: step-by-step setup (sccs 2.73.0)

[Deutsch](multi-provider-agents.de.md) · [English](multi-provider-agents.en.md)

This guide sets things up, in twelve steps, so that **Claude Code** (Anthropic) hands reviews, second opinions and bounded analyses to **Gemini** (Google), **Kimi** (Moonshot via OpenRouter) and **Codex** (OpenAI), and checks every finding against the code itself. It is written for readers at home in the shell who do not know sccs.

## The idea in five sentences

- **sccs** (SkillsCommandsConfigsSync) is a command-line tool that synchronises Claude Code files (skills, agents, commands, hooks) between machines. Since 2.73.0 it has the command `sccs agents`.
- One interactive Claude Code window is the **supervisor**: it hands out tasks and evaluates the results.
- The bridge to other providers is a set of **wrapper agents**: small files in `~/.claude/agents/` that only forward a single CLI call (`agy`, `opencode run` or `codex exec`). They run on the smallest Claude model, have only the tools `Bash` and `Read`, and are **always read-only**.
- A finding from a foreign model counts as an **unverified claim**. The supervisor checks each one against the code and reports which held.
- `sccs agents` is **configuration only**: it never starts agent work, never installs CLIs and never logs in. You use the terminal multiplexer **Herdr** merely as a window; it is not part of the configuration. No separate orchestrator (CAO) is involved.

## The providers involved

| Provider | Tool (CLI) | Template for `sccs agents new` | Note |
|---|---|---|---|
| Anthropic | Claude Code (`claude`) | – | supervisor, no wrapper needed |
| Google | Antigravity CLI (`agy`) | `agy` | `gemini-*` models only |
| Moonshot (Kimi) via OpenRouter | OpenCode CLI (`opencode`) | `opencode` | costs OpenRouter credit per call |
| OpenAI | Codex CLI (`codex`) | `codex` | plus the Claude Code plugin `codex@openai-codex` |
| Pi | `pi` | none | display only |

## Setup in twelve steps

All snippets use fish syntax. Places marked “assumption” could not be checked against the real help output.

### 1. Install or update sccs 2.73.0

[uv](https://docs.astral.sh/uv/) is required.

```fish
uv tool install sccs        # first install
uv tool upgrade sccs        # existing install
sccs --version
```

**Success:** `sccs, version 2.73.0` (or higher).

### 2. Install and check the tools

`sccs doctor` checks Node.js, the `claude` CLI and the configured Claude plugins (including `codex@openai-codex`) and installs missing parts after a prompt. It does **not** install the three foreign CLIs `agy`, `opencode` and `codex`; set those up following each vendor's instructions (assumption: the install commands depend on the vendor and are not checked here).

```fish
sccs doctor check               # read-only: status table per component
sccs doctor install             # install missing plugins/tools, one prompt per action
```

If the Codex plugin is missing you can also fetch it by hand (help checked; the marketplace source `openai/codex-plugin-cc` appears in the doctor table):

```fish
claude plugin list
claude plugin install codex@openai-codex
```

**Success:** `sccs doctor check` shows Node.js, Claude CLI and `codex@openai-codex` as `OK`. Whether the three foreign CLIs are present is shown by step 4.

### 3. Log in at each provider

You log in inside each tool itself; `sccs` only shows the state.

```fish
claude                     # Claude Code: log in on first start
codex login                # OpenAI; check the state with: codex login status
opencode auth login        # OpenCode: choose the provider OpenRouter and enter the key
opencode auth list         # list configured providers
agy                        # Antigravity: start once interactively and log in
```

`codex login` also has `--with-api-key` (key from standard input). For `opencode auth login`, choosing “OpenRouter” in the dialog is an assumption; the help only names the optional parameter `url`. For `agy`, `agy --help` lists no login command of its own; starting it without arguments to log in is an assumption, based on the wrapper's error hint (“the user must run `agy` once interactively”).

**Success:** `codex login status` and `opencode auth list` report a logged-in account. `agy -p "Reply with OK"` answers instead of reporting an authentication error.

### 4. Look at the state

```fish
sccs agents                # terminal: full-screen view; in a pipe/script: table
sccs agents tools          # which CLIs are installed, version, login, default model
sccs agents list           # all agents in ~/.claude/agents with tool, model and mode
```

The **Installed** column reads `yes` or `no`. In **Login**, `yes` means a credentials file exists (it is never read); `unknown` means it cannot be told, since credentials may also live in a keyring or environment variables. The **Mode** column reads `read-only` (managed by sccs), `read-only (not adopted)` (hand-written wrapper, not yet taken over), `unmanaged` (matches no template, sccs never writes it) or `plugin` (for example `codex:codex-rescue`, display only). A trailing `€` means every call costs OpenRouter credit.

**Success:** every tool you want to use shows `Installed: yes`. Pi may show `no`.

### 5. Adopt existing wrappers or create new ones

**a) Adopt existing hand-written wrappers.** If `sccs agents list` shows a wrapper as `read-only (not adopted)`:

```fish
sccs agents adopt antigravity-worker
sccs agents adopt opencode-worker
```

sccs asks once, inserts only an `sccs:` block into the frontmatter and leaves the rest of the file byte for byte unchanged. `--yes` skips the question.

**b) Create new wrappers.** Name: lowercase letters, digits and `-`, no `/`, no `.md`.

```fish
sccs agents new agy gemini-review
sccs agents new opencode kimi-review --model openrouter/~moonshotai/kimi-latest
sccs agents new codex codex-review
```

Without `--model` the template default applies: `gemini-4-argon-high` for `agy`, `openrouter/~moonshotai/kimi-latest` for `opencode`, and for `codex` the default model from `~/.codex/config.toml`; if none is set there, `new` exits with “No default Codex model in ~/.codex/config.toml; pass --model.”. An existing file is never overwritten. Pi has no template: `sccs agents new pi …` exits with “Pi has no tested wrapper template yet.”

**Success:** the file `~/.claude/agents/<name>.md` exists and `sccs agents list` shows the agent as `read-only`.

### 6. Choose models

```fish
sccs agents models agy             # models the tool itself reports
sccs agents models opencode
sccs agents models codex
sccs agents set-model gemini-review gemini-4-argon-high
```

`set-model` changes only the model in the wrapper's command line. The wrapper's own model (`model: haiku`) stays fixed. Rules:

- **`agy`: `gemini-*` only.** Antigravity also resells Claude and GPT models; falling back to one of them would be a self-review. If no Gemini model works, the wrapper says so and stops.
- **Free `opencode/*` models** trigger a warning (“Free opencode/* models have an unclear data policy — not for code with customer data.”): not for code with customer data.
- **`unverified`:** if the model list cannot be read (offline, logged out), sccs accepts a well-formed name with a warning and shows it as `unverified`.
- A name may contain only letters, digits and `. _ : / ~ -` and must not start with `-`.

The same works in the full-screen view: Enter or `m` picks from the tool's real model list.

**Success:** `sccs agents list` shows the chosen model; with a readable list, without `unverified`.

### 7. Check the export exclusion

`~/.claude/agents` is synced, and `sccs integrations codex|opencode|pi` exports agents into other tools. A wrapper saying “call `opencode run`” would reappear there as an agent and call itself. When you create or adopt a wrapper, sccs therefore adds its name once (with a backup of the configuration) to `opencode.exclude`, `pi.exclude` and `codex.exclude` in `~/.config/sccs/config.yaml`.

```fish
sccs agents                              # in the view: the line under the table shows “Export: off”
sccs integrations sync-all --dry-run     # show the plan, writes nothing
```

**Success:** the selected agent shows `Export: off`, and the plan from `sync-all --dry-run` contains none of your wrappers.

### 8. Restart Claude Code

A session that is already running does not know newly created agents. Quit Claude Code and start it again (step 10 shows the start).

**Success:** in the new Claude Code window the wrappers appear among the available agents (command `/agents`).

### 9. Provision further machines

The wrapper files live in the category `claude_agents` (local `~/.claude/agents`) and travel with the normal sync.

```fish
sccs sync --dry-run -c claude_agents          # preview on machine A (source)
sccs sync --commit --push -c claude_agents    # publish
sccs sync --pull -c claude_agents             # on machine B: fetch and apply
sccs agents                                   # on machine B: check the state
```

On machine B the CLIs must be installed and logged in themselves (steps 2 and 3); otherwise the wrapper's row shows the tool's missing state. The exclusion lists live in `config.yaml`; whether they reach machine B depends on how you distribute that file (assumption). Check `Export: off` there as in step 7.

**Success:** `sccs agents list` on machine B shows the wrappers; `Installed: yes` for the tools used there.

### 10. Start Claude in Herdr

Open a terminal window (for example a Herdr window), change into the project and start Claude Code:

```fish
cd ~/gitbase/my-project
claude
```

**Success:** Claude Code starts in the project; the wrappers are available (step 8).

### 11. Work with example tasks

Ask for work the way you would say it:

- “Lass den Diff von Codex, Gemini und Kimi prüfen und gleiche die Befunde am Code ab” (have Codex, Gemini and Kimi review the diff and reconcile the findings against the code)
- “Hol eine zweite Meinung von Gemini zu diesem Entwurf” (get a second opinion from Gemini on this draft)
- “Have Codex investigate the cause of this error through `codex:codex-rescue`” (an agent from the plugin; `/codex:review` starts a Codex review directly)

The supervisor starts the wrappers **in the background**, keeps working and is notified when a worker finishes. It marks every finding as an unverified claim of the model that made it, checks each one against the code and reports which held. A Gemini review of a diff of about 300 lines takes roughly four minutes.

**Success:** you get a list of findings per model, with the result of the check against the code.

### 12. Failure modes

- **`jetski: no output produced`** (Gemini): headless, Antigravity cannot ask for permission, and every command outside the allowlist is denied. Material was missing from the prompt; the wrapper therefore puts the diff or excerpts into the prompt. Ask again with the material.
- **Exit 124:** the outer `timeout 900` (15 minutes) fired; the task was too large. Split it: one call per file or directory, never a diff of more than about 2,000 lines in one piece.
- **`EPERM` on `/tmp/xcrun_db…` in a Codex run:** that is Codex' own `read-only` sandbox doing its job, **not** the nono sandbox. Skip it and carry on with reading tools; do not ask for a restart of the nono session.
- **Credit or login (OpenCode, Codex, Gemini):** the wrapper reports the error and does not retry with another provider. Top up OpenRouter credit, or repeat step 3 for the tool; `sccs agents tools` shows the login state.
- **New agent missing in the session:** restart Claude Code (step 8).

## Keys in the full-screen view

| Key | Effect |
|---|---|
| Enter or `m` | pick a model, or adopt a wrapper not adopted yet |
| `n` | create a new wrapper |
| `w` | tools view (version, login, default model, config path) |
| `?` | help; `Tab` switches between “Usage” and “Approach” |
| `r` | reload |
| `q` | quit |

## Further reading

- Reference for all subcommands, modes and traps: [docs/usage/agents.md](../docs/usage/agents.md)
- Why it is built this way (supervisor, read-only wrappers, no orchestrator, Gemini stays on Gemini): [section “Supervisor and wrapper agents” in docs/architecture.md](../docs/architecture.md#supervisor-and-wrapper-agents)
