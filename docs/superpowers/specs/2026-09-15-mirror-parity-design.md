# Mirror parity: keep a second Mac identical to the live workstation

**Date:** 2026-09-15
**Target release:** 2.68.0 (prerequisite fix: 2.67.2)
**Status:** approved design, awaiting review of this document

## Problem

A second Mac is meant to serve demonstrations, tests and long-running jobs
(builds, test suites, Odoo demo instances, CAO workers). For that it must carry
the same software as the live workstation. SCCS syncs Claude artefacts and shell
configuration between the two, but four kinds of software never travel:

1. **Homebrew** — the Brewfile is a synced category, but nothing keeps it current
   on the source (last dump 23.08., five packages drifted since) and nothing runs
   `brew bundle` on the target.
2. **Own git checkouts** — the shell loads Beam (`z`, `ze`) straight from
   `~/gitbase/example/beam`; on the target the checkout does not exist.
3. **uv tools and npm globals** — `sccs`, `odoodev`, `cao`, `@playwright/cli`,
   `less` … are installed per host by hand.
4. **Fisher plugins** — `fish_plugins` syncs, but `fisher update` is never run.

The two hosts have one direction of truth: the live workstation is the source,
the second Mac is a mirror. Software present only on the mirror is to be removed,
after confirmation.

## Decision

Extend `sccs doctor` (not a new command group — see the feedback rule "extend
before adding a command group"). The doctor already has the exact shape needed:
`check` reports drift, `install` adds what is missing, `optimize --strict` offers
removals one confirmation at a time. Four new areas plug into that shape.

### Roles

- `doctor.mirror.source_host` names the live workstation by hostname
  (`socket.gethostname()` with any `.local`/domain suffix stripped, so
  `live-mac.local` and `live-mac` are the same host).
- The host whose name matches is the **source**; every other host is a
  **mirror**. Unset `source_host` disables the whole area — `doctor check` shows
  no mirror rows at all.
- Two hard rules: **the source is never modified from the inventory** and **a
  mirror never writes the inventory**. Both are enforced in code and pinned by
  tests, not left to the operator.

### Files

Policy is hand-edited and lives in `config.yaml`, distributed through the
existing `sccs_config` category:

```yaml
doctor:
  mirror:
    source_host: live-mac
    cleanup: true                     # allow removals under optimize --strict
    repos:
      - url: git@gitlab.example:org/beam.git
        path: ~/gitbase/example/beam
    ignore_brew: []                   # names the reconciliation never touches
    ignore_uv_tools: []
    ignore_npm: []
```

The **inventory** is machine-written and changes with every update, so it does
not belong in the hand-edited config (rewriting `config.yaml` drops comments).
It lives in `~/.config/sccs/inventory.yaml`, synced by a new single-file category
`sccs_inventory` (bidirectional, enabled by default, all platforms):

```yaml
version: 1
captured_at: 2026-09-15T10:12:00
captured_on: live-mac
brewfile: ~/.config/homebrew/Brewfile   # reference only — Brewfile stays its own category
uv_tools:
  - {name: sccs, version: 2.67.1}
  - {name: odoodev-equitania, version: 0.68.0}
npm_globals:
  - {name: "@playwright/cli", version: 0.1.18}
```

Homebrew stays in the Brewfile (already synced as `homebrew_bundle`); Fisher
needs no inventory because `fish_plugins` already syncs.

### Capture on the source

`sccs doctor update` on the source rewrites both the Brewfile
(`brew bundle dump --file <path> --force`; Homebrew 7 writes descriptions by default and rejects `--describe`) and `inventory.yaml`
(`uv tool list`, `npm ls -g --depth=0 --json`). `doctor check` on the source
compares Brewfile and inventory against the live state and reports
`stale — run sccs doctor update` instead of staying silent. That is the missing
piece behind the drifted Brewfile.

### Reconciliation on a mirror

`doctor check` reports per area: **missing**, **extra**, **version differs**.

| Area | Truth | Missing / differs → `install` | Extra → `optimize --strict` |
|---|---|---|---|
| Homebrew | Brewfile | `brew bundle install --file <path> --no-upgrade`; taps included | `brew uninstall <name>` / `brew uninstall --cask <name>` / `brew untap <tap>` — one action each, never `brew bundle cleanup` |
| uv tools | inventory | `uv tool install <name>==<version> --reinstall` | `uv tool uninstall <name>` |
| npm globals | inventory | `npm install -g <name>@<version>` | `npm uninstall -g <name>` |
| repos | policy | missing → `git clone <url> <path>`; behind and clean → `git -C <path> pull --ff-only` | never removed |
| Fisher | `fish_plugins` | `fish -c 'fisher install <name>'` per missing plugin | `fish -c 'fisher remove <name>'` per extra — never `fisher update`, which removes unlisted plugins as a side effect |

Rules the table does not show:

- Homebrew cannot pin versions at all; the install path uses `--no-upgrade`, so
  parity there means "same packages", not "each at its current version".
  uv and npm are pinned to the source's version.
- Homebrew *extras* are computed against `brew leaves --installed-on-request` (what `brew bundle dump` writes) and
  `brew list --cask`, never against the full dependency closure, so a dependency
  pulled in by a Brewfile entry is never offered for removal.
- A repo with local modifications (`git status --porcelain` non-empty) is
  reported as `modified` and never touched, in either direction.
- `npm`, `corepack` and the uv tool `sccs` itself are hard-excluded from removal.
- `fisher update` is never emitted: with no arguments it uninstalls every plugin
  absent from `fish_plugins`, which would be a removal on the install path
  (found in review, 15.09.2026). Missing plugins are installed one by one,
  extras removed one by one under `optimize --strict`.
- Long-running actions carry their own timeout (`DoctorAction.timeout`):
  `brew bundle install` 1800 s, `git clone` 900 s; everything else keeps the
  doctor's default of 300 s.
- `cleanup: false` hides the removal actions even under `--strict`.

### Safety

- Every command goes through `doctor/runner.py` (`shell=False`, `stdin=DEVNULL`,
  allowlisted argv). Package names are validated with the existing
  allowlist pattern (no leading `-`); versions must match a semver-ish regex.
- Repo URLs are restricted to `git@host:path` and `https://` at validation time;
  target paths must resolve under `$HOME`.
- Removals only under `optimize --strict`, each its own confirm (default No),
  identical to foreign plugins/MCP servers today. `--yes` confirms every action
  in the plan, removals included — exactly as it does for foreign plugins in
  `optimize --strict` today; the protection is that removals never enter a plan
  outside `--strict` with `cleanup: true`.
- The source host never gets install or removal actions from this area.

### Reporting

- The doctor table gets a **Mirror** block: one row per area with the counts
  (`3 missing · 1 extra · 2 version`), and on the source a single row
  `source · inventory current` / `source · inventory stale`.
- The non-strict `optimize` run prints one advisory block when a mirror has
  extras and `cleanup` is on; a source never gets it. `optimize` splices the
  same actions as `update`, so on the source it still captures the inventory.
- `doctor check --json` gains a `mirror` key: `role`, `source_host`, and per
  area the lists `missing`, `extra`, `version_differs`, plus `repos` with
  `state` ∈ {`ok`, `missing`, `behind`, `modified`, `not_a_repo`}. sccs-gui
  consumes this.

### Code layout

- `sccs/doctor/mirror.py` — `MirrorConfig` (schema), `MirrorRole`, detectors
  (`BrewDetector`, `UvToolDetector`, `NpmGlobalDetector`, `RepoDetector`,
  `FisherDetector`), inventory read/write, and the action builders
  `_mirror_install_actions`, `_mirror_update_actions`, `_mirror_remove_actions`.
- `sccs/doctor/runner.py` — new wrappers `run_brew`, `run_uv_tool`, `run_npm_global`,
  `run_git_mirror`, `run_fisher`; allowlist extended for `brew`, `fisher`.
- `sccs/doctor/schema.py` — `DoctorConfig.mirror: MirrorConfig | None`.
- `sccs/config/defaults.py` — new category `sccs_inventory`.
- `sccs/cli.py` — `_collect_doctor_statuses` gains `mirror`; `doctor check/install/update/optimize` wire it through; `--json` payload extended.
- `docs/usage/doctor.md` (DE+EN), `usage/AGENT.md`, CLI reference.

### Tests

- Detectors against fake command output (`brew bundle check`, `brew leaves`,
  `uv tool list`, `npm ls -g --json`, `git status -sb`, `fisher list`).
- Three policy tests: the source never receives install/remove actions; a mirror
  never writes `inventory.yaml`; removal actions exist only in the strict
  optimize plan and disappear under `cleanup: false`.
- Validators: rejected URL schemes, path outside home, package name with leading
  dash, `npm`/`uv` never in a removal list.
- Homebrew extras never include a transitive dependency.

## Prerequisite: 2.67.2 sync fix (approved 15.09.2026)

Found while diagnosing the drift; independent of the mirror feature but must
land first, otherwise `scripts/` is still missing on the mirror after everything
above runs:

1. `fish_config.include` gains `scripts/*.py` and `functions/*.py` — the
   21 fish helpers that call `scripts/shell_safety.py` never reached the mirror.
2. `fish_functions` is disabled by default: it covered the same files as
   `fish_config` (`functions/*.fish`) with a second, independent sync state, which
   turns any divergence into a silent conflict. `fish_functions_macos` stays — it
   alone covers `functions/macos/`.
3. Same change in the operator's `config.yaml` (reaches the mirror via `sccs_config`).

## Out of scope

- Versions for Homebrew packages.
- Mirroring in the other direction, or more than one source.
- Odoo databases, Docker/Apple-Container images, application data.
- Anything under `~/.claude/` — already covered by the existing categories.
