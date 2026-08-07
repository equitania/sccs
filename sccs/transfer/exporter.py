# SCCS Transfer Exporter
# Scan local items and create ZIP export archives

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sccs.config.schema import ItemType, SccsConfig, SyncCategory
from sccs.doctor.managed import get_doctor_managed_excludes
from sccs.sync.item import SyncItem, scan_items_for_category
from sccs.transfer.manifest import (
    MANIFEST_FILENAME,
    ExportManifest,
    ManifestCategory,
    ManifestItem,
    create_manifest,
    serialize_manifest,
)
from sccs.utils.logging import get_logger
from sccs.utils.paths import expand_path, matches_any_pattern
from sccs.utils.platform import is_platform_match

logger = get_logger("sccs.transfer")


@dataclass
class ExportSelection:
    """Selected items for export within a single category."""

    category_name: str
    category: SyncCategory
    items: list[SyncItem]


@dataclass
class ExportResult:
    """Result of an export operation."""

    success: bool
    output_path: Path | None = None
    total_items: int = 0
    total_categories: int = 0
    error: str | None = None


class Exporter:
    """Scans local items and creates ZIP export archives."""

    def __init__(self, config: SccsConfig, *, include_managed: bool = False) -> None:
        """Initialize the exporter.

        Args:
            config: Loaded SCCS configuration.
            include_managed: When True, doctor-managed items (`gsd-*`,
                `playwright-cli`, …) are kept in the export. Off by default —
                those files are reproducible via `sccs doctor install` on the
                target machine, so shipping a frozen snapshot of them just
                creates drift (see `sccs/doctor/managed.py`).
        """
        self._config = config
        # Mirror SyncEngine.effective_global_exclude: the sync engine already
        # skips doctor-managed files, which is why they never reach the repo.
        # The exporter has to apply the same registry — otherwise the ZIP
        # ships 70 gsd-* skills the recipient's own doctor run would install.
        self._doctor_excludes: list[str] = []
        if not include_managed:
            self._doctor_excludes = get_doctor_managed_excludes(config.doctor)
        self.effective_global_exclude = list(config.global_exclude) + self._doctor_excludes

    def scan_available_items(self) -> dict[str, list[SyncItem]]:
        """Scan all enabled categories for locally available items.

        Returns:
            Dict of category_name -> list of SyncItems that exist locally.
            Empty categories are omitted.
        """
        result: dict[str, list[SyncItem]] = {}
        repo_base = expand_path(self._config.repository.path)

        for cat_name, category in self._config.sync_categories.items():
            if not category.enabled:
                continue
            if not is_platform_match(category.platforms):
                continue

            local_path = expand_path(category.local_path)
            items = scan_items_for_category(
                category_name=cat_name,
                category=category,
                local_base=local_path.parent,
                repo_base=repo_base,
                global_exclude=self.effective_global_exclude,
            )

            # Only include items that exist locally. Symlink items are dropped
            # here so they never reach the selection UI or the manifest — the
            # ZIP writer would refuse them anyway (see _add_category_to_zip),
            # and a manifest entry without a ZIP payload would break import.
            local_items = []
            for item in items:
                if not item.exists_local:
                    continue
                if item.local_path is not None and item.local_path.is_symlink():
                    logger.warning("Excluding symlink item from export scan: %s", item.local_path)
                    continue
                local_items.append(item)
            if local_items:
                result[cat_name] = local_items

        return result

    def build_selections_from_parsed(
        self,
        parsed: dict[str, list[str]],
        scanned: dict[str, list[SyncItem]],
    ) -> list[ExportSelection]:
        """Build ExportSelection list from parsed UI selections.

        Args:
            parsed: Dict of category_name -> list of selected item names.
            scanned: Dict of category_name -> list of all scanned SyncItems.

        Returns:
            List of ExportSelection objects.
        """
        selections: list[ExportSelection] = []
        for cat_name, item_names in parsed.items():
            category = self._config.sync_categories.get(cat_name)
            if category is None:
                continue
            all_items = scanned.get(cat_name, [])
            selected_items = [item for item in all_items if item.name in item_names]
            if selected_items:
                selections.append(
                    ExportSelection(
                        category_name=cat_name,
                        category=category,
                        items=selected_items,
                    )
                )
        return selections

    def build_selections_all(
        self,
        scanned: dict[str, list[SyncItem]],
    ) -> list[ExportSelection]:
        """Build ExportSelection for all scanned items (--all mode).

        Args:
            scanned: Dict of category_name -> list of all scanned SyncItems.

        Returns:
            List of ExportSelection objects.
        """
        selections: list[ExportSelection] = []
        for cat_name, items in scanned.items():
            category = self._config.sync_categories.get(cat_name)
            if category is None:
                continue
            selections.append(
                ExportSelection(
                    category_name=cat_name,
                    category=category,
                    items=items,
                )
            )
        return selections

    def export_to_zip(
        self,
        selections: list[ExportSelection],
        output_path: Path,
        raw_config: dict,
    ) -> ExportResult:
        """Create ZIP archive from selected items.

        Args:
            selections: List of ExportSelection objects.
            output_path: Path for the output ZIP file.
            raw_config: Raw YAML config dict for unexpanded paths.

        Returns:
            ExportResult with success status and details.
        """
        if not selections:
            return ExportResult(success=False, error="No items selected for export")

        try:
            manifest = self._build_manifest(selections, raw_config)
            total_items = 0

            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for selection in selections:
                    total_items += self._add_category_to_zip(zf, selection)

                # Add manifest as last entry
                manifest_yaml = serialize_manifest(manifest)
                zf.writestr(MANIFEST_FILENAME, manifest_yaml)

            return ExportResult(
                success=True,
                output_path=output_path,
                total_items=total_items,
                total_categories=len(selections),
            )
        except OSError as e:
            return ExportResult(success=False, error=f"Export failed: {e}")

    def _build_manifest(
        self,
        selections: list[ExportSelection],
        raw_config: dict,
    ) -> ExportManifest:
        """Build manifest from selections."""
        categories: dict[str, ManifestCategory] = {}
        raw_categories = raw_config.get("sync_categories", {})

        for selection in selections:
            cat_name = selection.category_name
            raw_cat = raw_categories.get(cat_name, {})

            # Use unexpanded local_path from raw config, fall back to category
            local_path = raw_cat.get("local_path", selection.category.local_path)

            # Platform hint from category config
            platform_hint = None
            platforms = selection.category.platforms
            if platforms:
                platform_hint = platforms[0] if len(platforms) == 1 else ", ".join(platforms)

            manifest_items: list[ManifestItem] = []
            for item in selection.items:
                zip_path = f"{cat_name}/{item.name}"
                if item.item_type == ItemType.DIRECTORY:
                    zip_path += "/"
                manifest_items.append(
                    ManifestItem(
                        name=item.name,
                        zip_path=zip_path,
                        item_type=item.item_type.value,
                        platform_hint=platform_hint,
                    )
                )

            categories[cat_name] = ManifestCategory(
                description=selection.category.description or cat_name,
                item_type=selection.category.item_type.value,
                local_path=local_path,
                items=manifest_items,
            )

        return create_manifest(categories)

    def _add_category_to_zip(
        self,
        zf: zipfile.ZipFile,
        selection: ExportSelection,
    ) -> int:
        """Add items from a category to the ZIP file.

        Returns:
            Number of items added.
        """
        count = 0
        # Deliberately the RAW global_exclude, not `effective_global_exclude`:
        # this filter runs against files *inside* an item directory. Applying
        # the doctor patterns here would silently drop a legitimate reference
        # file named e.g. `gsd-notes.md` from one of the user's own skills.
        # Doctor-managed *items* are already dropped in `scan_available_items`,
        # which every selection path goes through.
        global_exclude = self._config.global_exclude or []

        for item in selection.items:
            if item.local_path is None or not item.local_path.exists():
                continue

            if item.local_path.is_symlink():
                # Refusing to export symlinks: zf.write() dereferences the link
                # and would embed the *target's* contents in the archive — a
                # planted link (e.g. SKILL.md -> ~/.ssh/id_ed25519) would turn
                # a shared export ZIP into secret exfiltration. Same policy as
                # safe_copy and the importer's symlink-entry rejection.
                logger.warning("Skipping symlink item during export: %s", item.local_path)
                continue

            if item.item_type == ItemType.DIRECTORY:
                self._add_directory_to_zip(
                    zf,
                    item.local_path,
                    f"{selection.category_name}/{item.name}",
                    global_exclude,
                )
            else:
                zip_path = f"{selection.category_name}/{item.name}"
                zf.write(item.local_path, zip_path)

            count += 1

        return count

    def _add_directory_to_zip(
        self,
        zf: zipfile.ZipFile,
        dir_path: Path,
        zip_prefix: str,
        global_exclude: list[str],
    ) -> None:
        """Recursively add directory contents to ZIP."""
        for root, dirs, files in os.walk(dir_path):
            # os.walk(followlinks=False) never descends into symlinked dirs,
            # but prune them explicitly so the skip is deliberate and logged
            # rather than an accident of the walk default.
            for d in [d for d in dirs if (Path(root) / d).is_symlink()]:
                dirs.remove(d)
                logger.warning("Skipping symlink directory during export: %s", Path(root) / d)

            for fname in files:
                full_path = Path(root) / fname
                if full_path.is_symlink():
                    # See _add_category_to_zip: never dereference symlinks into
                    # the archive — that would leak the target file's contents.
                    logger.warning("Skipping symlink during export: %s", full_path)
                    continue
                rel_path = full_path.relative_to(dir_path)

                # Apply global excludes
                if matches_any_pattern(str(rel_path), global_exclude):
                    continue
                if matches_any_pattern(fname, global_exclude):
                    continue

                arc_name = f"{zip_prefix}/{rel_path}"
                zf.write(full_path, arc_name)


def generate_export_filename() -> str:
    """Generate default export filename with timestamp."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"sccs-export-{timestamp}.zip"
