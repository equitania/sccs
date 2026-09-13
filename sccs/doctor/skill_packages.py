# SCCS Doctor — skill packages installed through the `skills` CLI
#
# `npx skills add <owner>/<repo>` (vercel-labs/skills) fetches a whole bundle
# of SKILL.md folders from GitHub. HyperFrames (heygen-com/hyperframes) is the
# first one we manage: 20 skills, most of them WITHOUT a common prefix
# (`figma`, `slideshow`, `general-video`, …). That rules out the `gsd-*` trick
# of one glob for sync exclusion and profile parking.
#
# Design rules:
#   1. The `skills` CLI's own lock file (~/.agents/.skill-lock.json) is the
#      source of truth for which skill belongs to which package — every entry
#      records its `source`. A bundled name list is only the fallback for a
#      host without a lock, and only for a package the user opted into, so a
#      private skill that happens to be called `figma` is never excluded on a
#      machine where HyperFrames is not installed at all.
#   2. Install and update are the SAME command: `skills add … --copy` replaces
#      every skill directory wholesale and refreshes the lock (verified against
#      skills 1.x — leftovers and local edits are gone afterwards). `--copy`
#      matters: the CLI symlinks by default, and a symlink in ~/.claude/skills
#      is skipped by the sync scan and would move only the link when parked.
#   3. Opt-in via `doctor.skill_packages`. Nothing is checked by default.
#   4. There is no cheap upstream version query (the lock stores a folder hash,
#      not a release), so `doctor check` shows the lock date and `doctor update`
#      refreshes unconditionally — no invented "update available" signal.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    # installer.py imports this module; the action builders import
    # DoctorAction at call time to keep the import graph acyclic.
    from sccs.doctor.installer import DoctorAction

DEFAULT_SKILLS_LOCK = "~/.agents/.skill-lock.json"

_SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SkillPackageSpec(BaseModel):
    """A bundle of skills installed with `npx skills add <source>`."""

    name: str = Field(description="Package key used in doctor.skill_packages and profiles (e.g. 'hyperframes').")
    source: str = Field(description="GitHub `owner/repo` passed to `skills add` and matched against the lock file.")
    agent: str = Field(default="claude-code", description="`skills add --agent` value.")
    target_dir: str = Field(default="~/.claude/skills", description="Where the agent's skill copies land.")
    lock_file: str = Field(default=DEFAULT_SKILLS_LOCK, description="The `skills` CLI lock file.")
    known_skills: list[str] = Field(
        default_factory=list,
        description=(
            "Skill names the package shipped when this spec was written. Fallback only — "
            "used when the lock file is missing or lists nothing for `source`."
        ),
    )

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        if not _SOURCE_RE.match(v):
            raise ValueError(f"source must be a GitHub 'owner/repo', got {v!r}")
        return v

    @field_validator("agent")
    @classmethod
    def _validate_agent(cls, v: str) -> str:
        if not _SKILL_NAME_RE.match(v):
            raise ValueError(f"agent contains invalid characters: {v!r}")
        return v

    @field_validator("known_skills")
    @classmethod
    def _validate_known_skills(cls, v: list[str]) -> list[str]:
        for name in v:
            if not _SKILL_NAME_RE.match(name):
                raise ValueError(f"skill name contains invalid characters: {name!r}")
        return v

    def invocation(self) -> list[str]:
        """argv for install AND update (see design rule 2)."""
        return [
            "npx",
            "-y",
            "skills",
            "add",
            self.source,
            "--global",
            "--agent",
            self.agent,
            "--skill",
            "*",
            "--yes",
            "--copy",
        ]


# Opt-in only: enabled by listing the key in `doctor.skill_packages`.
BUILTIN_SKILL_PACKAGES: dict[str, SkillPackageSpec] = {
    "hyperframes": SkillPackageSpec(
        name="hyperframes",
        source="heygen-com/hyperframes",
        known_skills=[
            "embedded-captions",
            "faceless-explainer",
            "figma",
            "general-video",
            "hyperframes",
            "hyperframes-animation",
            "hyperframes-audio",
            "hyperframes-cli",
            "hyperframes-core",
            "hyperframes-creative",
            "hyperframes-keyframes",
            "hyperframes-registry",
            "media-use",
            "motion-graphics",
            "music-to-video",
            "pr-to-video",
            "product-launch-video",
            "remotion-to-hyperframes",
            "slideshow",
            "talking-head-recut",
        ],
    ),
}


def _lock_entries(spec: SkillPackageSpec) -> dict[str, dict] | None:
    """Lock entries whose `source` is this package, or None without a usable lock.

    An unreadable or malformed lock is treated like a missing one: the doctor
    must degrade to the fallback list, never crash on a third-party file.
    """
    path = Path(spec.lock_file).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    skills = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(skills, dict):
        return None
    wanted = spec.source.lower()
    return {
        name: entry
        for name, entry in skills.items()
        if isinstance(entry, dict)
        and str(entry.get("source", "")).lower() == wanted
        and isinstance(name, str)
        and _SKILL_NAME_RE.match(name)
    }


def lock_skill_names(spec: SkillPackageSpec) -> list[str]:
    """Names the lock attributes to this package — [] when there is no lock."""
    return sorted(_lock_entries(spec) or {})


def package_skill_names(spec: SkillPackageSpec) -> list[str]:
    """Lock-derived names, falling back to `known_skills` (design rule 1)."""
    return lock_skill_names(spec) or sorted(spec.known_skills)


def resolve_skill_packages(names: list[str], extra: list[SkillPackageSpec] | None = None) -> list[SkillPackageSpec]:
    """Built-in names (unknown ones ignored, like cli_tools) plus fully specified extras."""
    resolved = [BUILTIN_SKILL_PACKAGES[n] for n in names if n in BUILTIN_SKILL_PACKAGES]
    return resolved + list(extra or [])


def managed_skill_names(enabled: list[SkillPackageSpec]) -> set[str]:
    """Sync-exclude names for every known package.

    Lock-derived names count for ALL built-in and enabled packages — whatever
    `skills add` wrote is reproducible from upstream regardless of opt-in. The
    fallback list only counts for enabled packages (design rule 1).
    """
    names: set[str] = set()
    enabled_by_name = {s.name: s for s in enabled}
    for spec in {**BUILTIN_SKILL_PACKAGES, **enabled_by_name}.values():
        names.update(lock_skill_names(spec))
    for spec in enabled:
        if not lock_skill_names(spec):
            names.update(spec.known_skills)
    return names


@dataclass
class SkillPackageStatus:
    """Result of inspecting one skill package."""

    spec: SkillPackageSpec
    # state values:
    #   "ok"       — every expected skill is a real directory with a loadable SKILL.md
    #   "missing"  — none of the expected skills is present for the agent
    #   "partial"  — some are missing, or present only as a symlink
    #   "invalid"  — all present, but at least one SKILL.md will not load
    state: str
    expected: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    symlinked: list[str] = field(default_factory=list)
    invalid: dict[str, list[str]] = field(default_factory=dict)
    lock_found: bool = False
    updated_at: str | None = None

    @property
    def needs_install(self) -> bool:
        return self.state in ("missing", "partial")


class SkillPackageDetector:
    """Compare a package's lock entries against the agent's skill directory."""

    def get_statuses(self, specs: list[SkillPackageSpec]) -> list[SkillPackageStatus]:
        from sccs.integrations.skill_limits import check_skill_file

        out: list[SkillPackageStatus] = []
        for spec in specs:
            entries = _lock_entries(spec) or {}
            expected = sorted(entries) or sorted(spec.known_skills)
            root = Path(spec.target_dir).expanduser()
            missing: list[str] = []
            symlinked: list[str] = []
            invalid: dict[str, list[str]] = {}
            for name in expected:
                path = root / name
                if path.is_symlink():
                    symlinked.append(name)
                    continue
                skill_md = path / "SKILL.md"
                if not skill_md.is_file():
                    missing.append(name)
                    continue
                problems = check_skill_file(skill_md)
                if problems:
                    invalid[name] = problems

            if expected and len(missing) == len(expected):
                state = "missing"
            elif missing or symlinked:
                state = "partial"
            elif invalid:
                state = "invalid"
            else:
                state = "ok"

            stamps = [str(e.get("updatedAt")) for e in entries.values() if e.get("updatedAt")]
            out.append(
                SkillPackageStatus(
                    spec=spec,
                    state=state,
                    expected=expected,
                    missing=missing,
                    symlinked=symlinked,
                    invalid=invalid,
                    lock_found=bool(entries),
                    updated_at=max(stamps)[:10] if stamps else None,
                )
            )
        return out


def skill_package_install_actions(
    statuses: list[SkillPackageStatus] | None,
    *,
    install_deps: tuple[str, ...] = (),
) -> list[DoctorAction]:
    """Install a package whose skills are missing or only symlinked."""
    from sccs.doctor.installer import DoctorAction

    actions: list[DoctorAction] = []
    for st in statuses or []:
        if not st.needs_install:
            continue
        actions.append(
            DoctorAction(
                label=f"install skill package {st.spec.name} ({st.spec.source})",
                cmd=st.spec.invocation(),
                runnable=True,
                component=f"skill-package:{st.spec.name}",
                depends_on_components=install_deps,
                auto_confirm=True,  # same trust level as the GSD npx install
            )
        )
    return actions


def skill_package_update_actions(
    statuses: list[SkillPackageStatus] | None,
    *,
    install_deps: tuple[str, ...] = (),
) -> list[DoctorAction]:
    """Refresh every enabled package — install and update are one command."""
    from sccs.doctor.installer import DoctorAction

    actions: list[DoctorAction] = []
    for st in statuses or []:
        verb = "install" if st.needs_install else "refresh"
        actions.append(
            DoctorAction(
                label=f"{verb} skill package {st.spec.name} ({st.spec.source})",
                cmd=st.spec.invocation(),
                runnable=True,
                component=f"skill-package:{st.spec.name}",
                depends_on_components=install_deps,
                auto_confirm=True,
            )
        )
    return actions
