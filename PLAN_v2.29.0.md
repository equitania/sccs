# SCCS v2.29.0 — Doctor StatusLine Detector

**Status:** Planned
**Date:** 11.05.2026
**Trigger incident:** macOS-side Homebrew bumped Node 25.9.0_3 → 26.0.0; user's
`~/.claude/settings.json` contained a hardcoded Cellar path
(`/opt/homebrew/Cellar/node/25.9.0_3/bin/node`) and the Claude Code statusline
silently disappeared. `sccs doctor check` showed all-green because no detector
inspects `settings.json` → `statusLine.command`.

## Goal

Doctor verifies that the configured `statusLine` command in
`~/.claude/settings.json` is actually invokable. Three failure classes detected:

1. **MISSING_BINARY** — first argv token (e.g. node, python3, bash) not on PATH
   *or* literal path doesn't exist.
2. **MISSING_SCRIPT** — second argv token resolved as a script path but the
   file does not exist.
3. **STALE_CELLAR** — first argv token matches the Homebrew Cellar pattern
   `/opt/homebrew/Cellar/<pkg>/<version>/...` but the version directory is
   gone (Homebrew already cleaned it up after the upgrade).

A fourth class — **MISSING** — covers settings.json having no `statusLine` key
at all when the user has the `claude_statusline` sync category enabled.

Optional convenience class — **STALE_CELLAR** — auto-fixable via a doctor
install action that rewrites the command to use `/opt/homebrew/bin/<binary>`
(the symlink Homebrew maintains across versions).

## Out of scope

- Validating that the script *runs* without error (would require executing
  user code in doctor; too invasive).
- Parsing shell-quoted commands beyond the formats SCCS itself writes (we
  only need to recognise our own output and the common `"node" "script.js"`
  shape). Shell pipelines, env-var prefixes, etc. → status `OPAQUE` + skip.

## Schema additions (`sccs/doctor/schema.py`)

```python
class StatusLineCheckSpec(BaseModel):
    """Verify that ~/.claude/settings.json statusLine.command is invokable."""

    identifier: str = Field(
        description="Stable component-string slug for cascade engine.",
    )
    settings_path: str = Field(
        default="~/.claude/settings.json",
        description="Settings file to inspect (tilde-expanded at check-time).",
    )
    required: bool = Field(
        default=False,
        description=(
            "If True, missing statusLine key → MISSING status. "
            "If False, missing key → OK (statusline is opt-in). Default "
            "False to avoid pestering users who never wanted one."
        ),
    )
    auto_fix_stale_cellar: bool = Field(
        default=True,
        description=(
            "If True, doctor install offers to rewrite Cellar paths to "
            "/opt/homebrew/bin symlink equivalents."
        ),
    )

    @field_validator("identifier")
    @classmethod
    def _validate_identifier(cls, v: str) -> str:
        return _validate_safe_name(v, "StatusLine identifier")
```

Add `effective_status_line_checks()` method on `DoctorConfig` analogous to
`effective_path_prefix_checks()`. Add `status_line_checks` field with a single
default entry:

```python
DEFAULT_STATUS_LINE_CHECKS = [
    StatusLineCheckSpec(
        identifier="claude-statusline",
        settings_path="~/.claude/settings.json",
        required=False,
        auto_fix_stale_cellar=True,
    )
]
```

## Detector (`sccs/doctor/detectors.py`)

```python
@dataclass(frozen=True)
class StatusLineStatus:
    spec: StatusLineCheckSpec
    state: str  # "ok" | "missing" | "missing_binary" | "missing_script"
                # | "stale_cellar" | "opaque" | "no_settings_file"
    settings_path: str
    raw_command: str | None      # exactly what's in settings.json
    binary: str | None           # parsed first argv token
    script: str | None           # parsed second argv token (if file-like)
    detail: str                  # human-readable explanation


class StatusLineDetector:
    """Parse settings.json → statusLine.command, verify invokability.

    Parsing strategy (intentionally narrow):
      1. Read settings.json. If file absent → state=no_settings_file.
      2. Extract statusLine.command. If absent and not required → state=ok.
         If absent and required → state=missing.
      3. Tokenise with shlex.split(posix=True). Accept exactly the
         "<binary> <script> [<args>...]" shape. Anything more exotic
         (pipes, env prefixes, &&, $VAR not yet expanded) → state=opaque.
      4. First token: if it contains '/', check pathlib.Path(token).exists().
         Match Cellar pattern /opt/homebrew/Cellar/<pkg>/<version>/...
         → if version dir absent, state=stale_cellar.
         Otherwise use shutil.which() → if None, state=missing_binary.
      5. Second token (if present and looks like a path): tilde-expand,
         check existence → state=missing_script if absent.
      6. Otherwise state=ok.
    """
```

## Reporter integration (`sccs/doctor/reporter.py`)

Add `_status_line_row()` mirroring `_path_prefix_row()`:

- `state=ok` → green `OK`, detail = binary path
- `state=missing` (required) → red `FAIL`, detail = "statusLine key absent"
- `state=missing_binary` → red `FAIL`, detail = "binary not found: <token>"
- `state=missing_script` → red `FAIL`, detail = "script not found: <token>"
- `state=stale_cellar` → yellow `WARN`, detail =
  "Cellar path stale (Node upgraded?) — fix available"
- `state=opaque` → blue `INFO`, detail = "custom command shape, not checked"
- `state=no_settings_file` → grey `–`, detail = "no settings.json"

Row label: `statusline: claude` (single component, identifier-driven).

Wire `status_line_checks` parameter through `render_doctor_report()`,
`has_problems()`, `render_inline_summary()` — same pattern as `path_prefixes`.

## Installer / cascade integration (`sccs/doctor/installer.py`)

Single new action type: `_status_line_actions(status: StatusLineStatus)`.

- `state=stale_cellar` AND `spec.auto_fix_stale_cellar=True` →
  emits `DoctorAction(component="statusline:<id>", kind="auto_fix", ...)`
  whose execution path rewrites `settings.json` in-place:
  - Backup as `settings.json.bak-YYYYMMDD-HHMMSS` (same pattern as
    `settings_ensure.backup_before_modify`).
  - Replace `/opt/homebrew/Cellar/<pkg>/<version>/bin/<bin>` →
    `/opt/homebrew/bin/<bin>` in the command string.
  - Idempotent: re-running on already-fixed file is no-op.
- `state=missing_binary` / `state=missing_script` → manual block only
  (cannot safely guess the user's intent).
- `state=missing` (required) → manual block pointing to the
  `claude_statusline` sync category as the fix.

`blocks_downstream=False` for all — statusline failure doesn't cascade-block
plugin installs. Component string: `statusline:<identifier>`.

## CLI wiring (`sccs/cli.py`)

`_collect_doctor_statuses()` gains:

```python
status_line_checks = config.effective_status_line_checks()
status_line_statuses = StatusLineDetector().get_statuses(status_line_checks)
```

Pass through to `render_doctor_report`, `build_install_plan`,
`build_update_plan`.

## Tests (`tests/test_doctor.py`)

New `TestStatusLineDetector` class. Use `tmp_path` for synthetic settings.json
fixtures.

- `test_no_settings_file` → state=no_settings_file
- `test_no_status_line_key_optional` → state=ok (required=False)
- `test_no_status_line_key_required` → state=missing
- `test_ok_node_script` — symlink `node` exists, script exists → state=ok
- `test_missing_binary` — first token unresolvable → state=missing_binary
- `test_missing_script` — binary OK, script absent → state=missing_script
- `test_stale_cellar_pattern` — mock `/opt/homebrew/Cellar/node/X.Y.Z` absent
  → state=stale_cellar
- `test_opaque_pipeline` — command contains `|` or `&&` → state=opaque
- `test_auto_fix_rewrites_cellar` — execute install action, verify
  settings.json updated and backup created
- `test_auto_fix_idempotent` — running twice produces single fix

Target: 8–10 unit tests + 1 integration test through `sccs doctor check`
end-to-end on a fixture HOME.

## Documentation

- `docs/usage/doctor.md` — add `statusline` row to component tables (DE+EN),
  short section explaining detection classes.
- `RELEASE_NOTES.md` — v2.29.0 entry citing this incident (hardcoded Cellar
  path → stale after Homebrew Node bump).

## Version bumps

`pyproject.toml`, `sccs/__init__.py`, `CLAUDE.md` → `2.28.1` → `2.29.0`.

## Order of work (TDD-friendly)

1. Schema + defaults (no behaviour yet, just dataclasses).
2. Detector + unit tests on synthetic settings.json.
3. Reporter row + render tests.
4. Installer auto-fix action + tests.
5. CLI wiring.
6. End-to-end test via `sccs doctor check` against tmp HOME.
7. Docs + RELEASE_NOTES + version bump.
8. Quality gates: ruff, mypy, pytest, then commit + tag + PyPI.

Estimated diff: ~600 LoC added, ~30 LoC modified (CLI/reporter parameter
threading).
