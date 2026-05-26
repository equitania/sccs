# Technology Stack

**Analysis Date:** 2026-05-26

## Languages

**Primary:**
- Python 3.10–3.13 — all application code under `sccs/`

**Secondary:**
- None — pure Python project

## Runtime

**Environment:**
- CPython 3.10+ (minimum declared in `pyproject.toml`)
- Tested against 3.10, 3.11, 3.12, 3.13 per classifiers

**Package Manager:**
- uv (development/install workflow per project CLAUDE.md)
- pip-compatible (wheel published via hatchling)
- Lockfile: `uv.lock` — present and committed

## Frameworks

**Core:**
- Click `>=8.1.0,<9.0.0` — CLI command group, options, arguments (`sccs/cli.py`)
- Pydantic `>=2.0.0,<3.0.0` — config schema validation (`sccs/config/schema.py`, `sccs/doctor/schema.py`, `sccs/transfer/manifest.py`)
- PyYAML `>=6.0,<7.0.0` — config file read/write (`sccs/config/loader.py`)
- Rich `>=13.0.0,<15.0.0` — terminal output, tables, progress (`sccs/output/console.py`, `sccs/output/diff.py`)
- questionary `>=2.0.0,<3.0.0` — interactive prompts during install/conflict resolution (`sccs/doctor/installer.py`, `sccs/transfer/ui.py`, `sccs/output/diff.py`)

**Testing:**
- pytest `>=8.0.0` — test runner; config in `pyproject.toml` `[tool.pytest.ini_options]`
- pytest-cov `>=6.0.0` — coverage; minimum 66% enforced (`[tool.coverage.report]`)

**Build/Dev:**
- hatchling — build backend declared in `[build-system]`
- ruff `>=0.11.0` — linting + formatting (replaces black/isort); line-length 120, target py310
- mypy `>=1.14.0` — type checking; `python_version = "3.10"`, `ignore_missing_imports = true`
- pre-commit `>=4.0.0` — git hooks
- bandit `>=1.9.0` — security linting (explicitly in dev dependencies)
- types-PyYAML `>=6.0.0` — mypy stubs

## Key Dependencies

**Critical:**
- `click` — the entire CLI surface lives on Click command groups/decorators
- `pydantic` v2 — config models are the schema contract; v1 API is NOT used
- `PyYAML` — all config I/O; `yaml.safe_load` / `yaml.dump` only
- `rich` — all formatted terminal output; no bare `print()` in CLI paths
- `questionary` — all interactive confirm/checkbox/select prompts

**Infrastructure:**
- Standard library only for subprocess, pathlib, json, shutil, hashlib, re, fnmatch, zipfile, tempfile, logging

## Configuration

**Environment:**
- `SCCS_CONFIG` — override config file path (read in `sccs/config/loader.py:get_config_path()`)
- `HOME` — resolved via `Path.home()` for all `~/` expansions
- `PLAYWRIGHT_BROWSERS_PATH` — override Playwright browser cache dir (read in `sccs/doctor/detectors.py:_resolve_playwright_cache()`)
- `PATH` — inspected directly via `os.environ["PATH"]` for doctor PATH checks (never mutated)

**Build:**
- `pyproject.toml` — single source of truth for dependencies, scripts, tool config, version
- `uv.lock` — reproducible installs
- No `requirements.txt` or `requirements-dev.txt` files

## Platform Requirements

**Development:**
- Python 3.10+
- uv for environment management
- git (for `sccs/git/operations.py` subprocess calls)
- Node.js ≥20 recommended for `sccs doctor` targets (detected at runtime, not required to build/test)

**Production:**
- macOS, Linux, Windows — all supported; platform-specific branches in `sccs/utils/platform.py`
- Claude Desktop integration: macOS only (`sccs/integrations/claude_desktop.py`)
- POSIX uid/gid permission checks: skipped on Windows (`sccs/doctor/detectors.py:PermissionDetector`)
- Fish shell config sync: requires `fish` binary on PATH

---

*Stack analysis: 2026-05-26*
