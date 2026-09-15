# Mirror Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sccs doctor` keeps a second Mac's software (Homebrew, uv tools, npm globals, own git checkouts, Fisher plugins) identical to the live workstation, and removes what only the mirror has — after confirmation.

**Architecture:** One new doctor area, `sccs/doctor/mirror.py`, following the `cli_tools`/`skill_packages` shape: a config block, detectors that return dataclass statuses, action builders that return `DoctorAction` lists, rows in the reporter, a key in the `--json` payload. The live workstation ("source", matched by hostname) captures its inventory on `doctor update`; every other host ("mirror") reconciles against it. Truth lives in two synced files: the existing Brewfile and a new `inventory.yaml`.

**Tech Stack:** Python 3.10+, Pydantic v2, Click, Rich, PyYAML, pytest. External tools driven through `sccs/doctor/runner.py`: `brew`, `uv`, `npm`, `git`, `fish`.

**Spec:** `docs/superpowers/specs/2026-09-15-mirror-parity-design.md`

## Global Constraints

- **Python 3.10+** — every new module starts with `from __future__ import annotations`; use `X | None`, never `Optional[X]`.
- **Every external command goes through `sccs.doctor.runner._run`** (`shell=False`, `stdin=DEVNULL`, argv[0] validated). A task that calls `subprocess` directly is wrong. All new wrappers live in `sccs/doctor/runner.py`, catch `DoctorError`, and degrade to `None`/`False` — a detector never raises because a tool is absent.
- **The source host is never modified from the inventory. A mirror never writes the inventory.** Pinned by tests in Task 8; every action builder checks `report.role` first.
- **Removals exist only in `build_optimize_plan(..., strict=True)` and only when `MirrorConfig.cleanup` is `True`.** Each removal is its own `DoctorAction` with `auto_confirm=False` (the dataclass default). Never `brew bundle cleanup`.
- **Hard-excluded from removal:** npm `npm`, `corepack`; uv tool `sccs`. Also excluded from comparison entirely: npm `npm`, `corepack` (they appear in `npm ls -g` on every host).
- **Names and versions are validated before they become argv:** names through `sccs.doctor.schema._validate_safe_name`, versions through `_VERSION_PATTERN = re.compile(r"^[0-9][A-Za-z0-9.+\-]*$")` (Task 1). Anything that fails validation is skipped with a warning, never passed to a command.
- **`--json` goes through `sccs.output.json_emit.emit_json`**, never the Rich console.
- **Tests are platform-independent.** CI runs on Linux. Drive `HOME` with `monkeypatch.setenv("HOME", str(tmp_path))` **and** `monkeypatch.setattr(Path, "home", lambda: tmp_path)`. Stub every runner wrapper with `monkeypatch.setattr("sccs.doctor.mirror.<wrapper>", ...)`; never call `brew`/`uv`/`npm`/`git`/`fish` in a test.
- **No hostnames, domains, URLs or paths of real machines in code, tests or docs** — the repo mirrors to GitHub. Use `live-mac`, `git@gitlab.example:org/repo.git`, `~/gitbase/example/repo`.
- **Commit prefixes:** `[ADD]` new features, `[CHG]` modifications, `[FIX]` bug fixes. Every commit message ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Quality gate before every commit:** `ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q`.
- **Version bump to 2.68.0 followed by `uv lock` happens in Task 11, once.**

---

## File structure

| File | Responsibility |
|---|---|
| `sccs/doctor/mirror.py` (new) | `MirrorConfig`/`MirrorRepoSpec` schema, role resolution, `Inventory` model + read/write, Brewfile parser, the five detectors, `MirrorReport`, `collect_mirror_report()`, the three action builders. One module, sectioned with `# --- ` headers; it is the whole area, like `skill_packages.py`. |
| `sccs/doctor/runner.py` | New wrappers: `run_brew_lines`, `run_brew_bundle_dump`, `run_uv_tool_list`, `run_npm_global_list`, `run_git_status_branch`, `run_git_fetch`, `run_fisher_list`. |
| `sccs/doctor/schema.py` | `DoctorConfig.mirror: MirrorConfig | None`. |
| `sccs/doctor/installer.py` | `build_install_plan`/`build_update_plan`/`build_optimize_plan` take `mirror=` and append the mirror actions. |
| `sccs/doctor/reporter.py` | `_mirror_rows()`, `render_doctor_report(mirror=)`, `has_problems(mirror=)`. |
| `sccs/cli.py` | `_collect_doctor_statuses` collects `mirror`; `doctor check/install/update/optimize` pass it through; `--json` payload gains `mirror`. |
| `sccs/config/defaults.py` | New categories `homebrew_bundle` (macos) and `sccs_inventory` (all platforms). |
| `tests/test_doctor_mirror.py` (new) | All tests for the area. |
| `docs/usage/doctor.md`, `docs/usage/categories.md`, `docs/usage/cli-reference.md`, `usage/AGENT.md`, `RELEASE_NOTES.md`, `CLAUDE.md`, `~/.claude/skills/sccs/SKILL.md` | Docs. |

---

### Task 1: Config schema and role resolution

**Files:**
- Create: `sccs/doctor/mirror.py`
- Modify: `sccs/doctor/schema.py` (DoctorConfig, after `skill_packages` field ~line 867)
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Produces: `MirrorRepoSpec(url: str, path: str, branch: str | None)`, `MirrorConfig(source_host, cleanup, brewfile, inventory_path, fish_plugins, repos, ignore_brew, ignore_uv_tools, ignore_npm)`, `MirrorRole = Literal["source", "mirror", "off"]`, `normalize_host(name: str) -> str`, `current_hostname() -> str`, `resolve_role(cfg: MirrorConfig | None, hostname: str | None = None) -> MirrorRole`, `_VERSION_PATTERN`, `DoctorConfig.mirror`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doctor_mirror.py
"""v2.68.0: mirror parity — keep a second Mac identical to the live workstation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


class TestMirrorConfig:
    def test_repo_spec_accepts_ssh_and_https(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec

        MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        MirrorRepoSpec(url="https://gitlab.example/org/beam.git", path="~/gitbase/example/beam")

    @pytest.mark.parametrize(
        "url",
        ["ssh://evil/x", "file:///etc/passwd", "-oProxyCommand=x", "git@host:path with space"],
    )
    def test_repo_spec_rejects_other_schemes(self, home: Path, url: str):
        from sccs.doctor.mirror import MirrorRepoSpec

        with pytest.raises(ValidationError):
            MirrorRepoSpec(url=url, path="~/gitbase/example/beam")

    def test_repo_path_must_be_under_home(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec

        with pytest.raises(ValidationError):
            MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="/opt/beam")

    def test_ignore_lists_are_validated_names(self):
        from sccs.doctor.mirror import MirrorConfig

        with pytest.raises(ValidationError):
            MirrorConfig(source_host="live-mac", ignore_brew=["-rf"])

    def test_defaults(self):
        from sccs.doctor.mirror import MirrorConfig

        cfg = MirrorConfig(source_host="live-mac")
        assert cfg.cleanup is True
        assert cfg.brewfile == "~/.config/homebrew/Brewfile"
        assert cfg.inventory_path == "~/.config/sccs/inventory.yaml"
        assert cfg.fish_plugins == "~/.config/fish/fish_plugins"
        assert cfg.repos == []

    def test_doctor_config_carries_mirror(self):
        from sccs.doctor.schema import DoctorConfig

        cfg = DoctorConfig(mirror={"source_host": "live-mac"})
        assert cfg.mirror is not None
        assert cfg.mirror.source_host == "live-mac"
        assert DoctorConfig().mirror is None


class TestRoleResolution:
    def test_normalize_strips_domain_and_case(self):
        from sccs.doctor.mirror import normalize_host

        assert normalize_host("Live-Mac.local") == "live-mac"
        assert normalize_host("live-mac.example.net") == "live-mac"
        assert normalize_host("live-mac") == "live-mac"

    def test_source_when_hostname_matches(self):
        from sccs.doctor.mirror import MirrorConfig, resolve_role

        cfg = MirrorConfig(source_host="live-mac")
        assert resolve_role(cfg, hostname="Live-Mac.local") == "source"
        assert resolve_role(cfg, hostname="demo-mac") == "mirror"

    def test_off_without_config_or_source_host(self):
        from sccs.doctor.mirror import MirrorConfig, resolve_role

        assert resolve_role(None, hostname="x") == "off"
        assert resolve_role(MirrorConfig(source_host=None), hostname="x") == "off"

    def test_uses_current_hostname_by_default(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import MirrorConfig, resolve_role

        monkeypatch.setattr(mirror, "current_hostname", lambda: "live-mac.local")
        assert resolve_role(MirrorConfig(source_host="live-mac")) == "source"


class TestVersionPattern:
    @pytest.mark.parametrize("v", ["2.67.2", "0.1.18", "1.0.0-rc.1", "4.6.4+build"])
    def test_accepts(self, v: str):
        from sccs.doctor.mirror import _VERSION_PATTERN

        assert _VERSION_PATTERN.match(v)

    @pytest.mark.parametrize("v", ["", "-1", "1.0; rm", "v1.0", "1.0 2"])
    def test_rejects(self, v: str):
        from sccs.doctor.mirror import _VERSION_PATTERN

        assert not _VERSION_PATTERN.match(v)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.doctor.mirror'`

- [ ] **Step 3: Create `sccs/doctor/mirror.py` with the schema section**

```python
"""Mirror parity — keep a second Mac identical to the live workstation.

One host is the *source* (matched by hostname); every other host is a
*mirror*. The source captures its software inventory on `doctor update`,
a mirror reconciles against it on `doctor check/install/optimize`.

Two rules hold the design together and are pinned by tests:
- the source is never modified from the inventory;
- a mirror never writes the inventory.

Truth lives in two synced files: the Brewfile (category `homebrew_bundle`)
and `inventory.yaml` (category `sccs_inventory`). See
docs/superpowers/specs/2026-09-15-mirror-parity-design.md.
"""

from __future__ import annotations

import re
import socket
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from sccs.doctor.schema import _validate_safe_name
from sccs.utils.paths import expand_path

# --- schema -----------------------------------------------------------------

MirrorRole = Literal["source", "mirror", "off"]

_VERSION_PATTERN = re.compile(r"^[0-9][A-Za-z0-9.+\-]*$")
# git@host:path or https://host/path — nothing else. `-` at the start would
# be read as an option by git, `file:`/`ssh:` would let a config reach any path.
_REPO_URL_PATTERN = re.compile(
    r"^(?:git@[A-Za-z0-9.\-]+:[A-Za-z0-9_][A-Za-z0-9_./\-]*"
    r"|https://[A-Za-z0-9.\-]+/[A-Za-z0-9_][A-Za-z0-9_./\-]*)$"
)


def _validate_under_home(value: str, field: str) -> str:
    target = expand_path(value).resolve()
    home = Path.home().resolve()
    if target != home and home not in target.parents:
        raise ValueError(f"{field} must resolve under the home directory: {value!r}")
    return value


class MirrorRepoSpec(BaseModel):
    """A git checkout the mirror must have (e.g. the Beam shell extension)."""

    url: str = Field(description="git@host:path or https://host/path")
    path: str = Field(description="Checkout path, must resolve under ~")
    branch: str | None = Field(default=None, description="Branch to clone; default branch when unset")

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not _REPO_URL_PATTERN.match(v):
            raise ValueError(f"url must be git@host:path or https://host/path: {v!r}")
        return v

    @field_validator("path")
    @classmethod
    def _validate_path(cls, v: str) -> str:
        return _validate_under_home(v, "path")

    @field_validator("branch")
    @classmethod
    def _validate_branch(cls, v: str | None) -> str | None:
        return _validate_safe_name(v, "branch") if v else v


class MirrorConfig(BaseModel):
    """Policy for the mirror area (hand-edited, travels with config.yaml)."""

    source_host: str | None = Field(
        default=None,
        description="Hostname of the live workstation. Unset → the area is off.",
    )
    cleanup: bool = Field(default=True, description="Offer removals under `optimize --strict`.")
    brewfile: str = Field(default="~/.config/homebrew/Brewfile")
    inventory_path: str = Field(default="~/.config/sccs/inventory.yaml")
    fish_plugins: str = Field(default="~/.config/fish/fish_plugins")
    repos: list[MirrorRepoSpec] = Field(default_factory=list)
    ignore_brew: list[str] = Field(default_factory=list)
    ignore_uv_tools: list[str] = Field(default_factory=list)
    ignore_npm: list[str] = Field(default_factory=list)

    @field_validator("ignore_brew", "ignore_uv_tools", "ignore_npm")
    @classmethod
    def _validate_ignores(cls, v: list[str]) -> list[str]:
        return [_validate_safe_name(name, "ignore entry") for name in v]

    @field_validator("brewfile", "inventory_path", "fish_plugins")
    @classmethod
    def _validate_paths(cls, v: str) -> str:
        return _validate_under_home(v, "path")


# --- roles ------------------------------------------------------------------


def normalize_host(name: str) -> str:
    """`Live-Mac.local` and `live-mac` are the same host."""
    return name.split(".", 1)[0].strip().lower()


def current_hostname() -> str:
    return socket.gethostname()


def resolve_role(cfg: MirrorConfig | None, hostname: str | None = None) -> MirrorRole:
    if cfg is None or not cfg.source_host:
        return "off"
    host = hostname if hostname is not None else current_hostname()
    return "source" if normalize_host(host) == normalize_host(cfg.source_host) else "mirror"
```

- [ ] **Step 4: Add the field to `DoctorConfig`**

In `sccs/doctor/schema.py`, directly after the `skill_packages` field (the last field before the methods):

```python
    mirror: "MirrorConfig | None" = Field(
        default=None,
        description=(
            "Mirror parity: source_host names the live workstation; every other host "
            "reconciles Homebrew, uv tools, npm globals, git checkouts and Fisher plugins "
            "against it. Unset → no rows. See sccs/doctor/mirror.py."
        ),
    )
```

`mirror.py` imports `_validate_safe_name` from `schema.py`, so `schema.py` cannot import `mirror.py` at module level. Resolve it the way the module already resolves other late imports: add at the **bottom** of `schema.py`

```python
from sccs.doctor.mirror import MirrorConfig  # noqa: E402 — late import breaks the cycle

DoctorConfig.model_rebuild()
```

and keep the annotation as the string `"MirrorConfig | None"`. Run `mypy sccs/` — if it complains about the forward reference, add `from typing import TYPE_CHECKING` and under `if TYPE_CHECKING: from sccs.doctor.mirror import MirrorConfig` at the top of `schema.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q`
Expected: all PASS. Then `pytest -q` — the existing `DoctorConfig()` constructions must still work (`mirror` defaults to `None`).

- [ ] **Step 6: Commit**

```bash
git add sccs/doctor/mirror.py sccs/doctor/schema.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: mirror config schema and source/mirror role resolution

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Runner wrappers for brew, uv, npm, git and fisher

**Files:**
- Modify: `sccs/doctor/runner.py` (append after `run_npm_view_version`, ~line 262)
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Produces:
  - `run_brew_lines(*args: str) -> list[str] | None` — runs `brew <args>` and returns non-empty stdout lines; `None` when brew is missing or exits non-zero.
  - `run_brew_bundle_dump(brewfile: Path) -> bool` — `brew bundle dump --file <path> --force --describe`.
  - `run_uv_tool_list() -> str | None` — raw stdout of `uv tool list`.
  - `run_npm_global_list() -> str | None` — raw stdout of `npm ls -g --depth=0 --json` (npm exits 1 on peer warnings while still printing JSON, so stdout is returned whenever it is non-empty).
  - `run_git_status_branch(path: Path) -> str | None` — first line of `git -C <path> status --porcelain=v1 -b`, plus the rest joined; returned as the full stdout.
  - `run_git_fetch(path: Path) -> bool` — `git -C <path> fetch --quiet`, timeout 30.
  - `run_fisher_list() -> list[str] | None` — `fish -c "fisher list"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_doctor_mirror.py`:

```python
class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class TestRunnerWrappers:
    def test_brew_lines_returns_stripped_nonempty_lines(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import runner

        seen: list[list[str]] = []

        def fake(cmd, **kw):
            seen.append(cmd)
            return _Proc(stdout="bat\n\nanomalyco/tap/opencode \n")

        monkeypatch.setattr(runner, "_run", fake)
        assert runner.run_brew_lines("leaves") == ["bat", "anomalyco/tap/opencode"]
        assert seen == [["brew", "leaves"]]

    def test_brew_lines_none_when_brew_missing(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import runner
        from sccs.doctor.runner import DoctorError

        def boom(cmd, **kw):
            raise DoctorError("brew: not found")

        monkeypatch.setattr(runner, "_run", boom)
        assert runner.run_brew_lines("leaves") is None

    def test_brew_bundle_dump_argv(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor import runner

        seen: list[list[str]] = []
        monkeypatch.setattr(runner, "_run", lambda cmd, **kw: (seen.append(cmd), _Proc())[1])
        assert runner.run_brew_bundle_dump(tmp_path / "Brewfile") is True
        assert seen == [["brew", "bundle", "dump", "--file", str(tmp_path / "Brewfile"), "--force", "--describe"]]

    def test_npm_global_list_returns_stdout_even_on_exit_1(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import runner

        monkeypatch.setattr(runner, "_run", lambda cmd, **kw: _Proc(stdout='{"dependencies": {}}', returncode=1))
        assert runner.run_npm_global_list() == '{"dependencies": {}}'

    def test_git_fetch_false_on_failure(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor import runner

        monkeypatch.setattr(runner, "_run", lambda cmd, **kw: _Proc(returncode=128))
        assert runner.run_git_fetch(tmp_path) is False

    def test_fisher_list_goes_through_fish(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import runner

        seen: list[list[str]] = []
        monkeypatch.setattr(
            runner, "_run", lambda cmd, **kw: (seen.append(cmd), _Proc(stdout="jorgebucaran/fisher\nedc/bass\n"))[1]
        )
        assert runner.run_fisher_list() == ["jorgebucaran/fisher", "edc/bass"]
        assert seen == [["fish", "-c", "fisher list"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestRunnerWrappers -q`
Expected: FAIL — `AttributeError: module 'sccs.doctor.runner' has no attribute 'run_brew_lines'`

- [ ] **Step 3: Implement the wrappers**

Append to `sccs/doctor/runner.py`:

```python
# --- mirror parity (v2.68.0) -------------------------------------------------
# Every wrapper degrades to None/False: a detector must be able to say "brew is
# not installed here" without raising, and a missing tool is a status, not a crash.


def _lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def run_brew_lines(*args: str) -> list[str] | None:
    """`brew <args>` → stripped non-empty stdout lines, or None when brew is
    missing or the command fails. Used for `leaves`, `list --formula --full-name`,
    `list --cask`, `tap`."""
    try:
        proc = _run(["brew", *args], timeout=60, check=False)
    except DoctorError:
        return None
    if proc.returncode != 0:
        return None
    return _lines(proc)


def run_brew_bundle_dump(brewfile: Path) -> bool:
    """Rewrite the Brewfile from the installed set (source host only)."""
    try:
        proc = _run(
            ["brew", "bundle", "dump", "--file", str(brewfile), "--force", "--describe"],
            timeout=120,
            check=False,
        )
    except DoctorError:
        return False
    return proc.returncode == 0


def run_uv_tool_list() -> str | None:
    try:
        proc = _run(["uv", "tool", "list"], timeout=30, check=False)
    except DoctorError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout or ""


def run_npm_global_list() -> str | None:
    """`npm ls -g --depth=0 --json`. npm exits 1 on peer/extraneous warnings
    while still printing the JSON, so stdout wins over the exit code."""
    try:
        proc = _run(["npm", "ls", "-g", "--depth=0", "--json"], timeout=60, check=False)
    except DoctorError:
        return None
    out = (proc.stdout or "").strip()
    return out or None


def run_git_status_branch(path: Path) -> str | None:
    """`git -C <path> status --porcelain=v1 -b` — first line carries the
    tracking info (`## main...origin/main [behind 2]`), the rest the dirt."""
    try:
        proc = _run(["git", "-C", str(path), "status", "--porcelain=v1", "-b"], timeout=30, check=False)
    except DoctorError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout or ""


def run_git_fetch(path: Path) -> bool:
    try:
        proc = _run(["git", "-C", str(path), "fetch", "--quiet"], timeout=30, check=False)
    except DoctorError:
        return False
    return proc.returncode == 0


def run_fisher_list() -> list[str] | None:
    """Fisher is a fish function, so it only exists inside fish."""
    try:
        proc = _run(["fish", "-c", "fisher list"], timeout=30, check=False)
    except DoctorError:
        return None
    if proc.returncode != 0:
        return None
    return _lines(proc)
```

`Path` is already imported in `runner.py` (check the top of the file; add `from pathlib import Path` if not).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sccs/doctor/runner.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: runner wrappers for brew, uv, npm, git and fisher (mirror parity)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Inventory model, parsers, read/write and capture

**Files:**
- Modify: `sccs/doctor/mirror.py` (new section `# --- inventory`)
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Consumes: `run_uv_tool_list`, `run_npm_global_list` (Task 2), `atomic_write`, `expand_path`.
- Produces:
  - `PackageRef(name: str, version: str)` (pydantic).
  - `Inventory(version: int = 1, captured_at: str, captured_on: str, uv_tools: list[PackageRef], npm_globals: list[PackageRef])` (pydantic).
  - `parse_uv_tool_list(text: str) -> list[PackageRef]`
  - `parse_npm_global_json(text: str) -> list[PackageRef]` — drops `npm`, `corepack`.
  - `NPM_ALWAYS_IGNORED = frozenset({"npm", "corepack"})`, `UV_NEVER_REMOVED = frozenset({"sccs"})`.
  - `load_inventory(path: Path) -> Inventory | None` — `None` when missing or unparsable (logs a warning).
  - `write_inventory(path: Path, inv: Inventory) -> None` — YAML via `atomic_write`.
  - `capture_inventory(hostname: str) -> Inventory` — runs the two list commands, empty lists when a tool is absent.

- [ ] **Step 1: Write the failing tests**

```python
UV_LIST = """agentmgr v0.2.2
- agentmgr
sccs v2.67.2
- sccs
odoodev-equitania v0.68.0
- odoodev
- odoodev-x
"""

NPM_JSON = """{
  "name": "lib",
  "dependencies": {
    "@playwright/cli": {"version": "0.1.18", "overridden": false},
    "less": {"version": "4.6.4"},
    "npm": {"version": "11.19.1"},
    "corepack": {"version": "0.34.0"}
  }
}"""


class TestInventory:
    def test_parse_uv_tool_list(self):
        from sccs.doctor.mirror import PackageRef, parse_uv_tool_list

        assert parse_uv_tool_list(UV_LIST) == [
            PackageRef(name="agentmgr", version="0.2.2"),
            PackageRef(name="sccs", version="2.67.2"),
            PackageRef(name="odoodev-equitania", version="0.68.0"),
        ]

    def test_parse_npm_drops_npm_and_corepack(self):
        from sccs.doctor.mirror import PackageRef, parse_npm_global_json

        assert parse_npm_global_json(NPM_JSON) == [
            PackageRef(name="@playwright/cli", version="0.1.18"),
            PackageRef(name="less", version="4.6.4"),
        ]

    def test_parse_npm_garbage_is_empty(self):
        from sccs.doctor.mirror import parse_npm_global_json

        assert parse_npm_global_json("not json") == []
        assert parse_npm_global_json('{"dependencies": {"x": {}}}') == []

    def test_roundtrip(self, tmp_path: Path):
        from sccs.doctor.mirror import Inventory, PackageRef, load_inventory, write_inventory

        inv = Inventory(
            captured_at="2026-09-15T10:00:00",
            captured_on="live-mac",
            uv_tools=[PackageRef(name="sccs", version="2.67.2")],
            npm_globals=[PackageRef(name="@playwright/cli", version="0.1.18")],
        )
        path = tmp_path / "inventory.yaml"
        write_inventory(path, inv)
        assert load_inventory(path) == inv
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Written by `sccs doctor update` on the source host")

    def test_load_missing_or_broken_is_none(self, tmp_path: Path):
        from sccs.doctor.mirror import load_inventory

        assert load_inventory(tmp_path / "nope.yaml") is None
        (tmp_path / "bad.yaml").write_text("uv_tools: [", encoding="utf-8")
        assert load_inventory(tmp_path / "bad.yaml") is None
        (tmp_path / "wrong.yaml").write_text("version: 1\nuv_tools: 3\n", encoding="utf-8")
        assert load_inventory(tmp_path / "wrong.yaml") is None

    def test_capture_uses_wrappers_and_tolerates_missing_tools(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror

        monkeypatch.setattr(mirror, "run_uv_tool_list", lambda: UV_LIST)
        monkeypatch.setattr(mirror, "run_npm_global_list", lambda: None)
        inv = mirror.capture_inventory("live-mac")
        assert [p.name for p in inv.uv_tools] == ["agentmgr", "sccs", "odoodev-equitania"]
        assert inv.npm_globals == []
        assert inv.captured_on == "live-mac"
        assert inv.version == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestInventory -q`
Expected: FAIL — `ImportError: cannot import name 'parse_uv_tool_list'`

- [ ] **Step 3: Implement the inventory section**

Add to the imports of `sccs/doctor/mirror.py`:

```python
import json
from datetime import datetime

import yaml

from sccs.doctor.runner import run_npm_global_list, run_uv_tool_list
from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write, expand_path

logger = get_logger("sccs.doctor.mirror")
```

Then the section:

```python
# --- inventory --------------------------------------------------------------

NPM_ALWAYS_IGNORED = frozenset({"npm", "corepack"})
UV_NEVER_REMOVED = frozenset({"sccs"})

_INVENTORY_HEADER = "# Written by `sccs doctor update` on the source host — do not edit by hand.\n"
_UV_LINE = re.compile(r"^(?P<name>[A-Za-z0-9_.\-]+) v(?P<version>\S+)$")


class PackageRef(BaseModel):
    name: str
    version: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return _validate_safe_name(v, "package name")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not _VERSION_PATTERN.match(v):
            raise ValueError(f"version has invalid characters: {v!r}")
        return v


class Inventory(BaseModel):
    version: int = 1
    captured_at: str
    captured_on: str
    uv_tools: list[PackageRef] = Field(default_factory=list)
    npm_globals: list[PackageRef] = Field(default_factory=list)


def parse_uv_tool_list(text: str) -> list[PackageRef]:
    """`uv tool list` prints `name vX.Y.Z` followed by `- entrypoint` lines."""
    out: list[PackageRef] = []
    for line in text.splitlines():
        m = _UV_LINE.match(line.strip())
        if not m:
            continue
        try:
            out.append(PackageRef(name=m.group("name"), version=m.group("version")))
        except ValueError:
            logger.warning("uv tool list: skipping unparsable entry %r", line)
    return out


def parse_npm_global_json(text: str) -> list[PackageRef]:
    """`npm ls -g --depth=0 --json` → dependencies with a version; npm itself
    and corepack are on every host and never part of the comparison."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    deps = data.get("dependencies") if isinstance(data, dict) else None
    if not isinstance(deps, dict):
        return []
    out: list[PackageRef] = []
    for name, info in deps.items():
        if name in NPM_ALWAYS_IGNORED or not isinstance(info, dict):
            continue
        version = info.get("version")
        if not isinstance(version, str):
            continue
        try:
            out.append(PackageRef(name=name, version=version))
        except ValueError:
            logger.warning("npm ls -g: skipping unparsable entry %r", name)
    return out


def load_inventory(path: Path) -> Inventory | None:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Inventory.model_validate(data)
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        logger.warning("inventory %s is unreadable: %s", path, exc)
        return None


def write_inventory(path: Path, inv: Inventory) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(inv.model_dump(), sort_keys=False, allow_unicode=True)
    atomic_write(path, _INVENTORY_HEADER + body)


def capture_inventory(hostname: str) -> Inventory:
    uv_text = run_uv_tool_list()
    npm_text = run_npm_global_list()
    return Inventory(
        captured_at=datetime.now().replace(microsecond=0).isoformat(),
        captured_on=normalize_host(hostname),
        uv_tools=parse_uv_tool_list(uv_text or ""),
        npm_globals=parse_npm_global_json(npm_text or ""),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sccs/doctor/mirror.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: inventory model, uv/npm parsers and capture (mirror parity)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Brewfile parser and Homebrew detector

**Files:**
- Modify: `sccs/doctor/mirror.py` (new section `# --- homebrew`)
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Consumes: `run_brew_lines` (Task 2).
- Produces:
  - `BrewSet(taps: set[str], formulae: set[str], casks: set[str])` (dataclass).
  - `parse_brewfile(text: str) -> BrewSet` — first double-quoted token of lines starting with `tap `/`brew `/`cask `; everything else ignored.
  - `BrewStatus(state: Literal["ok","drift","unavailable","no_brewfile"], missing_taps, missing_formulae, missing_casks, extra_taps, extra_formulae, extra_casks: list[str])` (dataclass, lists sorted).
  - `BrewDetector.get_status(brewfile: Path, ignore: list[str]) -> BrewStatus`.

- [ ] **Step 1: Write the failing tests**

```python
BREWFILE = '''tap "anomalyco/tap"
tap "eqms/claude-workbench", trusted: true
brew "bat"
brew "sleepwatcher", restart_service: :changed
brew "anomalyco/tap/opencode", trusted: true
cask "iterm2"
# comment
vscode "ms-python.python"
'''


class TestBrewfile:
    def test_parse_takes_first_quoted_token(self):
        from sccs.doctor.mirror import parse_brewfile

        s = parse_brewfile(BREWFILE)
        assert s.taps == {"anomalyco/tap", "eqms/claude-workbench"}
        assert s.formulae == {"bat", "sleepwatcher", "anomalyco/tap/opencode"}
        assert s.casks == {"iterm2"}


class TestBrewDetector:
    def _stub(self, monkeypatch, *, leaves, formulae, casks, taps):
        from sccs.doctor import mirror

        table = {
            ("leaves",): leaves,
            ("list", "--formula", "--full-name"): formulae,
            ("list", "--cask"): casks,
            ("tap",): taps,
        }
        monkeypatch.setattr(mirror, "run_brew_lines", lambda *args: table[args])

    def test_drift_missing_and_extra(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor.mirror import BrewDetector

        (tmp_path / "Brewfile").write_text(BREWFILE, encoding="utf-8")
        self._stub(
            monkeypatch,
            leaves=["bat", "ffmpeg"],
            formulae=["bat", "ffmpeg", "sleepwatcher", "python@3.13"],  # sleepwatcher is a dependency → present
            casks=["iterm2", "davit"],
            taps=["anomalyco/tap", "leoafarias/fvm"],
        )
        st = BrewDetector().get_status(tmp_path / "Brewfile", ignore=[])
        assert st.state == "drift"
        assert st.missing_formulae == ["anomalyco/tap/opencode"]
        assert st.missing_taps == ["eqms/claude-workbench"]
        assert st.missing_casks == []
        assert st.extra_formulae == ["ffmpeg"]  # python@3.13 is not a leaf → never an extra
        assert st.extra_casks == ["davit"]
        assert st.extra_taps == ["leoafarias/fvm"]

    def test_ignore_list_hides_both_directions(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor.mirror import BrewDetector

        (tmp_path / "Brewfile").write_text('brew "bat"\nbrew "poppler"\n', encoding="utf-8")
        self._stub(monkeypatch, leaves=["bat", "ffmpeg"], formulae=["bat", "ffmpeg"], casks=[], taps=[])
        st = BrewDetector().get_status(tmp_path / "Brewfile", ignore=["ffmpeg", "poppler"])
        assert st.state == "ok"

    def test_unavailable_without_brew(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import BrewDetector

        (tmp_path / "Brewfile").write_text('brew "bat"\n', encoding="utf-8")
        monkeypatch.setattr(mirror, "run_brew_lines", lambda *args: None)
        assert BrewDetector().get_status(tmp_path / "Brewfile", ignore=[]).state == "unavailable"

    def test_no_brewfile(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from sccs.doctor.mirror import BrewDetector

        assert BrewDetector().get_status(tmp_path / "Brewfile", ignore=[]).state == "no_brewfile"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestBrewfile tests/test_doctor_mirror.py::TestBrewDetector -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Add `from dataclasses import dataclass, field` to the imports and `run_brew_lines` to the runner import. Then:

```python
# --- homebrew ---------------------------------------------------------------

_BREWFILE_LINE = re.compile(r'^(?P<kind>tap|brew|cask)\s+"(?P<name>[^"]+)"')


@dataclass
class BrewSet:
    taps: set[str] = field(default_factory=set)
    formulae: set[str] = field(default_factory=set)
    casks: set[str] = field(default_factory=set)


def parse_brewfile(text: str) -> BrewSet:
    """Brewfile → sets. Options after the name (`restart_service:`,
    `trusted:`) are ignored; `vscode`/`mas` lines are not ours."""
    out = BrewSet()
    for line in text.splitlines():
        m = _BREWFILE_LINE.match(line.strip())
        if not m:
            continue
        getattr(out, {"tap": "taps", "brew": "formulae", "cask": "casks"}[m.group("kind")]).add(m.group("name"))
    return out


@dataclass
class BrewStatus:
    # "ok" | "drift" | "unavailable" (brew not installed) | "no_brewfile"
    state: str
    missing_taps: list[str] = field(default_factory=list)
    missing_formulae: list[str] = field(default_factory=list)
    missing_casks: list[str] = field(default_factory=list)
    extra_taps: list[str] = field(default_factory=list)
    extra_formulae: list[str] = field(default_factory=list)
    extra_casks: list[str] = field(default_factory=list)

    @property
    def missing_count(self) -> int:
        return len(self.missing_taps) + len(self.missing_formulae) + len(self.missing_casks)

    @property
    def extra_count(self) -> int:
        return len(self.extra_taps) + len(self.extra_formulae) + len(self.extra_casks)


class BrewDetector:
    """Missing = in the Brewfile but not installed (checked against the FULL
    installed formula list, so a Brewfile entry that arrived as a dependency
    counts as present). Extra = a *leaf* (`brew leaves`) not in the Brewfile —
    never a dependency, so nothing pulled in by a wanted package is ever
    offered for removal."""

    def get_status(self, brewfile: Path, ignore: list[str]) -> BrewStatus:
        if not brewfile.is_file():
            return BrewStatus(state="no_brewfile")
        wanted = parse_brewfile(brewfile.read_text(encoding="utf-8"))
        leaves = run_brew_lines("leaves")
        formulae = run_brew_lines("list", "--formula", "--full-name")
        casks = run_brew_lines("list", "--cask")
        taps = run_brew_lines("tap")
        if leaves is None or formulae is None or casks is None or taps is None:
            return BrewStatus(state="unavailable")
        skip = set(ignore)
        st = BrewStatus(
            state="ok",
            missing_taps=sorted(wanted.taps - set(taps) - skip),
            missing_formulae=sorted(wanted.formulae - set(formulae) - skip),
            missing_casks=sorted(wanted.casks - set(casks) - skip),
            extra_taps=sorted(set(taps) - wanted.taps - skip),
            extra_formulae=sorted(set(leaves) - wanted.formulae - skip),
            extra_casks=sorted(set(casks) - wanted.casks - skip),
        )
        if st.missing_count or st.extra_count:
            st.state = "drift"
        return st
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sccs/doctor/mirror.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: Brewfile parser and Homebrew drift detector (mirror parity)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: uv-tool and npm-global detectors

**Files:**
- Modify: `sccs/doctor/mirror.py` (new section `# --- packages`)
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Consumes: `Inventory`, `PackageRef`, `parse_uv_tool_list`, `parse_npm_global_json`, `run_uv_tool_list`, `run_npm_global_list`.
- Produces:
  - `VersionDiff(name: str, have: str, want: str)` (dataclass).
  - `PackageAreaStatus(area: Literal["uv","npm"], state: Literal["ok","drift","unavailable"], missing: list[PackageRef], extra: list[str], version_differs: list[VersionDiff])`.
  - `PackageDetector.get_status(area: str, wanted: list[PackageRef], ignore: list[str]) -> PackageAreaStatus`.
  - `compare_packages(area, wanted, installed, ignore) -> PackageAreaStatus` — pure, used by the detector and by the source-staleness check in Task 7.

- [ ] **Step 1: Write the failing tests**

```python
class TestPackageDetector:
    def test_compare_reports_all_three_kinds(self):
        from sccs.doctor.mirror import PackageRef, VersionDiff, compare_packages

        wanted = [PackageRef(name="sccs", version="2.68.0"), PackageRef(name="odoodev-equitania", version="0.68.0")]
        installed = [PackageRef(name="sccs", version="2.67.2"), PackageRef(name="build", version="1.6.1")]
        st = compare_packages("uv", wanted, installed, ignore=[])
        assert st.state == "drift"
        assert st.missing == [PackageRef(name="odoodev-equitania", version="0.68.0")]
        assert st.extra == ["build"]
        assert st.version_differs == [VersionDiff(name="sccs", have="2.67.2", want="2.68.0")]

    def test_ignore_hides_everywhere(self):
        from sccs.doctor.mirror import PackageRef, compare_packages

        wanted = [PackageRef(name="a", version="1")]
        installed = [PackageRef(name="b", version="1")]
        assert compare_packages("npm", wanted, installed, ignore=["a", "b"]).state == "ok"

    def test_detector_uv_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import PackageDetector, PackageRef

        monkeypatch.setattr(mirror, "run_uv_tool_list", lambda: None)
        st = PackageDetector().get_status("uv", [PackageRef(name="sccs", version="1")], ignore=[])
        assert st.state == "unavailable"

    def test_detector_npm_reads_json(self, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import PackageDetector, PackageRef

        monkeypatch.setattr(mirror, "run_npm_global_list", lambda: NPM_JSON)
        st = PackageDetector().get_status("npm", [PackageRef(name="less", version="4.6.4")], ignore=[])
        assert st.state == "drift"
        assert st.extra == ["@playwright/cli"]
        assert st.missing == [] and st.version_differs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestPackageDetector -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# --- packages (uv tools, npm globals) --------------------------------------


@dataclass
class VersionDiff:
    name: str
    have: str
    want: str


@dataclass
class PackageAreaStatus:
    area: str  # "uv" | "npm"
    state: str  # "ok" | "drift" | "unavailable"
    missing: list[PackageRef] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    version_differs: list[VersionDiff] = field(default_factory=list)


def compare_packages(
    area: str,
    wanted: list[PackageRef],
    installed: list[PackageRef],
    ignore: list[str],
) -> PackageAreaStatus:
    skip = set(ignore)
    want = {p.name: p for p in wanted if p.name not in skip}
    have = {p.name: p for p in installed if p.name not in skip}
    st = PackageAreaStatus(
        area=area,
        state="ok",
        missing=[want[n] for n in sorted(set(want) - set(have))],
        extra=sorted(set(have) - set(want)),
        version_differs=[
            VersionDiff(name=n, have=have[n].version, want=want[n].version)
            for n in sorted(set(want) & set(have))
            if have[n].version != want[n].version
        ],
    )
    if st.missing or st.extra or st.version_differs:
        st.state = "drift"
    return st


class PackageDetector:
    def installed(self, area: str) -> list[PackageRef] | None:
        if area == "uv":
            text = run_uv_tool_list()
            return None if text is None else parse_uv_tool_list(text)
        text = run_npm_global_list()
        return None if text is None else parse_npm_global_json(text)

    def get_status(self, area: str, wanted: list[PackageRef], ignore: list[str]) -> PackageAreaStatus:
        installed = self.installed(area)
        if installed is None:
            return PackageAreaStatus(area=area, state="unavailable")
        return compare_packages(area, wanted, installed, ignore)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sccs/doctor/mirror.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: uv-tool and npm-global drift detectors (mirror parity)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Repo and Fisher detectors

**Files:**
- Modify: `sccs/doctor/mirror.py` (sections `# --- repos`, `# --- fisher`)
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Consumes: `MirrorRepoSpec`, `run_git_status_branch`, `run_git_fetch`, `run_fisher_list`.
- Produces:
  - `RepoStatus(spec: MirrorRepoSpec, state: Literal["ok","missing","behind","modified","not_a_repo","error"], detail: str = "", fetched: bool = False)`.
  - `parse_git_status_branch(text: str) -> tuple[bool, bool]` → `(behind, dirty)`.
  - `RepoDetector.get_statuses(specs, *, fetch: bool) -> list[RepoStatus]`.
  - `FisherStatus(state: Literal["ok","drift","unavailable","no_plugins_file"], missing: list[str], extra: list[str])`.
  - `FisherDetector.get_status(fish_plugins: Path) -> FisherStatus`.

- [ ] **Step 1: Write the failing tests**

```python
class TestRepoDetector:
    def _spec(self, home: Path, name: str = "beam"):
        from sccs.doctor.mirror import MirrorRepoSpec

        return MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path=f"~/gitbase/example/{name}")

    def test_parse_status_branch(self):
        from sccs.doctor.mirror import parse_git_status_branch

        assert parse_git_status_branch("## main...origin/main\n") == (False, False)
        assert parse_git_status_branch("## main...origin/main [behind 2]\n") == (True, False)
        assert parse_git_status_branch("## main...origin/main [ahead 1, behind 2]\n M x.fish\n") == (True, True)
        assert parse_git_status_branch("## main...origin/main\n?? new.fish\n") == (False, True)

    def test_missing(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import RepoDetector

        st = RepoDetector().get_statuses([self._spec(home)], fetch=False)[0]
        assert st.state == "missing"

    def test_not_a_repo(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import RepoDetector

        (home / "gitbase/example/beam").mkdir(parents=True)
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: None)
        assert RepoDetector().get_statuses([self._spec(home)], fetch=False)[0].state == "not_a_repo"

    def test_behind_modified_ok(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import RepoDetector

        (home / "gitbase/example/beam").mkdir(parents=True)
        fetched: list[Path] = []
        monkeypatch.setattr(mirror, "run_git_fetch", lambda p: (fetched.append(p), True)[1])
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: "## main...origin/main [behind 3]\n")
        st = RepoDetector().get_statuses([self._spec(home)], fetch=True)[0]
        assert st.state == "behind" and st.fetched is True and fetched
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: "## main...origin/main [behind 3]\n M a\n")
        assert RepoDetector().get_statuses([self._spec(home)], fetch=False)[0].state == "modified"
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: "## main...origin/main\n")
        assert RepoDetector().get_statuses([self._spec(home)], fetch=False)[0].state == "ok"

    def test_fetch_failure_does_not_hide_local_state(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import RepoDetector

        (home / "gitbase/example/beam").mkdir(parents=True)
        monkeypatch.setattr(mirror, "run_git_fetch", lambda p: False)
        monkeypatch.setattr(mirror, "run_git_status_branch", lambda p: "## main...origin/main\n")
        st = RepoDetector().get_statuses([self._spec(home)], fetch=True)[0]
        assert st.state == "ok" and st.fetched is False and "fetch failed" in st.detail


class TestFisherDetector:
    def test_drift(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import FisherDetector

        plugins = tmp_path / "fish_plugins"
        plugins.write_text("jorgebucaran/fisher\nedc/bass\njethrokuan/z\n", encoding="utf-8")
        monkeypatch.setattr(mirror, "run_fisher_list", lambda: ["jorgebucaran/fisher", "edc/bass", "old/plugin"])
        st = FisherDetector().get_status(plugins)
        assert st.state == "drift"
        assert st.missing == ["jethrokuan/z"] and st.extra == ["old/plugin"]

    def test_ok_unavailable_and_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import FisherDetector

        plugins = tmp_path / "fish_plugins"
        assert FisherDetector().get_status(plugins).state == "no_plugins_file"
        plugins.write_text("edc/bass\n", encoding="utf-8")
        monkeypatch.setattr(mirror, "run_fisher_list", lambda: ["edc/bass"])
        assert FisherDetector().get_status(plugins).state == "ok"
        monkeypatch.setattr(mirror, "run_fisher_list", lambda: None)
        assert FisherDetector().get_status(plugins).state == "unavailable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestRepoDetector tests/test_doctor_mirror.py::TestFisherDetector -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Add `run_fisher_list, run_git_fetch, run_git_status_branch` to the runner import. Then:

```python
# --- repos ------------------------------------------------------------------

_BEHIND = re.compile(r"\[(?:[^\]]*, )?behind \d+")


def parse_git_status_branch(text: str) -> tuple[bool, bool]:
    """(behind, dirty) from `git status --porcelain=v1 -b` output."""
    lines = text.splitlines()
    if not lines:
        return (False, False)
    behind = bool(_BEHIND.search(lines[0]))
    dirty = any(line.strip() for line in lines[1:])
    return (behind, dirty)


@dataclass
class RepoStatus:
    spec: MirrorRepoSpec
    # "ok" | "missing" | "behind" | "modified" | "not_a_repo" | "error"
    state: str
    detail: str = ""
    fetched: bool = False

    @property
    def path(self) -> Path:
        return expand_path(self.spec.path)


class RepoDetector:
    """A repo with local modifications is `modified` even when it is also
    behind — it is reported and never touched. Fetch failure is recorded in
    `detail`, the local tracking state still decides."""

    def get_statuses(self, specs: list[MirrorRepoSpec], *, fetch: bool) -> list[RepoStatus]:
        out: list[RepoStatus] = []
        for spec in specs:
            path = expand_path(spec.path)
            if not path.exists():
                out.append(RepoStatus(spec=spec, state="missing"))
                continue
            fetched = False
            detail = ""
            if fetch:
                fetched = run_git_fetch(path)
                if not fetched:
                    detail = "fetch failed — state from last fetch"
            text = run_git_status_branch(path)
            if text is None:
                out.append(RepoStatus(spec=spec, state="not_a_repo", detail="git status failed", fetched=fetched))
                continue
            behind, dirty = parse_git_status_branch(text)
            if dirty:
                state = "modified"
            elif behind:
                state = "behind"
            else:
                state = "ok"
            out.append(RepoStatus(spec=spec, state=state, detail=detail, fetched=fetched))
        return out


# --- fisher -----------------------------------------------------------------


@dataclass
class FisherStatus:
    # "ok" | "drift" | "unavailable" | "no_plugins_file"
    state: str
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)


class FisherDetector:
    def get_status(self, fish_plugins: Path) -> FisherStatus:
        if not fish_plugins.is_file():
            return FisherStatus(state="no_plugins_file")
        wanted = {line.strip() for line in fish_plugins.read_text(encoding="utf-8").splitlines() if line.strip()}
        installed = run_fisher_list()
        if installed is None:
            return FisherStatus(state="unavailable")
        have = set(installed)
        st = FisherStatus(state="ok", missing=sorted(wanted - have), extra=sorted(have - wanted))
        if st.missing or st.extra:
            st.state = "drift"
        return st
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sccs/doctor/mirror.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: git checkout and Fisher drift detectors (mirror parity)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `MirrorReport` and `collect_mirror_report()` (both roles)

**Files:**
- Modify: `sccs/doctor/mirror.py` (section `# --- report`)
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `MirrorReport(role: MirrorRole, hostname: str, source_host: str | None, inventory: Inventory | None, inventory_path: str, brewfile: str, brew: BrewStatus | None, uv: PackageAreaStatus | None, npm: PackageAreaStatus | None, repos: list[RepoStatus], fisher: FisherStatus | None, source_stale: bool, cleanup: bool)` with properties `has_drift -> bool` (mirror: any missing/version/repo missing-behind-modified/fisher drift; source: `source_stale`) and `has_extras -> bool`.
  - `collect_mirror_report(cfg: MirrorConfig | None, *, hostname: str | None = None, fetch: bool = False) -> MirrorReport | None` — `None` when role is `off`.

On the **source**, the same detectors run against the same files: `brew.state == "drift"` means the Brewfile is stale; `uv`/`npm` drift against the *current inventory file* means the inventory is stale; a missing inventory file is stale too. Repos and Fisher are checked on both roles (a source that is behind origin is worth a row, but it is not a "problem").

- [ ] **Step 1: Write the failing tests**

```python
def _stub_all(monkeypatch, *, brew_state="ok", uv_state="ok", npm_state="ok"):
    """Stub every detector the report uses; states are set directly."""
    from sccs.doctor import mirror
    from sccs.doctor.mirror import BrewStatus, FisherStatus, PackageAreaStatus

    monkeypatch.setattr(mirror.BrewDetector, "get_status", lambda self, brewfile, ignore: BrewStatus(state=brew_state))
    monkeypatch.setattr(
        mirror.PackageDetector,
        "get_status",
        lambda self, area, wanted, ignore: PackageAreaStatus(area=area, state=uv_state if area == "uv" else npm_state),
    )
    monkeypatch.setattr(mirror.RepoDetector, "get_statuses", lambda self, specs, fetch: [])
    monkeypatch.setattr(mirror.FisherDetector, "get_status", lambda self, p: FisherStatus(state="ok"))


class TestCollectMirrorReport:
    def test_off_returns_none(self):
        from sccs.doctor.mirror import MirrorConfig, collect_mirror_report

        assert collect_mirror_report(None, hostname="x") is None
        assert collect_mirror_report(MirrorConfig(), hostname="x") is None

    def test_mirror_reads_inventory(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import Inventory, MirrorConfig, PackageRef, collect_mirror_report, write_inventory

        _stub_all(monkeypatch, uv_state="drift")
        cfg = MirrorConfig(source_host="live-mac")
        inv = Inventory(captured_at="t", captured_on="live-mac", uv_tools=[PackageRef(name="sccs", version="1")])
        write_inventory(home / ".config/sccs/inventory.yaml", inv)
        rep = collect_mirror_report(cfg, hostname="demo-mac")
        assert rep is not None and rep.role == "mirror"
        assert rep.inventory == inv
        assert rep.has_drift is True
        assert rep.source_stale is False

    def test_mirror_without_inventory_has_no_package_rows(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import MirrorConfig, collect_mirror_report

        _stub_all(monkeypatch)
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="demo-mac")
        assert rep is not None and rep.inventory is None
        assert rep.uv is None and rep.npm is None
        assert rep.has_drift is False

    def test_source_is_stale_when_brew_or_inventory_drift(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import MirrorConfig, collect_mirror_report

        _stub_all(monkeypatch, brew_state="drift")
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="live-mac")
        assert rep is not None and rep.role == "source"
        assert rep.source_stale is True

    def test_source_with_missing_inventory_is_stale(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import MirrorConfig, collect_mirror_report

        _stub_all(monkeypatch)
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="live-mac")
        assert rep is not None and rep.source_stale is True

    def test_source_current(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor.mirror import Inventory, MirrorConfig, collect_mirror_report, write_inventory

        _stub_all(monkeypatch)
        write_inventory(home / ".config/sccs/inventory.yaml", Inventory(captured_at="t", captured_on="live-mac"))
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="live-mac")
        assert rep is not None and rep.source_stale is False and rep.has_drift is False

    def test_has_extras(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import BrewStatus, Inventory, MirrorConfig, collect_mirror_report, write_inventory

        _stub_all(monkeypatch)
        monkeypatch.setattr(
            mirror.BrewDetector, "get_status", lambda self, b, i: BrewStatus(state="drift", extra_formulae=["ffmpeg"])
        )
        write_inventory(home / ".config/sccs/inventory.yaml", Inventory(captured_at="t", captured_on="live-mac"))
        rep = collect_mirror_report(MirrorConfig(source_host="live-mac"), hostname="demo-mac")
        assert rep is not None and rep.has_extras is True and rep.has_drift is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestCollectMirrorReport -q`
Expected: FAIL — `ImportError: cannot import name 'collect_mirror_report'`

- [ ] **Step 3: Implement**

```python
# --- report -----------------------------------------------------------------


@dataclass
class MirrorReport:
    role: str  # MirrorRole
    hostname: str
    source_host: str | None
    inventory: Inventory | None
    inventory_path: str
    brewfile: str
    brew: BrewStatus | None
    uv: PackageAreaStatus | None
    npm: PackageAreaStatus | None
    repos: list[RepoStatus]
    fisher: FisherStatus | None
    source_stale: bool
    cleanup: bool

    @property
    def has_drift(self) -> bool:
        """Something the mirror lacks or has at the wrong version. On the
        source this is `source_stale`. Extras are NOT drift — they are
        reported in yellow and offered under `optimize --strict` only."""
        if self.role == "source":
            return self.source_stale
        if self.brew is not None and self.brew.missing_count:
            return True
        for area in (self.uv, self.npm):
            if area is not None and (area.missing or area.version_differs):
                return True
        if any(r.state in {"missing", "behind", "modified", "not_a_repo"} for r in self.repos):
            return True
        return bool(self.fisher is not None and self.fisher.state == "drift")

    @property
    def has_extras(self) -> bool:
        if self.brew is not None and self.brew.extra_count:
            return True
        return any(area is not None and area.extra for area in (self.uv, self.npm))


def collect_mirror_report(
    cfg: MirrorConfig | None,
    *,
    hostname: str | None = None,
    fetch: bool = False,
) -> MirrorReport | None:
    role = resolve_role(cfg, hostname)
    if role == "off" or cfg is None:
        return None
    host = hostname if hostname is not None else current_hostname()
    inventory_path = expand_path(cfg.inventory_path)
    inventory = load_inventory(inventory_path)
    brew = BrewDetector().get_status(expand_path(cfg.brewfile), cfg.ignore_brew)
    uv = npm = None
    if inventory is not None:
        detector = PackageDetector()
        uv = detector.get_status("uv", inventory.uv_tools, cfg.ignore_uv_tools)
        npm = detector.get_status("npm", inventory.npm_globals, cfg.ignore_npm)
    repos = RepoDetector().get_statuses(cfg.repos, fetch=fetch)
    fisher = FisherDetector().get_status(expand_path(cfg.fish_plugins))

    source_stale = False
    if role == "source":
        source_stale = (
            inventory is None
            or brew.state in {"drift", "no_brewfile"}
            or any(area is not None and area.state == "drift" for area in (uv, npm))
        )
    return MirrorReport(
        role=role,
        hostname=normalize_host(host),
        source_host=cfg.source_host,
        inventory=inventory,
        inventory_path=str(inventory_path),
        brewfile=str(expand_path(cfg.brewfile)),
        brew=brew,
        uv=uv,
        npm=npm,
        repos=repos,
        fisher=fisher,
        source_stale=source_stale,
        cleanup=cfg.cleanup,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sccs/doctor/mirror.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: mirror report for source and mirror roles

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Action builders and plan wiring (the two hard rules)

**Files:**
- Modify: `sccs/doctor/mirror.py` (section `# --- actions`)
- Modify: `sccs/doctor/installer.py` — `build_install_plan` (~1592), `build_update_plan` (~1654), `build_optimize_plan` (~1710)
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Consumes: `DoctorAction` (`sccs.doctor.installer`), `run_brew_bundle_dump`, `capture_inventory`, `write_inventory`.
- Produces:
  - `mirror_install_actions(report: MirrorReport | None) -> list[DoctorAction]` — mirror only: `brew bundle install`, `uv tool install <n>==<v> --reinstall`, `npm install -g <n>@<v>`, `git clone`, `git pull --ff-only`, `fish -c "fisher update"`.
  - `mirror_update_actions(report: MirrorReport | None) -> list[DoctorAction]` — source: one `python_callable` capture action (`auto_confirm=True`); mirror: `mirror_install_actions(report)`.
  - `mirror_remove_actions(report: MirrorReport | None) -> list[DoctorAction]` — mirror only, `report.cleanup` only: one action per extra, `auto_confirm=False`; never `npm`, `corepack`, `sccs`.
  - `build_install_plan(..., mirror: MirrorReport | None = None)`, `build_update_plan(..., mirror=...)`, `build_optimize_plan(..., mirror=...)`.

Component naming: `mirror:brew`, `mirror:uv:<name>`, `mirror:npm:<name>`, `mirror:repo:<basename>`, `mirror:fisher`, `mirror:capture`.

- [ ] **Step 1: Write the failing tests**

```python
def _report(**kw):
    from sccs.doctor.mirror import MirrorReport

    base = dict(
        role="mirror",
        hostname="demo-mac",
        source_host="live-mac",
        inventory=None,
        inventory_path="/x/inventory.yaml",
        brewfile="/x/Brewfile",
        brew=None,
        uv=None,
        npm=None,
        repos=[],
        fisher=None,
        source_stale=False,
        cleanup=True,
    )
    base.update(kw)
    return MirrorReport(**base)


class TestMirrorActions:
    def test_install_actions_cover_every_area(self, home: Path):
        from sccs.doctor.mirror import (
            BrewStatus,
            FisherStatus,
            MirrorRepoSpec,
            PackageAreaStatus,
            PackageRef,
            RepoStatus,
            VersionDiff,
            mirror_install_actions,
        )

        spec_missing = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        spec_behind = MirrorRepoSpec(url="https://gitlab.example/org/two.git", path="~/gitbase/example/two", branch="main")
        rep = _report(
            brew=BrewStatus(state="drift", missing_formulae=["bat"], extra_formulae=["ffmpeg"]),
            uv=PackageAreaStatus(
                area="uv",
                state="drift",
                missing=[PackageRef(name="odoodev-equitania", version="0.68.0")],
                version_differs=[VersionDiff(name="sccs", have="2.67.2", want="2.68.0")],
                extra=["build"],
            ),
            npm=PackageAreaStatus(area="npm", state="drift", missing=[PackageRef(name="@playwright/cli", version="0.1.18")]),
            repos=[RepoStatus(spec=spec_missing, state="missing"), RepoStatus(spec=spec_behind, state="behind")],
            fisher=FisherStatus(state="drift", missing=["jethrokuan/z"]),
        )
        cmds = [a.cmd for a in mirror_install_actions(rep)]
        assert ["brew", "bundle", "install", "--file", "/x/Brewfile", "--no-upgrade"] in cmds
        assert ["uv", "tool", "install", "odoodev-equitania==0.68.0", "--reinstall"] in cmds
        assert ["uv", "tool", "install", "sccs==2.68.0", "--reinstall"] in cmds
        assert ["npm", "install", "-g", "@playwright/cli@0.1.18"] in cmds
        assert ["git", "clone", "git@gitlab.example:org/beam.git", str(home / "gitbase/example/beam")] in cmds
        assert ["git", "-C", str(home / "gitbase/example/two"), "pull", "--ff-only"] in cmds
        assert ["fish", "-c", "fisher update"] in cmds
        # extras never appear in install actions
        assert not any(a.cmd and "uninstall" in a.cmd for a in mirror_install_actions(rep))

    def test_clone_with_branch(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec, RepoStatus, mirror_install_actions

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam", branch="dev")
        (a,) = mirror_install_actions(_report(repos=[RepoStatus(spec=spec, state="missing")]))
        assert a.cmd == ["git", "clone", "--branch", "dev", "git@gitlab.example:org/beam.git", str(home / "gitbase/example/beam")]

    def test_modified_repo_is_print_only(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec, RepoStatus, mirror_install_actions

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        (a,) = mirror_install_actions(_report(repos=[RepoStatus(spec=spec, state="modified")]))
        assert a.runnable is False and a.cmd is None and "modified" in (a.manual_block or "")

    def test_pull_is_auto_confirmed_but_installs_are_not(self, home: Path):
        from sccs.doctor.mirror import MirrorRepoSpec, PackageAreaStatus, PackageRef, RepoStatus, mirror_install_actions

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        rep = _report(
            repos=[RepoStatus(spec=spec, state="behind")],
            uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")]),
        )
        by_component = {a.component: a for a in mirror_install_actions(rep)}
        assert by_component["mirror:repo:beam"].auto_confirm is True
        assert by_component["mirror:uv:x"].auto_confirm is False

    # --- the two hard rules ---------------------------------------------

    def test_source_never_receives_install_or_remove_actions(self):
        from sccs.doctor.mirror import (
            BrewStatus,
            PackageAreaStatus,
            PackageRef,
            mirror_install_actions,
            mirror_remove_actions,
        )

        rep = _report(
            role="source",
            source_stale=True,
            brew=BrewStatus(state="drift", missing_formulae=["bat"], extra_formulae=["ffmpeg"]),
            uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")], extra=["y"]),
        )
        assert mirror_install_actions(rep) == []
        assert mirror_remove_actions(rep) == []

    def test_mirror_never_writes_inventory(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import mirror_update_actions

        writes: list[Path] = []
        monkeypatch.setattr(mirror, "write_inventory", lambda p, inv: writes.append(p))
        monkeypatch.setattr(mirror, "run_brew_bundle_dump", lambda p: True)
        for a in mirror_update_actions(_report(role="mirror")):
            if a.python_callable:
                a.python_callable()
        assert writes == []
        assert all(a.component != "mirror:capture" for a in mirror_update_actions(_report(role="mirror")))

    def test_source_update_captures_both_files(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from sccs.doctor import mirror
        from sccs.doctor.mirror import Inventory, mirror_update_actions

        dumped: list[Path] = []
        written: list[tuple[Path, Inventory]] = []
        monkeypatch.setattr(mirror, "run_brew_bundle_dump", lambda p: (dumped.append(p), True)[1])
        monkeypatch.setattr(mirror, "capture_inventory", lambda host: Inventory(captured_at="t", captured_on=host))
        monkeypatch.setattr(mirror, "write_inventory", lambda p, inv: written.append((p, inv)))
        (a,) = mirror_update_actions(_report(role="source", source_stale=True))
        assert a.component == "mirror:capture" and a.auto_confirm is True and a.python_callable
        a.python_callable()
        assert dumped == [Path("/x/Brewfile")]
        assert written[0][0] == Path("/x/inventory.yaml") and written[0][1].captured_on == "demo-mac"

    def test_source_update_runs_even_when_current(self):
        """`doctor update` on the source always refreshes — that is what keeps
        the files current; staleness only decides the check row."""
        from sccs.doctor.mirror import mirror_update_actions

        assert len(mirror_update_actions(_report(role="source", source_stale=False))) == 1

    def test_remove_actions_one_per_extra_never_protected(self):
        from sccs.doctor.mirror import BrewStatus, PackageAreaStatus, mirror_remove_actions

        rep = _report(
            brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"], extra_casks=["davit"], extra_taps=["a/b"]),
            uv=PackageAreaStatus(area="uv", state="drift", extra=["build", "sccs"]),
            npm=PackageAreaStatus(area="npm", state="drift", extra=["pnpm", "npm", "corepack"]),
        )
        actions = mirror_remove_actions(rep)
        cmds = [a.cmd for a in actions]
        assert ["brew", "uninstall", "ffmpeg"] in cmds
        assert ["brew", "uninstall", "--cask", "davit"] in cmds
        assert ["brew", "untap", "a/b"] in cmds
        assert ["uv", "tool", "uninstall", "build"] in cmds
        assert ["npm", "uninstall", "-g", "pnpm"] in cmds
        assert not any("sccs" in (a.cmd or []) for a in actions)
        assert not any(c[-1] in {"npm", "corepack"} for c in cmds if c)
        assert all(a.auto_confirm is False and a.label.startswith("REMOVE ") for a in actions)
        assert len(actions) == 5

    def test_remove_actions_respect_cleanup_false(self):
        from sccs.doctor.mirror import BrewStatus, mirror_remove_actions

        rep = _report(cleanup=False, brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"]))
        assert mirror_remove_actions(rep) == []

    def test_none_report_yields_nothing(self):
        from sccs.doctor.mirror import mirror_install_actions, mirror_remove_actions, mirror_update_actions

        assert mirror_install_actions(None) == mirror_update_actions(None) == mirror_remove_actions(None) == []


class TestPlanWiring:
    def _base(self):
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.schema import DoctorConfig

        return dict(
            config=DoctorConfig(),
            node=NodeStatus(installed=True, version="22.0.0", major=22, path="/usr/bin/node"),
            claude_cli=ClaudeCliStatus(installed=True, version="1.0.0", path="/usr/bin/claude"),
            plugins=[],
            npx_tools=[],
        )

    def test_install_plan_contains_mirror_actions(self, home: Path):
        from sccs.doctor.installer import build_install_plan
        from sccs.doctor.mirror import PackageAreaStatus, PackageRef

        rep = _report(uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")]))
        plan = build_install_plan(**self._base(), mirror=rep)
        assert any(a.component == "mirror:uv:x" for a in plan.actions)

    def test_removals_only_in_strict_optimize(self, home: Path):
        from sccs.doctor.installer import build_install_plan, build_optimize_plan, build_update_plan
        from sccs.doctor.mirror import BrewStatus

        rep = _report(brew=BrewStatus(state="drift", extra_formulae=["ffmpeg"]))
        base = self._base()
        opt = dict(foreign_plugins=[], mcp_servers=[], foreign_mcp_servers=[])
        has_remove = lambda plan: any(a.label.startswith("REMOVE ") and "ffmpeg" in a.label for a in plan.actions)  # noqa: E731
        assert not has_remove(build_install_plan(**base, mirror=rep))
        assert not has_remove(build_update_plan(**base, mirror=rep))
        assert not has_remove(build_optimize_plan(**base, **opt, mirror=rep, strict=False))
        assert has_remove(build_optimize_plan(**base, **opt, mirror=rep, strict=True))
```

Check the real constructor signatures of `NodeStatus` and `ClaudeCliStatus` in `sccs/doctor/detectors.py` before running and adjust the `_base()` helper to them (look at how `tests/test_doctor.py::_make_status_set` builds them, line ~523).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestMirrorActions tests/test_doctor_mirror.py::TestPlanWiring -q`
Expected: FAIL — `ImportError: cannot import name 'mirror_install_actions'`

- [ ] **Step 3: Implement the action builders**

Add `from sccs.doctor.runner import run_brew_bundle_dump` (extend the existing import line) and, **inside the functions** (not at module level, to avoid the `installer → mirror → installer` cycle), `from sccs.doctor.installer import DoctorAction`. Use `TYPE_CHECKING` for the annotation:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sccs.doctor.installer import DoctorAction
```

Then:

```python
# --- actions ----------------------------------------------------------------
#
# Two rules, both enforced here and pinned by tests:
#   - the source never receives install/remove actions (it IS the truth);
#   - a mirror never writes the inventory (only the source captures).


def _safe(name: str, field: str) -> str | None:
    try:
        return _validate_safe_name(name, field)
    except ValueError as exc:
        logger.warning("mirror: skipping %s — %s", field, exc)
        return None


def mirror_install_actions(report: MirrorReport | None) -> list[DoctorAction]:
    from sccs.doctor.installer import DoctorAction

    if report is None or report.role != "mirror":
        return []
    actions: list[DoctorAction] = []

    if report.brew is not None and report.brew.missing_count:
        actions.append(
            DoctorAction(
                label=f"brew bundle install — {report.brew.missing_count} missing from Brewfile",
                cmd=["brew", "bundle", "install", "--file", report.brewfile, "--no-upgrade"],
                component="mirror:brew",
            )
        )

    for area in (report.uv, report.npm):
        if area is None:
            continue
        wanted = list(area.missing) + [PackageRef(name=d.name, version=d.want) for d in area.version_differs]
        for pkg in wanted:
            name = _safe(pkg.name, f"{area.area} package")
            if name is None or not _VERSION_PATTERN.match(pkg.version):
                continue
            if area.area == "uv":
                cmd = ["uv", "tool", "install", f"{name}=={pkg.version}", "--reinstall"]
            else:
                cmd = ["npm", "install", "-g", f"{name}@{pkg.version}"]
            actions.append(
                DoctorAction(
                    label=f"install {area.area} {name} {pkg.version}",
                    cmd=cmd,
                    component=f"mirror:{area.area}:{name}",
                )
            )

    for repo in report.repos:
        path = repo.path
        component = f"mirror:repo:{path.name}"
        if repo.state == "missing":
            cmd = ["git", "clone"]
            if repo.spec.branch:
                cmd += ["--branch", repo.spec.branch]
            cmd += [repo.spec.url, str(path)]
            actions.append(DoctorAction(label=f"clone {repo.spec.url} → {path}", cmd=cmd, component=component))
        elif repo.state == "behind":
            actions.append(
                DoctorAction(
                    label=f"pull --ff-only {path}",
                    cmd=["git", "-C", str(path), "pull", "--ff-only"],
                    component=component,
                    auto_confirm=True,
                )
            )
        elif repo.state in {"modified", "not_a_repo"}:
            actions.append(
                DoctorAction(
                    label=f"{path}: {repo.state} — left untouched",
                    cmd=None,
                    runnable=False,
                    manual_block=(
                        f"# {path} is {repo.state}; SCCS never touches a checkout with local changes.\n"
                        f"# Commit or stash there, then re-run `sccs doctor install`."
                    ),
                    component=component,
                )
            )

    if report.fisher is not None and report.fisher.state == "drift":
        actions.append(
            DoctorAction(
                label=f"fisher update — {len(report.fisher.missing)} missing, {len(report.fisher.extra)} extra",
                cmd=["fish", "-c", "fisher update"],
                component="mirror:fisher",
            )
        )
    return actions


def mirror_update_actions(report: MirrorReport | None) -> list[DoctorAction]:
    from sccs.doctor.installer import DoctorAction

    if report is None:
        return []
    if report.role == "mirror":
        return mirror_install_actions(report)

    brewfile = Path(report.brewfile)
    inventory_path = Path(report.inventory_path)
    hostname = report.hostname

    def _capture() -> None:
        if not run_brew_bundle_dump(brewfile):
            logger.warning("brew bundle dump failed — Brewfile left as is")
        write_inventory(inventory_path, capture_inventory(hostname))

    return [
        DoctorAction(
            label="capture source inventory (Brewfile + inventory.yaml)",
            python_callable=_capture,
            component="mirror:capture",
            auto_confirm=True,
        )
    ]


def mirror_remove_actions(report: MirrorReport | None) -> list[DoctorAction]:
    """One confirm-gated action per extra. Only `build_optimize_plan(strict=True)`
    calls this; `cleanup: false` turns it off entirely."""
    from sccs.doctor.installer import DoctorAction

    if report is None or report.role != "mirror" or not report.cleanup:
        return []
    actions: list[DoctorAction] = []

    def add(label: str, cmd: list[str], component: str) -> None:
        actions.append(DoctorAction(label=f"REMOVE {label}", cmd=cmd, component=component))

    if report.brew is not None:
        for name in report.brew.extra_formulae:
            if (n := _safe(name, "formula")) is not None:
                add(f"brew formula {n}", ["brew", "uninstall", n], f"mirror:brew:{n}")
        for name in report.brew.extra_casks:
            if (n := _safe(name, "cask")) is not None:
                add(f"brew cask {n}", ["brew", "uninstall", "--cask", n], f"mirror:brew:{n}")
        for name in report.brew.extra_taps:
            if (n := _safe(name, "tap")) is not None:
                add(f"brew tap {n}", ["brew", "untap", n], f"mirror:brew:{n}")
    if report.uv is not None:
        for name in report.uv.extra:
            if name in UV_NEVER_REMOVED:
                continue
            if (n := _safe(name, "uv tool")) is not None:
                add(f"uv tool {n}", ["uv", "tool", "uninstall", n], f"mirror:uv:{n}")
    if report.npm is not None:
        for name in report.npm.extra:
            if name in NPM_ALWAYS_IGNORED:
                continue
            if (n := _safe(name, "npm package")) is not None:
                add(f"npm global {n}", ["npm", "uninstall", "-g", n], f"mirror:npm:{n}")
    return actions
```

- [ ] **Step 4: Wire the plans in `installer.py`**

Add the keyword parameter `mirror: "MirrorReport | None" = None` to all three builders (after `skill_packages`, before `strict` in optimize) with `if TYPE_CHECKING: from sccs.doctor.mirror import MirrorReport` at the top. Then, in each function, right before the final `return InstallPlan(actions=actions)`:

`build_install_plan`:
```python
    from sccs.doctor.mirror import mirror_install_actions

    actions.extend(mirror_install_actions(mirror))
```

`build_update_plan`:
```python
    from sccs.doctor.mirror import mirror_update_actions

    actions.extend(mirror_update_actions(mirror))
```

`build_optimize_plan` — inside the existing `if strict:` branch, after `_foreign_mcp_remove_actions`:
```python
        from sccs.doctor.mirror import mirror_remove_actions

        actions.extend(mirror_remove_actions(mirror))
```
and, in the non-strict branch, a summary block when the report has extras:
```python
        if mirror is not None and mirror.has_extras:
            actions.append(
                DoctorAction(
                    label="mirror has software the source does not — review needed",
                    cmd=[],
                    runnable=False,
                    manual_block="# Re-run with `--strict` to queue one confirm-gated removal per extra.",
                    component="mirror:extras:summary",
                )
            )
```
and, after the strict/non-strict block, the install part for optimize:
```python
    from sccs.doctor.mirror import mirror_install_actions

    actions.extend(mirror_install_actions(mirror))
```
(read `build_optimize_plan` first — it composes install+update; add the mirror install once, not twice.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q && pytest -q`
Expected: all PASS (the existing plan tests pass `mirror=None` implicitly).

- [ ] **Step 6: Commit**

```bash
git add sccs/doctor/mirror.py sccs/doctor/installer.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: mirror install/update/remove actions and plan wiring

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Reporter rows and `has_problems`

**Files:**
- Modify: `sccs/doctor/reporter.py` — new `_mirror_rows()`, `render_doctor_report(mirror=)`, `has_problems(mirror=)`
- Test: `tests/test_doctor_mirror.py`

**Interfaces:**
- Produces: `_mirror_rows(report: MirrorReport | None) -> list[tuple[str, str, str, str]]` (Component, Status, Version, Detail — same 4-tuple as `_cli_tool_row`). `render_doctor_report(..., mirror: MirrorReport | None = None)`. `has_problems(..., mirror: MirrorReport | None = None) -> bool` — `True` when `mirror.role == "mirror" and mirror.has_drift`. Source staleness and extras never flip the exit code.

Row texts:

| Row | Status | Detail |
|---|---|---|
| `mirror: role` | `_OK` | `source · inventory current` / `mirror of live-mac` |
| `mirror: role` (source, stale) | `_STALE` | `source · Brewfile/inventory stale — run sccs doctor update` |
| `mirror: brew` | `_OK` / `_MISSING` (missing>0) / `_STALE` (only extras) / `_INFO` (unavailable, no_brewfile) | `3 missing · 1 extra` |
| `mirror: uv` / `mirror: npm` | same rule; `_INFO` `inventory not synced yet` when the area is `None` on a mirror | `1 missing · 1 version · 2 extra` |
| `mirror: repo <basename>` | `_OK` / `_MISSING` (missing, not_a_repo) / `_OUTDATED` (behind) / `_STALE` (modified) | url or detail |
| `mirror: fisher` | `_OK` / `_MISSING` (drift) / `_INFO` (unavailable, no file) | `1 missing · 1 extra` |

- [ ] **Step 1: Write the failing tests**

```python
class TestReporter:
    def test_rows_for_mirror_with_drift(self, home: Path):
        from sccs.doctor.mirror import BrewStatus, FisherStatus, MirrorRepoSpec, PackageAreaStatus, PackageRef, RepoStatus
        from sccs.doctor.reporter import _mirror_rows

        spec = MirrorRepoSpec(url="git@gitlab.example:org/beam.git", path="~/gitbase/example/beam")
        rep = _report(
            brew=BrewStatus(state="drift", missing_formulae=["bat"], extra_formulae=["ffmpeg"]),
            uv=PackageAreaStatus(area="uv", state="drift", missing=[PackageRef(name="x", version="1")]),
            npm=PackageAreaStatus(area="npm", state="ok"),
            repos=[RepoStatus(spec=spec, state="behind")],
            fisher=FisherStatus(state="ok"),
        )
        rows = {r[0]: r for r in _mirror_rows(rep)}
        assert "mirror of live-mac" in rows["mirror: role"][3]
        assert "MISSING" in rows["mirror: brew"][1] and "1 missing" in rows["mirror: brew"][3] and "1 extra" in rows["mirror: brew"][3]
        assert "MISSING" in rows["mirror: uv"][1]
        assert "OK" in rows["mirror: npm"][1]
        assert "OUTDATED" in rows["mirror: repo beam"][1]
        assert "OK" in rows["mirror: fisher"][1]

    def test_only_extras_is_stale_not_missing(self):
        from sccs.doctor.mirror import BrewStatus
        from sccs.doctor.reporter import _mirror_rows

        rows = {r[0]: r for r in _mirror_rows(_report(brew=BrewStatus(state="drift", extra_casks=["davit"])))}
        assert "STALE" in rows["mirror: brew"][1]

    def test_source_rows(self):
        from sccs.doctor.reporter import _mirror_rows

        rows = {r[0]: r for r in _mirror_rows(_report(role="source", source_stale=True))}
        assert "STALE" in rows["mirror: role"][1] and "sccs doctor update" in rows["mirror: role"][3]
        rows = {r[0]: r for r in _mirror_rows(_report(role="source", source_stale=False))}
        assert "OK" in rows["mirror: role"][1] and "inventory current" in rows["mirror: role"][3]

    def test_no_rows_when_off(self):
        from sccs.doctor.reporter import _mirror_rows

        assert _mirror_rows(None) == []

    def test_has_problems_only_for_mirror_drift(self):
        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.mirror import BrewStatus
        from sccs.doctor.reporter import has_problems

        base = dict(
            node=NodeStatus(installed=True, version="22.0.0", major=22, path="/usr/bin/node"),
            claude_cli=ClaudeCliStatus(installed=True, version="1.0.0", path="/usr/bin/claude"),
            plugins=[],
            npx_tools=[],
        )
        assert has_problems(**base, mirror=_report(brew=BrewStatus(state="drift", missing_formulae=["bat"]))) is True
        assert has_problems(**base, mirror=_report(brew=BrewStatus(state="drift", extra_formulae=["x"]))) is False
        assert has_problems(**base, mirror=_report(role="source", source_stale=True)) is False
        assert has_problems(**base, mirror=None) is False

    def test_render_includes_mirror_block(self, home: Path):
        from rich.console import Console

        from sccs.doctor.detectors import ClaudeCliStatus, NodeStatus
        from sccs.doctor.mirror import BrewStatus
        from sccs.doctor.reporter import render_doctor_report

        console = Console(record=True, width=120, force_terminal=False)
        render_doctor_report(
            console,
            node=NodeStatus(installed=True, version="22.0.0", major=22, path="/usr/bin/node"),
            claude_cli=ClaudeCliStatus(installed=True, version="1.0.0", path="/usr/bin/claude"),
            plugins=[],
            npx_tools=[],
            min_node_major=22,
            mirror=_report(brew=BrewStatus(state="drift", missing_formulae=["bat"])),
        )
        text = console.export_text()
        assert "mirror: brew" in text and "mirror: role" in text
```

(Adjust `NodeStatus`/`ClaudeCliStatus` construction to the real signatures, as in Task 8.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestReporter -q`
Expected: FAIL — `ImportError: cannot import name '_mirror_rows'`

- [ ] **Step 3: Implement**

In `reporter.py`, next to `_cli_tool_row`:

```python
def _counts(*pairs: tuple[int, str]) -> str:
    return " · ".join(f"{n} {word}" for n, word in pairs if n)


def _area_status(missing: int, version: int, extra: int, available: bool) -> str:
    if not available:
        return _INFO
    if missing or version:
        return _MISSING
    if extra:
        return _STALE
    return _OK


def _mirror_rows(report: "MirrorReport | None") -> list[tuple[str, str, str, str]]:
    """Mirror parity (v2.68.0). Missing/wrong version on a mirror is red;
    extras are yellow (offered under `optimize --strict` only); a stale
    source is yellow and never a problem."""
    if report is None:
        return []
    rows: list[tuple[str, str, str, str]] = []
    if report.role == "source":
        if report.source_stale:
            rows.append(("mirror: role", _STALE, "", "source · Brewfile/inventory stale — run `sccs doctor update`"))
        else:
            rows.append(("mirror: role", _OK, "", "source · inventory current"))
    else:
        rows.append(("mirror: role", _OK, "", f"mirror of {report.source_host}"))

    brew = report.brew
    if brew is None or brew.state in {"unavailable", "no_brewfile"}:
        detail = "brew not installed" if brew is None or brew.state == "unavailable" else "no Brewfile synced yet"
        rows.append(("mirror: brew", _INFO, "", detail))
    else:
        rows.append(
            (
                "mirror: brew",
                _area_status(brew.missing_count, 0, brew.extra_count, True),
                "",
                _counts((brew.missing_count, "missing"), (brew.extra_count, "extra")) or "in sync with Brewfile",
            )
        )

    for label, area in (("uv", report.uv), ("npm", report.npm)):
        if area is None:
            rows.append((f"mirror: {label}", _INFO, "", "inventory not synced yet"))
            continue
        if area.state == "unavailable":
            rows.append((f"mirror: {label}", _INFO, "", f"{label} not installed"))
            continue
        rows.append(
            (
                f"mirror: {label}",
                _area_status(len(area.missing), len(area.version_differs), len(area.extra), True),
                "",
                _counts((len(area.missing), "missing"), (len(area.version_differs), "version"), (len(area.extra), "extra"))
                or "in sync with inventory",
            )
        )

    for repo in report.repos:
        status = {
            "ok": _OK,
            "behind": _OUTDATED,
            "modified": _STALE,
        }.get(repo.state, _MISSING)
        detail = repo.detail or (repo.spec.url if repo.state != "ok" else str(repo.path))
        rows.append((f"mirror: repo {repo.path.name}", status, "", f"{repo.state} — {detail}"))

    fisher = report.fisher
    if fisher is None or fisher.state in {"unavailable", "no_plugins_file"}:
        rows.append(("mirror: fisher", _INFO, "", "fisher or fish_plugins not available"))
    elif fisher.state == "drift":
        rows.append(("mirror: fisher", _MISSING, "", _counts((len(fisher.missing), "missing"), (len(fisher.extra), "extra"))))
    else:
        rows.append(("mirror: fisher", _OK, "", "in sync with fish_plugins"))
    return rows
```

Add `mirror: "MirrorReport | None" = None` to `render_doctor_report` and append `for row in _mirror_rows(mirror): table.add_row(*row)` where the other optional rows are added (after the `cli_tools` rows — read the function). Add `mirror: "MirrorReport | None" = None` to `has_problems` and, before its final `return False`:

```python
    if mirror is not None and mirror.role == "mirror" and mirror.has_drift:
        return True
```

Import under `TYPE_CHECKING`: `from sccs.doctor.mirror import MirrorReport`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doctor_mirror.py -q && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sccs/doctor/reporter.py tests/test_doctor_mirror.py
git commit -m "[ADD] doctor: mirror rows in the check table and has_problems

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: CLI wiring, `--json`, and the two default categories

**Files:**
- Modify: `sccs/cli.py` — `_collect_doctor_statuses` (~3020), `doctor_check` (~3200, the `--json` dict ~3225 and the `render_doctor_report`/`has_problems` calls), `doctor_install` (~3315), `doctor_update` (~3380), `doctor_optimize` (~3459)
- Modify: `sccs/config/defaults.py` — add `homebrew_bundle` after `starship_config`, `sccs_inventory` after `git_config`
- Test: `tests/test_doctor_mirror.py`, `tests/test_config.py`

**Interfaces:**
- `_collect_doctor_statuses(...)` result dict gains `"mirror": MirrorReport | None` (collected with `fetch=check_updates`).
- `doctor check --json` payload gains `"mirror": statuses.get("mirror")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_doctor_mirror.py`:

```python
class TestCliWiring:
    def _parse_clean(self, output: str):
        import json

        assert "\x1b" not in output
        lines = [line for line in output.splitlines() if line.strip()]
        assert len(lines) == 1, lines
        return json.loads(lines[0])

    def test_check_json_carries_mirror(self, home: Path, monkeypatch: pytest.MonkeyPatch):
        from click.testing import CliRunner

        from sccs import cli as cli_mod
        from sccs.doctor import mirror
        from sccs.doctor.mirror import BrewStatus, MirrorConfig

        cfg_path = home / ".config/sccs/config.yaml"
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(
            "repository:\n  path: ~/repo\ndoctor:\n  mirror:\n    source_host: live-mac\n", encoding="utf-8"
        )
        monkeypatch.setenv("SCCS_CONFIG", str(cfg_path))
        monkeypatch.setattr(mirror, "current_hostname", lambda: "demo-mac")
        monkeypatch.setattr(
            cli_mod,
            "collect_mirror_report",
            lambda cfg, hostname=None, fetch=False: _report(brew=BrewStatus(state="drift", missing_formulae=["bat"])),
        )
        # keep the rest of the doctor quiet
        for name in ("node", "claude_cli", "plugins", "npx_tools"):
            pass  # rely on the existing test_cli_json doctor stubs — see note below
        result = CliRunner().invoke(cli_mod.cli, ["doctor", "check", "--json", "--no-update-check"])
        payload = self._parse_clean(result.output)
        assert payload["mirror"]["role"] == "mirror"
        assert payload["mirror"]["brew"]["missing_formulae"] == ["bat"]
        assert payload["has_problems"] is True

    def test_default_categories(self):
        from sccs.config.defaults import DEFAULT_CONFIG

        cats = DEFAULT_CONFIG["sync_categories"]
        assert cats["homebrew_bundle"]["local_path"] == "~/.config/homebrew/Brewfile"
        assert cats["homebrew_bundle"]["platforms"] == ["macos"]
        assert cats["sccs_inventory"]["local_path"] == "~/.config/sccs/inventory.yaml"
        assert cats["sccs_inventory"]["repo_path"] == ".config/sccs/inventory.yaml"
        assert cats["sccs_inventory"]["enabled"] is True
```

**Note on stubbing the rest of the doctor:** look at `tests/test_cli_json.py` for the existing `doctor check --json` test and copy its stubbing of `_collect_doctor_statuses` inputs (it patches the detectors so no `node`/`claude` binaries are needed). Reuse exactly that setup here instead of the placeholder loop above; the loop is only a marker for where it goes. The assertion that matters is the `mirror` key and `has_problems`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor_mirror.py::TestCliWiring -q`
Expected: FAIL — `KeyError: 'mirror'` / `KeyError: 'homebrew_bundle'`.

- [ ] **Step 3: Wire the CLI**

In `sccs/cli.py`, import at module level next to the other doctor imports:

```python
from sccs.doctor.mirror import collect_mirror_report
```

In `_collect_doctor_statuses`, before the `result = {...}` literal:

```python
    mirror = collect_mirror_report(getattr(doctor_cfg, "mirror", None), fetch=check_updates)
```

and add `"mirror": mirror,` to the dict.

In `doctor_check`: pass `mirror=statuses.get("mirror")` to **both** `render_doctor_report(...)` and `has_problems(...)`, and add `"mirror": statuses.get("mirror"),` to the `emit_json({...})` literal.

In `doctor_install`, `doctor_update`, `doctor_optimize`: add `mirror=statuses.get("mirror")` to the `build_*_plan(...)` calls.

`emit_json` must serialise `MirrorReport` (dataclass containing pydantic models and nested dataclasses). Check `sccs/output/json_emit.py`: if its default handler already covers `dataclasses.asdict` + `BaseModel.model_dump`, nothing to do; if it only covers dataclasses, extend the default with

```python
    if isinstance(obj, BaseModel):
        return obj.model_dump()
```

and add a test in `tests/test_doctor_mirror.py::TestCliWiring` that `emit_json({"m": _report(...)})` produces one line of valid JSON (capture with `capsys`).

- [ ] **Step 4: Add the default categories**

In `sccs/config/defaults.py`, after `starship_config`:

```python
        # Homebrew Bundle (macOS) — truth for the mirror area's Homebrew check.
        # Refresh on the source with `sccs doctor update` (brew bundle dump).
        "homebrew_bundle": {
            "enabled": True,
            "description": "Homebrew Bundle — formulae, casks and taps (Brewfile)",
            "local_path": "~/.config/homebrew/Brewfile",
            "repo_path": ".config/homebrew/Brewfile",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "platforms": ["macos"],
        },
```

after `git_config`:

```python
        # SCCS inventory (v2.68.0) — uv tools and npm globals captured on the
        # source host by `sccs doctor update`; a mirror reads it, never writes it.
        "sccs_inventory": {
            "enabled": True,
            "description": "SCCS software inventory for mirror parity (written by doctor update on the source)",
            "local_path": "~/.config/sccs/inventory.yaml",
            "repo_path": ".config/sccs/inventory.yaml",
            "sync_mode": "bidirectional",
            "item_type": "file",
        },
```

Run `pytest tests/test_config.py -q` — the new `TestFishDefaultsCoverEachFileOnce` scan only looks at `~/.config/fish` categories and is unaffected; `test_transfer.py` counts categories in a few places — if a count assertion breaks, update the number and say so in the commit.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q && ruff check sccs/ tests/ && mypy sccs/`
Expected: PASS, no findings.

- [ ] **Step 6: Commit**

```bash
git add sccs/cli.py sccs/config/defaults.py sccs/output/json_emit.py tests/test_doctor_mirror.py tests/test_config.py tests/test_transfer.py
git commit -m "[ADD] doctor: mirror area in check/install/update/optimize, --json, default categories

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Docs, release notes, version 2.68.0

**Files:**
- Modify: `docs/usage/doctor.md` (new section after "Skill-Pakete" in DE and after "Skill packages" in EN), `docs/usage/categories.md` (both tables), `docs/usage/cli-reference.md` (doctor block), `usage/AGENT.md` (version line + doctor rows), `RELEASE_NOTES.md`, `CLAUDE.md` (version + one "Mirror parity" bullet at the top of the notes list), `.project-tips` (version), `pyproject.toml`, `sccs/__init__.py` (two lines), `~/.claude/skills/sccs/SKILL.md` (version + one paragraph), `uv.lock`.

- [ ] **Step 1: `docs/usage/doctor.md` — German section**

Insert after the "Skill-Pakete (HyperFrames)" section:

````markdown
### Spiegel-Abgleich (zweiter Mac) — ab v2.68.0

Ein zweiter Mac soll dieselbe Software tragen wie der Live-Rechner. Der Doctor
gleicht vier Bereiche ab: Homebrew (Formulae, Casks, Taps), uv-Tools und
npm-Globals, eigene Git-Checkouts und Fisher-Plugins.

```yaml
doctor:
  mirror:
    source_host: live-mac            # Hostname des Live-Rechners; Domain-Suffix egal
    cleanup: true                    # Überzähliges unter `optimize --strict` anbieten
    repos:
      - url: git@gitlab.example:org/beam.git
        path: ~/gitbase/example/beam
    ignore_brew: []                  # Namen, die der Abgleich nie anfasst
    ignore_uv_tools: []
    ignore_npm: []
```

Der Rechner, dessen Hostname passt, ist die **Quelle**; jeder andere ist
**Spiegel**. Ohne `source_host` zeigt der Doctor keine Spiegelzeilen.

- **Quelle**: `sccs doctor update` schreibt Brewfile (`brew bundle dump`) und
  `~/.config/sccs/inventory.yaml` neu; beide werden über die Kategorien
  `homebrew_bundle` und `sccs_inventory` verteilt. `doctor check` meldet
  `STALE`, wenn die Dateien nicht mehr dem Live-Stand entsprechen. Die Quelle
  wird nie aus dem Inventar verändert.
- **Spiegel**: `doctor check` zeigt je Bereich fehlend, überzählig, falsche
  Version (`mirror: brew`, `mirror: uv`, `mirror: npm`, `mirror: repo <name>`,
  `mirror: fisher`). Fehlendes ist rot und Exit 1; Überzähliges ist gelb und
  kein Fehler. `doctor install` installiert Fehlendes (`brew bundle install`,
  `uv tool install name==version`, `npm install -g name@version`, `git clone`,
  `git pull --ff-only`, `fisher update`); uv und npm werden auf die Version der
  Quelle gepinnt, Homebrew kennt keine Versionen. Ein Checkout mit lokalen
  Änderungen wird gemeldet und nie angefasst. Ein Spiegel schreibt das Inventar
  nie.
- **Entfernen**: nur `sccs doctor optimize --strict`, eine Aktion je
  überzähligem Paket, jede einzeln zu bestätigen. `npm`, `corepack` und `sccs`
  werden nie entfernt; `cleanup: false` schaltet Entfernungen ganz ab.
````

- [ ] **Step 2: `docs/usage/doctor.md` — English section**

Insert after "Skill packages (HyperFrames)":

````markdown
### Mirror parity (second Mac) — since v2.68.0

A second Mac is to carry the same software as the live workstation. The doctor
reconciles four areas: Homebrew (formulae, casks, taps), uv tools and npm
globals, own git checkouts, and Fisher plugins.

```yaml
doctor:
  mirror:
    source_host: live-mac            # hostname of the live workstation; domain suffix ignored
    cleanup: true                    # offer removals under `optimize --strict`
    repos:
      - url: git@gitlab.example:org/beam.git
        path: ~/gitbase/example/beam
    ignore_brew: []                  # names the reconciliation never touches
    ignore_uv_tools: []
    ignore_npm: []
```

The host whose hostname matches is the **source**; every other host is a
**mirror**. Without `source_host` the doctor shows no mirror rows.

- **Source**: `sccs doctor update` rewrites the Brewfile (`brew bundle dump`)
  and `~/.config/sccs/inventory.yaml`; both travel through the `homebrew_bundle`
  and `sccs_inventory` categories. `doctor check` reports `STALE` when the files
  no longer match the live state. The source is never modified from the
  inventory.
- **Mirror**: `doctor check` reports missing, extra and wrong-version per area
  (`mirror: brew`, `mirror: uv`, `mirror: npm`, `mirror: repo <name>`,
  `mirror: fisher`). Missing is red and exit 1; extras are yellow and not a
  failure. `doctor install` installs what is missing (`brew bundle install`,
  `uv tool install name==version`, `npm install -g name@version`, `git clone`,
  `git pull --ff-only`, `fisher update`); uv and npm are pinned to the source's
  version, Homebrew has no versions. A checkout with local changes is reported
  and never touched. A mirror never writes the inventory.
- **Removal**: only `sccs doctor optimize --strict`, one action per extra,
  each confirmed on its own. `npm`, `corepack` and `sccs` are never removed;
  `cleanup: false` switches removals off entirely.
````

- [ ] **Step 3: `docs/usage/categories.md`**

Add to both tables (DE after `starship_config`, EN likewise):

```markdown
| `homebrew_bundle` | `~/.config/homebrew/Brewfile` | macOS | Homebrew-Bundle, Wahrheit für den Spiegel-Abgleich |
| `sccs_inventory` | `~/.config/sccs/inventory.yaml` | alle | Software-Inventar der Quelle (uv-Tools, npm-Globals), schreibt nur `doctor update` |
```

```markdown
| `homebrew_bundle` | `~/.config/homebrew/Brewfile` | macOS | Homebrew bundle, truth for the mirror area |
| `sccs_inventory` | `~/.config/sccs/inventory.yaml` | all | Source software inventory (uv tools, npm globals), written only by `doctor update` |
```

- [ ] **Step 4: `docs/usage/cli-reference.md` and `usage/AGENT.md`**

In the doctor block of `cli-reference.md` add:

```
sccs doctor check                # … zeigt auf einem Spiegel `mirror: …`-Zeilen (v2.68.0)
sccs doctor update               # auf der Quelle: Brewfile + inventory.yaml neu schreiben
sccs doctor optimize --strict    # auf einem Spiegel: Überzähliges einzeln zur Bestätigung
```

In `usage/AGENT.md`: bump the version line to 2.68.0 and add one guardrail bullet: "`sccs doctor` mirror area: the host named by `doctor.mirror.source_host` is never modified; removals only under `optimize --strict`, one confirm each."

- [ ] **Step 5: `RELEASE_NOTES.md`**

Prepend:

```markdown
## Version 2.68.0 (DD.MM.YYYY)

### Added (mirror parity — a second Mac identical to the live workstation)

- **`doctor.mirror`** — `source_host` names the live workstation; every other host is a mirror. `sccs doctor check` gains a `mirror:` block for Homebrew, uv tools, npm globals, own git checkouts and Fisher plugins; `install` adds what is missing; `optimize --strict` offers one confirm-gated removal per extra.
- **Two files carry the truth**: the Brewfile (category `homebrew_bundle`, now a bundled default on macOS) and `~/.config/sccs/inventory.yaml` (new category `sccs_inventory`). On the source, `doctor update` rewrites both; `doctor check` says `STALE` when they no longer match the live state — the missing piece behind a Brewfile that had drifted for weeks.
- **Two rules, pinned by tests**: the source is never modified from the inventory, and a mirror never writes the inventory. Removals exist only under `optimize --strict` with `cleanup: true`; `npm`, `corepack` and `sccs` are never removed; Homebrew extras are computed against `brew leaves`, so a dependency is never offered for removal; a checkout with local changes is reported and never touched.
- uv and npm are pinned to the source's version; Homebrew cannot pin, so parity there means the same packages, each current.
```

Use today's date from the environment for `DD.MM.YYYY`.

- [ ] **Step 6: `CLAUDE.md`, `.project-tips`, skill file, version, lock**

- `CLAUDE.md`: `**Version**: 2.68.0` and a new first bullet:

```markdown
- **Mirror parity** (v2.68.0): `sccs/doctor/mirror.py` reconciles a second Mac against the live workstation. Roles come from `doctor.mirror.source_host` matched against the normalised hostname. **Two rules are pinned by tests**: the source never receives install/remove actions, and a mirror never writes `inventory.yaml` — only `mirror_update_actions` on the source captures, via one `python_callable` action. Removals live only in `build_optimize_plan(strict=True)` and only with `cleanup: true`; each is its own `DoctorAction` with `auto_confirm=False`, never `brew bundle cleanup`. Homebrew *missing* is checked against the full installed list, Homebrew *extra* against `brew leaves` — a dependency is never offered for removal. Extras are yellow, never a problem; missing/wrong version on a mirror is red and exit 1; a stale source is yellow. Every name goes through `_validate_safe_name` and every version through `_VERSION_PATTERN` before it becomes argv.
```

- `.project-tips`: `# sccs v2.68.0 …`
- `~/.claude/skills/sccs/SKILL.md`: `**Version**: 2.68.0` and one paragraph `**Spiegel-Abgleich (v2.68.0)**: …` summarising the CLAUDE.md bullet in German.
- `pyproject.toml`: `version = "2.68.0"`; `sccs/__init__.py`: both `2.68.0` lines.
- Run `uv lock` and confirm `grep -A1 '^name = "sccs"' uv.lock` shows `2.68.0`.

- [ ] **Step 7: Quality gate and commit**

Run: `ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q`
Expected: clean, all tests pass.

```bash
git add -A docs/usage RELEASE_NOTES.md CLAUDE.md .project-tips usage/AGENT.md pyproject.toml sccs/__init__.py uv.lock
git commit -m "[CHG] release 2.68.0 — mirror parity docs, release notes, version

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

The skill file lives outside the repo (`~/.claude/skills/sccs/SKILL.md`) and reaches the sync repo through `sccs sync`; it is not part of this commit.

---

### Task 12: Real-host verification (not automated; the operator runs it)

No code. After Task 11 is merged and 2.68.0 is installed on both Macs:

1. On the live Mac: set `doctor.mirror.source_host` to its hostname in `~/.config/sccs/config.yaml`, add the Beam repo, run `sccs doctor check` → expect `mirror: role STALE` (Brewfile drifted). Run `sccs doctor update` → expect the capture action, then `doctor check` → `source · inventory current`. `sccs sync` and commit/push the sync repo (Brewfile, inventory.yaml, config.yaml).
2. On the second Mac: `sccs sync --pull`, then `sccs doctor check` → expect red rows for missing brew packages, uv tools, the Beam checkout, and Fisher drift. `sccs doctor install` → confirm each. `exec fish`, then `z` and `ze` must exist. `sccs doctor check` again → all `OK` except yellow extras. `sccs doctor optimize --strict` → confirm each removal. Final `sccs doctor check` → exit 0, no yellow.
3. Record anything that only the real host showed in `RELEASE_NOTES.md` under 2.68.0 (that is how every previous area's "found against a real install" notes came to be).

---

## Self-review

**Spec coverage.** Roles (Task 1), files and inventory (Tasks 3, 10), capture on the source (Task 8 `mirror_update_actions`, staleness in Task 7), reconciliation table (Tasks 4–6 detect, Task 8 acts), the six "rules the table does not show" (leaves-vs-full-list in Task 4, `modified` never touched in Tasks 6/8, hard-excluded names in Tasks 3/8, `cleanup: false` in Task 8, version pinning in Task 8, Homebrew no-version in docs), safety (validators in Task 1, `_safe` + `_VERSION_PATTERN` in Task 8, runner in Task 2, `auto_confirm` split in Task 8), reporting (Task 9 table, Task 10 JSON), code layout (as planned, one module), tests (policy tests in Task 8 `TestMirrorActions`, detectors against fake output in Tasks 2–6, validators in Task 1, dependency-never-extra in Task 4), prerequisite 2.67.2 (already shipped). Gap closed during review: the spec's `sccs_inventory` category assumed a bundled `homebrew_bundle` that did not exist — Task 10 adds both.

**Placeholders.** None; every step has code or exact text. Two deliberate "read the real signature first" notes (Tasks 8 and 9, `NodeStatus`/`ClaudeCliStatus`) point at `tests/test_doctor.py::_make_status_set`.

**Type consistency.** `MirrorReport` fields used in Tasks 8–10 match Task 7; `PackageAreaStatus(area, state, missing, extra, version_differs)` used identically in Tasks 5, 7, 8, 9; `RepoStatus.path` property used by Task 8 and 9; wrapper names in Task 2 match every `monkeypatch.setattr("sccs.doctor.mirror.<name>", …)` in later tasks (they are imported into `mirror.py`'s namespace, which is why the patches target `sccs.doctor.mirror`, not `sccs.doctor.runner`).
