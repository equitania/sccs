# Coding Conventions

**Analysis Date:** 2026-05-11

## Naming Patterns

**Files:**
- Snake_case for all Python modules: `sync_engine.py`, `category.py`, `config_loader.py`
- Test files prefixed `test_`: `test_doctor.py`, `test_config.py`, `test_sync.py`
- Schema modules named `schema.py` per sub-package: `sccs/config/schema.py`, `sccs/doctor/schema.py`

**Classes:**
- PascalCase throughout: `SyncEngine`, `CategoryHandler`, `DoctorConfig`, `PluginSpec`
- Status result objects are frozen dataclasses (not Pydantic): `NodeStatus`, `ClaudeCliStatus`, `PluginStatus`
- Pydantic models for config/schema: `SccsConfig`, `SyncCategory`, `DoctorConfig`, `PluginSpec`
- Enums: PascalCase class, UPPER_CASE members: `SyncMode.BIDIRECTIONAL`, `ItemType.DIRECTORY`

**Functions / methods:**
- Snake_case: `get_enabled_categories()`, `build_install_plan()`, `execute_plan()`
- Private helpers with leading underscore: `_validate_head()`, `_run()`, `_validate_safe_name()`
- Detector entry point always `get_status()` (single) or `get_statuses(list)` (batch)
- `effective_*()` methods on `DoctorConfig` resolve override-or-default lists: `effective_plugins()`, `effective_npx_tools()`

**Variables:**
- Snake_case: `config_path`, `temp_home`, `dry_run`
- Single-letter names forbidden (ruff E741): use `lbl` not `l` in generator expressions

**Constants / module-level:**
- UPPER_SNAKE for compiled regexes and named sets: `_SAFE_NAME_PATTERN`, `_VALID_PATH_KINDS`
- `DEFAULT_*` prefix for bundled defaults: `DEFAULT_CLAUDE_PLUGINS`, `DEFAULT_NPX_TOOLS`

## Code Style

**Formatter:** ruff format
- Quote style: **double quotes** (`"string"`, not `'string'`)
- Line length: **120 characters**
- Target Python: 3.10

**Linter:** ruff lint
- Rule sets: `E`, `F`, `W`, `I`, `UP`, `B`, `SIM`
- Ignored: `E203`, `E266`, `SIM102`, `SIM105`, `SIM108`
- isort integrated via ruff: `known-first-party = ["sccs"]`

**Type checker:** mypy
- `python_version = "3.10"`
- `warn_return_any = true`, `warn_unused_configs = true`
- `ignore_missing_imports = true` (not strict mode)
- `from __future__ import annotations` used in modules that need forward references

## Import Organization

**Order (enforced by ruff/isort):**
1. `from __future__ import annotations` (when needed)
2. Standard library (`os`, `re`, `sys`, `pathlib`, `dataclasses`, `subprocess`)
3. Third-party (`click`, `pydantic`, `rich`, `yaml`, `questionary`)
4. First-party sccs (`from sccs.config.schema import ...`)

**Path aliases:** None — all imports use full dotted paths from `sccs.*`

**Lazy imports inside methods:** Used in `DoctorConfig.effective_*()` methods to break circular imports:
```python
def effective_plugins(self) -> list[PluginSpec]:
    from sccs.doctor.defaults import DEFAULT_CLAUDE_PLUGINS  # lazy
    ...
```

## Pydantic Model Patterns

**Base class:** `pydantic.BaseModel` (Pydantic v2, `>=2.0.0`)

**Validation entry point:** `SccsConfig.model_validate(yaml_data)` — never direct constructor for dicts

**Field definitions:**
```python
name: str = Field(description="...")
optional_field: str | None = Field(default=None, description="...")
list_field: list[str] = Field(default_factory=list, description="...")
bounded_int: int = Field(default=20, ge=10, le=99, description="...")
```

**Field validators — always `@field_validator` + `@classmethod`:**
```python
@field_validator("name")
@classmethod
def _validate_name(cls, v: str) -> str:
    return _validate_safe_name(v, "Plugin name")
```

**Override-or-default pattern** (`None` = keep defaults, list = full replacement):
```python
plugins: list[PluginSpec] | None = Field(default=None, ...)
extra_plugins: list[PluginSpec] = Field(default_factory=list, ...)
```
Resolved via `effective_*()` methods — never inline in callers.

**Path expansion:** `~` expanded in `SyncCategory.local_path` via field validator — callers always receive expanded paths.

## Frozen Dataclass Patterns (Status Objects)

Detector results use `@dataclass` (not Pydantic) — read-only inspection results, not config:

```python
@dataclass
class NodeStatus:
    installed: bool
    version: str | None
    major: int | None
    meets_minimum: bool
    install_hint: NodeInstallSpec
    platform: str
```

Located in `sccs/doctor/detectors.py`. All status dataclasses follow the same structure:
- `installed: bool` or `available: bool` as first field
- Optional string fields typed `str | None`
- No default values on required fields

## Security Validation Patterns

**Argument-injection guard** — used across `sccs/doctor/schema.py`, `sccs/doctor/runner.py`, `sccs/config/schema.py`:

```python
_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./@\-]*$")

def _validate_safe_name(value: str, field: str) -> str:
    if value.startswith("-"):
        raise ValueError(f"{field} must not start with '-': {value!r}")
    if not _SAFE_NAME_PATTERN.match(value):
        raise ValueError(f"{field} contains invalid characters: {value!r}")
    return value
```

**Path safety** — reject shell metacharacters (`;`, `|`, `&`, `$`, `` ` ``, `\n`, `\r`):
```python
body = v[1:] if v.startswith("~") else v
if any(ch in body for ch in (";", "|", "&", "$", "`", "\n", "\r")):
    raise ValueError(f"path contains shell metacharacters: {v!r}")
```

**`sudo` ban** — `NodeInstallSpec._validate_cmd` explicitly rejects `sudo` as argv head.

**Git remote guard** — `SccsConfig` rejects option-like remote names (`--upload-pack=…`, `-u`) via Pydantic validator.

## Error Handling

**Domain error class:** `DoctorError` in `sccs/doctor/runner.py` — raised for subprocess failures, empty commands, missing binaries, security rejections. Never raises raw `subprocess.SubprocessError`.

**Config validation:** Pydantic `ValidationError` propagates to CLI layer; callers use `pytest.raises(ValidationError)` in tests.

**File not found:** `load_config()` raises `FileNotFoundError` (not wrapped).

**Validate-config return pattern:** `(bool, list[str])` tuple from `validate_config_file()` — no exceptions for invalid YAML, errors collected into list.

## Subprocess Policy

- All subprocesses via `_run()` in `sccs/doctor/runner.py`
- `stdin=subprocess.DEVNULL` always — prevents interactive prompts hanging
- `capture_output=True` always
- No shell=True anywhere
- `FileNotFoundError` caught and re-raised as `DoctorError("Command not found: ...")`

## Logging / Output

- `rich` console via `sccs/output/console.py` — never bare `print()`
- Verbose mode controlled by `config.output.verbose`

## Comments

**Module-level docstring:** `# SCCS <Module Name>\n# <One-line description>` — plain comment, not triple-quoted
**Inline rationale comments:** Used extensively for security decisions and regression guards:
```python
# Defensive hardening: any doctor subprocess that asks for stdin
# should fail fast instead of hanging the parent for `timeout` seconds.
```
**Class/method docstrings:** Triple-quoted, present on all public Pydantic models and detector classes.

## Git Commit Prefixes

- `[ADD]` — new features or extensions
- `[CHG]` — modifications to existing code
- `[FIX]` — bug fixes

**Version header rule:** Increment version in `pyproject.toml`, `sccs/__init__.py`, and `CLAUDE.md` header simultaneously. Format: `DD.MM.YYYY` for dates. New features require a version bump before tagging.

---

*Convention analysis: 2026-05-11*
