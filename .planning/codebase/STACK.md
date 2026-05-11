# Technology Stack

**Analysis Date:** 2026-05-11

## Languages

**Primary:**
- Python 3.10–3.13 — all application code under `sccs/`

**Secondary:**
- YAML — configuration (`~/.config/sccs/config.yaml`), state files
- TOML — project metadata (`pyproject.toml`)

## Runtime

**Environment:**
- CPython 3.10+ (minimum enforced in `pyproject.toml` `requires-python = ">=3.10"`)
- Cross-platform: macOS, Linux, Windows (Windows skips POSIX permission checks)

**Package Manager:**
- UV (project rule — never pip)
- Lockfile: not present; `pyproject.toml` is the single source of truth

## Frameworks

**Core:**
- Click `>=8.1.0,<9.0.0` — CLI command groups and argument parsing (`sccs/cli.py`)
- Pydantic `>=2.0.0,<3.0.0` — config/schema validation (`sccs/config/schema.py`, `sccs/doctor/schema.py`)
- PyYAML `>=6.0,<7.0.0` — YAML load/save (`sccs/config/loader.py`, state files)
- Rich `>=13.0.0,<15.0.0` — terminal output, tables, panels (`sccs/output/console.py`, `sccs/output/diff.py`)
- questionary `>=2.0.0,<3.0.0` — interactive confirm prompts in installer (`sccs/doctor/installer.py`)

**Testing:**
- pytest `>=8.0.0` — test runner, config in `pyproject.toml` `[tool.pytest.ini_options]`
- pytest-cov `>=6.0.0` — coverage; floor `fail_under = 66` (`pyproject.toml`)

**Build/Dev:**
- hatchling — build backend (`pyproject.toml` `[build-system]`)
- ruff `>=0.11.0` — linter + formatter, line-length 120, target py310 (`pyproject.toml` `[tool.ruff]`)
- mypy `>=1.14.0` — static type checking, `python_version = "3.10"` (`pyproject.toml` `[tool.mypy]`)
- pre-commit `>=4.0.0` — git hooks
- bandit `>=1.9.0` — security linting (`pyproject.toml` dev deps)
- types-PyYAML `>=6.0.0` — mypy stubs

## Key Dependencies

**Critical:**
- `click` — entry point wiring; `sccs/cli.py` registers all command groups; `pyproject.toml` `[project.scripts]` maps `sccs` → `sccs.cli:cli`
- `pydantic` — `SccsConfig`, `SyncCategory`, `DoctorConfig`, `NpxToolSpec`, `PluginSpec` etc. all use `BaseModel.model_validate()`
- `PyYAML` — config read/write in `sccs/config/loader.py`; state persistence in `sccs/sync/state.py` and `sccs/doctor/state.py`
- `rich` — all terminal output; `sccs/output/console.py` wraps a `Console` instance
- `questionary` — `_confirm()` in `sccs/doctor/installer.py` for interactive install prompts

**Infrastructure:**
- `subprocess` (stdlib) — all external-binary calls via `sccs/doctor/runner.py:_run()` and `sccs/git/operations.py:_run_git()`
- `shutil` (stdlib) — `which()` wrapper in `sccs/doctor/runner.py`; `copytree()` in `sccs/doctor/installer.py:_sync_bundled_skill()`
- `pathlib` (stdlib) — universal path handling throughout
- `hashlib` (stdlib) — SHA-256 content hashing in `sccs/utils/hashing.py`

## Configuration

**Environment:**
- `SCCS_CONFIG` — overrides config file path
- `HOME` — user home directory for path expansion
- `PLAYWRIGHT_BROWSERS_PATH` — overrides Playwright browser cache root (detected in `sccs/doctor/detectors.py:_resolve_playwright_cache()`)
- `PATH` — inspected directly via `os.environ` in `sccs/doctor/detectors.py:PathPrefixDetector`

**Build:**
- `pyproject.toml` — single config file for build, dependencies, ruff, mypy, pytest, coverage
- No `setup.py`, no `requirements.txt`, no `requirements-dev.txt`

## Platform Requirements

**Development:**
- UV installed (`uv venv && uv pip install -e ".[dev]"`)
- Python 3.10+
- git binary on PATH (required for `sccs/git/operations.py`)

**Production:**
- Distributed via PyPI as `sccs` package
- Entry point: `sccs` CLI binary installed by pip/uv
- Runtime deps only: click, rich, PyYAML, pydantic, questionary

---

*Stack analysis: 2026-05-11*
