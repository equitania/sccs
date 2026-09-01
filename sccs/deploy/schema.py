# Deployment profile model, validation and `extends` flattening.

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

# Categories that hold project memory from other engagements. A typo must
# not carry one customer's context onto another customer's server, so this
# raises rather than filtering silently.
BLOCKED_CATEGORIES: frozenset[str] = frozenset({"claude_memories", "claude_plans", "claude_todos"})

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
            raise ValueError(f"target_platform '{self.target_platform}' is not one of {sorted(VALID_PLATFORMS)}")
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
                raise DeploymentProfileError(f"Profile '{name}' retains '{category}' but does not install it")
    return flattened
