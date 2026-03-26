# SCCS Transfer Manifest
# Pydantic models for ZIP export/import manifest

from __future__ import annotations

import platform
from datetime import datetime, timezone

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


class ExportManifest(BaseModel):
    """Root manifest stored as sccs_manifest.yaml in ZIP root."""

    sccs_version: str
    created_at: str
    created_on: str
    categories: dict[str, ManifestCategory]

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
