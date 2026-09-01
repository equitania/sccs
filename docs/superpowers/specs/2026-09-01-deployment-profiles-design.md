# Deployment Profiles — Design (v2.65.0)

**Date:** 01.09.2026
**Status:** draft, awaiting review
**Scope:** named, scenario-scoped bundles for foreign hosts, plus a verified
removal path that takes the knowledge back off the machine

## Problem

Working on a customer's Odoo server needs a handful of skills, the fish
configuration and a few shortcuts. Today the only transport is `sccs export`,
which offers the whole synchronised inventory — 75 skills, every category — and
leaves the selection to an interactive prompt that has to be redone correctly
every single time.

Two things are missing:

1. **A named, reproducible selection per scenario.** "Odoo work on a customer
   server" is a recurring situation, not a fresh decision.
2. **A way back.** Our skills are our knowledge. After the engagement they must
   leave the customer's machine — reliably, and demonstrably. Shell
   configuration and shortcuts may stay; they are a convenience, not an asset.

There is currently no record of what an import wrote, so there is nothing to
remove *from*. The manifest lives in the ZIP, not on the target host.

## Naming

`sccs profile` is already taken by the v2.57.0 feature that parks local
artefacts to shrink the system prompt. The new command group is **`sccs
deploy`**. The config key is `deployment_profiles:`, never `profiles:`.

## Verified facts

Checked against the installed configuration and the local artefact tree on
01.09.2026.

- `~/.claude/skills` holds 75 skill directories; `~/.claude/commands` 10 command
  files; `~/.claude/agents` 7 agent files.
- Twelve skills declare `INHERITS FROM` in their `SKILL.md`, naming
  `odoo-common` and/or `uv-python-tools` as prerequisites: `fr-mapper`,
  `eq-chatbot-core`, `odoo-merge-to`, `odoorpc-toolbox`,
  `odoo-migration-estimator`, `odoo-differ`, `odoo-mcp`, `odoo-module-migrator`,
  `sccs`, `odoo-dev`, `ownerp-demodata`, `uv-python-tools`.
- `fish_config` already excludes `*.macos.fish`; `fish_functions` excludes
  `macos/*`. The macOS-only categories (`fish_config_macos`,
  `fish_functions_macos`) carry `platforms: [macos]`.
- `sccs_manifest.yaml` records per item: `name`, `zip_path`, `item_type`,
  `platform_hint`; per category: `description`, `item_type`, `local_path`.
  It does **not** record content hashes, and there is no receipt written on
  import.
- `Importer` already rejects zip-slip paths and symlinks
  (`tests/test_importer_security.py`).
- `Exporter` already drops doctor-managed items (`gsd-*`, `playwright-cli`)
  unless `--include-managed` is given.

## Architecture

A deployment profile is a **named selection over the existing export path**.
It resolves to an `ExportSelection` and is handed to the existing `Exporter`;
installation goes through the existing `Importer`. There is no second copy
path — the same rule that governs `integrations sync-all`.

New module `sccs/deploy/`:

```
sccs/deploy/
├── schema.py      # DeploymentProfile, validators, BLOCKED_CATEGORIES
├── defaults.py    # DEFAULT_DEPLOYMENT_PROFILES (the four bundled profiles)
├── resolve.py     # profile -> ExportSelection; dependency + platform checks
├── receipt.py     # DeployReceipt, ReceiptEntry, ReceiptManager
├── bundle.py      # export wrapper: manifest `deployment:` section
├── revoke.py      # RevokePlan, trace enumeration, verification sweep
└── traces.py      # the trace locations and the ~/.claude.json surgery
```

### The profile

```yaml
deployment_profiles:
  odoo-server:
    description: "Odoo work on a customer server"
    target_platform: linux
    include:
      claude_skills:    [odoo-common, odoo16, odoo17, odoo18, odoo19, ...]
      claude_commands:  [s, docs, finalize, tips]
      claude_agents:    [odoo-developer, python-toolsmith]
      claude_framework: [CLAUDE.md, SOUL.md, PRINCIPLES.md, RULES.md]
      fish_config:      ["*"]
      fish_functions:   ["*"]
      starship_config:  ["*"]
    retain:
      - fish_config
      - fish_functions
      - starship_config
```

Values are fnmatch globs matched against item names, consistent with the
existing `include`/`exclude` handling in `SyncCategory`.

A profile may declare `extends: <name>`. The parent's `include` map is merged
per category (union of the glob lists) and its `retain` list is unioned;
`target_platform` and `description` are overridden by the child. Resolution is
single-level and a cycle raises — `odoo-dev-full` is the only user, and a deep
inheritance chain would make it hard to answer "what is actually in this
bundle" without running the resolver.

**`retain` belongs to the profile, not the category.** The same fish
configuration is part of the payload on a second machine of ours and a parting
gift on a customer host. "May stay behind" is a property of the scenario.

**`claude_framework` is carried deliberately and removed deliberately.**
Without `CLAUDE.md`/`RULES.md` the agent on the customer host does not behave
like ours — fish syntax, delete protection, commit prefixes would all be
absent. At the same time `SOUL.md` is our working method. So: ship it, and
never list it under `retain`.

### Blocked categories

`claude_memories`, `claude_plans`, `claude_todos` may not appear in any
deployment profile. The schema validator **raises**; it does not silently
filter. These hold project memory from other engagements, and a typo must not
carry one customer's context onto another customer's server.

### Dependency check

`resolve.py` reads the `INHERITS FROM` line of every included skill. If a child
is present without its parent, `deploy export` and `deploy show` report it.
This is a **warning that blocks by default**, releasable with
`--allow-missing-deps` — a bundle whose skills silently degrade on a machine we
will not be sitting at is worse than a failed export.

### Platform targeting

`target_platform` is matched against each category's `platforms:` list and each
item's `platform_hint`, replacing the running machine as the reference. Without
this a Mac exports `fish_config_macos` into a Linux bundle. The mechanism
already exists (`is_platform_match`); only the reference value changes.

### Self-describing bundle

`sccs_manifest.yaml` gains a `deployment:` section:

```yaml
deployment:
  profile: odoo-server
  target_platform: linux
  retain: [fish_config, fish_functions, starship_config]
  purge_traces: true
```

The customer host has no `config.yaml` of ours, so it must not depend on one to
know what has to leave again. The bundle carries its own removal policy.

## Installation and the receipt

`sccs deploy install bundle.zip` runs the existing `Importer` and then writes
`~/.config/sccs/.deploy_receipt.yaml`:

```yaml
version: 1
installs:
  - profile: odoo-server
    installed_at: "2026-09-01T10:12:00+00:00"
    sccs_version: "2.65.0"
    retain: [fish_config, fish_functions, starship_config]
    entries:
      - category: claude_skills
        name: odoo-common
        target: /home/user/.claude/skills/odoo-common
        item_type: directory
        content_hash: "sha256:..."
        pre_existing: false
```

Entries are keyed on `(category, name)`; a re-install updates in place rather
than appending. Multiple profiles may be installed side by side.

### `pre_existing` — the load-bearing field

If something already exists at the target path *before* we write, that is
recorded and **never touched by `revoke`**. Same line as the `foreign_target`
guard in the Codex export: "written by us" and "was already here" are different
facts, and only the first justifies a deletion.

The opposite case is decided the other way on purpose: an artefact **we**
installed and the customer has since modified is still removed — it still
carries our knowledge. It is listed by name as "modified since installation"
before the confirmation, so the decision is visible rather than inherited.

`content_hash` exists to make that distinction, not to veto the removal.

## Revocation

`sccs deploy revoke` reads the receipt and sorts into four buckets:

| Bucket | Action |
|---|---|
| removed | receipt entry, not under `retain`, still present |
| retained | category listed in `retain` |
| untouched | `pre_existing: true` |
| already gone | target path no longer exists |

### Work traces

Enumerated separately, and listed individually before confirmation:

- `~/.claude/projects/` — transcripts and project memory. **The actual leak:** a
  session transcript quotes our skills verbatim. Deleting the skills while
  leaving the transcript protects nothing.
- `~/.claude/plans`, `~/.claude/todos`, `~/.claude/shell-snapshots`
- **everything under `~/.config/sccs/` except the deploy receipt** — enumerated
  entry by entry at removal time, not from a hand-kept list. `config.yaml` holds
  the repository path and the full category layout; `.sync_state.yaml` names
  every synchronised skill; `sync.log`, `.doctor_state.yaml`,
  `.codex_export_state.yaml`, `.profile_state.yaml`, the `profiles/` parking
  area, `backups/` and the `config.yaml.bak-*` copies each hold more of the
  same. Deleting the skills while leaving behind a file that lists them all by
  name is the transcript mistake one line further down. A fixed list would rot
  the moment a new state file is added, so the directory is read at runtime.
  The receipt is excluded because `revoke` still needs it — it removes it last.

Traces are not owned by any single profile. With several installs on one host,
`revoke --profile NAME` removes that profile's entries only and leaves the
traces alone; they are purged when the **last** install is revoked. Otherwise
removing one of two profiles would delete transcripts the other is still
producing.

`~/.claude.json` is **trimmed, not deleted**: only `history` and
`projects[*].history` are removed. The file also carries the customer's auth
and onboarding state; removing it would cause damage nobody asked for. The
rewrite goes through `atomic_write` with mode 0600, like the settings sync.

### Confirmation

Full list, then typed confirmation, per the global delete-protection rule.
`--dry-run` always available, `--yes` for non-interactive use only.
The receipt itself is removed last, after everything it points at.

### Verification sweep

`revoke` ends by re-scanning the known locations against the profile's globs
and reporting anything left behind, with a non-zero exit if the sweep finds
something.

A removal that reports success while a skill directory survived is the worst
possible outcome of this feature — worse than not cleaning up at all, because
the report is what the decision to stop looking is based on.

## CLI

```
sccs deploy list                    Show profiles
sccs deploy show odoo-server        Resolved item list, size, dependency check
sccs deploy export odoo-server      Build the bundle
sccs deploy install bundle.zip      Install + write receipt
sccs deploy status                  What of ours is on this host
sccs deploy revoke                  Removal
```

All of them accept `--json`, matching the Core-First commands since v2.50.0, so
the Tauri GUI wrapper can consume them later.

`export` additionally: `-o/--output`, `--platform` (override
`target_platform`), `--dry-run`, `--allow-missing-deps`.
`revoke` additionally: `--dry-run`, `--yes`, `--profile NAME` (remove one of
several installed profiles), `--keep-traces`.

### The `/aufräumen` command

Every profile that installs skills ships a small command file that shows `sccs
deploy status` and, after a prompt, runs `sccs deploy revoke`. On the customer
host you tell the agent to clean up and it has a defined route instead of an
improvisation involving `rm -rf`.

The file is **generated by `deploy export`** from a template in
`sccs/deploy/defaults.py` — it is not one of the synced `~/.claude/commands`
and must not be added there, or it would end up in every bundle and on our own
machines. It is written into the ZIP as a `claude_commands` item, so it becomes
a normal receipt entry and removes itself with the rest.

## The four bundled profiles

Listed for review — this is the part most likely to need correction.

### `odoo-server` (target: linux)

Customer-server work: running Odoo, intervening, reading logs.

Skills: `odoo-common`, `odoo16`, `odoo17`, `odoo18`, `odoo19`, `odoo-shell`,
`odoo-dev`, `odoorpc-toolbox`, `odoo-module-migrator`, `odoo-merge-to`,
`myodoo-docker`, `docker-expert`, `nginx-set-conf`, `uv-python-tools`,
`sharp-edges`, `verification-loop`, `session-hygiene`
Commands: `s`, `docs`, `finalize`, `tips`
Agents: `odoo-developer`, `python-toolsmith`
Framework: `CLAUDE.md`, `SOUL.md`, `PRINCIPLES.md`, `RULES.md`
Shell (retained): `fish_config`, `fish_functions`, `starship_config`

Deliberately **not** included: `remote-support`. It is written for hosts Claude
cannot reach — on the customer server Claude is *on* the machine, and its
triggers ("beim Kunden", "Kundenserver") would misfire permanently. Also out:
everything for marketing, the App Store, blog posts and website themes.

### `odoo-dev-full` (target: linux)

Everything from `odoo-server`, plus documentation and publication:
`odoo-module-docs`, `odoo-funktionsumfang`, `odoo-funktionsumfang-merge`,
`eq-helper-docs`, `odoo-appstore-listing`, `odoo-module2website`,
`odoo-website-design`, `odoo-website-themes`, `odoo-docs-sync`,
`odoo-agent-doc-coverage`, `odoo-ai-addon`, `odoo-chat`, `eq-chatbot-core`,
`ownerp-demodata`, `odoo-differ`, `odoo-migration-estimator`, `clean-room`,
`changelog-automation`, `project-docs`, `create-test-plan`, `tdd-workflow`,
`glab`, `gitlab-workflow`
Additional commands: `afterwork`, `check-skills`, `project-audit`

For a second machine of ours or a longer engagement — not for a customer host
we only visit.

### `fastreport` (target: linux)

Skills: `fr-reports`, `fr-mapper`, `fr-odoo`, `fr-api`, `fr-designer`,
`odoo-common`, `uv-python-tools`
Agents: `fastreport-integrator`
Framework and shell as in `odoo-server`.

`fr-reports` is the largest skill in the inventory at 372 KB — worth a look at
`deploy show` before every export.

### `shell-only` (target: linux)

Environment only, no knowledge: `fish_config`, `fish_functions`,
`starship_config`, `git_config`, `project_templates`. No skills, no agents, no
framework. Every category is under `retain`, so `revoke` on a pure `shell-only`
host removes nothing and says so.

## Testing

Against a temporary `HOME`, platform-independent — CI runs on Linux.

1. **Round trip:** export → install → revoke → a sweep over the profile globs
   finds nothing.
2. **`pre_existing` survives:** a skill placed before the install is still there
   after the revoke.
3. **`retain` survives:** fish config and functions untouched by the revoke.
4. **Modified artefact is removed** and appears in the report as modified.
5. **Linux target drops macOS items:** `fish_config_macos` and
   `*.macos.fish` are absent from the bundle even when exporting from macOS.
6. **Blocked categories:** a profile naming `claude_memories` fails validation.
7. **Dependency check:** a profile with `odoo-merge-to` but without
   `odoo-common` is refused, and accepted with `--allow-missing-deps`.
8. **`~/.claude.json` surgery:** `history` gone, every other key byte-identical.
9. **`shell-only` revoke** removes nothing and exits 0 with an explicit message.
10. **Verification sweep fails loudly:** with a leftover planted by hand, the
    revoke exits non-zero.

## Out of scope

- Encrypting or signing the bundle. The transport is our own; a signature would
  suggest a guarantee against tampering that we cannot back up.
- Automatic removal on a timer or at session end. Removal is an explicit act.
- Removing `sccs` itself from the customer host. It is a public PyPI tool and
  carries no knowledge of ours; only its `config.yaml` does, and that is covered.
- Syncing back from the customer host. Deployment is one-way by construction.

## Version

2.65.0, followed by `uv lock`.
