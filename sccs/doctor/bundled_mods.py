# SCCS Doctor — Claude Code mods that ship inside the sccs package
#
# A mod is a Claude Code plugin whose hooks module changes the interface
# (sccs/data/marketplace/<name>/). `paste-lens`, the first one, puts a long
# paste back into the prompt box instead of `[Pasted text #1 +42 lines]`.
#
# Design rules:
#   1. Opt-in via `doctor.bundled_mods`. A mod changes how the prompt box
#      behaves and builds on an early-access API of Claude Code, so nobody who
#      installs sccs gets one unasked.
#   2. Claude Code installs a plugin from a marketplace, and a directory is a
#      valid one. The bundled tree is copied to a stable folder first
#      (`~/.local/share/sccs/mods`): the package's own path changes with the
#      Python version and the install method, and a marketplace that moved is
#      a broken marketplace.
#   3. No source is ever configurable: the tree comes from the installed
#      package and nowhere else, so these actions run without a prompt like
#      the other bundled steps. Mod names from the config are only looked up
#      in the bundled marketplace, never turned into a path.
#   4. The staging folder is replaced wholesale, and only when it is empty or
#      already holds this marketplace — a foreign folder is refused.
#   5. An installed mod is kept out of the foreign-plugin list through an
#      `allowlist_only` entry in `effective_plugins()`.

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sccs.doctor.installer import DoctorAction

BUNDLED_MARKETPLACE = "sccs-mods"
DEFAULT_STAGE_DIR = "~/.local/share/sccs/mods"
_INSTALLED_PLUGINS_PATH = "~/.claude/plugins/installed_plugins.json"
_KNOWN_MARKETPLACES_PATH = "~/.claude/plugins/known_marketplaces.json"

_MOD_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
_IGNORED_NAMES = ("__pycache__", ".DS_Store")


def bundled_root() -> Path:
    """The marketplace tree inside the installed package."""
    return Path(__file__).resolve().parent.parent / "data" / "marketplace"


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def available_mods(root: Path | None = None) -> dict[str, str]:
    """`name -> version` of every mod the bundled marketplace lists."""
    root = root or bundled_root()
    manifest = _read_json(root / ".claude-plugin" / "marketplace.json") or {}
    mods: dict[str, str] = {}
    for entry in manifest.get("plugins") or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not _MOD_NAME_RE.match(name):
            continue
        plugin = _read_json(root / name / ".claude-plugin" / "plugin.json") or {}
        version = plugin.get("version")
        if isinstance(version, str) and version:
            mods[name] = version
    return mods


def resolve_bundled_mods(names: list[str], root: Path | None = None) -> list[str]:
    """Configured names that the bundled marketplace really has; unknown ones are ignored."""
    known = available_mods(root)
    return [n for n in dict.fromkeys(names) if n in known]


def _tree(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in _IGNORED_NAMES for part in path.parts) or path.suffix == ".pyc":
            continue
        try:
            files[path.relative_to(root).as_posix()] = path.read_bytes()
        except OSError:
            continue
    return files


@dataclass
class BundledModStatus:
    """Result of inspecting one bundled mod."""

    name: str
    bundled_version: str
    installed_version: str | None
    staged_current: bool
    marketplace_registered: bool
    root: Path
    stage_dir: Path

    @property
    def state(self) -> str:
        if self.installed_version is None:
            return "missing"
        if self.installed_version != self.bundled_version:
            return "outdated"
        return "ok"

    @property
    def needs_action(self) -> bool:
        return self.state != "ok"


class BundledModDetector:
    """Compare the bundled marketplace with what Claude Code has installed."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        stage_dir: Path | None = None,
        installed_plugins_path: Path | None = None,
        known_marketplaces_path: Path | None = None,
    ) -> None:
        self.root = root or bundled_root()
        self.stage_dir = stage_dir or Path(DEFAULT_STAGE_DIR).expanduser()
        self.installed_plugins_path = installed_plugins_path or Path(_INSTALLED_PLUGINS_PATH).expanduser()
        self.known_marketplaces_path = known_marketplaces_path or Path(_KNOWN_MARKETPLACES_PATH).expanduser()

    def _installed_version(self, name: str) -> str | None:
        data = _read_json(self.installed_plugins_path) or {}
        plugins = data.get("plugins")
        entries = plugins.get(f"{name}@{BUNDLED_MARKETPLACE}") if isinstance(plugins, dict) else None
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if isinstance(entry, dict) and entry.get("scope", "user") == "user":
                version = entry.get("version")
                return str(version) if version else "unknown"
        return None

    def _marketplace_registered(self) -> bool:
        data = _read_json(self.known_marketplaces_path) or {}
        entry = data.get(BUNDLED_MARKETPLACE)
        source = entry.get("source") if isinstance(entry, dict) else None
        path = source.get("path") if isinstance(source, dict) else None
        if not isinstance(path, str):
            return False
        try:
            return Path(path).expanduser().resolve() == self.stage_dir.resolve()
        except OSError:
            return False

    def get_statuses(self, names: list[str]) -> list[BundledModStatus]:
        known = available_mods(self.root)
        wanted = [n for n in dict.fromkeys(names) if n in known]
        if not wanted:
            return []
        staged_current = _tree(self.root) == _tree(self.stage_dir)
        registered = self._marketplace_registered()
        return [
            BundledModStatus(
                name=name,
                bundled_version=known[name],
                installed_version=self._installed_version(name),
                staged_current=staged_current,
                marketplace_registered=registered,
                root=self.root,
                stage_dir=self.stage_dir,
            )
            for name in wanted
        ]


def stage_marketplace(root: Path, stage_dir: Path) -> None:
    """Replace `stage_dir` with a copy of the bundled marketplace (design rule 4)."""
    from sccs.doctor.runner import DoctorError

    if not (root / ".claude-plugin" / "marketplace.json").is_file():
        raise DoctorError(f"bundled marketplace not found in the package: {root}")
    if stage_dir.is_symlink() or (stage_dir.exists() and not stage_dir.is_dir()):
        raise DoctorError(f"refusing to replace {stage_dir}: not a plain folder")
    if stage_dir.is_dir() and any(stage_dir.iterdir()):
        manifest = _read_json(stage_dir / ".claude-plugin" / "marketplace.json") or {}
        if manifest.get("name") != BUNDLED_MARKETPLACE:
            raise DoctorError(f"refusing to replace {stage_dir}: not the {BUNDLED_MARKETPLACE} marketplace")
        shutil.rmtree(stage_dir)
    stage_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, stage_dir, ignore=_IGNORED, dirs_exist_ok=True)


def bundled_mod_actions(statuses: list[BundledModStatus] | None) -> list[DoctorAction]:
    """Stage the marketplace, register it, then install or update each mod.

    The same list serves install, update and optimize: every step is a no-op
    once the host is current, and then no action is planned at all.
    """
    from sccs.doctor.installer import DoctorAction

    statuses = statuses or []
    if not statuses:
        return []
    first = statuses[0]
    stale = not first.staged_current
    unregistered = not first.marketplace_registered
    pending = [st for st in statuses if st.needs_action]
    if not (stale or unregistered or pending):
        return []

    actions: list[DoctorAction] = []
    staged = "bundled-mods:staged"
    marketplace = "bundled-mods:marketplace"
    root, stage_dir = first.root, first.stage_dir

    if stale:

        def _stage(root: Path = root, stage_dir: Path = stage_dir) -> None:
            stage_marketplace(root, stage_dir)

        actions.append(
            DoctorAction(
                label=f"copy the bundled mods to {stage_dir}",
                python_callable=_stage,
                runnable=True,
                component=staged,
                auto_confirm=True,
            )
        )
    if unregistered:
        actions.append(
            DoctorAction(
                label=f"register marketplace {BUNDLED_MARKETPLACE} ({stage_dir})",
                cmd=["claude", "plugin", "marketplace", "add", str(stage_dir)],
                runnable=True,
                component=marketplace,
                depends_on_components=(staged,),
                auto_confirm=True,
            )
        )
    elif stale:
        actions.append(
            DoctorAction(
                label=f"refresh marketplace {BUNDLED_MARKETPLACE}",
                cmd=["claude", "plugin", "marketplace", "update", BUNDLED_MARKETPLACE],
                runnable=True,
                component=marketplace,
                depends_on_components=(staged,),
                auto_confirm=True,
            )
        )
    for st in pending:
        verb = "install" if st.state == "missing" else "update"
        actions.append(
            DoctorAction(
                label=f"{verb} mod {st.name} {st.bundled_version} (bundled with sccs)",
                cmd=["claude", "plugin", verb, f"{st.name}@{BUNDLED_MARKETPLACE}"],
                runnable=True,
                component=f"bundled-mod:{st.name}",
                depends_on_components=(staged, marketplace),
                auto_confirm=True,
            )
        )
    return actions
