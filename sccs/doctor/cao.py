# SCCS Doctor — CAO provider patches
#
# CAO (AWS Labs CLI Agent Orchestrator) resolves providers through a
# hard-coded if/elif chain fed by an enum, not through a plugin point: its
# plugin system is observer-only and cannot register a provider. Adding one
# therefore means editing the *installed* package — and any `cao update`,
# `uv tool upgrade` or reinstall replaces that package and silently removes
# the provider again.
#
# That is the whole reason this module exists. Keeping the provider source in
# a repository transports the file; it does not keep CAO working. `sccs doctor
# check` reports a wiped provider, `sccs doctor install` puts it back.
#
# What lives where, deliberately:
#   * the mechanism (find, verify, patch)  → here, in the published package
#   * the provider source itself           → the private sync repo, materialised
#                                            at ~/.config/cao/provider
# SCCS publishes to PyPI and GitHub; which agent CLIs a fleet routes work
# across is not something this package carries.

from __future__ import annotations

import logging
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sccs.doctor.schema import CaoProviderSpec
from sccs.utils.paths import atomic_write, expand_path

logger = logging.getLogger(__name__)

# uv installs a tool as <root>/lib/python3.X/site-packages/<pkg>. Globbing the
# python version keeps the lookup working across a `uv tool upgrade` that moves
# the install between interpreter versions — the trap a hardcoded path walks into.
_PACKAGE_NAME = "cli_agent_orchestrator"
_SITE_PACKAGES_GLOB = f"lib/python3.*/site-packages/{_PACKAGE_NAME}"
_UV_TOOL_SUBDIR = Path("share/uv/tools/cli-agent-orchestrator")

_UNSET: Any = object()


def _default_roots() -> list[Path]:
    return [Path.home() / ".local" / _UV_TOOL_SUBDIR]


def find_cao_package(
    roots: list[Path] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """Locate the installed `cli_agent_orchestrator` package directory.

    Resolution order: the roots derived from a `cao` binary on PATH (a uv tool
    shim at ~/.local/bin/cao points at ~/.local/share/uv/tools/…), then the
    default home location. Returns None when CAO is not installed — the normal
    case on most hosts, and never an error.
    """
    candidates: list[Path] = []
    if roots is not None:
        candidates.extend(roots)
    else:
        binary = which("cao")
        if binary:
            raw = Path(binary)
            # Two readings, because `which` can hand back either end of the
            # uv shim and only one of them is right in each case:
            #   shim  ~/.local/bin/cao          → ~/.local + share/uv/tools/<tool>
            #   real  <tool>/bin/cao            → <tool> already, appending again
            #                                     would look under <tool>/share/…
            # Resolving only the second is not enough: the shim IS a symlink,
            # so a lone resolve() silently turns the first case into the second.
            candidates.append(raw.parent.parent / _UV_TOOL_SUBDIR)
            candidates.append(raw.resolve().parent.parent)
        candidates.extend(_default_roots())

    for root in candidates:
        for hit in sorted(root.glob(_SITE_PACKAGES_GLOB)):
            if (hit / "__init__.py").is_file():
                return hit
    return None


@dataclass
class CaoProviderStatus:
    """Result of checking one provider against the installed package.

    States:
      patched      every site carries its marker and the provider file matches
      missing      nothing is patched (the state right after a `cao update`)
      partial      some sites patched, or the copied provider is outdated
      anchor_lost  CAO's layout changed — refuse and report, never guess
    """

    spec: CaoProviderSpec
    state: str
    package_path: Path | None = None
    pending: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    binary_on_path: bool = True


class CaoDetector:
    """Detect whether the extra providers are present in the installed CAO.

    A row appears only when BOTH the package and the provider source exist.
    That is the opt-in: someone who never synced the private provider repo has
    not asked for this and must not be advertised at, and someone without CAO
    has nothing to patch.
    """

    def __init__(
        self,
        package_path: Path | None = _UNSET,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._which = which
        self._package = find_cao_package(which=which) if package_path is _UNSET else package_path

    @property
    def package_path(self) -> Path | None:
        return self._package

    def get_statuses(self, specs: list[CaoProviderSpec]) -> list[CaoProviderStatus]:
        if self._package is None:
            return []

        out: list[CaoProviderStatus] = []
        for spec in specs:
            source = _source_path(spec)
            if not source.is_file():
                continue  # source not synced here → not opted in → no row

            pending: list[str] = []
            problems: list[str] = []

            # The provider module itself, first — so a lone stale copy reads as
            # exactly that in the report.
            dest = self._package / spec.package_subpath
            if not _same_content(source, dest):
                pending.append(spec.package_subpath)

            for site in spec.sites:
                target = self._package / site.rel_path
                if not target.exists():
                    problems.append(f"{site.rel_path}: file not found in the installed package")
                    continue
                try:
                    text = target.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    problems.append(f"{site.rel_path}: unreadable ({exc})")
                    continue
                if site.marker in text:
                    continue
                if site.anchor not in text:
                    problems.append(f"{site.rel_path}: anchor not found — CAO's layout changed")
                    continue
                pending.append(site.rel_path)

            total = 1 + len(spec.sites)
            if problems:
                state = "anchor_lost"
            elif not pending:
                state = "patched"
            elif len(pending) == total:
                state = "missing"
            else:
                state = "partial"

            out.append(
                CaoProviderStatus(
                    spec=spec,
                    state=state,
                    package_path=self._package,
                    pending=pending,
                    problems=problems,
                    binary_on_path=self._which(spec.binary) is not None,
                )
            )
        return out


def _source_path(spec: CaoProviderSpec) -> Path:
    return expand_path(spec.source_dir) / spec.source_file


def _same_content(source: Path, dest: Path) -> bool:
    if not dest.is_file():
        return False
    try:
        return source.read_bytes() == dest.read_bytes()
    except OSError:
        return False


def _verified_target(package: Path, rel_path: str, *, must_exist: bool) -> Path:
    """Resolve `rel_path` inside `package`, refusing anything that leaves it.

    The schema already rejects absolute paths and '..' segments at parse time;
    this is the second half of the guard, against what the *filesystem* can do
    — a symlink planted in the package would otherwise redirect the write.
    """
    target = package / rel_path
    if target.is_symlink():
        raise RuntimeError(f"{rel_path}: refusing to patch a symlink inside the CAO package")
    if must_exist and not target.exists():
        raise RuntimeError(f"{rel_path}: file not found in the installed package")

    root = package.resolve()
    resolved = target.resolve() if target.exists() else (root / rel_path)
    if root not in resolved.parents:
        raise RuntimeError(f"{rel_path}: resolves outside the CAO package ({resolved})")
    return target


def apply_provider_patch(spec: CaoProviderSpec, package: Path) -> list[str]:
    """Patch `spec` into the installed CAO package. Returns what changed.

    Verification runs to completion BEFORE the first write: a half-patched
    package is worse than an unpatched one, because it still imports but fails
    at launch. Idempotent — a site whose marker is present is skipped, so a
    re-run after `cao update` restores exactly what was lost.

    Raises RuntimeError when the source is absent or a site cannot be located;
    nothing is written in that case.
    """
    source = _source_path(spec)
    if not source.is_file():
        raise RuntimeError(f"provider source not found: {source} — run `sccs sync --category cao_provider`")

    # Accumulate per file, not per site: providers/manager.py carries two
    # sites (the import and the instantiation branch). Deriving both from the
    # same on-disk text and writing them in turn makes the second write
    # discard the first — a package that imports but never launches a worker.
    edits: dict[Path, str] = {}
    order: list[Path] = []
    changed: list[str] = []

    dest = _verified_target(package, spec.package_subpath, must_exist=False)
    copy_provider = not _same_content(source, dest)

    for site in spec.sites:
        target = _verified_target(package, site.rel_path, must_exist=True)
        text = edits.get(target)
        if text is None:
            text = target.read_text(encoding="utf-8")
        if site.marker in text:
            continue
        if site.anchor not in text:
            raise RuntimeError(
                f"{site.rel_path}: anchor not found — CAO's layout changed, "
                f"the patch definition for '{spec.name}' needs updating"
            )
        edits[target] = text.replace(site.anchor, site.anchor + site.insertion, 1)
        if target not in order:
            order.append(target)
        changed.append(site.rel_path)

    # ---- writes below this line ------------------------------------------
    if copy_provider:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        changed.insert(0, spec.package_subpath)

    for target in order:
        atomic_write(target, edits[target], mode=_current_mode(target))

    if changed:
        logger.info("Patched CAO provider '%s': %s", spec.name, ", ".join(changed))
    return changed


def _current_mode(path: Path) -> int | None:
    """Preserve the file's permissions across the atomic replace.

    atomic_write renames a mkstemp file into place, which would otherwise leave
    an importable module at 0600 — unreadable for any other user of a shared
    install.
    """
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None
