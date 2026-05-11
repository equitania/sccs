# Testing Patterns

**Analysis Date:** 2026-05-11

## Test Framework

**Runner:** pytest `>=8.0.0`
- Config: `pyproject.toml` `[tool.pytest.ini_options]`
- `testpaths = ["tests"]`
- `python_files = ["test_*.py"]`
- `python_functions = ["test_*"]`
- `addopts = "-v --tb=short"`

**Assertion library:** pytest built-in assertions (no unittest.TestCase assertions)

**Coverage:** pytest-cov `>=6.0.0`
- Source: `sccs/`
- Omit: `tests/*`, `sccs/__main__.py`
- Minimum: **66%** (enforced via `fail_under`)
- Missing lines shown: `show_missing = true`
- Excluded from coverage: `pragma: no cover`, `if __name__ == .__main__.`, `if TYPE_CHECKING:`

**Run Commands:**
```bash
pytest                    # Run all tests
pytest -v                 # Verbose (default via addopts)
pytest --cov=sccs         # With coverage
pytest tests/test_doctor.py  # Single test file
pytest tests/test_doctor.py::TestNodeDetector  # Single class
```

## Test File Organization

**Location:** All tests in `tests/` directory (not co-located with source)

**Naming:** `test_<module_or_feature>.py`

**Current test files:**
- `tests/conftest.py` — shared fixtures
- `tests/test_config.py` — config schema, loading, validation
- `tests/test_sync.py` — sync engine
- `tests/test_doctor.py` — doctor detectors, installer, runner security
- `tests/test_settings.py` — settings.json merge logic
- `tests/test_cli.py` — Click CLI
- `tests/test_git_operations.py` — git commands
- `tests/test_hashing.py` — SHA256 utilities
- `tests/test_migration.py` — config migration
- `tests/test_paths_security.py`, `tests/test_importer_security.py` — security regression tests
- `tests/test_platform.py`, `tests/test_platform_utils.py` — platform detection
- `tests/test_conflict_resolution.py`, `tests/test_merge.py`, `tests/test_diff.py`
- `tests/test_transfer.py`, `tests/test_convert.py`, `tests/test_console.py`
- `tests/test_docs.py`, `tests/test_integrations.py`

## Test Structure

**Suite organization — class-based, grouped by subject:**
```python
class TestSchemaValidation:
    def test_plugin_spec_rejects_leading_dash(self): ...
    def test_plugin_spec_accepts_scoped_npm_name(self): ...

class TestNodeDetector:
    def test_missing_node_returns_not_installed(self, monkeypatch): ...
    def test_current_node_passes(self, monkeypatch): ...
```

**Section delimiters** used in larger test files:
```python
# --------------------------------------------------------------------------- #
# Schema validation                                                           #
# --------------------------------------------------------------------------- #
```

**Test naming convention:** `test_<what>_<expected_outcome>` or `test_<scenario>`:
- `test_missing_node_returns_not_installed`
- `test_rejects_option_like_remote`
- `test_current_node_passes`

## Fixtures (tests/conftest.py)

**`temp_dir`** → `Generator[Path, None, None]`
- Wraps `tempfile.TemporaryDirectory()`
- Use for any file I/O test

**`temp_home(temp_dir, monkeypatch)`** → `Path`
- Creates `<temp_dir>/home/`, sets `HOME` env var
- Foundation for all tests that expand `~`

**`mock_claude_dir(temp_home)`** → `Path`
- Full `~/.claude/` directory structure with subdirs: `skills/`, `commands/`, `hooks/`, `scripts/`, `mcp/`
- Writes all framework files (`CLAUDE.md`, `COMMANDS.md`, etc.) with test content
- Creates one sample skill (`test-skill/SKILL.md`) and one sample command

**`mock_repo(temp_dir)`** → `Path`
- Bare repo directory with `.claude/framework/`, `.claude/skills/`, `.claude/commands/`

**`sample_config(temp_home, mock_repo)`** → `dict`
- Full YAML-ready config dict with three categories: `claude_framework`, `claude_skills`, `claude_commands`
- `auto_commit: False`, `auto_push: False`

**`config_file(temp_home, sample_config)`** → `Path`
- Writes `sample_config` to `~/.config/sccs/config.yaml` via `yaml.dump()`

**`state_file(temp_home)`** → `Path`
- Returns path `~/.config/sccs/.sync_state.yaml` (creates parent dirs)

**Local fixtures in test files** (not in conftest):
```python
# tests/test_settings.py
@pytest.fixture
def settings_dir(tmp_path: Path) -> Path: ...

@pytest.fixture
def settings_file(settings_dir: Path) -> Path: ...
```

## Mocking Patterns

**`monkeypatch.setattr`** — primary tool for replacing module-level functions:
```python
# Replace a runner function with a lambda
monkeypatch.setattr("sccs.doctor.detectors.run_node_version", lambda: None)
monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: "/usr/local/bin/claude")
```

**`monkeypatch.setenv`** — for environment variable tests:
```python
monkeypatch.setenv("HOME", str(home))
monkeypatch.setenv("SCCS_CONFIG", str(config_file))
```

**`unittest.mock.patch`** — used when call args inspection is needed:
```python
with patch("sccs.doctor.runner.subprocess.run", return_value=fake) as run_mock:
    _run(["echo", "x"])
kwargs = run_mock.call_args.kwargs
assert kwargs["stdin"] is subprocess.DEVNULL
```

**Synthetic CLI output** — detectors that parse CLI output (`ClaudePluginDetector`) accept raw string directly, no subprocess call needed:
```python
SAMPLE_OUTPUT = """Installed plugins:
  ❯ claude-mem@thedotmack
    Version: 12.6.0
"""
detector = ClaudePluginDetector(raw_output=SAMPLE_OUTPUT)
statuses = detector.get_statuses([PluginSpec(name="claude-mem")])
```
This is the canonical pattern for testing all parser/detector logic without spawning real processes.

**What to mock:**
- `run_node_version`, `run_claude_plugin_list`, `which` — always mock in detector unit tests
- `subprocess.run` — only when verifying call kwargs (e.g., `stdin=DEVNULL` regression)

**What NOT to mock:**
- Pydantic validation — tested by constructing models directly and catching `ValidationError`
- File I/O — use `temp_dir`/`tmp_path` fixtures instead

## Parametrize Pattern

Used for allowlist/blocklist validation tests:
```python
@pytest.mark.parametrize(
    "bad_remote",
    [
        "--upload-pack=/tmp/evil",
        "-u",
        "origin; rm -rf /",
        "origin space",
        "",
    ],
)
def test_rejects_option_like_remote(self, temp_dir: Path, bad_remote: str):
    with pytest.raises(ValidationError):
        SccsConfig(repository={"path": str(temp_dir), "remote": bad_remote}, sync_categories={})

@pytest.mark.parametrize("good_remote", ["origin", "upstream", "fork-2", "my_remote"])
def test_accepts_normal_remote(self, temp_dir: Path, good_remote: str):
    config = SccsConfig(repository={"path": str(temp_dir), "remote": good_remote}, sync_categories={})
    assert config.repository.remote == good_remote
```

## Doctor Detector Tests

**Pattern:** Construct detector with synthetic state, call `get_status()` / `get_statuses()`, assert fields.

**Node detection** (`TestNodeDetector`):
- Monkeypatch `run_node_version` to return a version string or `None`
- Pass `platform_name=` explicitly: `"macos"`, `"linux"`, `"windows"`
- Assert `status.installed`, `status.meets_minimum`, `status.install_hint.cmd`

**Plugin detection** (`TestClaudePluginDetector`):
- Class-level `SAMPLE_OUTPUT` / `REAL_OUTPUT` string constants — realistic `claude plugin list` text
- `ClaudePluginDetector(raw_output=...)` — no subprocess
- Test 4-tier detection: `"exact"`, `"alternative"`, `"bare"`, `"missing"`
- Word-boundary regression: shorter plugin name must not match longer name prefix

**Npx tool detection** (`TestNpxToolDetector`):
- Monkeypatch `which` to return path or `None`
- Use `DEFAULT_NPX_TOOLS` constants from `sccs.doctor.defaults` for end-to-end spec verification

**Runner security** (`TestRunnerSecurity`):
- Call private `_validate_head()` and `_run()` directly from `sccs.doctor.runner`
- `DoctorError` (not `ValidationError`) is the expected exception type
- Test `pytest.raises(DoctorError, match="Empty")` — use `match=` for error message verification

**Regression guards** — named tests that document why a specific invariant must hold:
```python
def test_default_npx_get_shit_done_uses_dash_y(self):
    # Without -y, npx prompts on stdout — hangs with capture_output=True
    spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "get-shit-done-cc")
    assert spec.invocation[1] == "-y"
```

## Settings Tests (test_settings.py)

Tests for `sccs/sync/settings.py` JSON merge logic use local `tmp_path` fixtures:
- `settings_file` fixture writes a real `settings.json` with existing content
- `_make_config()` helper constructs `SettingsEnsure` model
- Assertions on `result.success`, `result.keys_added`, `result.file_modified`
- Verifies non-destructive: existing keys never overwritten

## Error Testing

```python
# Pydantic ValidationError
with pytest.raises(ValidationError):
    PluginSpec(name="--evil")

# Domain error with message match
with pytest.raises(DoctorError, match="Empty"):
    _run([])

with pytest.raises(DoctorError, match="Command not found"):
    _run(["this-binary-does-not-exist-xyz123"])

# Standard Python exceptions
with pytest.raises(FileNotFoundError):
    load_config(temp_dir / "nonexistent.yaml")
```

## Helper Patterns

**Module-level factory helpers** (not fixtures) used within a single test file:
```python
def _make_config(target: Path, entries: dict, **kwargs) -> SettingsEnsure:
    return SettingsEnsure(target_file=str(target), entries=entries, ...)
```

**Iterating defaults** to pick a specific spec:
```python
spec = next(s for s in DEFAULT_NPX_TOOLS if s.name == "playwright-cli")
```

**Encoding:** All fixture file writes use `encoding="utf-8"` explicitly.

---

*Testing analysis: 2026-05-11*
