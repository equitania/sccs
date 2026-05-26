# Testing Patterns

**Analysis Date:** 2026-05-26

## Test Framework

**Runner:** pytest >= 8.0.0
- Config: `pyproject.toml → [tool.pytest.ini_options]`
- `testpaths = ["tests"]`
- `python_files = ["test_*.py"]`
- `python_functions = ["test_*"]`
- `addopts = "-v --tb=short"`

**Assertion Library:** pytest built-in assertions (no third-party assertion library)

**Coverage:** pytest-cov >= 6.0.0
- Source: `sccs/` only (`tests/` and `sccs/__main__.py` omitted)
- Current enforced floor: **66%** (see comment in `pyproject.toml` — target is 80%)
- `show_missing = true`
- Excluded from coverage: `pragma: no cover`, `if __name__ == .__main__.`, `if TYPE_CHECKING:`

**Run Commands:**
```bash
pytest                                                        # Run all tests (verbose, short traceback)
pytest -v                                                     # Already default via addopts
pytest --cov=sccs --cov-report=term-missing                  # With coverage
pytest --cov=sccs --cov-report=term-missing --cov-fail-under=66  # Enforced baseline
pytest tests/test_doctor.py                                   # Single file
pytest tests/test_doctor.py::TestClaudePluginDetector        # Single class
pytest tests/test_doctor.py::TestClaudePluginDetector::test_bare_name_match_when_marketplace_unspecified  # Single test
```

## Test File Organization

**Location:** Separate `tests/` directory at repo root — not co-located with source.

**Naming:** `test_<module_or_feature>.py`

**Current test files (v2.32.1):**
```
tests/
├── conftest.py                     # Shared fixtures (temp dirs, mock claude dir, sample config)
├── test_cli.py                     # Click CLI command integration (355 lines)
├── test_config.py                  # Config loading/validation (222 lines)
├── test_conflict_resolution.py     # Conflict resolution logic
├── test_console.py                 # Rich console output
├── test_convert.py                 # Fish→PowerShell converter (355 lines)
├── test_diff.py                    # Diff display
├── test_docs.py                    # Hub README generator
├── test_doctor.py                  # Doctor subsystem — largest file (3813 lines)
├── test_git_operations.py          # Git subprocess wrapper (436 lines)
├── test_git_resolve.py             # Divergence resolution
├── test_hashing.py                 # SHA256 content hashing
├── test_importer_security.py       # Import ZIP path traversal guards
├── test_integrations.py            # Antigravity + Claude Desktop detectors (377 lines)
├── test_merge.py                   # Interactive merge
├── test_migration.py               # New-category migration state
├── test_paths_atomic.py            # Atomic write operations
├── test_paths_security.py          # Symlink rejection guards (73 lines)
├── test_platform.py                # Platform detection
├── test_platform_utils.py          # Platform utility helpers
├── test_settings.py                # settings_ensure JSON patching
├── test_sync.py                    # Sync engine core (299 lines)
└── test_transfer.py                # Export/Import ZIP archive
```

## Test Structure

**Suite Organization:** Classes group related tests; plain functions for one-off checks.
```python
class TestClaudePluginDetector:
    """Tests for plugin detection logic."""

    SAMPLE_OUTPUT = """Installed plugins: ..."""  # class-level test data

    def test_marketplace_match_matches_full_target(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT)
        statuses = detector.get_statuses([PluginSpec(name="skill-creator", marketplace="claude-plugins-official")])
        assert statuses[0].installed is True

    def test_missing_plugin_detected(self):
        detector = ClaudePluginDetector(raw_output=self.SAMPLE_OUTPUT)
        statuses = detector.get_statuses([PluginSpec(name="superpowers", marketplace="claude-plugins-official")])
        assert statuses[0].installed is False
```

**Class-level test data:** Multiline strings stored as class attributes (e.g. `SAMPLE_OUTPUT`, `REAL_OUTPUT` in `TestClaudePluginDetector`). This avoids fixture overhead for pure data.

**Docstrings on test methods:** Used for regression guards and non-obvious assertions. The docstring explains the `why`, not just the `what`:
```python
def test_word_boundary_prevents_false_match_against_longer_name(self):
    """`superpowers@...` must not match the longer
    `superpowers-developing-for-claude-code@...` line."""
```

## Mocking

**Framework:** `unittest.mock` — `patch`, `MagicMock`, `monkeypatch`

**Two patterns in use:**

### Pattern 1: `unittest.mock.patch` (context manager or decorator)
Used for subprocess and module-level functions:
```python
from unittest.mock import patch

with patch("sccs.doctor.runner.subprocess.run", return_value=fake) as run_mock:
    _run(["echo", "x"])
kwargs = run_mock.call_args.kwargs
assert kwargs["stdin"] is subprocess.DEVNULL
```

Stacking multiple patches (Python 3.10+ parenthesised `with`):
```python
with (
    patch("sccs.doctor.installer._run", return_value=fake_proc) as run_mock,
    patch("sccs.doctor.installer.questionary") as q_mock,
):
    q_mock.confirm.return_value.ask.return_value = False
    result = execute_plan(plan, assume_yes=False, print_fn=lambda _: None)
```

### Pattern 2: `monkeypatch` fixture
Used for patching module attributes, environment variables, and `which`:
```python
def test_missing_node_returns_not_installed(self, monkeypatch):
    monkeypatch.setattr("sccs.doctor.detectors.run_node_version", lambda: None)
    status = NodeDetector(platform_name="macos").get_status(min_major=20)
    assert status.installed is False

def test_missing_when_not_on_path(self, monkeypatch):
    monkeypatch.setattr("sccs.doctor.detectors.which", lambda _: None)
    status = ClaudeCliDetector().get_status()
    assert status.installed is False
```

**What to Mock:**
- `which` / `shutil.which` calls (platform detection)
- `subprocess.run` (any subprocess invocation)
- `run_node_version` (version string retrieval)
- `questionary.confirm` (interactive prompt)
- `HOME` environment variable (via `monkeypatch.setenv`)

**What NOT to Mock:**
- Pydantic `ValidationError` — test real validation with real schemas
- File system operations — use `tmp_path` / `temp_dir` fixtures instead
- `DoctorStateManager` — pass a real instance with `tmp_path` state file

## Fixtures and Factories

**Shared fixtures** in `tests/conftest.py`:

```python
@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def temp_home(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary home directory — patches HOME env var."""
    home = temp_dir / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home

@pytest.fixture
def mock_claude_dir(temp_home: Path) -> Path:
    """Create a mock ~/.claude directory with subdirs, framework files, skill, and command."""

@pytest.fixture
def mock_repo(temp_dir: Path) -> Path:
    """Create a mock repository directory with .claude subdirs."""

@pytest.fixture
def sample_config(temp_home: Path, mock_repo: Path) -> dict:
    """Return a full config dict with three categories (framework, skills, commands)."""

@pytest.fixture
def config_file(temp_home: Path, sample_config: dict) -> Path:
    """Write sample_config as YAML to ~/.config/sccs/config.yaml."""

@pytest.fixture
def state_file(temp_home: Path) -> Path:
    """Return path for a fresh state file."""
```

**Local factory helper** (`_make_status_set` in `tests/test_doctor.py`):
```python
def _make_status_set(
    node_ok=True,
    cli_ok=True,
    plugins_present=None,
    tools_present=None,
    plugin_found_marketplace=None,
    plugin_detection_source=None,
    specs=None,
):
    """Build the four detector results for plan tests."""
    # Returns dict with "node", "claude_cli", "plugins", "npx_tools" keys
```
Use this pattern for test helpers that build complex status objects — keeps individual tests concise.

**Location:** All shared fixtures in `tests/conftest.py`. Test-local helpers defined as module-level functions in the relevant test file.

## Platform-Specific Tests

Use `pytest.mark.skipif` for platform-specific behaviour:
```python
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Symlink semantics differ on Windows and require elevated privileges",
)
```
Example: `tests/test_paths_security.py` skips symlink tests on Windows.

**CI matrix** (`.github/workflows/ci.yml`): Python 3.10, 3.11, 3.12, 3.13 on `ubuntu-latest`. Tests must pass on all four versions. No macOS or Windows CI runners — keep platform assumptions out of tests.

## Coverage

**Requirements:**
- Enforced floor: **66%** (pyproject.toml `fail_under = 66`)
- CI uses `--cov-fail-under=60` (slightly lower, confirmed in `.github/workflows/ci.yml`)
- `# pragma: no cover` for unreachable branches (`if TYPE_CHECKING:`, `__main__` guard)

**Weak areas** (noted in `pyproject.toml`): `sccs/cli.py` and `sccs/transfer/ui.py` — interactive TTY paths difficult to cover.

**View Coverage:**
```bash
pytest --cov=sccs --cov-report=term-missing
pytest --cov=sccs --cov-report=html   # generates htmlcov/
```

## Test Types

**Unit Tests (dominant pattern):**
- Test individual classes/functions in isolation
- Mock all external dependencies (subprocess, file system where practical)
- Examples: `TestClaudePluginDetector`, `TestSchemaValidation`, `TestParseNodeMajor`, `TestSyncItem`

**Integration Tests (via real temp FS):**
- Use `temp_dir` / `temp_home` / `mock_claude_dir` / `mock_repo` fixtures
- Touch the real file system in a temp directory
- Examples: `TestScanItems`, `TestActions`, `TestDoctorStateManager`
- No external process calls — subprocess is always mocked

**Security / Regression Tests (dedicated test files):**
- `tests/test_paths_security.py` — symlink rejection in `safe_copy` and `create_backup`
- `tests/test_importer_security.py` — ZIP path traversal guards
- `tests/test_doctor.py::TestRunnerSecurity` — argument-injection and sudo rejection
- These are small, focused, and must never be removed

**No E2E tests.** The CLI is tested via `CliRunner` (Click testing utility) in `tests/test_cli.py`, not via subprocess invocation.

## Common Patterns

**Pydantic validation errors:**
```python
def test_plugin_spec_rejects_leading_dash(self):
    with pytest.raises(ValidationError):
        PluginSpec(name="--evil")
```

**Custom exception errors:**
```python
def test_run_rejects_empty_cmd(self):
    with pytest.raises(DoctorError, match="Empty"):
        _run([])
```

**Subprocess mocking:**
```python
fake = subprocess.CompletedProcess(args=["echo"], returncode=0, stdout="ok", stderr="")
with patch("sccs.doctor.runner.subprocess.run", return_value=fake) as run_mock:
    _run(["echo", "x"])
run_mock.assert_called_once()
```

**State-file tests (use `tmp_path`, not `temp_dir`):**
```python
def test_marks_and_recognises_run(self, tmp_path):
    state_path = tmp_path / ".doctor_state.yaml"
    mgr = DoctorStateManager(state_path=state_path)
    mgr.mark_npx_tool("tool-x", ["npx", "tool-x", "--global"])
    assert mgr.is_npx_tool_marked("tool-x", ["npx", "tool-x", "--global"]) is True
```

**Corrupt-file resilience:**
```python
def test_load_handles_corrupt_yaml(self, tmp_path):
    state_path = tmp_path / "broken.yaml"
    state_path.write_text(":\n:\n: not valid", encoding="utf-8")
    mgr = DoctorStateManager(state_path=state_path)
    state = mgr.load()  # must not raise
    assert state.npx_tools == {}
```

**File content written in tests:**
```python
test_file.write_text("test content", encoding="utf-8")   # Always explicit UTF-8
```

## Regression Comments in Tests

Security fixes and non-obvious behaviour fixes get a comment in the test explaining the historical context:
```python
def test_default_npx_get_shit_done_uses_dash_y(self):
    # Without `-y`, npx prompts on stdout for "Need to install... Ok to
    # proceed?" on Linux/fresh systems — and capture_output=True hides
    # that prompt from the user. Regression guard for the v2.22.x Debian hang.
```
Always add a regression comment when a test encodes a specific past bug fix.

---

*Testing analysis: 2026-05-26*
