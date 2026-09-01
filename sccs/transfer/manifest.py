# SCCS Transfer Manifest
# Pydantic models for ZIP export/import manifest

from __future__ import annotations

import platform
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel

from sccs import __version__

MANIFEST_FILENAME = "sccs_manifest.yaml"


class ManifestItem(BaseModel):
    """Single item (file or directory) in the export manifest."""

    name: str
    zip_path: str
    item_type: str  # "file" or "directory"
    platform_hint: str | None = None


class ManifestCategory(BaseModel):
    """Category section in the export manifest."""

    description: str
    item_type: str
    local_path: str  # Unexpanded path (e.g. ~/.claude/skills)
    items: list[ManifestItem]


def is_single_file_category(category: ManifestCategory) -> bool:
    """True when the category's `local_path` names the file itself.

    Mirrors the export-side convention in `sync.item.scan_items_for_category`:
    a `file` category whose `local_path` is a plain path to a single file
    (`starship_config` -> `~/.config/starship.toml`, `gitconfig` ->
    `~/.gitconfig`) yields exactly one item named after that file. Every other
    `file` category points at a DIRECTORY and yields the files inside it.

    The import side cannot repeat the export side's `local_path.is_dir()`
    test — on a fresh customer host the path does not exist yet — so the
    manifest itself has to carry the answer, and it does: for a single-file
    category, and only for one, the category carries EXACTLY ONE item and
    that item's name equals the basename of `local_path`.

    The item count is load-bearing, not decoration. A directory-backed
    `file` category can legitimately contain a file named like the
    directory itself (`~/.claude/commands/commands.md`); without the count
    such a category would be mistaken for a single-file one and every one
    of its files would be written into the directory's PARENT.
    """
    if category.item_type != "file":
        return False
    raw = category.local_path
    if not raw or raw.endswith("/") or any(ch in raw for ch in "*?["):
        return False
    base_name = PurePosixPath(raw.replace("\\", "/")).name
    if not base_name or base_name in {".", ".."}:
        return False
    if len(category.items) != 1:
        return False
    return category.items[0].name == base_name


def resolves_to_parent(category: ManifestCategory, expanded: Path) -> bool:
    """True when `expanded` names the artefact itself, so items land beside it.

    `is_single_file_category` reads the manifest alone, because on a fresh
    customer host there is nothing on disk to look at. Where there IS
    something, run the export side's own test as well: a `local_path` that
    is a directory on this host is directory-backed, full stop — no manifest
    fingerprint can outvote it. That closes the one false positive the
    manifest heuristic cannot see, a directory-backed `file` category whose
    single selected item happens to be named like the directory.
    """
    return is_single_file_category(category) and not expanded.is_dir()


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


class ExportManifest(BaseModel):
    """Root manifest stored as sccs_manifest.yaml in ZIP root."""

    sccs_version: str
    created_at: str
    created_on: str
    categories: dict[str, ManifestCategory]
    # None for bundles produced by plain `sccs export` — that path stays
    # unchanged and its archives must keep importing.
    deployment: DeploymentSection | None = None

    @property
    def total_items(self) -> int:
        """Total number of items across all categories."""
        return sum(len(cat.items) for cat in self.categories.values())

    @property
    def total_categories(self) -> int:
        """Number of categories in the manifest."""
        return len(self.categories)


def create_manifest(categories: dict[str, ManifestCategory]) -> ExportManifest:
    """Create a new export manifest with current metadata."""
    system = platform.system().lower()
    platform_name = {"darwin": "macos", "linux": "linux", "windows": "windows"}.get(system, system)

    return ExportManifest(
        sccs_version=__version__,
        created_at=datetime.now(timezone.utc).isoformat(),
        created_on=platform_name,
        categories=categories,
    )


def serialize_manifest(manifest: ExportManifest) -> str:
    """Serialize manifest to YAML string."""
    data = manifest.model_dump(mode="json")
    return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)


def deserialize_manifest(content: str) -> ExportManifest:
    """Deserialize YAML string to manifest.

    Raises:
        ValueError: If content is invalid YAML or doesn't match schema.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid manifest YAML: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Manifest must be a YAML mapping")

    return ExportManifest.model_validate(data)
