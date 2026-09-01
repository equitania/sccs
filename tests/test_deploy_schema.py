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

    config = SccsConfig.model_validate({"repository": {"path": "~/gitbase/sccs-sync"}, "sync_categories": {}})
    assert config.deployment_profiles == {}


def test_version_is_bumped_for_this_feature():
    from sccs import __version__

    # Tuple comparison, not string: "2.100.0" < "2.65.0" as strings.
    assert tuple(int(p) for p in __version__.split(".")[:3]) >= (2, 65, 0)
