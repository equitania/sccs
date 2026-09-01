"""Profile resolution: selection building, target platform, dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.config.schema import SccsConfig
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
    deps = read_skill_dependencies(home / ".claude" / "skills", ["odoo-merge-to", "odoo-common"])
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
