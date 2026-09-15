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

The config schema (`MirrorRepoSpec`, `MirrorConfig`, `_VERSION_PATTERN`,
`_REPO_URL_PATTERN`) lives in `sccs/doctor/schema.py`, not here: this module
needs `_validate_safe_name` from `schema.py`, so `schema.py` cannot import
from here without a cycle. The names are re-exported below so
`from sccs.doctor.mirror import ...` keeps working.
"""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from sccs.doctor.runner import (
    run_brew_bundle_dump,
    run_brew_lines,
    run_fisher_list,
    run_git_fetch,
    run_git_status_branch,
    run_npm_global_list,
    run_uv_tool_list,
)
from sccs.doctor.schema import (  # noqa: F401 — re-exported
    _REPO_URL_PATTERN,
    _VERSION_PATTERN,
    MirrorConfig,
    MirrorRepoSpec,
    _validate_safe_name,
)
from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write, expand_path

if TYPE_CHECKING:
    from sccs.doctor.installer import DoctorAction

__all__ = [
    "MirrorConfig",
    "MirrorRepoSpec",
    "MirrorRole",
    "_VERSION_PATTERN",
    "normalize_host",
    "current_hostname",
    "resolve_role",
    "PackageRef",
    "Inventory",
    "parse_uv_tool_list",
    "parse_npm_global_json",
    "load_inventory",
    "write_inventory",
    "capture_inventory",
    "NPM_ALWAYS_IGNORED",
    "UV_NEVER_REMOVED",
    "BrewSet",
    "parse_brewfile",
    "BrewStatus",
    "BrewDetector",
    "VersionDiff",
    "PackageAreaStatus",
    "compare_packages",
    "PackageDetector",
    "RepoStatus",
    "parse_git_status_branch",
    "RepoDetector",
    "FisherStatus",
    "FisherDetector",
    "MirrorReport",
    "collect_mirror_report",
    "mirror_install_actions",
    "mirror_update_actions",
    "mirror_remove_actions",
    "mirror_extras_summary_action",
]

logger = get_logger("sccs.doctor.mirror")

# --- roles ------------------------------------------------------------------

MirrorRole = Literal["source", "mirror", "off"]


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


# --- inventory ---------------------------------------------------------------

NPM_ALWAYS_IGNORED = frozenset({"npm", "corepack"})
UV_NEVER_REMOVED = frozenset({"sccs"})

_INVENTORY_HEADER = "# Written by `sccs doctor update` on the source host — do not edit by hand.\n"
_UV_LINE = re.compile(r"^(?P<name>[A-Za-z0-9_.\-]+) v(?P<version>\S+)(?P<rest>(?: \[[^\]]*\])*)$")
_UV_BRACKET = re.compile(r"\[([^\]]*)\]")
_PYTHON_PATTERN = re.compile(r"^\d+\.\d+$")
# git+https://host/path or git+ssh://git@host/path — what `uv tool list
# --show-version-specifiers` prints for a tool installed from git.
_GIT_URL_PATTERN = re.compile(r"^git\+(?:https|ssh)://[A-Za-z0-9._@\-]+(?::\d+)?/[A-Za-z0-9_][A-Za-z0-9_./@\-]*$")
PACKAGE_SOURCES = ("registry", "local", "git")


class PackageRef(BaseModel):
    name: str
    version: str
    # "registry" (an index such as PyPI), "git" (git_url is set) or "local"
    # (a checkout or wheel on the source host — a mirror cannot fetch it).
    source: str = "registry"
    python: str | None = None  # major.minor the tool runs on, e.g. "3.13"
    extras: list[str] = Field(default_factory=list)
    git_url: str | None = None

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        if v not in PACKAGE_SOURCES:
            raise ValueError(f"source must be one of {PACKAGE_SOURCES}: {v!r}")
        return v

    @field_validator("python")
    @classmethod
    def _validate_python(cls, v: str | None) -> str | None:
        if v is not None and not _PYTHON_PATTERN.match(v):
            raise ValueError(f"python must be major.minor: {v!r}")
        return v

    @field_validator("extras")
    @classmethod
    def _validate_extras(cls, v: list[str]) -> list[str]:
        return [_validate_safe_name(e, "extra") for e in v]

    @field_validator("git_url")
    @classmethod
    def _validate_git_url(cls, v: str | None) -> str | None:
        if v is not None and not _GIT_URL_PATTERN.match(v):
            raise ValueError(f"git_url must be git+https://… or git+ssh://…: {v!r}")
        return v

    @property
    def spec(self) -> str:
        """The requirement `uv tool install` gets: `name[extras]==version`, or
        `name @ git+url` for a git source."""
        if self.source == "git" and self.git_url:
            return f"{self.name} @ {self.git_url}"
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        return f"{self.name}{extras}=={self.version}"

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
    """`uv tool list --show-python --show-extras --show-version-specifiers`
    prints `name vX.Y.Z [required: …] [extras: a, b] [CPython 3.13.12]`
    followed by `- entrypoint` lines. `required: file://…` is a local
    checkout or wheel, `required: git+…` a git source; anything else (or no
    bracket) came from an index. The plain `name vX.Y.Z` form still parses."""
    out: list[PackageRef] = []
    for line in text.splitlines():
        m = _UV_LINE.match(line.strip())
        if not m:
            continue
        fields: dict[str, object] = {"name": m.group("name"), "version": m.group("version")}
        for bracket in _UV_BRACKET.findall(m.group("rest") or ""):
            key, _, value = bracket.partition(":")
            key, value = key.strip(), value.strip()
            if key == "required":
                if value.startswith("file://"):
                    fields["source"] = "local"
                elif value.startswith("git+"):
                    fields["source"] = "git"
                    fields["git_url"] = value
            elif key == "extras":
                fields["extras"] = [e.strip() for e in value.split(",") if e.strip()]
            elif bracket.startswith(("CPython", "PyPy")):
                parts = bracket.split()[-1].split(".")
                if len(parts) >= 2:
                    fields["python"] = f"{parts[0]}.{parts[1]}"
        try:
            out.append(PackageRef.model_validate(fields))
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


def _capture_area(
    area: str,
    text: str | None,
    parse: Callable[[str], list[PackageRef]],
    previous: list[PackageRef] | None,
) -> list[PackageRef]:
    """A wrapper returning `None` means the tool is absent OR a run failed —
    both must fall back to the previous inventory's entries for that area,
    never to an empty list: an empty list is persisted and then reads as
    "every installed package is an extra" on every mirror."""
    if text is not None:
        return parse(text)
    if previous is not None:
        logger.warning(
            "mirror: %s unavailable while capturing — keeping the previous inventory's %d entries",
            area,
            len(previous),
        )
        return list(previous)
    logger.warning("mirror: %s unavailable while capturing — no previous inventory, recording an empty list", area)
    return []


def capture_inventory(hostname: str, previous: Inventory | None = None) -> Inventory:
    return Inventory(
        captured_at=datetime.now().replace(microsecond=0).isoformat(),
        captured_on=normalize_host(hostname),
        uv_tools=_capture_area("uv", run_uv_tool_list(), parse_uv_tool_list, previous.uv_tools if previous else None),
        npm_globals=_capture_area(
            "npm", run_npm_global_list(), parse_npm_global_json, previous.npm_globals if previous else None
        ),
    )


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
    counts as present). Extra = a *leaf installed on request*
    (`brew leaves --installed-on-request`, the same set `brew bundle dump`
    writes) not in the Brewfile — never a dependency, so nothing pulled in by
    a wanted package is ever offered for removal."""

    def get_status(self, brewfile: Path, ignore: list[str]) -> BrewStatus:
        if not brewfile.is_file():
            return BrewStatus(state="no_brewfile")
        wanted = parse_brewfile(brewfile.read_text(encoding="utf-8"))
        # `--installed-on-request` is what `brew bundle dump` writes: a build
        # dependency that ends up a leaf (rust after `brew install beam`) is
        # neither in the Brewfile nor wanted, and must not read as an extra.
        leaves = run_brew_lines("leaves", "--installed-on-request")
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


# --- packages (uv tools, npm globals) ----------------------------------------


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
    # Wanted but built on the source from a local checkout or wheel: no
    # registry can serve it, so it is reported (yellow) and never actioned.
    manual: list[PackageRef] = field(default_factory=list)


def compare_packages(
    area: str,
    wanted: list[PackageRef],
    installed: list[PackageRef],
    ignore: list[str],
) -> PackageAreaStatus:
    skip = set(ignore)
    want = {p.name: p for p in wanted if p.name not in skip}
    have = {p.name: p for p in installed if p.name not in skip}
    automatic = {n for n, p in want.items() if p.source != "local"}
    st = PackageAreaStatus(
        area=area,
        state="ok",
        missing=[want[n] for n in sorted((set(want) - set(have)) & automatic)],
        extra=sorted(set(have) - set(want)),
        version_differs=[
            VersionDiff(name=n, have=have[n].version, want=want[n].version)
            for n in sorted(set(want) & set(have) & automatic)
            if have[n].version != want[n].version
        ],
        manual=[want[n] for n in sorted(set(want) - automatic) if n not in have or have[n].version != want[n].version],
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
    # "ok" | "missing" | "behind" | "modified" | "not_a_repo"
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
        if any(r.state in {"missing", "behind"} for r in self.repos):
            return True
        return bool(self.fisher is not None and self.fisher.missing)

    @property
    def has_extras(self) -> bool:
        if self.brew is not None and self.brew.extra_count:
            return True
        if any(area is not None and area.extra for area in (self.uv, self.npm)):
            return True
        return bool(self.fisher is not None and self.fisher.extra)


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


# --- actions ----------------------------------------------------------------
#
# Two rules, both enforced here and pinned by tests:
#   - the source never receives install/remove actions (it IS the truth);
#   - a mirror never writes the inventory (only the source captures).


def _safe(name: str, field_name: str) -> str | None:
    try:
        return _validate_safe_name(name, field_name)
    except ValueError as exc:
        logger.warning("mirror: skipping %s — %s", field_name, exc)
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
                timeout=1800,
            )
        )

    for area in (report.uv, report.npm):
        if area is None:
            continue
        wanted = list(area.missing) + [PackageRef(name=d.name, version=d.want) for d in area.version_differs]
        for pkg in wanted:
            name = _safe(pkg.name, f"{area.area} package")
            if name is None:
                continue
            if not _VERSION_PATTERN.match(pkg.version):
                logger.warning("mirror: skipping %s %s — invalid version %r", area.area, name, pkg.version)
                continue
            if area.area == "uv":
                cmd = ["uv", "tool", "install", pkg.spec]
                if pkg.python:
                    cmd += ["--python", pkg.python]
                cmd.append("--reinstall")
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
            actions.append(
                DoctorAction(label=f"clone {repo.spec.url} → {path}", cmd=cmd, component=component, timeout=900)
            )
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

    if report.fisher is not None:
        for name in report.fisher.missing:
            n = _safe(name, "fisher plugin")
            if n is None:
                continue
            actions.append(
                DoctorAction(
                    label=f"fisher install {n}",
                    cmd=["fish", "-c", f"fisher install {n}"],
                    component=f"mirror:fisher:{n}",
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
        previous = load_inventory(inventory_path)
        write_inventory(inventory_path, capture_inventory(hostname, previous))

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
                add(f"brew formula {n}", ["brew", "uninstall", n], f"mirror:brew:formula:{n}")
        for name in report.brew.extra_casks:
            if (n := _safe(name, "cask")) is not None:
                add(f"brew cask {n}", ["brew", "uninstall", "--cask", n], f"mirror:brew:cask:{n}")
        for name in report.brew.extra_taps:
            if (n := _safe(name, "tap")) is not None:
                add(f"brew tap {n}", ["brew", "untap", n], f"mirror:brew:tap:{n}")
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
    if report.fisher is not None:
        for name in report.fisher.extra:
            if (n := _safe(name, "fisher plugin")) is not None:
                add(f"fisher plugin {n}", ["fish", "-c", f"fisher remove {n}"], f"mirror:fisher:{n}")
    return actions


def mirror_extras_summary_action(report: MirrorReport | None) -> list[DoctorAction]:
    """Non-strict `optimize` warning: one print-only action naming the extras,
    gated the same way `mirror_remove_actions` is (mirror role, cleanup on) so
    the summary never appears for a report that could not act on the extras
    anyway."""
    from sccs.doctor.installer import DoctorAction

    if report is None or report.role != "mirror" or not report.cleanup or not report.has_extras:
        return []
    return [
        DoctorAction(
            label="mirror has software the source does not — review needed",
            cmd=[],
            runnable=False,
            manual_block="# Re-run with `--strict` to queue one confirm-gated removal per extra.",
            component="mirror:extras:summary",
        )
    ]
