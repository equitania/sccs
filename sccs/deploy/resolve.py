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
from sccs.transfer.exporter import Exporter, ExportSelection
from sccs.utils.logging import get_logger
from sccs.utils.paths import matches_any_pattern

logger = get_logger("sccs.deploy")

# Matches the documented convention in ~/.claude/skills/*/SKILL.md, e.g.
#   **INHERITS FROM:** odoo-common (UV package manager), uv-python-tools (...)
#   INHERITS FROM: odoo-common. NOT for: ...
#
# Case-sensitive on purpose: the convention is always the literal uppercase
# marker "INHERITS FROM". Matching case-insensitively also caught ordinary
# prose against the real skill corpus — "This skill inherits from: nothing
# (elementary/standalone)" in uv-python-tools, "Inherits from
# eq_fr_core_base.frx" describing FastReport template inheritance in
# fr-reports — and reported both as missing dependencies.
_INHERITS_RE = re.compile(r"INHERITS FROM:?\**\s*(?P<rest>.+)")
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
    # The platform this resolution actually used — the profile's own, unless
    # `--platform` overrode it. The bundle's manifest must stamp THIS, not
    # `profile.target_platform`: the ZIP contents already follow the override,
    # and a manifest that says "linux" over a macOS payload is a lie the
    # install host cannot detect.
    target_platform: str = ""

    def __post_init__(self) -> None:
        if not self.target_platform:
            self.target_platform = self.profile.target_platform

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

    resolved = ResolvedProfile(name=name, profile=profile, target_platform=platform)
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
