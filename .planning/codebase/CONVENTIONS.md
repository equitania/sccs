# Coding Conventions

**Analysis Date:** 2026-05-26

## Naming Patterns

**Files:**
- Module files: `snake_case.py` (e.g. `sync_engine.py`, `fish_to_pwsh.py`)
- Test files: `test_<module>.py` (e.g. `test_doctor.py`, `test_git_operations.py`)
- No barrel index abuse — each module exports only what it owns

**Functions:**
- Public functions: `snake_case` (e.g. `load_config`, `expand_path`, `safe_copy`)
- Private helpers: `_snake_case` with leading underscore (e.g. `_run_git`, `_validate_head`, `_run`, `_make_status_set`)
- Class methods: `snake_case` (e.g. `get_enabled_categories`, `is_platform_match`)
- Pydantic classmethods: named `_validate_<field>` or `expand_<thing>`

**Variables:**
- `snake_case` throughout; no abbreviations beyond standard (`cfg`, `mgr`, `spec`)
- Boolean flags: `is_` or `has_` prefix (`is_platform_match`, `has_problems`, `has_issues`)

**Classes:**
- `PascalCase` for all classes (e.g. `SyncEngine`, `DoctorConfig`, `PluginSpec`, `CategoryHandler`)
- Enums: `PascalCase` class, `UPPER_SNAKE` members (e.g. `ActionType.COPY_TO_REPO`, `SyncMode.BIDIRECTIONAL`)
- Dataclasses: `PascalCase`, prefer `@dataclass` for simple result containers (`SyncResult`, `CategorySyncResult`)

**Constants:**
- Module-level: `UPPER_SNAKE_CASE` (e.g. `DEFAULT_CLAUDE_PLUGINS`, `NODE_INSTALL`, `_SAFE_NAME_PATTERN`)

**Compiled Regex:**
- `_UPPER_SNAKE_PATTERN` with leading underscore for module-private compiled regex (e.g. `_GIT_REMOTE_PATTERN` in `sccs/config/schema.py`, `_SAFE_HEAD_PATTERN` in `sccs/doctor/runner.py`)

## Code Style

**Formatter:** ruff format
- Quote style: **double quotes**
- Line length: **120 characters**
- Applied via pre-commit hook (`ruff-format` id in `/.pre-commit-config.yaml`)

**Linter:** ruff check with `--fix`
- Selected rules: `E`, `F`, `W`, `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM` (simplify)
- Ignored: `E203`, `E266`, `SIM102`, `SIM105`, `SIM108`
- Applied via pre-commit hook (`ruff` id)

**Type checker:** mypy
- `python_version = "3.10"` target (in `pyproject.toml`)
- `warn_return_any = true`, `warn_unused_configs = true`
- `ignore_missing_imports = true`
- Applied via pre-commit hook (runs `mypy sccs/` — tests excluded)

**Pre-commit hooks** (`.pre-commit-config.yaml`):
- `ruff` (lint + auto-fix)
- `ruff-format`
- `mypy sccs/`
- `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-added-large-files`

## Import Organization

**Order** (enforced by ruff isort with `known-first-party = ["sccs"]`):
1. `from __future__ import annotations` (when used — doctor modules use it for forward references)
2. Standard library (`re`, `sys`, `pathlib`, `subprocess`, `dataclasses`, etc.)
3. Third-party (`click`, `rich`, `pydantic`, `yaml`, `questionary`)
4. First-party `sccs.*` — absolute imports only

**Path Aliases:** None. All imports are absolute (`from sccs.sync.engine import SyncEngine`).

**Late/Lazy imports:** Used inside Click command handlers for heavy optional subsystems (doctor, docs, transfer, integrations) to keep startup fast:
```python
# Inside command handler, not at module top
from sccs.docs.generator import DocsGenerator
docs_gen = DocsGenerator(config)
```
Also used in `sccs/__init__.py` via `__getattr__` for public API lazy loading.

## Module Header Convention

Every source module begins with a short comment block:
```python
# SCCS <Module Name>
# <One-sentence description>
```
Examples from codebase: `# SCCS Doctor Subprocess Runner`, `# SCCS Path Utilities`, `# SCCS Sync Engine`.

## Version Header Convention

`sccs/__init__.py` carries the authoritative version comment — increment on every release:
```python
# SCCS - SkillsCommandsConfigsSync
# Unified YAML-configured synchronization for Claude Code files
#
# Version: 2.32.1
# Date: 25.05.2026
```
Version must also match `pyproject.toml → [project] version`. Date format: `DD.MM.YYYY`.

## Error Handling

**Custom Exception Classes:**
Each major subsystem defines its own exception with an identical constructor signature:
- `GitError` — `sccs/git/operations.py`
- `DoctorError` — `sccs/doctor/runner.py`

Both carry `message: str`, `returncode: int = 1`, `stderr: str = ""`.

**CLI error pattern** (used consistently in all Click commands):
```python
try:
    config = load_config()
except FileNotFoundError as e:
    console.print_error(str(e))
    sys.exit(1)
```

**Non-fatal errors:** bare `except Exception: pass` only where the feature is cosmetic and non-blocking. Always annotated with `# noqa: BLE001` and a comment explaining why.

**Security-critical validation:**
- All subprocess `argv[0]` values validated against an allowlist regex before exec (`_validate_head` in `sccs/doctor/runner.py`, `_GIT_REMOTE_PATTERN` in `sccs/config/schema.py`)
- Pydantic `@field_validator` for schema-level input sanitisation
- `subprocess` calls: always `shell=False`, command as `list[str]`, `stdin=subprocess.DEVNULL`
- `# nosec B404` / `# nosec B603` comments suppress bandit false positives on intentional subprocess use

## Logging

**Framework:** `sccs/utils/logging.py` — wraps Python `logging` via `configure_logging()`

**Patterns:**
- Console output goes through `Console` (Rich-based), never `logging`
- `logging` is used only for file-based output when `output.log_file` is configured
- Console output methods: `console.print_info()`, `console.print_success()`, `console.print_error()`, `console.print_warning()`
- Rich markup used directly in `console.print(f"[bold cyan]...[/bold cyan]")` for formatted output

## Comments

**Module headers:** `# SCCS <Name>\n# <description>` instead of module docstrings.

**Inline comments** explain:
- Security decisions: `# Regression guard for the v2.22.x Debian hang`
- Protocol contracts: HARD RULES block at top of `sccs/doctor/runner.py`
- Non-obvious logic in diff/merge/state code

**Docstrings:**
- Public class methods use Google-style with `Args:` and `Returns:`:
```python
def get_handler(self, category_name: str) -> CategoryHandler | None:
    """
    Get handler for a category.

    Args:
        category_name: Name of the category.

    Returns:
        CategoryHandler or None if category doesn't exist.
    """
```
- Short private helpers have one-line docstrings or none.

**noqa markers:**
- `# nosec B404` / `# nosec B603` — bandit false-positive suppression
- `# noqa: BLE001` — intentional broad exception catch

## Type Annotations

**Policy:** Full type annotations on all public functions and class attributes.
- Use `str | None` (union syntax), not `Optional[str]` — Python 3.10+ target
- `from __future__ import annotations` in doctor modules for forward references
- Lowercase generics: `list[str]`, `dict[str, Any]`, `tuple[str, ...]`
- Return type `None` always explicit on CLI handlers: `def sync(...) -> None:`
- `TYPE_CHECKING` guard for circular-import-only imports (excluded from coverage in `pyproject.toml`)

## Pydantic Models

All config models inherit `BaseModel` (Pydantic v2):
- `Field(description="...")` on every field — serves as inline documentation
- `@field_validator` with `@classmethod` for input sanitisation and `~` path expansion
- `model_validate()` for dict-to-model conversion (not positional constructor)
- Mutable defaults: `Field(default_factory=lambda: ["*"])`

## Function Design

**Size:** Click command handlers are long by design — they own the full workflow. Business logic is delegated to engine/handler classes. Utility functions are short (10–30 lines).

**Parameters:**
- Keyword-only for optional flags in internal helpers: `def _run(cmd, *, check=True, capture=True, timeout=60)`
- Click options always include `help=` string

**Return Values:**
- Result objects (`SyncResult`, `InstallPlan`) instead of tuples for multi-value returns
- `bool` return for simple success/failure in git operations (e.g. `push()`, `pull()`)
- `None` explicit on CLI handlers (enforced by mypy)

## Module Design

**Exports:**
- `__init__.py` files expose a curated public API via `__all__`
- Sub-package `__init__.py` re-exports key names (no wildcard imports)
- `sccs/__init__.py` uses `__getattr__` lazy loading for startup performance

**Barrel Files:**
- Each sub-package has `__init__.py` that re-exports specific names
- Never `from module import *`

## CLI Design (Click)

- Top-level `cli` group with `--verbose` / `--no-color` global options
- All subcommands use `@click.pass_context` and access `ctx.obj["console"]`
- Command groups: `config`, `categories`, `convert`, `docs`, `doctor`, `integrations`
- Exit codes: always explicit — `sys.exit(0)` success, `sys.exit(1)` error; never rely on implicit exit
- Non-TTY / CI paths: interactive prompts guarded with `sys.stdout.isatty()`

## Language Policy

**Code and documentation:** English only (variable names, docstrings, comments, commit messages).
**User-facing console strings:** English in code; German for platform hints emitted to interactive TTY (e.g. `_print_platform_hint` in `sccs/cli.py`).

---

*Convention analysis: 2026-05-26*
