# Shared config adoption (v2.70.0).
#
# config.yaml reaches other hosts only through a category that syncs
# ~/.config/sccs — and a host bootstrapped with `sccs config init` has no
# such category until it has the shared config. Chicken and egg: it never
# receives the plugins, skill packages or corrected category definitions the
# other hosts carry, and nothing says so. Found on a Linux host on 11.10.2026
# whose `doctor check` showed only the bundled plugins.
#
# `doctor check` reports the gap (yellow — the host works, it just runs its
# own config); `doctor install` / `optimize` adopt the shared copy after a
# prompt that `--yes` does not skip, because it replaces the whole file.

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml

from sccs.doctor.runner import DoctorError
from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write, expand_path

if TYPE_CHECKING:
    from sccs.doctor.installer import DoctorAction

logger = get_logger("sccs.doctor.shared_config")

SharedConfigState = Literal["adopted", "not_adopted", "no_repo_copy"]


@dataclass
class SharedConfigStatus:
    state: SharedConfigState
    local_path: Path
    repo_path: Path
    repo_copy: Path

    @property
    def detail(self) -> str:
        if self.state == "adopted":
            return "synced through this host's config"
        if self.state == "not_adopted":
            return f"shared config.yaml in repo — not adopted on this host ({self.repo_copy})"
        return "no shared config.yaml in the repo yet"


def _shared_copy_relpath() -> Path:
    from sccs.config.defaults import DEFAULT_CONFIG

    return Path(DEFAULT_CONFIG["sync_categories"]["sccs_config"]["repo_path"]) / "config.yaml"


def _syncs_config_dir(categories: dict, config_dir: Path) -> bool:
    """True when some enabled category already carries ~/.config/sccs.

    Matched by `local_path`, not by name: the category predates the bundled
    default and a user may have called it anything.
    """
    for cat in categories.values():
        if not isinstance(cat, dict) or not cat.get("enabled", True):
            continue
        local = cat.get("local_path")
        if isinstance(local, str) and expand_path(local).resolve() == config_dir.resolve():
            return True
    return False


def detect_shared_config(config_path: Path) -> SharedConfigStatus | None:
    """Status of the shared config for this host, or None without a local config."""
    if not config_path.is_file():
        return None
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("shared config: cannot read %s — %s", config_path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    from sccs.config.loader import read_local_repo_path

    repo_raw = read_local_repo_path(config_path) or (raw.get("repository") or {}).get("path")
    if not isinstance(repo_raw, str):
        return None
    repo_path = expand_path(repo_raw)
    repo_copy = repo_path / _shared_copy_relpath()

    categories = raw.get("sync_categories") or {}
    if isinstance(categories, dict) and _syncs_config_dir(categories, config_path.parent):
        state: SharedConfigState = "adopted"
    elif repo_copy.is_file():
        state = "not_adopted"
    else:
        state = "no_repo_copy"
    return SharedConfigStatus(state=state, local_path=config_path, repo_path=repo_path, repo_copy=repo_copy)


def _repo_path_differs(shared_text: str, repo_path: Path) -> bool:
    """True when the shared config names a repo location other than this host's.

    An unreadable shared copy counts as differing — pinning the path that
    demonstrably works here is the safe side; load_config rejects the copy
    a moment later anyway.
    """
    try:
        raw = yaml.safe_load(shared_text) or {}
    except yaml.YAMLError:
        return True
    shared = (raw.get("repository") or {}).get("path") if isinstance(raw, dict) else None
    if not isinstance(shared, str):
        return True
    return expand_path(shared).resolve() != repo_path.resolve()


def _git_pull(repo_path: Path) -> bool:
    from sccs.git.operations import pull

    return pull(repo_path)


def adopt_shared_config(
    status: SharedConfigStatus,
    *,
    pull_fn: Callable[[Path], bool] | None = None,
) -> None:
    """Replace the local config with the shared copy — backed up, validated, rolled back on failure.

    The repo path is the one key that must not be adopted: it is where THIS
    host keeps its clone. When the shared copy names another location, the
    current one is pinned in local.yaml first — otherwise the adopted config
    points at a directory that does not exist here (a Windows host with its
    clone in C:\\Projects, 2.70.0).
    """
    from sccs.config.loader import get_local_config_path, load_config, read_local_repo_path, write_local_repo_path

    pull = pull_fn or _git_pull
    if not pull(status.repo_path):
        raise DoctorError(
            f"git pull in {status.repo_path} failed — shared config not adopted. "
            "Resolve the repository state (`sccs sync --pull`) and run `sccs doctor install` again."
        )
    if not status.repo_copy.is_file():
        raise DoctorError(f"{status.repo_copy} is gone after the pull — nothing to adopt")

    original = status.local_path.read_text(encoding="utf-8")
    backup = status.local_path.parent / "backups" / f"config.yaml.{datetime.now():%Y%m%d-%H%M%S}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(status.local_path, backup)

    shared_text = status.repo_copy.read_text(encoding="utf-8")
    pinned_local = None
    if read_local_repo_path(status.local_path) is None and _repo_path_differs(shared_text, status.repo_path):
        pinned_local = write_local_repo_path(str(status.repo_path), status.local_path)
        logger.info("repository path %s kept for this host in %s", status.repo_path, pinned_local)

    atomic_write(status.local_path, shared_text, mode=0o600)
    try:
        load_config(status.local_path)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        atomic_write(status.local_path, original, mode=0o600)
        if pinned_local is not None:
            get_local_config_path(status.local_path).unlink(missing_ok=True)
        raise DoctorError(f"shared config is invalid ({exc}) — previous config restored") from exc
    logger.info("shared config adopted from %s; previous config at %s", status.repo_copy, backup)


def shared_config_actions(status: SharedConfigStatus | None) -> list[DoctorAction]:
    """One confirm-gated adoption step for a host that has not adopted the shared config."""
    from sccs.doctor.installer import DoctorAction

    if status is None or status.state != "not_adopted":
        return []
    return [
        DoctorAction(
            label=f"Adopt the shared config.yaml from {status.repo_path} (current one is backed up)",
            runnable=True,
            component="shared-config:adopt",
            python_callable=lambda: adopt_shared_config(status),
            always_confirm=True,
        )
    ]
