# Deployment Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship named, scenario-scoped bundles (`sccs deploy export odoo-server`) for foreign hosts, plus a receipt-backed removal path (`sccs deploy revoke`) that takes our knowledge back off the machine and proves it.

**Architecture:** A deployment profile is a named selection over the *existing* export path. `sccs/deploy/` resolves a profile to `ExportSelection` objects and hands them to the existing `Exporter`; `deploy install` goes through the existing `Importer` and then writes a receipt. There is no second copy path. Removal reads only the receipt, so it works on a host with no SCCS config at all.

**Tech Stack:** Python 3.10+, Pydantic v2, Click, Rich, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-deployment-profiles-design.md`

## Global Constraints

- **Python 3.10+** (`requires-python = ">=3.10"`, ruff `target-version = "py310"`, mypy `python_version = "3.10"`). Every module starts with `from __future__ import annotations`; use `X | None`, never `Optional[X]`.
- **No second export/import path.** All file movement goes through `sccs.transfer.exporter.Exporter` and `sccs.transfer.importer.Importer`. A task that copies files itself is wrong.
- **`--json` goes through `sccs.output.json_emit.emit_json`** (which uses `click.echo`), never the Rich `Console` — the console forces ANSI.
- **Tests are platform-independent.** CI runs on Linux. Never assume macOS paths; drive `HOME` with `monkeypatch.setenv("HOME", str(tmp_path))` plus `monkeypatch.setattr(Path, "home", lambda: tmp_path)`.
- **CLI `--json` assertions must prove the output is ANSI-free.** CI colours output (`FORCE_COLOR`), a local pipe does not. The established pattern is the local helper `_parse_clean(output)` in `tests/test_cli_json.py:19-24` — it asserts no `\x1b` is present, asserts exactly one non-empty line, and returns the parsed object. **Copy that helper into `tests/test_deploy_cli.py`** and use it instead of `json.loads(result.output.strip())` everywhere in Task 8. It is not in `conftest.py`; do not import it across test modules.
- **Blocked categories** are exactly `claude_memories`, `claude_plans`, `claude_todos`. The validator raises; it never silently filters.
- **Commit prefixes:** `[ADD]` new features, `[CHG]` modifications, `[FIX]` bug fixes.
- **Quality gate before every commit:** `ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q`.
- **Version bump to 2.65.0 followed by `uv lock` happens in Task 9, once.** Do not bump in intermediate tasks.

---

### Task 1: Profile schema, defaults, and config wiring

**Files:**
- Create: `sccs/deploy/__init__.py`
- Create: `sccs/deploy/schema.py`
- Create: `sccs/deploy/defaults.py`
- Modify: `sccs/config/schema.py` (add `deployment_profiles` field to `SccsConfig`, near the existing `profiles` field around line 354)
- Test: `tests/test_deploy_schema.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `BLOCKED_CATEGORIES: frozenset[str]`
  - `class DeploymentProfileError(Exception)`
  - `class DeploymentProfile(BaseModel)` with fields `description: str`, `target_platform: str`, `extends: str | None`, `include: dict[str, list[str]]`, `retain: list[str]`
  - `def resolve_deployment_profiles(user: dict[str, DeploymentProfile] | None) -> dict[str, DeploymentProfile]` — bundled defaults merged with user entries, then `extends` flattened
  - `DEFAULT_DEPLOYMENT_PROFILES: dict[str, DeploymentProfile]` with keys `odoo-server`, `odoo-dev-full`, `fastreport`, `shell-only`
  - `SccsConfig.deployment_profiles: dict[str, DeploymentProfile]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_schema.py`:

```python
"""Deployment profile schema: validation, blocked categories, extends."""

from __future__ import annotations

import pytest

from sccs.deploy.defaults import DEFAULT_DEPLOYMENT_PROFILES
from sccs.deploy.schema import (
    BLOCKED_CATEGORIES,
    DeploymentProfile,
    DeploymentProfileError,
    resolve_deployment_profiles,
)


def test_blocked_category_raises():
    """A profile naming a blocked category is refused, not filtered."""
    with pytest.raises(ValueError, match="claude_memories"):
        DeploymentProfile(
            description="bad",
            target_platform="linux",
            include={"claude_memories": ["*"]},
        )


def test_all_blocked_categories_are_refused():
    for blocked in BLOCKED_CATEGORIES:
        with pytest.raises(ValueError, match=blocked):
            DeploymentProfile(include={blocked: ["*"]})


def test_retain_must_name_an_included_category():
    """Retaining a category that is not shipped is a typo, not a no-op."""
    with pytest.raises(ValueError, match="fish_config"):
        DeploymentProfile(
            include={"claude_skills": ["odoo-common"]},
            retain=["fish_config"],
        )


def test_unknown_target_platform_raises():
    with pytest.raises(ValueError, match="target_platform"):
        DeploymentProfile(target_platform="solaris", include={"claude_skills": ["*"]})


def test_extends_merges_include_and_retain():
    profiles = {
        "base": DeploymentProfile(
            description="base",
            target_platform="linux",
            include={"claude_skills": ["odoo-common"], "fish_config": ["*"]},
            retain=["fish_config"],
        ),
        "child": DeploymentProfile(
            description="child",
            extends="base",
            include={"claude_skills": ["odoo-chat"], "claude_agents": ["odoo-developer"]},
        ),
    }
    resolved = resolve_deployment_profiles(profiles)
    child = resolved["child"]
    assert sorted(child.include["claude_skills"]) == ["odoo-chat", "odoo-common"]
    assert child.include["fish_config"] == ["*"]
    assert child.include["claude_agents"] == ["odoo-developer"]
    assert child.retain == ["fish_config"]
    assert child.description == "child"
    assert child.extends is None


def test_extends_cycle_raises():
    profiles = {
        "a": DeploymentProfile(extends="b", include={"claude_skills": ["x"]}),
        "b": DeploymentProfile(extends="a", include={"claude_skills": ["y"]}),
    }
    with pytest.raises(DeploymentProfileError, match="cycle"):
        resolve_deployment_profiles(profiles)


def test_extends_unknown_parent_raises():
    profiles = {"a": DeploymentProfile(extends="nope", include={"claude_skills": ["x"]})}
    with pytest.raises(DeploymentProfileError, match="nope"):
        resolve_deployment_profiles(profiles)


def test_user_entry_replaces_bundled_profile_of_same_name():
    override = DeploymentProfile(
        description="mine",
        target_platform="linux",
        include={"claude_skills": ["odoo-common"]},
    )
    resolved = resolve_deployment_profiles({"odoo-server": override})
    assert resolved["odoo-server"].description == "mine"
    assert resolved["odoo-server"].include["claude_skills"] == ["odoo-common"]
    assert "fastreport" in resolved


def test_bundled_profiles_are_valid_and_complete():
    resolved = resolve_deployment_profiles(None)
    assert set(resolved) == {"odoo-server", "odoo-dev-full", "fastreport", "shell-only"}
    for name, profile in resolved.items():
        assert profile.description, f"{name} has no description"
        assert profile.include, f"{name} ships nothing"
        for category in profile.include:
            assert category not in BLOCKED_CATEGORIES


def test_shell_only_retains_everything_it_ships():
    shell_only = DEFAULT_DEPLOYMENT_PROFILES["shell-only"]
    assert set(shell_only.retain) == set(shell_only.include)
    assert "claude_skills" not in shell_only.include


def test_odoo_server_excludes_remote_support():
    """remote-support targets hosts Claude cannot reach; on the customer
    server Claude is on the machine and its triggers would misfire."""
    skills = DEFAULT_DEPLOYMENT_PROFILES["odoo-server"].include["claude_skills"]
    assert "remote-support" not in skills


def test_config_accepts_deployment_profiles():
    from sccs.config.schema import SccsConfig

    config = SccsConfig.model_validate(
        {
            "repository": {"path": "~/gitbase/sccs-sync"},
            "sync_categories": {},
            "deployment_profiles": {
                "custom": {
                    "description": "custom",
                    "target_platform": "linux",
                    "include": {"claude_skills": ["odoo-common"]},
                }
            },
        }
    )
    assert config.deployment_profiles["custom"].target_platform == "linux"


def test_config_without_deployment_profiles_defaults_to_empty():
    from sccs.config.schema import SccsConfig

    config = SccsConfig.model_validate(
        {"repository": {"path": "~/gitbase/sccs-sync"}, "sync_categories": {}}
    )
    assert config.deployment_profiles == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deploy_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.deploy'`

- [ ] **Step 3: Create the package and the schema**

Create `sccs/deploy/__init__.py`:

```python
# SCCS Deployment Profiles — scenario-scoped bundles for foreign hosts
#
# `sccs export` offers the whole synchronised inventory. On a customer
# server we want a named, reproducible slice of it — and a way to take it
# back off the machine afterwards.
#
# Design rules:
#   1. NO SECOND COPY PATH. A profile resolves to ExportSelection objects
#      and is handed to sccs.transfer.exporter.Exporter; installation goes
#      through sccs.transfer.importer.Importer.
#   2. The bundle is SELF-DESCRIBING. The customer host has no config.yaml
#      of ours, so the manifest carries the removal policy.
#   3. "written by us" and "was already here" are different facts. Only
#      the first justifies a deletion (see receipt.py:ReceiptEntry).
#   4. Project memory of other engagements (claude_memories, claude_plans,
#      claude_todos) may never enter a bundle — the validator raises.

from __future__ import annotations
```

Create `sccs/deploy/schema.py`:

```python
# Deployment profile model, validation and `extends` flattening.

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

# Categories that hold project memory from other engagements. A typo must
# not carry one customer's context onto another customer's server, so this
# raises rather than filtering silently.
BLOCKED_CATEGORIES: frozenset[str] = frozenset(
    {"claude_memories", "claude_plans", "claude_todos"}
)

VALID_PLATFORMS: frozenset[str] = frozenset({"linux", "macos", "windows"})


class DeploymentProfileError(Exception):
    """Raised when a set of deployment profiles cannot be resolved."""


class DeploymentProfile(BaseModel):
    """A named, scenario-scoped selection over the sync categories."""

    description: str = Field(default="", description="Shown by `sccs deploy list`.")
    target_platform: str = Field(
        default="linux",
        description=(
            "Platform the bundle is built FOR. Categories and items are "
            "filtered against this, not against the exporting machine."
        ),
    )
    extends: str | None = Field(
        default=None,
        description="Name of a profile whose include map and retain list are merged in.",
    )
    include: dict[str, list[str]] = Field(
        default_factory=dict,
        description="category name -> fnmatch globs matched against item names.",
    )
    retain: list[str] = Field(
        default_factory=list,
        description=(
            "Categories installed but NOT removed by `sccs deploy revoke`. "
            "Belongs to the scenario, not to the category: the same fish "
            "config is payload on our second machine and a parting gift on "
            "a customer host."
        ),
    )

    @model_validator(mode="after")
    def _validate(self) -> DeploymentProfile:
        for category in self.include:
            if category in BLOCKED_CATEGORIES:
                raise ValueError(
                    f"Category '{category}' may never be part of a deployment "
                    f"profile — it holds project memory from other engagements"
                )
        if self.target_platform not in VALID_PLATFORMS:
            raise ValueError(
                f"target_platform '{self.target_platform}' is not one of "
                f"{sorted(VALID_PLATFORMS)}"
            )
        # `retain` is checked against the *own* include map only. A child
        # profile may retain a category it inherits, so this validator runs
        # again after flattening in resolve_deployment_profiles().
        if self.extends is None:
            for category in self.retain:
                if category not in self.include:
                    raise ValueError(
                        f"retain names '{category}', which the profile does not "
                        f"install — retaining an absent category is a typo"
                    )
        return self


def _flatten(
    name: str,
    profiles: dict[str, DeploymentProfile],
    seen: tuple[str, ...] = (),
) -> DeploymentProfile:
    """Resolve one profile's `extends` chain into a standalone profile."""
    if name in seen:
        chain = " -> ".join([*seen, name])
        raise DeploymentProfileError(f"Deployment profile cycle: {chain}")

    profile = profiles.get(name)
    if profile is None:
        raise DeploymentProfileError(f"Unknown deployment profile: {name}")

    if profile.extends is None:
        return profile

    parent = _flatten(profile.extends, profiles, (*seen, name))

    merged_include: dict[str, list[str]] = {k: list(v) for k, v in parent.include.items()}
    for category, globs in profile.include.items():
        existing = merged_include.setdefault(category, [])
        for glob in globs:
            if glob not in existing:
                existing.append(glob)

    merged_retain = list(parent.retain)
    for category in profile.retain:
        if category not in merged_retain:
            merged_retain.append(category)

    return DeploymentProfile(
        description=profile.description or parent.description,
        target_platform=profile.target_platform,
        extends=None,
        include=merged_include,
        retain=merged_retain,
    )


def resolve_deployment_profiles(
    user: dict[str, DeploymentProfile] | None,
) -> dict[str, DeploymentProfile]:
    """Merge user profiles over the bundled defaults and flatten `extends`.

    A user entry fully REPLACES the bundled profile of the same name, so a
    profile can be re-scoped without patching the package — same semantics
    as `sccs.doctor.profiles.resolve_profiles`.

    Raises:
        DeploymentProfileError: on an unknown parent or an `extends` cycle.
    """
    from sccs.deploy.defaults import DEFAULT_DEPLOYMENT_PROFILES

    merged: dict[str, DeploymentProfile] = dict(DEFAULT_DEPLOYMENT_PROFILES)
    if user:
        merged.update(user)

    flattened = {name: _flatten(name, merged) for name in merged}

    for name, profile in flattened.items():
        for category in profile.retain:
            if category not in profile.include:
                raise DeploymentProfileError(
                    f"Profile '{name}' retains '{category}' but does not install it"
                )
    return flattened
```

- [ ] **Step 4: Write the bundled defaults**

Create `sccs/deploy/defaults.py`:

```python
# The four bundled deployment profiles.
#
# Skill names are verified against ~/.claude/skills as of 01.09.2026. A
# profile naming a skill that no longer exists is caught by
# `sccs deploy show`, which reports it rather than shipping a gap.

from __future__ import annotations

from sccs.deploy.schema import DeploymentProfile

# Framework files every knowledge-bearing profile carries. Without
# CLAUDE.md/RULES.md the agent on the customer host does not behave like
# ours (fish syntax, delete protection, commit prefixes). They are never
# under `retain` — SOUL.md is our working method.
_FRAMEWORK = ["CLAUDE.md", "SOUL.md", "PRINCIPLES.md", "RULES.md"]

_SHELL = {
    "fish_config": ["*"],
    "fish_functions": ["*"],
    "starship_config": ["*"],
}
_SHELL_RETAIN = ["fish_config", "fish_functions", "starship_config"]

DEFAULT_DEPLOYMENT_PROFILES: dict[str, DeploymentProfile] = {
    "odoo-server": DeploymentProfile(
        description="Odoo work on a customer server",
        target_platform="linux",
        include={
            "claude_skills": [
                "odoo-common",
                "odoo16",
                "odoo17",
                "odoo18",
                "odoo19",
                "odoo-shell",
                "odoo-dev",
                "odoorpc-toolbox",
                "odoo-module-migrator",
                "odoo-merge-to",
                "myodoo-docker",
                "docker-expert",
                "nginx-set-conf",
                "uv-python-tools",
                "sharp-edges",
                "verification-loop",
                "session-hygiene",
            ],
            "claude_commands": ["s.md", "docs.md", "finalize.md", "tips.md"],
            "claude_agents": ["odoo-developer.md", "python-toolsmith.md"],
            "claude_framework": _FRAMEWORK,
            **_SHELL,
        },
        retain=list(_SHELL_RETAIN),
    ),
    "odoo-dev-full": DeploymentProfile(
        description="Full Odoo development incl. documentation and publication",
        target_platform="linux",
        extends="odoo-server",
        include={
            "claude_skills": [
                "odoo-module-docs",
                "odoo-funktionsumfang",
                "odoo-funktionsumfang-merge",
                "eq-helper-docs",
                "odoo-appstore-listing",
                "odoo-module2website",
                "odoo-website-design",
                "odoo-website-themes",
                "odoo-docs-sync",
                "odoo-agent-doc-coverage",
                "odoo-ai-addon",
                "odoo-chat",
                "eq-chatbot-core",
                "ownerp-demodata",
                "odoo-differ",
                "odoo-migration-estimator",
                "clean-room",
                "changelog-automation",
                "project-docs",
                "create-test-plan",
                "tdd-workflow",
                "glab",
                "gitlab-workflow",
            ],
            "claude_commands": ["afterwork.md", "check-skills.md", "project-audit.md"],
        },
    ),
    "fastreport": DeploymentProfile(
        description="FastReport work on a customer server",
        target_platform="linux",
        include={
            "claude_skills": [
                "fr-reports",
                "fr-mapper",
                "fr-odoo",
                "fr-api",
                "fr-designer",
                "odoo-common",
                "uv-python-tools",
            ],
            "claude_commands": ["s.md", "docs.md", "finalize.md"],
            "claude_agents": ["fastreport-integrator.md", "odoo-developer.md"],
            "claude_framework": _FRAMEWORK,
            **_SHELL,
        },
        retain=list(_SHELL_RETAIN),
    ),
    "shell-only": DeploymentProfile(
        description="Environment only — no knowledge, nothing to revoke",
        target_platform="linux",
        include={
            **_SHELL,
            "git_config": ["*"],
            "project_templates": ["*"],
        },
        retain=[*_SHELL_RETAIN, "git_config", "project_templates"],
    ),
}
```

- [ ] **Step 5: Wire the field into SccsConfig**

In `sccs/config/schema.py`, add the import near the existing `from sccs.doctor.profiles import ProfileSpec` (line 11):

```python
from sccs.deploy.schema import DeploymentProfile
```

Add the field directly after the existing `profiles` field (around line 361):

```python
    # Deployment profiles are fully optional: legacy config.yaml files
    # without a `deployment_profiles:` key get the bundled defaults from
    # sccs/deploy/defaults.py. An entry here fully replaces the bundled
    # profile of the same name.
    deployment_profiles: dict[str, DeploymentProfile] = Field(
        default_factory=dict,
        description=(
            "Named, scenario-scoped bundles that `sccs deploy export` builds "
            "for foreign hosts. Merged over the bundled defaults in "
            "sccs/deploy/defaults.py:DEFAULT_DEPLOYMENT_PROFILES."
        ),
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_deploy_schema.py -q`
Expected: PASS (13 tests)

If `test_config_accepts_deployment_profiles` fails with a circular import, move the `DeploymentProfile` import in `sccs/config/schema.py` into a `TYPE_CHECKING` block and quote the annotation — `sccs/deploy/schema.py` must not import from `sccs.config`.

- [ ] **Step 7: Quality gate and commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
git add sccs/deploy/ sccs/config/schema.py tests/test_deploy_schema.py
git commit -m "[ADD] deploy: deployment profile schema, defaults and config field"
```

---

### Task 2: Profile resolution — selections, target platform, dependency check

**Files:**
- Create: `sccs/deploy/resolve.py`
- Modify: `sccs/utils/platform.py:42-55` (`is_platform_match` gains an optional reference platform)
- Modify: `sccs/transfer/exporter.py:53-113` (`Exporter` gains `target_platform`)
- Test: `tests/test_deploy_resolve.py`

**Interfaces:**
- Consumes: `DeploymentProfile`, `resolve_deployment_profiles` (Task 1).
- Produces:
  - `def is_platform_match(platforms: list[str] | None, *, platform: str | None = None) -> bool`
  - `Exporter(config, *, include_managed: bool = False, target_platform: str | None = None)`
  - `@dataclass class ResolvedProfile` with `name: str`, `profile: DeploymentProfile`, `selections: list[ExportSelection]`, `missing_deps: list[tuple[str, str]]`, `missing_items: list[tuple[str, str]]`
  - `def resolve_profile(config: SccsConfig, name: str, profiles: dict[str, DeploymentProfile], *, target_platform: str | None = None) -> ResolvedProfile`
  - `def read_skill_dependencies(skills_dir: Path, names: list[str]) -> dict[str, list[str]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_resolve.py`:

```python
"""Profile resolution: selection building, target platform, dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.config.schema import ItemType, SccsConfig, SyncCategory
from sccs.deploy.resolve import (
    ResolvedProfile,
    read_skill_dependencies,
    resolve_profile,
)
from sccs.deploy.schema import DeploymentProfile
from sccs.utils.platform import is_platform_match


def test_is_platform_match_honours_explicit_platform():
    assert is_platform_match(["linux"], platform="linux")
    assert not is_platform_match(["macos"], platform="linux")
    assert is_platform_match(None, platform="linux")
    assert is_platform_match([], platform="linux")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated HOME with a small skills/commands tree."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    skills = tmp_path / ".claude" / "skills"
    for name in ("odoo-common", "odoo-merge-to", "fr-reports"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\n---\n\nBody.\n", encoding="utf-8"
        )
    (skills / "odoo-merge-to" / "SKILL.md").write_text(
        "---\nname: odoo-merge-to\ndescription: test\n---\n\n"
        "**INHERITS FROM:** odoo-common (UV package manager, commit prefixes)\n",
        encoding="utf-8",
    )

    macos_fish = tmp_path / ".config" / "fish" / "conf.d"
    macos_fish.mkdir(parents=True)
    (macos_fish / "brew.macos.fish").write_text("# mac only\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(home):
    return SccsConfig.model_validate(
        {
            "repository": {"path": str(home / "repo")},
            "sync_categories": {
                "claude_skills": {
                    "enabled": True,
                    "local_path": "~/.claude/skills",
                    "repo_path": ".claude/skills",
                    "item_type": "directory",
                    "item_marker": "SKILL.md",
                    "include": ["*"],
                },
                "fish_config_macos": {
                    "enabled": True,
                    "local_path": "~/.config/fish/conf.d",
                    "repo_path": ".config/fish/conf.d",
                    "item_type": "file",
                    "item_pattern": "*.macos.fish",
                    "include": ["*.macos.fish"],
                    "platforms": ["macos"],
                },
            },
        }
    )


def test_resolve_selects_only_named_items(config):
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"claude_skills": ["odoo-common", "fr-reports"]},
    )
    resolved = resolve_profile(config, "t", {"t": profile})
    assert isinstance(resolved, ResolvedProfile)
    names = {i.name for s in resolved.selections for i in s.items}
    assert names == {"odoo-common", "fr-reports"}


def test_linux_target_drops_macos_category(config):
    """Filtering runs against target_platform, not the running machine."""
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"claude_skills": ["odoo-common"], "fish_config_macos": ["*"]},
    )
    resolved = resolve_profile(config, "t", {"t": profile})
    assert {s.category_name for s in resolved.selections} == {"claude_skills"}


def test_macos_target_keeps_macos_category(config):
    profile = DeploymentProfile(
        description="t",
        target_platform="macos",
        include={"fish_config_macos": ["*"]},
    )
    resolved = resolve_profile(config, "t", {"t": profile})
    assert {s.category_name for s in resolved.selections} == {"fish_config_macos"}


def test_missing_dependency_is_reported(config):
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"claude_skills": ["odoo-merge-to"]},
    )
    resolved = resolve_profile(config, "t", {"t": profile})
    assert resolved.missing_deps == [("odoo-merge-to", "odoo-common")]


def test_satisfied_dependency_is_not_reported(config):
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"claude_skills": ["odoo-merge-to", "odoo-common"]},
    )
    resolved = resolve_profile(config, "t", {"t": profile})
    assert resolved.missing_deps == []


def test_named_item_that_does_not_exist_is_reported(config):
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"claude_skills": ["odoo-common", "ghost-skill"]},
    )
    resolved = resolve_profile(config, "t", {"t": profile})
    assert resolved.missing_items == [("claude_skills", "ghost-skill")]


def test_read_skill_dependencies_parses_inherits_from(home):
    deps = read_skill_dependencies(
        home / ".claude" / "skills", ["odoo-merge-to", "odoo-common"]
    )
    assert deps["odoo-merge-to"] == ["odoo-common"]
    assert deps["odoo-common"] == []


def test_read_skill_dependencies_ignores_missing_skill(home):
    deps = read_skill_dependencies(home / ".claude" / "skills", ["ghost"])
    assert deps == {"ghost": []}


def test_read_skill_dependencies_handles_both_corpus_shapes(tmp_path):
    """Both real shapes in ~/.claude/skills must parse."""
    skills = tmp_path / "skills"
    (skills / "a").mkdir(parents=True)
    (skills / "a" / "SKILL.md").write_text(
        "**INHERITS FROM:** odoo-common (UV package manager, commit prefixes), "
        "uv-python-tools (UV installation, README templates)\n",
        encoding="utf-8",
    )
    (skills / "b").mkdir(parents=True)
    (skills / "b" / "SKILL.md").write_text(
        'Versionen anwenden". INHERITS FROM: odoo-common. NOT for: full module '
        "migration of an entire module between versions\n",
        encoding="utf-8",
    )
    deps = read_skill_dependencies(skills, ["a", "b"])
    assert deps["a"] == ["odoo-common", "uv-python-tools"]
    assert deps["b"] == ["odoo-common"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deploy_resolve.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.deploy.resolve'`

- [ ] **Step 3: Widen `is_platform_match`**

Replace `sccs/utils/platform.py:42-55` with:

```python
def is_platform_match(platforms: list[str] | None, *, platform: str | None = None) -> bool:
    """
    Check if a platform filter matches.

    Args:
        platforms: List of platform names to match against.
                   None or empty list means all platforms match.
        platform: Reference platform. Defaults to the running machine.
                  `sccs deploy export` passes the profile's target platform
                  here — otherwise a Mac would pack `fish_config_macos`
                  into a Linux bundle.

    Returns:
        True if the reference platform is in the list, or if list is
        None/empty.
    """
    if not platforms:
        return True
    return (platform or get_current_platform()) in platforms
```

- [ ] **Step 4: Give the Exporter a target platform**

In `sccs/transfer/exporter.py`, change `__init__` (line 53) to:

```python
    def __init__(
        self,
        config: SccsConfig,
        *,
        include_managed: bool = False,
        target_platform: str | None = None,
    ) -> None:
```

Add to the docstring's Args block:

```
            target_platform: Platform the export is built FOR ("linux",
                "macos", "windows"). Defaults to the running machine.
```

Add to the body, after the existing attribute assignments:

```python
        self._target_platform = target_platform
```

In `scan_available_items` change the filter line to:

```python
            if not is_platform_match(category.platforms, platform=self._target_platform):
                continue
```

- [ ] **Step 5: Write the resolver**

Create `sccs/deploy/resolve.py`:

```python
# Resolve a deployment profile into ExportSelection objects.
#
# The profile names items; the existing Exporter scan says which of them
# actually exist locally. Anything named but absent is reported rather than
# silently dropped — a bundle with a hole in it is discovered on a machine
# we will not be sitting at.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sccs.config.schema import SccsConfig
from sccs.deploy.schema import DeploymentProfile, DeploymentProfileError
from sccs.transfer.exporter import ExportSelection, Exporter
from sccs.utils.logging import get_logger
from sccs.utils.paths import matches_any_pattern

logger = get_logger("sccs.deploy")

# Matches the documented convention in ~/.claude/skills/*/SKILL.md, e.g.
#   **INHERITS FROM:** odoo-common (UV package manager), uv-python-tools (...)
#   INHERITS FROM: odoo-common. NOT for: ...
_INHERITS_RE = re.compile(r"INHERITS FROM:?\**\s*(?P<rest>.+)", re.IGNORECASE)
_DEP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass
class ResolvedProfile:
    """A deployment profile resolved against the local artefact tree."""

    name: str
    profile: DeploymentProfile
    selections: list[ExportSelection] = field(default_factory=list)
    # (skill, required parent) pairs where the parent is not in the bundle.
    missing_deps: list[tuple[str, str]] = field(default_factory=list)
    # (category, item name) pairs named by the profile but absent locally.
    missing_items: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_items(self) -> int:
        return sum(len(s.items) for s in self.selections)

    @property
    def is_clean(self) -> bool:
        return not self.missing_deps and not self.missing_items


def read_skill_dependencies(skills_dir: Path, names: list[str]) -> dict[str, list[str]]:
    """Read the `INHERITS FROM` line of each named skill.

    Returns a mapping name -> list of required skill names. A skill without
    the line, or one that does not exist, maps to an empty list.
    """
    result: dict[str, list[str]] = {}
    for name in names:
        deps: list[str] = []
        skill_md = skills_dir / name / "SKILL.md"
        try:
            text = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            result[name] = deps
            continue

        for line in text.splitlines():
            match = _INHERITS_RE.search(line)
            if not match:
                continue
            # Two real shapes occur in the corpus, and both must parse:
            #   "**INHERITS FROM:** odoo-common (UV package manager), uv-python-tools (...)"
            #   "INHERITS FROM: odoo-common. NOT for: full module migration ..."
            # Drop parenthesised asides first, then split on comma, period and
            # semicolon. Anything with a space or colon left in it is prose,
            # not a skill name, and _DEP_NAME_RE rejects it.
            rest = re.sub(r"\([^)]*\)", " ", match.group("rest"))
            for chunk in re.split(r"[,.;]", rest):
                candidate = chunk.strip().strip("*_ ").lower()
                if _DEP_NAME_RE.match(candidate) and candidate not in deps:
                    deps.append(candidate)
            break
        result[name] = deps
    return result


def resolve_profile(
    config: SccsConfig,
    name: str,
    profiles: dict[str, DeploymentProfile],
    *,
    target_platform: str | None = None,
) -> ResolvedProfile:
    """Resolve a named profile against the local artefact tree.

    Args:
        config: Loaded SCCS configuration.
        name: Profile name.
        profiles: Flattened profile map from `resolve_deployment_profiles`.
        target_platform: Overrides the profile's own `target_platform`.

    Raises:
        DeploymentProfileError: If `name` is unknown.
    """
    profile = profiles.get(name)
    if profile is None:
        raise DeploymentProfileError(f"Unknown deployment profile: {name}")

    platform = target_platform or profile.target_platform
    exporter = Exporter(config, target_platform=platform)
    scanned = exporter.scan_available_items()

    resolved = ResolvedProfile(name=name, profile=profile)
    parsed: dict[str, list[str]] = {}

    for category, globs in profile.include.items():
        cat_config = config.sync_categories.get(category)
        if cat_config is None:
            resolved.missing_items.append((category, "<category not configured>"))
            continue
        available = scanned.get(category, [])
        matched = [item.name for item in available if matches_any_pattern(item.name, globs)]
        if matched:
            parsed[category] = matched

        # A literal glob (no wildcard characters) that matched nothing is a
        # named item that is gone. A wildcard matching nothing is not.
        for glob in globs:
            if any(ch in glob for ch in "*?["):
                continue
            if glob not in matched:
                resolved.missing_items.append((category, glob))

    resolved.selections = exporter.build_selections_from_parsed(parsed, scanned)

    skill_names = parsed.get("claude_skills", [])
    if skill_names:
        skills_cat = config.sync_categories.get("claude_skills")
        if skills_cat is not None:
            from sccs.utils.paths import expand_path

            deps = read_skill_dependencies(expand_path(skills_cat.local_path), skill_names)
            shipped = set(skill_names)
            for skill, required in deps.items():
                for parent in required:
                    if parent not in shipped:
                        resolved.missing_deps.append((skill, parent))

    logger.debug(
        "Resolved profile %s: %d items, %d missing deps, %d missing items",
        name,
        resolved.total_items,
        len(resolved.missing_deps),
        len(resolved.missing_items),
    )
    return resolved
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_deploy_resolve.py -q`
Expected: PASS (10 tests)

- [ ] **Step 7: Verify nothing regressed in the existing export path**

Run: `pytest tests/test_transfer.py tests/test_exporter_security.py -q`
Expected: PASS — `target_platform=None` keeps the previous behaviour exactly.

- [ ] **Step 8: Quality gate and commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
git add sccs/deploy/resolve.py sccs/utils/platform.py sccs/transfer/exporter.py tests/test_deploy_resolve.py
git commit -m "[ADD] deploy: profile resolution with target platform and dependency check"
```

---

### Task 3: Self-describing bundle — manifest section, cleanup command, builder

**Files:**
- Modify: `sccs/transfer/manifest.py` (add `DeploymentSection`, add `ExportManifest.deployment`)
- Modify: `sccs/transfer/exporter.py` (`export_to_zip` and `_build_manifest` accept a deployment section)
- Create: `sccs/deploy/bundle.py`
- Test: `tests/test_deploy_bundle.py`

**Interfaces:**
- Consumes: `ResolvedProfile` (Task 2), `Exporter` (Task 2).
- Produces:
  - `class DeploymentSection(BaseModel)` with `profile: str`, `target_platform: str`, `retain: list[str]`, `purge_traces: bool`, `sweep_globs: dict[str, list[str]]`
  - `ExportManifest.deployment: DeploymentSection | None`
  - `Exporter.export_to_zip(selections, output_path, raw_config, *, deployment: DeploymentSection | None = None)`
  - `CLEANUP_COMMAND_NAME: str` (`"sccs-cleanup.md"`)
  - `def build_cleanup_command(profile_name: str) -> str`
  - `def build_bundle(config: SccsConfig, resolved: ResolvedProfile, output_path: Path, raw_config: dict) -> ExportResult`

**Naming note:** the command file is `sccs-cleanup.md`, invoked as `/sccs-cleanup`. The spec called it `/aufräumen`; an ASCII filename avoids encoding surprises on a foreign filesystem and namespaces the command to the tool. The prompt text inside stays German.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_bundle.py`:

```python
"""Bundle building: manifest deployment section and cleanup command."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import yaml

from sccs.config.schema import SccsConfig
from sccs.deploy.bundle import CLEANUP_COMMAND_NAME, build_bundle, build_cleanup_command
from sccs.deploy.resolve import resolve_profile
from sccs.deploy.schema import DeploymentProfile
from sccs.transfer.manifest import MANIFEST_FILENAME, deserialize_manifest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    skills = tmp_path / ".claude" / "skills"
    (skills / "odoo-common").mkdir(parents=True)
    (skills / "odoo-common" / "SKILL.md").write_text(
        "---\nname: odoo-common\ndescription: t\n---\n\nBody.\n", encoding="utf-8"
    )
    commands = tmp_path / ".claude" / "commands"
    commands.mkdir(parents=True)
    (commands / "s.md").write_text("# s\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(home):
    return SccsConfig.model_validate(
        {
            "repository": {"path": str(home / "repo")},
            "sync_categories": {
                "claude_skills": {
                    "enabled": True,
                    "local_path": "~/.claude/skills",
                    "repo_path": ".claude/skills",
                    "item_type": "directory",
                    "item_marker": "SKILL.md",
                    "include": ["*"],
                },
                "claude_commands": {
                    "enabled": True,
                    "local_path": "~/.claude/commands",
                    "repo_path": ".claude/commands",
                    "item_type": "file",
                    "item_pattern": "*.md",
                    "include": ["*.md"],
                },
            },
        }
    )


@pytest.fixture
def profile():
    return DeploymentProfile(
        description="test profile",
        target_platform="linux",
        include={"claude_skills": ["odoo-common"], "claude_commands": ["s.md"]},
        retain=["claude_commands"],
    )


def test_bundle_carries_deployment_section(config, profile, tmp_path):
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    result = build_bundle(config, resolved, out, {})
    assert result.success

    with zipfile.ZipFile(out) as zf:
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))

    assert manifest.deployment is not None
    assert manifest.deployment.profile == "t"
    assert manifest.deployment.target_platform == "linux"
    assert manifest.deployment.retain == ["claude_commands"]
    assert manifest.deployment.sweep_globs["claude_skills"] == ["odoo-common"]


def test_bundle_contains_cleanup_command(config, profile, tmp_path):
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    build_bundle(config, resolved, out, {})

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert f"claude_commands/{CLEANUP_COMMAND_NAME}" in names


def test_cleanup_command_is_a_manifest_item(config, profile, tmp_path):
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    build_bundle(config, resolved, out, {})

    with zipfile.ZipFile(out) as zf:
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))
    item_names = {i.name for i in manifest.categories["claude_commands"].items}
    assert CLEANUP_COMMAND_NAME in item_names


def test_shell_only_bundle_has_no_cleanup_command(config, tmp_path):
    """A profile that ships no skills has nothing to clean up."""
    shell_only = DeploymentProfile(
        description="shell",
        target_platform="linux",
        include={"claude_commands": ["s.md"]},
        retain=["claude_commands"],
    )
    resolved = resolve_profile(config, "shell", {"shell": shell_only})
    out = tmp_path / "bundle.zip"
    build_bundle(config, resolved, out, {})

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert f"claude_commands/{CLEANUP_COMMAND_NAME}" not in names


def test_cleanup_command_names_the_profile_and_the_commands():
    text = build_cleanup_command("odoo-server")
    assert "odoo-server" in text
    assert "sccs deploy status" in text
    assert "sccs deploy revoke" in text
    assert "rm -rf" not in text


def test_manifest_without_deployment_section_still_parses():
    """Bundles from `sccs export` (v2.64.0 and older) stay readable."""
    legacy = yaml.dump(
        {
            "sccs_version": "2.64.0",
            "created_at": "2026-08-01T00:00:00+00:00",
            "created_on": "macos",
            "categories": {},
        }
    )
    manifest = deserialize_manifest(legacy)
    assert manifest.deployment is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deploy_bundle.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.deploy.bundle'`

- [ ] **Step 3: Extend the manifest**

In `sccs/transfer/manifest.py`, add after `ManifestCategory`:

```python
class DeploymentSection(BaseModel):
    """Removal policy carried by a `sccs deploy export` bundle.

    The customer host has no config.yaml of ours, so it must not depend on
    one to know what has to leave again.
    """

    profile: str
    target_platform: str
    retain: list[str] = []
    purge_traces: bool = True
    # category -> the globs the profile selected with. `deploy revoke` uses
    # these for its verification sweep, which must work without our config.
    sweep_globs: dict[str, list[str]] = {}
```

Add the optional field to `ExportManifest`:

```python
    # None for bundles produced by plain `sccs export` — that path stays
    # unchanged and its archives must keep importing.
    deployment: DeploymentSection | None = None
```

- [ ] **Step 4: Let the Exporter carry the section**

In `sccs/transfer/exporter.py`, add the import:

```python
from sccs.transfer.manifest import (
    MANIFEST_FILENAME,
    DeploymentSection,
    ExportManifest,
    ManifestCategory,
    ManifestItem,
    create_manifest,
    serialize_manifest,
)
```

Change `export_to_zip`'s signature and its manifest call:

```python
    def export_to_zip(
        self,
        selections: list[ExportSelection],
        output_path: Path,
        raw_config: dict,
        *,
        deployment: DeploymentSection | None = None,
    ) -> ExportResult:
```

```python
            manifest = self._build_manifest(selections, raw_config, deployment=deployment)
```

Change `_build_manifest`'s signature and its return:

```python
    def _build_manifest(
        self,
        selections: list[ExportSelection],
        raw_config: dict,
        *,
        deployment: DeploymentSection | None = None,
    ) -> ExportManifest:
```

```python
        manifest = create_manifest(categories)
        manifest.deployment = deployment
        return manifest
```

- [ ] **Step 5: Write the bundle builder**

Create `sccs/deploy/bundle.py`:

```python
# Build a deployment bundle: the profile's items plus a self-describing
# manifest and a generated cleanup command.

from __future__ import annotations

import tempfile
from pathlib import Path

from sccs.config.schema import ItemType, SccsConfig
from sccs.deploy.resolve import ResolvedProfile
from sccs.sync.item import SyncItem
from sccs.transfer.exporter import ExportResult, ExportSelection, Exporter
from sccs.transfer.manifest import DeploymentSection
from sccs.utils.logging import get_logger

logger = get_logger("sccs.deploy")

CLEANUP_COMMAND_NAME = "sccs-cleanup.md"
CLEANUP_CATEGORY = "claude_commands"

_CLEANUP_TEMPLATE = """---
description: Entfernt die von SCCS eingespielten Skills und Arbeitsspuren wieder
---

# Aufräumen

Auf diesem Host wurde das SCCS-Deployment-Profil `{profile}` eingespielt.

Gehe in genau dieser Reihenfolge vor:

1. Zeige `sccs deploy status`, damit sichtbar ist, was noch liegt.
2. Zeige `sccs deploy revoke --dry-run` und lege die Liste vor.
3. Frage nach ausdrücklicher Bestätigung.
4. Erst danach `sccs deploy revoke`.

Entferne niemals etwas von Hand. Wenn `sccs` fehlt oder der Rückbau
fehlschlägt, melde das und warte auf Anweisung — kein `rm`, kein `find -delete`.

Die Shell-Konfiguration bleibt absichtlich stehen; `revoke` weiß, was davon
betroffen ist.
"""


def build_cleanup_command(profile_name: str) -> str:
    """Render the cleanup slash command for a bundle.

    Generated rather than synced: a file in ~/.claude/commands would end up
    in every bundle and on our own machines.
    """
    return _CLEANUP_TEMPLATE.format(profile=profile_name)


def _deployment_section(resolved: ResolvedProfile) -> DeploymentSection:
    return DeploymentSection(
        profile=resolved.name,
        target_platform=resolved.profile.target_platform,
        retain=list(resolved.profile.retain),
        purge_traces=True,
        sweep_globs={
            selection.category_name: [item.name for item in selection.items]
            for selection in resolved.selections
        },
    )


def build_bundle(
    config: SccsConfig,
    resolved: ResolvedProfile,
    output_path: Path,
    raw_config: dict,
) -> ExportResult:
    """Create the deployment ZIP for a resolved profile.

    Adds a generated cleanup command when the profile ships skills — a
    profile that carries no knowledge has nothing to revoke.
    """
    if not resolved.selections:
        return ExportResult(success=False, error=f"Profile '{resolved.name}' selects no items")

    ships_skills = any(s.category_name == "claude_skills" and s.items for s in resolved.selections)
    section = _deployment_section(resolved)
    exporter = Exporter(config, target_platform=resolved.profile.target_platform)

    with tempfile.TemporaryDirectory() as tmp_dir:
        selections = list(resolved.selections)

        if ships_skills:
            cleanup_path = Path(tmp_dir) / CLEANUP_COMMAND_NAME
            cleanup_path.write_text(build_cleanup_command(resolved.name), encoding="utf-8")

            cleanup_item = SyncItem(
                name=CLEANUP_COMMAND_NAME,
                category=CLEANUP_CATEGORY,
                item_type=ItemType.FILE,
                local_path=cleanup_path,
            )
            category = config.sync_categories.get(CLEANUP_CATEGORY)
            if category is None:
                logger.warning(
                    "Category %s not configured — bundle ships without a cleanup command",
                    CLEANUP_CATEGORY,
                )
            else:
                for index, selection in enumerate(selections):
                    if selection.category_name == CLEANUP_CATEGORY:
                        selections[index] = ExportSelection(
                            category_name=CLEANUP_CATEGORY,
                            category=selection.category,
                            items=[*selection.items, cleanup_item],
                        )
                        break
                else:
                    selections.append(
                        ExportSelection(
                            category_name=CLEANUP_CATEGORY,
                            category=category,
                            items=[cleanup_item],
                        )
                    )
                section.sweep_globs.setdefault(CLEANUP_CATEGORY, []).append(
                    CLEANUP_COMMAND_NAME
                )

        return exporter.export_to_zip(
            selections, output_path, raw_config, deployment=section
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_deploy_bundle.py -q`
Expected: PASS (6 tests)

- [ ] **Step 7: Verify the plain export path is unchanged**

Run: `pytest tests/test_transfer.py tests/test_exporter_security.py -q`
Expected: PASS

- [ ] **Step 8: Quality gate and commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
git add sccs/deploy/bundle.py sccs/transfer/manifest.py sccs/transfer/exporter.py tests/test_deploy_bundle.py
git commit -m "[ADD] deploy: self-describing bundle with deployment section and cleanup command"
```

---

### Task 4: The receipt

**Files:**
- Create: `sccs/deploy/receipt.py`
- Test: `tests/test_deploy_receipt.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (the receipt is deliberately standalone — `revoke` must work on a host with no SCCS config).
- Produces:
  - `DEFAULT_RECEIPT_PATH: Path` (`~/.config/sccs/.deploy_receipt.yaml`)
  - `@dataclass class ReceiptEntry`: `category: str`, `name: str`, `target: str`, `item_type: str`, `content_hash: str | None`, `pre_existing: bool`
  - `@dataclass class InstallRecord`: `profile: str`, `installed_at: str`, `sccs_version: str`, `retain: list[str]`, `sweep_globs: dict[str, list[str]]`, `entries: list[ReceiptEntry]`
  - `@dataclass class DeployReceipt`: `version: int`, `installs: list[InstallRecord]`
  - `class ReceiptManager`: `load() -> DeployReceipt`, `save(receipt) -> None`, `record_install(record) -> None`, `remove_install(profile) -> None`, `exists() -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_receipt.py`:

```python
"""Receipt persistence: round trip, re-install, removal."""

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.deploy.receipt import (
    DeployReceipt,
    InstallRecord,
    ReceiptEntry,
    ReceiptManager,
)


@pytest.fixture
def manager(tmp_path):
    return ReceiptManager(tmp_path / ".deploy_receipt.yaml")


def _record(profile="odoo-server", names=("odoo-common",)):
    return InstallRecord(
        profile=profile,
        installed_at="2026-09-01T10:00:00+00:00",
        sccs_version="2.65.0",
        retain=["fish_config"],
        sweep_globs={"claude_skills": list(names)},
        entries=[
            ReceiptEntry(
                category="claude_skills",
                name=name,
                target=f"/home/u/.claude/skills/{name}",
                item_type="directory",
                content_hash="sha256:abc",
                pre_existing=False,
            )
            for name in names
        ],
    )


def test_missing_receipt_loads_empty(manager):
    receipt = manager.load()
    assert isinstance(receipt, DeployReceipt)
    assert receipt.installs == []
    assert not manager.exists()


def test_round_trip(manager):
    manager.record_install(_record())
    loaded = manager.load()
    assert len(loaded.installs) == 1
    assert loaded.installs[0].profile == "odoo-server"
    assert loaded.installs[0].entries[0].name == "odoo-common"
    assert loaded.installs[0].entries[0].pre_existing is False
    assert loaded.installs[0].sweep_globs == {"claude_skills": ["odoo-common"]}


def test_reinstall_replaces_record_of_same_profile(manager):
    manager.record_install(_record(names=("odoo-common",)))
    manager.record_install(_record(names=("odoo-common", "odoo19")))
    loaded = manager.load()
    assert len(loaded.installs) == 1
    assert len(loaded.installs[0].entries) == 2


def test_two_profiles_coexist(manager):
    manager.record_install(_record(profile="odoo-server"))
    manager.record_install(_record(profile="fastreport", names=("fr-reports",)))
    assert {r.profile for r in manager.load().installs} == {"odoo-server", "fastreport"}


def test_remove_install_drops_only_that_profile(manager):
    manager.record_install(_record(profile="odoo-server"))
    manager.record_install(_record(profile="fastreport", names=("fr-reports",)))
    manager.remove_install("odoo-server")
    assert [r.profile for r in manager.load().installs] == ["fastreport"]


def test_receipt_file_is_owner_only(manager, tmp_path):
    manager.record_install(_record())
    mode = (tmp_path / ".deploy_receipt.yaml").stat().st_mode & 0o777
    assert mode == 0o600


def test_corrupt_receipt_raises_rather_than_silently_emptying(manager, tmp_path):
    (tmp_path / ".deploy_receipt.yaml").write_text("{[not: yaml", encoding="utf-8")
    with pytest.raises(ValueError, match="receipt"):
        manager.load()


def test_unknown_version_raises(manager, tmp_path):
    (tmp_path / ".deploy_receipt.yaml").write_text("version: 99\ninstalls: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        manager.load()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deploy_receipt.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.deploy.receipt'`

- [ ] **Step 3: Write the receipt module**

Create `sccs/deploy/receipt.py`:

```python
# What `sccs deploy install` wrote, so `sccs deploy revoke` knows what to
# take back.
#
# The receipt is deliberately standalone: it stores absolute target paths,
# the retain list and the sweep globs, so removal works on a host that has
# no SCCS config at all.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write

logger = get_logger("sccs.deploy")

DEFAULT_RECEIPT_PATH = Path.home() / ".config" / "sccs" / ".deploy_receipt.yaml"

RECEIPT_VERSION = 1


@dataclass
class ReceiptEntry:
    """One artefact written by an install."""

    category: str
    name: str
    target: str
    item_type: str
    content_hash: str | None = None
    # True when something already existed at `target` before we wrote.
    # Such an entry is NEVER removed by revoke — "written by us" and "was
    # already here" are different facts, and only the first justifies a
    # deletion. Same line as the foreign_target guard in the Codex export.
    pre_existing: bool = False


@dataclass
class InstallRecord:
    """One `sccs deploy install` run."""

    profile: str
    installed_at: str
    sccs_version: str
    retain: list[str] = field(default_factory=list)
    sweep_globs: dict[str, list[str]] = field(default_factory=dict)
    entries: list[ReceiptEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstallRecord:
        return cls(
            profile=data["profile"],
            installed_at=data.get("installed_at", ""),
            sccs_version=data.get("sccs_version", ""),
            retain=list(data.get("retain") or []),
            sweep_globs={k: list(v) for k, v in (data.get("sweep_globs") or {}).items()},
            entries=[ReceiptEntry(**e) for e in (data.get("entries") or [])],
        )


@dataclass
class DeployReceipt:
    """Everything SCCS installed on this host."""

    version: int = RECEIPT_VERSION
    installs: list[InstallRecord] = field(default_factory=list)

    def find(self, profile: str) -> InstallRecord | None:
        for record in self.installs:
            if record.profile == profile:
                return record
        return None


class ReceiptManager:
    """Loads and saves the deployment receipt."""

    def __init__(self, receipt_path: Path | None = None) -> None:
        self._path = receipt_path or DEFAULT_RECEIPT_PATH

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> DeployReceipt:
        """Load the receipt, or an empty one when the file does not exist.

        Raises:
            ValueError: If the file exists but cannot be read as a receipt.
                Silently returning an empty receipt would make `revoke`
                report "nothing to remove" on a host that is full of our
                artefacts — the one failure this feature must not have.
        """
        if not self._path.exists():
            return DeployReceipt()

        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as e:
            raise ValueError(f"Cannot read deployment receipt at {self._path}: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(f"Deployment receipt at {self._path} is not a mapping")

        version = data.get("version", RECEIPT_VERSION)
        if version != RECEIPT_VERSION:
            raise ValueError(
                f"Deployment receipt version {version} is not supported "
                f"(this SCCS understands version {RECEIPT_VERSION})"
            )

        try:
            installs = [InstallRecord.from_dict(r) for r in (data.get("installs") or [])]
        except (KeyError, TypeError) as e:
            raise ValueError(f"Malformed deployment receipt at {self._path}: {e}") from e

        return DeployReceipt(version=version, installs=installs)

    def save(self, receipt: DeployReceipt) -> None:
        """Write the receipt atomically, owner-readable only."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": receipt.version,
            "installs": [r.to_dict() for r in receipt.installs],
        }
        content = yaml.dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True)
        atomic_write(self._path, content, mode=0o600)
        logger.debug("Wrote deployment receipt: %s", self._path)

    def record_install(self, record: InstallRecord) -> None:
        """Add or replace the record for `record.profile`."""
        receipt = self.load()
        receipt.installs = [r for r in receipt.installs if r.profile != record.profile]
        receipt.installs.append(record)
        self.save(receipt)

    def remove_install(self, profile: str) -> None:
        """Drop one profile's record; delete the file when none remain."""
        receipt = self.load()
        receipt.installs = [r for r in receipt.installs if r.profile != profile]
        if receipt.installs:
            self.save(receipt)
        elif self._path.exists():
            self._path.unlink()
            logger.debug("Removed empty deployment receipt: %s", self._path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_deploy_receipt.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Quality gate and commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
git add sccs/deploy/receipt.py tests/test_deploy_receipt.py
git commit -m "[ADD] deploy: installation receipt with pre_existing ownership marker"
```

---

### Task 5: Installation — home guard, pre-existing detection, receipt writing

**Files:**
- Create: `sccs/deploy/install.py`
- Test: `tests/test_deploy_install.py`

**Interfaces:**
- Consumes: `ReceiptManager`, `InstallRecord`, `ReceiptEntry` (Task 4); `DeploymentSection` (Task 3).
- Produces:
  - `@dataclass class InstallOutcome`: `success: bool`, `profile: str`, `installed: int`, `skipped: int`, `errors: list[str]`, `record: InstallRecord | None`
  - `def install_bundle(zip_path: Path, *, config: SccsConfig | None, receipt_manager: ReceiptManager, dry_run: bool = False, overwrite: bool = True) -> InstallOutcome`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_install.py`:

```python
"""Installation: pre-existing detection, home guard, receipt writing."""

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.config.schema import SccsConfig
from sccs.deploy.bundle import build_bundle
from sccs.deploy.install import install_bundle
from sccs.deploy.receipt import ReceiptManager
from sccs.deploy.resolve import resolve_profile
from sccs.deploy.schema import DeploymentProfile


@pytest.fixture
def source_home(tmp_path, monkeypatch):
    """The exporting machine."""
    home = tmp_path / "source"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    skills = home / ".claude" / "skills"
    for name in ("odoo-common", "odoo19"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: t\n---\n\nBody of {name}.\n", encoding="utf-8"
        )
    return home


@pytest.fixture
def source_config(source_home):
    return SccsConfig.model_validate(
        {
            "repository": {"path": str(source_home / "repo")},
            "sync_categories": {
                "claude_skills": {
                    "enabled": True,
                    "local_path": "~/.claude/skills",
                    "repo_path": ".claude/skills",
                    "item_type": "directory",
                    "item_marker": "SKILL.md",
                    "include": ["*"],
                }
            },
        }
    )


@pytest.fixture
def bundle(source_config, tmp_path):
    profile = DeploymentProfile(
        description="t",
        target_platform="linux",
        include={"claude_skills": ["odoo-common", "odoo19"]},
    )
    resolved = resolve_profile(source_config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    assert build_bundle(source_config, resolved, out, {}).success
    return out


def _switch_home(monkeypatch, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)


def test_install_writes_items_and_receipt(bundle, tmp_path, monkeypatch):
    target = tmp_path / "target"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(bundle, config=None, receipt_manager=manager)

    assert outcome.success
    assert outcome.installed == 2
    assert (target / ".claude" / "skills" / "odoo-common" / "SKILL.md").exists()

    record = manager.load().find("t")
    assert record is not None
    assert {e.name for e in record.entries} == {"odoo-common", "odoo19"}
    assert all(e.content_hash for e in record.entries)


def test_pre_existing_item_is_marked(bundle, tmp_path, monkeypatch):
    target = tmp_path / "target"
    _switch_home(monkeypatch, target)
    existing = target / ".claude" / "skills" / "odoo-common"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("customer's own\n", encoding="utf-8")

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    install_bundle(bundle, config=None, receipt_manager=manager)

    record = manager.load().find("t")
    marks = {e.name: e.pre_existing for e in record.entries}
    assert marks["odoo-common"] is True
    assert marks["odoo19"] is False


def test_dry_run_writes_nothing(bundle, tmp_path, monkeypatch):
    target = tmp_path / "target"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(bundle, config=None, receipt_manager=manager, dry_run=True)

    assert outcome.success
    assert not (target / ".claude" / "skills" / "odoo-common").exists()
    assert not manager.exists()


def test_bundle_without_deployment_section_is_refused(source_config, tmp_path, monkeypatch):
    """`sccs deploy install` takes deployment bundles, not plain exports."""
    from sccs.transfer.exporter import Exporter

    exporter = Exporter(source_config)
    scanned = exporter.scan_available_items()
    plain = tmp_path / "plain.zip"
    exporter.export_to_zip(exporter.build_selections_all(scanned), plain, {})

    target = tmp_path / "target2"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(plain, config=None, receipt_manager=manager)
    assert not outcome.success
    assert any("deployment" in e.lower() for e in outcome.errors)


def test_target_outside_home_is_refused(bundle, tmp_path, monkeypatch):
    """A manifest local_path outside HOME is rejected even in legacy mode."""
    import zipfile

    import yaml

    from sccs.transfer.manifest import MANIFEST_FILENAME

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(bundle) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == MANIFEST_FILENAME:
                doc = yaml.safe_load(data.decode("utf-8"))
                doc["categories"]["claude_skills"]["local_path"] = "/etc/sccs-evil"
                data = yaml.dump(doc).encode("utf-8")
            dst.writestr(info, data)

    target = tmp_path / "target3"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    outcome = install_bundle(tampered, config=None, receipt_manager=manager)
    assert not outcome.success
    assert any("home" in e.lower() for e in outcome.errors)
    assert not Path("/etc/sccs-evil").exists()


def test_reinstall_updates_the_record(bundle, tmp_path, monkeypatch):
    target = tmp_path / "target4"
    _switch_home(monkeypatch, target)
    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")

    install_bundle(bundle, config=None, receipt_manager=manager)
    install_bundle(bundle, config=None, receipt_manager=manager)

    receipt = manager.load()
    assert len(receipt.installs) == 1
    assert len(receipt.installs[0].entries) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deploy_install.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.deploy.install'`

- [ ] **Step 3: Write the installer**

Create `sccs/deploy/install.py`:

```python
# `sccs deploy install` — run the existing Importer, then write the receipt.
#
# On a customer host there is no config.yaml of ours, so the Importer runs
# in legacy mode (config=None) and accepts the manifest's local_path. That
# path is attacker-controlled, so we add the guard the legacy branch lacks:
# every target base must live under HOME.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sccs import __version__
from sccs.config.schema import SccsConfig
from sccs.deploy.receipt import InstallRecord, ReceiptEntry, ReceiptManager
from sccs.doctor._paths import is_home_path
from sccs.transfer.importer import Importer
from sccs.transfer.manifest import ManifestItem
from sccs.utils.hashing import directory_hash, file_hash
from sccs.utils.logging import get_logger

logger = get_logger("sccs.deploy")


@dataclass
class InstallOutcome:
    """Result of installing one deployment bundle."""

    success: bool
    profile: str = ""
    installed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    record: InstallRecord | None = None


def _target_path(base: Path, item: ManifestItem) -> Path:
    return base / item.name


def _hash_target(path: Path, item_type: str) -> str | None:
    if not path.exists():
        return None
    if item_type == "directory":
        return directory_hash(path)
    return file_hash(path)


def install_bundle(
    zip_path: Path,
    *,
    config: SccsConfig | None,
    receipt_manager: ReceiptManager,
    dry_run: bool = False,
    overwrite: bool = True,
) -> InstallOutcome:
    """Install a deployment bundle and record what was written.

    Args:
        zip_path: The bundle produced by `sccs deploy export`.
        config: Local SCCS config, or None on a host that has none.
        receipt_manager: Where the receipt is written.
        dry_run: Preview only — nothing is written, no receipt.
        overwrite: Replace existing targets. True by default: a deployment
            that silently skips half its payload is worse than one that
            refreshes it, and `pre_existing` records what was displaced.
    """
    importer = Importer(zip_path, config=config)

    try:
        manifest = importer.load_manifest()
    except (ValueError, OSError) as e:
        return InstallOutcome(success=False, errors=[f"Cannot read bundle: {e}"])

    if manifest.deployment is None:
        return InstallOutcome(
            success=False,
            errors=[
                "Archive has no deployment section — it was made by `sccs export`, "
                "not `sccs deploy export`. Use `sccs import` for it."
            ],
        )

    section = manifest.deployment

    # Home guard. With a config the Importer already pins every target to
    # the configured local_path; without one it accepts the manifest's word,
    # and the manifest came out of a file. Nothing we ship belongs outside HOME.
    for cat_name, cat_data in manifest.categories.items():
        if not is_home_path(cat_data.local_path):
            return InstallOutcome(
                success=False,
                profile=section.profile,
                errors=[
                    f"Category '{cat_name}' targets '{cat_data.local_path}', which is "
                    f"outside the home directory — refusing to install"
                ],
            )

    selections = importer.build_selections_all()

    # Record pre-existing state BEFORE the import writes anything.
    pre_existing: dict[tuple[str, str], bool] = {}
    bases: dict[str, Path] = {}
    for cat_name, item in selections:
        cat_data = manifest.categories[cat_name]
        base = Path(cat_data.local_path).expanduser()
        bases[cat_name] = base
        pre_existing[(cat_name, item.name)] = _target_path(base, item).exists()

    result = importer.apply(
        selections, dry_run=dry_run, overwrite=overwrite, backup=not dry_run
    )

    if dry_run:
        return InstallOutcome(
            success=result.success,
            profile=section.profile,
            installed=len(selections),
            errors=list(result.errors),
        )

    entries: list[ReceiptEntry] = []
    for cat_name, item in selections:
        target = _target_path(bases[cat_name], item)
        if not target.exists():
            continue
        entries.append(
            ReceiptEntry(
                category=cat_name,
                name=item.name,
                target=str(target),
                item_type=item.item_type,
                content_hash=_hash_target(target, item.item_type),
                pre_existing=pre_existing[(cat_name, item.name)],
            )
        )

    record = InstallRecord(
        profile=section.profile,
        installed_at=datetime.now(timezone.utc).isoformat(),
        sccs_version=__version__,
        retain=list(section.retain),
        sweep_globs={k: list(v) for k, v in section.sweep_globs.items()},
        entries=entries,
    )
    receipt_manager.record_install(record)
    logger.info("Installed profile %s: %d artefacts", section.profile, len(entries))

    return InstallOutcome(
        success=result.success,
        profile=section.profile,
        installed=len(entries),
        skipped=len(selections) - len(entries),
        errors=list(result.errors),
        record=record,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_deploy_install.py -q`
Expected: PASS (6 tests)

Signatures used here, verified against the tree on 01.09.2026: `directory_hash(path, *, algorithm="sha256", include_names=True, exclude_patterns=None) -> str | None` (`sccs/utils/hashing.py:51`) and `file_hash(path, *, algorithm="sha256", chunk_size=8192) -> str | None` (line 27). Both return `None` for a missing path, which is why `_hash_target` is typed `str | None`.

- [ ] **Step 5: Quality gate and commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
git add sccs/deploy/install.py tests/test_deploy_install.py
git commit -m "[ADD] deploy: bundle installation with home guard and receipt"
```

---

### Task 6: Work traces

**Files:**
- Create: `sccs/deploy/traces.py`
- Test: `tests/test_deploy_traces.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `@dataclass class TraceTarget`: `path: Path`, `label: str`, `kind: str` (`"tree"`, `"file"`, `"json_history"`), `exists: bool`, `size_bytes: int`
  - `def enumerate_traces(home: Path | None = None) -> list[TraceTarget]`
  - `def strip_claude_json_history(path: Path, *, dry_run: bool = False) -> bool`
  - `def remove_traces(targets: list[TraceTarget], *, dry_run: bool = False) -> list[str]` (returns error strings)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_traces.py`:

```python
"""Work traces: enumeration, ~/.claude.json surgery, removal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sccs.deploy.traces import (
    enumerate_traces,
    remove_traces,
    strip_claude_json_history,
)


@pytest.fixture
def home(tmp_path):
    claude = tmp_path / ".claude"
    (claude / "projects" / "-Users-x-repo").mkdir(parents=True)
    (claude / "projects" / "-Users-x-repo" / "session.jsonl").write_text(
        '{"role":"user"}\n', encoding="utf-8"
    )
    (claude / "plans").mkdir()
    (claude / "plans" / "p.md").write_text("plan\n", encoding="utf-8")
    (claude / "todos").mkdir()
    (claude / "shell-snapshots").mkdir()
    (tmp_path / ".config" / "sccs").mkdir(parents=True)
    (tmp_path / ".config" / "sccs" / "config.yaml").write_text("repository:\n", encoding="utf-8")
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "userID": "abc",
                "hasCompletedOnboarding": True,
                "history": [{"display": "secret prompt"}],
                "projects": {
                    "/x": {"allowedTools": ["Bash"], "history": [{"display": "another"}]}
                },
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_enumerate_finds_the_documented_locations(home):
    targets = enumerate_traces(home)
    labels = {t.label for t in targets if t.exists}
    assert "session transcripts and project memory" in labels
    assert {t.path for t in targets if t.exists} >= {
        home / ".claude" / "projects",
        home / ".claude" / "plans",
        home / ".claude" / "todos",
        home / ".claude" / "shell-snapshots",
        home / ".config" / "sccs" / "config.yaml",
        home / ".claude.json",
    }


def test_enumerate_marks_absent_paths(tmp_path):
    targets = enumerate_traces(tmp_path)
    assert all(not t.exists for t in targets)


def test_claude_json_keeps_everything_but_history(home):
    changed = strip_claude_json_history(home / ".claude.json")
    assert changed

    doc = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert "history" not in doc
    assert "history" not in doc["projects"]["/x"]
    assert doc["userID"] == "abc"
    assert doc["hasCompletedOnboarding"] is True
    assert doc["projects"]["/x"]["allowedTools"] == ["Bash"]


def test_claude_json_is_not_deleted(home):
    strip_claude_json_history(home / ".claude.json")
    assert (home / ".claude.json").exists()


def test_claude_json_dry_run_changes_nothing(home):
    before = (home / ".claude.json").read_text(encoding="utf-8")
    changed = strip_claude_json_history(home / ".claude.json", dry_run=True)
    assert changed
    assert (home / ".claude.json").read_text(encoding="utf-8") == before


def test_claude_json_without_history_reports_no_change(home):
    (home / ".claude.json").write_text(json.dumps({"userID": "abc"}), encoding="utf-8")
    assert strip_claude_json_history(home / ".claude.json") is False


def test_malformed_claude_json_is_left_alone(home):
    (home / ".claude.json").write_text("{not json", encoding="utf-8")
    assert strip_claude_json_history(home / ".claude.json") is False
    assert (home / ".claude.json").read_text(encoding="utf-8") == "{not json"


def test_claude_json_stays_owner_only(home):
    strip_claude_json_history(home / ".claude.json")
    assert (home / ".claude.json").stat().st_mode & 0o777 == 0o600


def test_remove_traces_clears_trees_and_files(home):
    targets = [t for t in enumerate_traces(home) if t.exists]
    errors = remove_traces(targets)
    assert errors == []
    assert not (home / ".claude" / "projects").exists()
    assert not (home / ".config" / "sccs" / "config.yaml").exists()
    assert (home / ".claude.json").exists()


def test_remove_traces_dry_run_removes_nothing(home):
    targets = [t for t in enumerate_traces(home) if t.exists]
    assert remove_traces(targets, dry_run=True) == []
    assert (home / ".claude" / "projects").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deploy_traces.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.deploy.traces'`

- [ ] **Step 3: Write the traces module**

Create `sccs/deploy/traces.py`:

```python
# What a working session leaves behind on a foreign host.
#
# The actual leak is not the skill directory — it is the transcript that
# quotes the skill verbatim. Deleting the skills while leaving the
# transcript protects nothing.

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write

logger = get_logger("sccs.deploy")

# (relative path, label, kind)
_TRACE_SPEC: tuple[tuple[str, str, str], ...] = (
    (".claude/projects", "session transcripts and project memory", "tree"),
    (".claude/plans", "saved plans", "tree"),
    (".claude/todos", "todo lists", "tree"),
    (".claude/shell-snapshots", "shell snapshots", "tree"),
    (".config/sccs/config.yaml", "SCCS config (repository path, category layout)", "file"),
    (".claude.json", "prompt history inside ~/.claude.json", "json_history"),
)


@dataclass
class TraceTarget:
    """One location that accumulates traces of our work."""

    path: Path
    label: str
    kind: str
    exists: bool = False
    size_bytes: int = 0


def _tree_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def enumerate_traces(home: Path | None = None) -> list[TraceTarget]:
    """List the trace locations, marking which of them exist."""
    base = home or Path.home()
    targets: list[TraceTarget] = []

    for rel, label, kind in _TRACE_SPEC:
        path = base / rel
        exists = path.exists()
        size = 0
        if exists:
            try:
                size = _tree_size(path) if path.is_dir() else path.stat().st_size
            except OSError:
                size = 0
        targets.append(TraceTarget(path=path, label=label, kind=kind, exists=exists, size_bytes=size))

    return targets


def strip_claude_json_history(path: Path, *, dry_run: bool = False) -> bool:
    """Remove `history` and `projects[*].history` from ~/.claude.json.

    The file is trimmed, never deleted: it also carries the host user's auth
    and onboarding state, and removing it would cause damage nobody asked
    for.

    Returns:
        True if there was history to remove (also in dry-run), else False.
        A malformed file is left untouched and reported as False.
    """
    if not path.exists():
        return False

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Leaving %s untouched — cannot parse it: %s", path, e)
        return False

    if not isinstance(doc, dict):
        return False

    changed = doc.pop("history", None) is not None
    projects = doc.get("projects")
    if isinstance(projects, dict):
        for project in projects.values():
            if isinstance(project, dict) and project.pop("history", None) is not None:
                changed = True

    if not changed or dry_run:
        return changed

    atomic_write(path, json.dumps(doc, indent=2) + "\n", mode=0o600)
    logger.info("Stripped prompt history from %s", path)
    return True


def remove_traces(targets: list[TraceTarget], *, dry_run: bool = False) -> list[str]:
    """Remove the given trace targets. Returns error strings, empty on success."""
    errors: list[str] = []

    for target in targets:
        if not target.path.exists():
            continue
        try:
            if target.kind == "json_history":
                strip_claude_json_history(target.path, dry_run=dry_run)
            elif dry_run:
                continue
            elif target.kind == "tree":
                shutil.rmtree(target.path)
                logger.info("Removed trace tree: %s", target.path)
            else:
                target.path.unlink()
                logger.info("Removed trace file: %s", target.path)
        except OSError as e:
            errors.append(f"{target.path}: {e}")

    return errors
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_deploy_traces.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Quality gate and commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
git add sccs/deploy/traces.py tests/test_deploy_traces.py
git commit -m "[ADD] deploy: work-trace enumeration and ~/.claude.json history stripping"
```

---

### Task 7: Revocation — plan, execution, verification sweep

**Files:**
- Create: `sccs/deploy/revoke.py`
- Test: `tests/test_deploy_revoke.py`

**Interfaces:**
- Consumes: `ReceiptManager`, `DeployReceipt`, `InstallRecord`, `ReceiptEntry` (Task 4); `TraceTarget`, `enumerate_traces`, `remove_traces` (Task 6).
- Produces:
  - `@dataclass class RevokeItem`: `entry: ReceiptEntry`, `bucket: str` (`"remove"`, `"retain"`, `"untouched"`, `"gone"`), `modified: bool`
  - `@dataclass class RevokePlan`: `profiles: list[str]`, `items: list[RevokeItem]`, `traces: list[TraceTarget]`, `purge_traces: bool`; properties `to_remove`, `retained`, `untouched`, `already_gone`, `modified`
  - `@dataclass class RevokeResult`: `success: bool`, `removed: int`, `errors: list[str]`, `leftovers: list[str]`
  - `def build_revoke_plan(receipt_manager: ReceiptManager, *, profile: str | None = None, keep_traces: bool = False, home: Path | None = None) -> RevokePlan`
  - `def execute_revoke(plan: RevokePlan, receipt_manager: ReceiptManager, *, dry_run: bool = False) -> RevokeResult`
  - `def sweep(plan: RevokePlan) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_revoke.py`:

```python
"""Revocation: buckets, trace policy, verification sweep."""

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.deploy.receipt import InstallRecord, ReceiptEntry, ReceiptManager
from sccs.deploy.revoke import build_revoke_plan, execute_revoke, sweep
from sccs.utils.hashing import directory_hash


@pytest.fixture
def host(tmp_path):
    """A host with two profiles installed."""
    skills = tmp_path / ".claude" / "skills"
    for name in ("odoo-common", "odoo19", "customers-own"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")

    fish = tmp_path / ".config" / "fish"
    fish.mkdir(parents=True)
    (fish / "config.fish").write_text("# fish\n", encoding="utf-8")

    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / ".claude" / "projects" / "s.jsonl").write_text("{}\n", encoding="utf-8")
    return tmp_path


def _entry(host: Path, name: str, *, pre_existing=False, category="claude_skills"):
    target = host / ".claude" / "skills" / name
    return ReceiptEntry(
        category=category,
        name=name,
        target=str(target),
        item_type="directory",
        content_hash=directory_hash(target),
        pre_existing=pre_existing,
    )


@pytest.fixture
def manager(host):
    manager = ReceiptManager(host / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(
        InstallRecord(
            profile="odoo-server",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            retain=["fish_config"],
            sweep_globs={"claude_skills": ["odoo-common", "odoo19", "customers-own"]},
            entries=[
                _entry(host, "odoo-common"),
                _entry(host, "odoo19"),
                _entry(host, "customers-own", pre_existing=True),
                ReceiptEntry(
                    category="fish_config",
                    name="config.fish",
                    target=str(host / ".config" / "fish" / "config.fish"),
                    item_type="file",
                    content_hash="sha256:x",
                ),
                ReceiptEntry(
                    category="claude_skills",
                    name="already-gone",
                    target=str(host / ".claude" / "skills" / "already-gone"),
                    item_type="directory",
                ),
            ],
        )
    )
    return manager


def test_plan_sorts_into_four_buckets(manager, host):
    plan = build_revoke_plan(manager, home=host)
    assert {i.entry.name for i in plan.to_remove} == {"odoo-common", "odoo19"}
    assert {i.entry.name for i in plan.retained} == {"config.fish"}
    assert {i.entry.name for i in plan.untouched} == {"customers-own"}
    assert {i.entry.name for i in plan.already_gone} == {"already-gone"}


def test_modified_artefact_is_flagged_but_still_removed(manager, host):
    (host / ".claude" / "skills" / "odoo19" / "SKILL.md").write_text("edited\n", encoding="utf-8")
    plan = build_revoke_plan(manager, home=host)
    assert {i.entry.name for i in plan.modified} == {"odoo19"}
    assert "odoo19" in {i.entry.name for i in plan.to_remove}


def test_execute_removes_only_the_remove_bucket(manager, host):
    plan = build_revoke_plan(manager, home=host)
    result = execute_revoke(plan, manager)

    assert result.success
    assert result.removed == 2
    assert not (host / ".claude" / "skills" / "odoo-common").exists()
    assert not (host / ".claude" / "skills" / "odoo19").exists()
    assert (host / ".claude" / "skills" / "customers-own").exists()
    assert (host / ".config" / "fish" / "config.fish").exists()


def test_execute_purges_traces_and_drops_the_receipt(manager, host):
    plan = build_revoke_plan(manager, home=host)
    execute_revoke(plan, manager)
    assert not (host / ".claude" / "projects").exists()
    assert not manager.exists()


def test_keep_traces_leaves_transcripts(manager, host):
    plan = build_revoke_plan(manager, keep_traces=True, home=host)
    execute_revoke(plan, manager)
    assert (host / ".claude" / "projects").exists()


def test_dry_run_changes_nothing(manager, host):
    plan = build_revoke_plan(manager, home=host)
    result = execute_revoke(plan, manager, dry_run=True)
    assert result.success
    assert (host / ".claude" / "skills" / "odoo-common").exists()
    assert manager.exists()


def test_traces_survive_while_another_profile_remains(manager, host):
    manager.record_install(
        InstallRecord(
            profile="fastreport",
            installed_at="2026-09-01T11:00:00+00:00",
            sccs_version="2.65.0",
            retain=[],
            sweep_globs={},
            entries=[],
        )
    )
    plan = build_revoke_plan(manager, profile="odoo-server", home=host)
    assert plan.purge_traces is False
    execute_revoke(plan, manager)
    assert (host / ".claude" / "projects").exists()
    assert [r.profile for r in manager.load().installs] == ["fastreport"]


def test_sweep_is_clean_after_a_successful_revoke(manager, host):
    plan = build_revoke_plan(manager, home=host)
    execute_revoke(plan, manager)
    assert sweep(plan) == []


def test_sweep_reports_a_planted_leftover(manager, host):
    plan = build_revoke_plan(manager, home=host)
    execute_revoke(plan, manager)
    (host / ".claude" / "skills" / "odoo19").mkdir(parents=True)
    leftovers = sweep(plan)
    assert any("odoo19" in item for item in leftovers)


def test_execute_fails_when_the_sweep_finds_something(manager, host, monkeypatch):
    plan = build_revoke_plan(manager, home=host)

    def fake_sweep(_plan):
        return [str(host / ".claude" / "skills" / "odoo19")]

    monkeypatch.setattr("sccs.deploy.revoke.sweep", fake_sweep)
    result = execute_revoke(plan, manager)
    assert not result.success
    assert result.leftovers


def test_empty_receipt_yields_an_empty_plan(host):
    empty = ReceiptManager(host / "nothing.yaml")
    plan = build_revoke_plan(empty, home=host)
    assert plan.items == []
    assert plan.profiles == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deploy_revoke.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sccs.deploy.revoke'`

- [ ] **Step 3: Write the revoke module**

Create `sccs/deploy/revoke.py`:

```python
# `sccs deploy revoke` — take our knowledge back off a foreign host.
#
# Reads only the receipt, so it works where there is no SCCS config. Ends
# with a verification sweep: a removal that reports success while a skill
# directory survived is the worst possible outcome of this feature, because
# the report is what the decision to stop looking is based on.

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sccs.deploy.receipt import ReceiptEntry, ReceiptManager
from sccs.deploy.traces import TraceTarget, enumerate_traces, remove_traces
from sccs.utils.hashing import directory_hash, file_hash
from sccs.utils.logging import get_logger

logger = get_logger("sccs.deploy")

BUCKET_REMOVE = "remove"
BUCKET_RETAIN = "retain"
BUCKET_UNTOUCHED = "untouched"
BUCKET_GONE = "gone"


@dataclass
class RevokeItem:
    """One receipt entry with its verdict."""

    entry: ReceiptEntry
    bucket: str
    modified: bool = False


@dataclass
class RevokePlan:
    """What a revoke would do, before it does it."""

    profiles: list[str] = field(default_factory=list)
    items: list[RevokeItem] = field(default_factory=list)
    traces: list[TraceTarget] = field(default_factory=list)
    purge_traces: bool = True

    def _bucket(self, bucket: str) -> list[RevokeItem]:
        return [i for i in self.items if i.bucket == bucket]

    @property
    def to_remove(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_REMOVE)

    @property
    def retained(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_RETAIN)

    @property
    def untouched(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_UNTOUCHED)

    @property
    def already_gone(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_GONE)

    @property
    def modified(self) -> list[RevokeItem]:
        return [i for i in self.items if i.modified]


@dataclass
class RevokeResult:
    """Outcome of a revoke, including what the sweep found."""

    success: bool
    removed: int = 0
    errors: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)


def _current_hash(path: Path, item_type: str) -> str | None:
    if not path.exists():
        return None
    return directory_hash(path) if item_type == "directory" else file_hash(path)


def build_revoke_plan(
    receipt_manager: ReceiptManager,
    *,
    profile: str | None = None,
    keep_traces: bool = False,
    home: Path | None = None,
) -> RevokePlan:
    """Sort the receipt into buckets and decide the trace policy.

    Args:
        profile: Revoke only this profile. Default: every installed one.
        keep_traces: Leave transcripts, plans, todos and history in place.
        home: Root for trace enumeration. Defaults to the real home.
    """
    receipt = receipt_manager.load()
    records = [r for r in receipt.installs if profile is None or r.profile == profile]
    remaining = [r for r in receipt.installs if r not in records]

    plan = RevokePlan(profiles=[r.profile for r in records])

    for record in records:
        for entry in record.entries:
            target = Path(entry.target)
            if entry.pre_existing:
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_UNTOUCHED))
                continue
            if entry.category in record.retain:
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_RETAIN))
                continue
            if not target.exists():
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_GONE))
                continue

            # A modified artefact is still removed — it still carries our
            # knowledge. The flag exists so the decision is visible rather
            # than inherited.
            now = _current_hash(target, entry.item_type)
            modified = bool(entry.content_hash) and now != entry.content_hash
            plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_REMOVE, modified=modified))

    # Traces belong to no single profile: purge them only when the last
    # install goes. Otherwise removing one of two profiles would delete
    # transcripts the other is still producing.
    plan.purge_traces = bool(records) and not remaining and not keep_traces
    if plan.purge_traces:
        plan.traces = [t for t in enumerate_traces(home) if t.exists]

    return plan


def sweep(plan: RevokePlan) -> list[str]:
    """Re-check every planned removal. Returns paths that are still there."""
    leftovers: list[str] = []
    for item in plan.to_remove:
        target = Path(item.entry.target)
        if target.exists():
            leftovers.append(str(target))
    return leftovers


def execute_revoke(
    plan: RevokePlan,
    receipt_manager: ReceiptManager,
    *,
    dry_run: bool = False,
) -> RevokeResult:
    """Carry out the plan, then verify it actually happened."""
    if dry_run:
        return RevokeResult(success=True, removed=len(plan.to_remove))

    errors: list[str] = []
    removed = 0

    for item in plan.to_remove:
        target = Path(item.entry.target)
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed += 1
            logger.info("Removed %s (%s)", target, item.entry.category)
        except OSError as e:
            errors.append(f"{target}: {e}")

    if plan.purge_traces:
        errors.extend(remove_traces(plan.traces))

    for profile in plan.profiles:
        receipt_manager.remove_install(profile)

    leftovers = sweep(plan)
    if leftovers:
        logger.error("Revoke left %d artefacts behind", len(leftovers))

    return RevokeResult(
        success=not errors and not leftovers,
        removed=removed,
        errors=errors,
        leftovers=leftovers,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_deploy_revoke.py -q`
Expected: PASS (11 tests)

- [ ] **Step 5: Quality gate and commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
git add sccs/deploy/revoke.py tests/test_deploy_revoke.py
git commit -m "[ADD] deploy: revoke with four-bucket plan and verification sweep"
```

---

### Task 8: The `sccs deploy` CLI group

**Files:**
- Modify: `sccs/cli.py` (new group after the `profile` group, around line 3760)
- Test: `tests/test_deploy_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: the CLI surface `sccs deploy list|show|export|install|status|revoke`, each with `--json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_cli.py`:

```python
"""CLI surface for `sccs deploy`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from sccs.cli import cli
from sccs.deploy.receipt import InstallRecord, ReceiptEntry, ReceiptManager


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    skills = tmp_path / ".claude" / "skills"
    for name in ("odoo-common", "odoo19"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: t\n---\n\nBody.\n", encoding="utf-8"
        )

    config_dir = tmp_path / ".config" / "sccs"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "repository:\n"
        f"  path: {tmp_path}/repo\n"
        "sync_categories:\n"
        "  claude_skills:\n"
        "    enabled: true\n"
        "    local_path: ~/.claude/skills\n"
        "    repo_path: .claude/skills\n"
        "    item_type: directory\n"
        "    item_marker: SKILL.md\n"
        "    include: ['*']\n"
        "deployment_profiles:\n"
        "  tiny:\n"
        "    description: tiny test profile\n"
        "    target_platform: linux\n"
        "    include:\n"
        "      claude_skills: ['odoo-common']\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCCS_CONFIG", str(config_dir / "config.yaml"))
    return tmp_path


def test_list_json_includes_bundled_and_user_profiles(runner, home):
    result = runner.invoke(cli, ["deploy", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    names = {p["name"] for p in payload["profiles"]}
    assert {"odoo-server", "odoo-dev-full", "fastreport", "shell-only", "tiny"} <= names


def test_show_reports_resolved_items(runner, home):
    result = runner.invoke(cli, ["deploy", "show", "tiny", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["total_items"] == 1
    assert payload["categories"]["claude_skills"] == ["odoo-common"]


def test_show_unknown_profile_exits_nonzero(runner, home):
    result = runner.invoke(cli, ["deploy", "show", "ghost", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output.strip())["success"] is False


def test_export_creates_a_bundle(runner, home, tmp_path):
    out = tmp_path / "b.zip"
    result = runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out), "--json"])
    assert result.exit_code == 0
    assert out.exists()
    assert json.loads(result.output.strip())["success"] is True


def test_export_dry_run_writes_no_file(runner, home, tmp_path):
    out = tmp_path / "b.zip"
    result = runner.invoke(
        cli, ["deploy", "export", "tiny", "-o", str(out), "--dry-run", "--json"]
    )
    assert result.exit_code == 0
    assert not out.exists()


def test_export_blocks_on_missing_dependency(runner, home, tmp_path):
    """odoo-merge-to without odoo-common is refused by default."""
    skills = home / ".claude" / "skills" / "odoo-merge-to"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: odoo-merge-to\ndescription: t\n---\n\n"
        "**INHERITS FROM:** odoo-common (commit prefixes)\n",
        encoding="utf-8",
    )
    config = home / ".config" / "sccs" / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "claude_skills: ['odoo-common']", "claude_skills: ['odoo-merge-to']"
        ),
        encoding="utf-8",
    )

    out = tmp_path / "b.zip"
    result = runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out), "--json"])
    assert result.exit_code == 1
    assert not out.exists()

    result = runner.invoke(
        cli,
        ["deploy", "export", "tiny", "-o", str(out), "--allow-missing-deps", "--json"],
    )
    assert result.exit_code == 0
    assert out.exists()


def test_status_on_a_clean_host(runner, home):
    result = runner.invoke(cli, ["deploy", "status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["installs"] == []


def test_status_reports_an_install(runner, home):
    manager = ReceiptManager(home / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(
        InstallRecord(
            profile="tiny",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            retain=[],
            sweep_globs={"claude_skills": ["odoo-common"]},
            entries=[
                ReceiptEntry(
                    category="claude_skills",
                    name="odoo-common",
                    target=str(home / ".claude" / "skills" / "odoo-common"),
                    item_type="directory",
                    content_hash="sha256:x",
                )
            ],
        )
    )
    result = runner.invoke(cli, ["deploy", "status", "--json"])
    payload = json.loads(result.output.strip())
    assert payload["installs"][0]["profile"] == "tiny"
    assert payload["installs"][0]["artefacts"] == 1


def test_revoke_without_yes_aborts(runner, home, monkeypatch):
    manager = ReceiptManager(home / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(
        InstallRecord(
            profile="tiny",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            entries=[
                ReceiptEntry(
                    category="claude_skills",
                    name="odoo-common",
                    target=str(home / ".claude" / "skills" / "odoo-common"),
                    item_type="directory",
                )
            ],
        )
    )
    # Force the interactive branch: under CliRunner stdout is not a TTY, so
    # without this the command would exit on the TTY guard and the test
    # would pass without ever reaching the confirmation prompt.
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)

    result = runner.invoke(cli, ["deploy", "revoke"], input="nein\n")
    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert (home / ".claude" / "skills" / "odoo-common").exists()


def test_revoke_dry_run_needs_no_confirmation(runner, home):
    result = runner.invoke(cli, ["deploy", "revoke", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output.strip())["dry_run"] is True


def test_roundtrip_export_install_revoke_leaves_nothing(runner, home, tmp_path, monkeypatch):
    """The whole point of the feature, end to end.

    Switching hosts means re-patching BOTH `HOME` and `Path.home` — the
    `home` fixture patched `Path.home` to the source host, and the receipt
    manager resolves its path through `Path.home()`. Setting the
    environment variable alone leaves the receipt on the wrong machine.
    """
    out = tmp_path / "b.zip"
    assert runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out)]).exit_code == 0

    target = tmp_path / "customer"
    target.mkdir()
    monkeypatch.setenv("HOME", str(target))
    monkeypatch.setattr(Path, "home", lambda: target)
    # The customer host has no config of ours — that is the normal case.
    monkeypatch.delenv("SCCS_CONFIG", raising=False)

    result = runner.invoke(cli, ["deploy", "install", str(out), "--json"])
    assert result.exit_code == 0, result.output
    assert (target / ".claude" / "skills" / "odoo-common").exists()
    assert (target / ".config" / "sccs" / ".deploy_receipt.yaml").exists()

    result = runner.invoke(cli, ["deploy", "revoke", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    assert not (target / ".claude" / "skills" / "odoo-common").exists()
    assert _parse_clean(result.output)["leftovers"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deploy_cli.py -q`
Expected: FAIL — `Error: No such command 'deploy'`

- [ ] **Step 3: Add the CLI group**

In `sccs/cli.py`, after the last `profile_group` command, add:

```python
@cli.group("deploy")
def deploy_group() -> None:
    """Build scenario-scoped bundles for foreign hosts — and take them back.

    \b
    A deployment profile names the skills, commands, agents and shell files
    one situation needs (Odoo work on a customer server, FastReport, the
    shell only). `deploy export` bundles exactly those; `deploy install`
    unpacks them on the target host and writes a receipt; `deploy revoke`
    reads that receipt and removes what we brought.

    \b
    Shell configuration listed under a profile's `retain` stays behind.
    Everything else — skills, agents, framework files, and the session
    transcripts that quote them — leaves.

    \b
    Examples:
        sccs deploy list                     Show profiles
        sccs deploy show odoo-server         What would be bundled
        sccs deploy export odoo-server       Build the bundle
        sccs deploy install bundle.zip       Install on the target host
        sccs deploy status                   What of ours is here
        sccs deploy revoke --dry-run         Preview the removal
    """


def _load_deployment_profiles():
    """Resolve the deployment profile map, config or not."""
    from sccs.deploy.schema import resolve_deployment_profiles

    try:
        config = load_config()
    except FileNotFoundError:
        return resolve_deployment_profiles(None)
    return resolve_deployment_profiles(config.deployment_profiles)


def _deploy_receipt_manager():
    from sccs.deploy.receipt import ReceiptManager

    return ReceiptManager(Path.home() / ".config" / "sccs" / ".deploy_receipt.yaml")


@deploy_group.command("list")
@click.option("--json", "output_json", is_flag=True, help="Output machine-readable JSON")
@click.pass_context
def deploy_list(ctx: click.Context, output_json: bool) -> None:
    """List deployment profiles."""
    from sccs.deploy.schema import DeploymentProfileError
    from sccs.output.json_emit import emit_json, emit_json_error

    console = ctx.obj["console"]
    try:
        profiles = _load_deployment_profiles()
    except DeploymentProfileError as e:
        if output_json:
            emit_json_error(str(e))
        else:
            console.print_error(str(e))
        sys.exit(1)

    rows = [
        {
            "name": name,
            "description": p.description,
            "target_platform": p.target_platform,
            "categories": sorted(p.include),
            "retain": sorted(p.retain),
        }
        for name, p in sorted(profiles.items())
    ]

    if output_json:
        emit_json({"profiles": rows})
        return

    for row in rows:
        console.print(f"  [bold]{row['name']}[/bold] → {row['target_platform']}")
        console.print(f"         [dim]{row['description']}[/dim]")
        console.print(f"         [dim]{len(row['categories'])} categories, retains {len(row['retain'])}[/dim]")


@deploy_group.command("show")
@click.argument("name")
@click.option("--platform", "platform", default=None, help="Override the profile's target platform")
@click.option("--json", "output_json", is_flag=True, help="Output machine-readable JSON")
@click.pass_context
def deploy_show(ctx: click.Context, name: str, platform: str | None, output_json: bool) -> None:
    """Show what a profile would bundle."""
    from sccs.deploy.resolve import resolve_profile
    from sccs.deploy.schema import DeploymentProfileError
    from sccs.output.json_emit import emit_json, emit_json_error

    console = ctx.obj["console"]
    try:
        config = load_config()
        profiles = _load_deployment_profiles()
        resolved = resolve_profile(config, name, profiles, target_platform=platform)
    except (FileNotFoundError, DeploymentProfileError) as e:
        if output_json:
            emit_json_error(str(e))
        else:
            console.print_error(str(e))
        sys.exit(1)

    categories = {s.category_name: [i.name for i in s.items] for s in resolved.selections}
    payload = {
        "success": True,
        "profile": name,
        "target_platform": platform or resolved.profile.target_platform,
        "total_items": resolved.total_items,
        "categories": categories,
        "missing_items": [list(m) for m in resolved.missing_items],
        "missing_deps": [list(d) for d in resolved.missing_deps],
    }

    if output_json:
        emit_json(payload)
        return

    console.print(f"\n[bold]{name}[/bold] — {resolved.profile.description}")
    console.print(f"Target: {payload['target_platform']} · {resolved.total_items} items\n")
    for category, names in sorted(categories.items()):
        retained = " [dim](retained on revoke)[/dim]" if category in resolved.profile.retain else ""
        console.print(f"  [bold]{category}[/bold] ({len(names)}){retained}")
        console.print(f"    [dim]{', '.join(sorted(names))}[/dim]")
    for category, item in resolved.missing_items:
        console.print_warning(f"Named but not found: {category}/{item}")
    for skill, parent in resolved.missing_deps:
        console.print_warning(f"{skill} inherits from {parent}, which is not in the bundle")


@deploy_group.command("export")
@click.argument("name")
@click.option("-o", "--output", "output_path", type=click.Path(path_type=Path), default=None)
@click.option("--platform", "platform", default=None, help="Override the profile's target platform")
@click.option("-n", "--dry-run", is_flag=True, help="Resolve and report, write no ZIP")
@click.option("--allow-missing-deps", is_flag=True, help="Bundle despite unmet skill dependencies")
@click.option("--json", "output_json", is_flag=True, help="Output machine-readable JSON")
@click.pass_context
def deploy_export(
    ctx: click.Context,
    name: str,
    output_path: Path | None,
    platform: str | None,
    dry_run: bool,
    allow_missing_deps: bool,
    output_json: bool,
) -> None:
    """Build a deployment bundle from a profile."""
    from sccs.deploy.bundle import build_bundle
    from sccs.deploy.resolve import resolve_profile
    from sccs.deploy.schema import DeploymentProfileError
    from sccs.output.json_emit import emit_json, emit_json_error

    console = ctx.obj["console"]
    try:
        config = load_config()
        profiles = _load_deployment_profiles()
        resolved = resolve_profile(config, name, profiles, target_platform=platform)
    except (FileNotFoundError, DeploymentProfileError) as e:
        if output_json:
            emit_json_error(str(e))
        else:
            console.print_error(str(e))
        sys.exit(1)

    if resolved.missing_deps and not allow_missing_deps:
        detail = "; ".join(f"{s} needs {p}" for s, p in resolved.missing_deps)
        message = (
            f"Unmet skill dependencies: {detail}. "
            f"Add them to the profile, or pass --allow-missing-deps."
        )
        if output_json:
            emit_json_error(message, missing_deps=[list(d) for d in resolved.missing_deps])
        else:
            console.print_error(message)
        sys.exit(1)

    if output_path is None:
        output_path = Path.cwd() / f"sccs-{name}-{datetime.now().strftime('%Y%m%d')}.zip"

    if dry_run:
        payload = {
            "success": True,
            "dry_run": True,
            "profile": name,
            "output": str(output_path),
            "total_items": resolved.total_items,
        }
        if output_json:
            emit_json(payload)
        else:
            console.print_info(f"Would bundle {resolved.total_items} items into {output_path}")
        return

    result = build_bundle(config, resolved, output_path, load_raw_user_data())

    if not result.success:
        if output_json:
            emit_json_error(result.error or "Export failed")
        else:
            console.print_error(f"Export failed: {result.error}")
        sys.exit(1)

    if output_json:
        emit_json(
            {
                "success": True,
                "profile": name,
                "output": str(result.output_path),
                "total_items": result.total_items,
                "total_categories": result.total_categories,
            }
        )
        return

    console.print_success(f"Bundled {result.total_items} items for profile '{name}'")
    console.print_info(f"  Archive: {result.output_path}")


@deploy_group.command("install")
@click.argument("zip_path", type=click.Path(exists=True, path_type=Path))
@click.option("-n", "--dry-run", is_flag=True, help="Preview without writing")
@click.option("--json", "output_json", is_flag=True, help="Output machine-readable JSON")
@click.pass_context
def deploy_install(ctx: click.Context, zip_path: Path, dry_run: bool, output_json: bool) -> None:
    """Install a deployment bundle and write the receipt."""
    from sccs.deploy.install import install_bundle
    from sccs.output.json_emit import emit_json, emit_json_error

    console = ctx.obj["console"]

    try:
        config = load_config()
    except FileNotFoundError:
        # A customer host has no config of ours. That is the normal case.
        config = None

    outcome = install_bundle(
        zip_path,
        config=config,
        receipt_manager=_deploy_receipt_manager(),
        dry_run=dry_run,
    )

    if not outcome.success:
        message = "; ".join(outcome.errors) or "Install failed"
        if output_json:
            emit_json_error(message, profile=outcome.profile)
        else:
            console.print_error(message)
        sys.exit(1)

    if output_json:
        emit_json(
            {
                "success": True,
                "dry_run": dry_run,
                "profile": outcome.profile,
                "installed": outcome.installed,
                "skipped": outcome.skipped,
            }
        )
        return

    verb = "Would install" if dry_run else "Installed"
    console.print_success(f"{verb} {outcome.installed} artefacts (profile '{outcome.profile}')")
    if not dry_run:
        console.print_info("  Run `sccs deploy revoke` to remove them again.")


@deploy_group.command("status")
@click.option("--json", "output_json", is_flag=True, help="Output machine-readable JSON")
@click.pass_context
def deploy_status(ctx: click.Context, output_json: bool) -> None:
    """Show what SCCS installed on this host."""
    from sccs.output.json_emit import emit_json, emit_json_error

    console = ctx.obj["console"]
    try:
        receipt = _deploy_receipt_manager().load()
    except ValueError as e:
        if output_json:
            emit_json_error(str(e))
        else:
            console.print_error(str(e))
        sys.exit(1)

    rows = [
        {
            "profile": r.profile,
            "installed_at": r.installed_at,
            "sccs_version": r.sccs_version,
            "artefacts": len(r.entries),
            "retained_categories": sorted(r.retain),
            "pre_existing": sum(1 for e in r.entries if e.pre_existing),
        }
        for r in receipt.installs
    ]

    if output_json:
        emit_json({"installs": rows})
        return

    if not rows:
        console.print_info("Nothing installed by `sccs deploy` on this host.")
        return
    for row in rows:
        console.print(
            f"  [bold]{row['profile']}[/bold] — {row['artefacts']} artefacts, "
            f"installed {row['installed_at']}"
        )
        console.print(
            f"         [dim]{row['pre_existing']} pre-existing (kept), "
            f"retains {', '.join(row['retained_categories']) or 'nothing'}[/dim]"
        )


@deploy_group.command("revoke")
@click.option("--profile", "profile", default=None, help="Revoke only this profile")
@click.option("-n", "--dry-run", is_flag=True, help="Preview without removing")
@click.option("--keep-traces", is_flag=True, help="Leave transcripts, plans and history in place")
@click.option("-y", "--yes", is_flag=True, help="Skip the confirmation prompt")
@click.option("--json", "output_json", is_flag=True, help="Output machine-readable JSON")
@click.pass_context
def deploy_revoke(
    ctx: click.Context,
    profile: str | None,
    dry_run: bool,
    keep_traces: bool,
    yes: bool,
    output_json: bool,
) -> None:
    """Remove what SCCS installed, and verify it is gone."""
    from sccs.deploy.revoke import build_revoke_plan, execute_revoke
    from sccs.output.json_emit import emit_json, emit_json_error

    console = ctx.obj["console"]
    manager = _deploy_receipt_manager()

    try:
        plan = build_revoke_plan(manager, profile=profile, keep_traces=keep_traces)
    except ValueError as e:
        if output_json:
            emit_json_error(str(e))
        else:
            console.print_error(str(e))
        sys.exit(1)

    if not plan.items and not plan.traces:
        if output_json:
            emit_json({"success": True, "dry_run": dry_run, "removed": 0, "leftovers": []})
        else:
            console.print_info("Nothing to revoke on this host.")
        return

    if not output_json:
        console.print(f"\n[bold]Would remove ({len(plan.to_remove)}):[/bold]")
        for item in plan.to_remove:
            flag = " [yellow](modified since installation)[/yellow]" if item.modified else ""
            console.print(f"  {item.entry.category}/{item.entry.name}{flag}")
        if plan.retained:
            console.print(f"\n[bold]Stays ({len(plan.retained)}):[/bold]")
            for item in plan.retained:
                console.print(f"  [dim]{item.entry.category}/{item.entry.name}[/dim]")
        if plan.untouched:
            console.print(f"\n[bold]Not ours, untouched ({len(plan.untouched)}):[/bold]")
            for item in plan.untouched:
                console.print(f"  [dim]{item.entry.category}/{item.entry.name}[/dim]")
        if plan.traces:
            console.print(f"\n[bold]Work traces ({len(plan.traces)}):[/bold]")
            for trace in plan.traces:
                console.print(f"  {trace.path} — [dim]{trace.label}[/dim]")

    if not dry_run and not yes:
        if not sys.stdout.isatty():
            message = "Refusing to revoke without a TTY — pass --yes for non-interactive use."
            if output_json:
                emit_json_error(message)
            else:
                console.print_error(message)
            sys.exit(1)
        answer = click.prompt("\nSoll das wirklich entfernt werden? (ja/nein)", default="nein")
        if answer.strip().lower() not in {"ja", "yes"}:
            console.print_warning("Aborted — nothing removed.")
            sys.exit(1)

    result = execute_revoke(plan, manager, dry_run=dry_run)

    if output_json:
        payload = {
            "success": result.success,
            "dry_run": dry_run,
            "removed": result.removed,
            "errors": result.errors,
            "leftovers": result.leftovers,
        }
        emit_json(payload)
        sys.exit(0 if result.success else 1)

    if result.leftovers:
        console.print_error(f"{len(result.leftovers)} artefacts survived the removal:")
        for leftover in result.leftovers:
            console.print(f"  {leftover}")
    for error in result.errors:
        console.print_error(error)

    if result.success:
        verb = "Would remove" if dry_run else "Removed"
        console.print_success(f"{verb} {result.removed} artefacts — sweep clean")
    else:
        sys.exit(1)
```

- [ ] **Step 4: Verify the imports the new code needs are present at module top**

`sccs/cli.py` already imports `sys`, `click`, `Path`, `load_config`, `load_raw_user_data`. Confirm `datetime` is imported (it is used by `deploy_export`):

Run: `grep -n "^from datetime\|^import datetime" sccs/cli.py`
If absent, add `from datetime import datetime` to the import block at the top.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_deploy_cli.py -q`
Expected: PASS (12 tests)

- [ ] **Step 6: Verify the full suite still passes**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Quality gate and commit**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
git add sccs/cli.py tests/test_deploy_cli.py
git commit -m "[ADD] deploy: CLI group list/show/export/install/status/revoke"
```

---

### Task 9: Release — version, lock, documentation

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `sccs/__init__.py:7`
- Modify: `uv.lock` (regenerated)
- Modify: `RELEASE_NOTES.md`
- Modify: `CLAUDE.md` (version line and a bullet in the notes block)
- Test: `tests/test_deploy_schema.py` (version assertion)

- [ ] **Step 1: Bump the version**

```bash
sed -i '' 's/^version = "2.64.0"/version = "2.65.0"/' pyproject.toml
sed -i '' 's/^__version__ = "2.64.0"/__version__ = "2.65.0"/' sccs/__init__.py
grep -n '2\.65\.0' pyproject.toml sccs/__init__.py
```

On Linux use `sed -i` without the `''` argument.

- [ ] **Step 2: Regenerate the lock file**

```bash
uv lock
git diff --stat uv.lock
```

Expected: `uv.lock` shows the new version. A stale lock has broken the image build three times — this step is not optional.

- [ ] **Step 3: Write the release notes**

Prepend to `RELEASE_NOTES.md`, matching the existing entry format:

```markdown
## [2.65.0] - 01.09.2026

### Added
- **Deployment profiles** (`sccs deploy`): named, scenario-scoped bundles for
  foreign hosts. `deploy export odoo-server` builds a ZIP with exactly the
  skills, commands, agents and shell files that one situation needs;
  `deploy install` unpacks it on the target host and writes a receipt;
  `deploy revoke` reads that receipt and removes what we brought.
- Four bundled profiles: `odoo-server`, `odoo-dev-full` (extends
  `odoo-server`), `fastreport`, `shell-only`. Overridable per name via
  `deployment_profiles:` in `config.yaml`.
- Work-trace removal: session transcripts, project memory, plans, todos and
  the prompt history in `~/.claude.json` — trimmed, never deleted, because
  the file also holds the host user's auth state.
- Generated `/sccs-cleanup` command inside every knowledge-bearing bundle, so
  the agent on the customer host has a defined route instead of an
  improvisation with `rm -rf`.

### Changed
- `is_platform_match()` accepts an explicit reference platform, and `Exporter`
  a `target_platform`. Without it a Mac packs `fish_config_macos` into a Linux
  bundle. Default behaviour is unchanged.
- `ExportManifest` gained an optional `deployment` section. Archives from
  `sccs export` keep importing unchanged.
```

- [ ] **Step 4: Update CLAUDE.md**

Change the version line to `**Version**: 2.65.0`, and add as the first bullet of the notes block:

```markdown
- **Deployment profiles** (v2.65.0): `sccs deploy export|install|revoke` (`sccs/deploy/`) ships a scenario-scoped slice of the inventory to a foreign host and takes it back. Four rules. **The receipt is standalone** — absolute targets, `retain` list and sweep globs live in `~/.config/sccs/.deploy_receipt.yaml`, because a customer host has no `config.yaml` of ours and `revoke` must work without one. **`pre_existing` beats everything**: something that was at the target path before we wrote is never removed, the same line as the Codex `foreign_target` guard — while an artefact *we* installed and the customer edited IS removed, flagged as modified, because it still carries our knowledge. **The transcript is the leak, not the skill** — `~/.claude/projects/` quotes skills verbatim, so it goes too; `~/.claude.json` is trimmed of `history` rather than deleted, since it also holds the host user's auth state. And **`revoke` ends with a verification sweep** that exits non-zero on leftovers: a removal reporting success while a skill directory survived is worse than no cleanup at all, because the report is what the decision to stop looking rests on. `claude_memories`/`claude_plans`/`claude_todos` are refused by the schema validator, never silently filtered.
```

- [ ] **Step 5: Add the version assertion**

Append to `tests/test_deploy_schema.py`:

```python
def test_version_is_bumped_for_this_feature():
    from sccs import __version__

    # Tuple comparison, not string: "2.100.0" < "2.65.0" as strings.
    assert tuple(int(p) for p in __version__.split(".")[:3]) >= (2, 65, 0)
```

- [ ] **Step 6: Full quality gate**

```bash
ruff format sccs/ tests/ && ruff check sccs/ tests/ && mypy sccs/ && pytest -q
```

Expected: all green.

- [ ] **Step 7: Verify the CLI end to end by hand**

```bash
sccs deploy list
sccs deploy show odoo-server
sccs deploy export odoo-server -o /tmp/odoo-server.zip --dry-run
```

Expected: `list` shows four profiles; `show odoo-server` resolves without missing dependencies and without missing items. **If `show` reports missing items, the skill names in `defaults.py` are wrong — fix them there, not in the test.**

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml sccs/__init__.py uv.lock RELEASE_NOTES.md CLAUDE.md tests/test_deploy_schema.py
git commit -m "[ADD] deploy: release 2.65.0 — deployment profiles and revocation"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| Naming (`sccs deploy`, `deployment_profiles`) | 1, 8 |
| Profile model, `retain` on the profile | 1 |
| `extends` | 1 |
| Blocked categories, validator raises | 1 |
| Dependency check, `--allow-missing-deps` | 2, 8 |
| Platform targeting | 2 |
| Self-describing bundle (`deployment:` section) | 3 |
| Cleanup command, generated not synced | 3 |
| Receipt, `pre_existing`, modified-but-removed | 4, 5, 7 |
| Home guard on legacy-mode install | 5 |
| Trace enumeration, `~/.claude.json` surgery | 6 |
| Four buckets | 7 |
| Traces purged only with the last install | 7 |
| Confirmation, `--dry-run`, `--yes` | 8 |
| Verification sweep, non-zero exit | 7, 8 |
| `--json` everywhere | 8 |
| Four bundled profiles | 1 |
| Version 2.65.0 + `uv lock` | 9 |

All ten spec test cases appear: round trip (Task 8), `pre_existing` (5, 7), `retain` (7), modified (7), Linux target (2), blocked categories (1), dependency check (2, 8), `~/.claude.json` (6), `shell-only` revoke (1 for the shape, 7 for the empty plan), sweep failure (7).

**Placeholder scan:** none. Every code step carries the actual code; every test step the actual test.

**Type consistency:** `ResolvedProfile.selections` is `list[ExportSelection]` in Tasks 2, 3 and 8. `ReceiptEntry`/`InstallRecord` field names match across Tasks 4, 5, 7 and 8. `build_revoke_plan`/`execute_revoke`/`sweep` signatures match between Task 7 and Task 8. `Exporter.export_to_zip`'s new `deployment` keyword matches between Task 3's exporter change and `build_bundle`.

**One deviation from the spec, recorded here:** the cleanup command is named `sccs-cleanup.md` (`/sccs-cleanup`), not `/aufräumen` — ASCII filename on a foreign filesystem, and the name says which tool owns it. The prompt text inside is German.
