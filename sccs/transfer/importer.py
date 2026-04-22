# SCCS Transfer Importer
# Extract ZIP archives and place items on target system

from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from sccs.config.schema import SccsConfig
from sccs.transfer.manifest import (
    MANIFEST_FILENAME,
    ExportManifest,
    ManifestItem,
    deserialize_manifest,
)
from sccs.utils.paths import create_backup, safe_copy

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of an import operation."""

    success: bool
    total_items: int = 0
    written: int = 0
    skipped: int = 0
    backed_up: int = 0
    errors: list[str] = field(default_factory=list)


class Importer:
    """Extracts ZIP archives and places items on the target system."""

    def __init__(self, zip_path: Path, config: SccsConfig | None = None) -> None:
        """
        Args:
            zip_path: Path to the ZIP archive to import.
            config: Optional SccsConfig providing the allowlist of acceptable
                target paths. When supplied, every manifest `local_path` must
                match a known category's `local_path` and every item target
                must resolve underneath that path. Without a config, the
                importer operates in legacy mode — recommended only for tests
                and scripted use.
        """
        self._zip_path = zip_path
        self._config = config
        self._manifest: ExportManifest | None = None

    def load_manifest(self) -> ExportManifest:
        """Read and validate manifest from ZIP.

        Returns:
            Parsed ExportManifest.

        Raises:
            ValueError: If ZIP doesn't contain a valid manifest.
            FileNotFoundError: If ZIP file doesn't exist.
        """
        if not self._zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {self._zip_path}")

        if not zipfile.is_zipfile(self._zip_path):
            raise ValueError(f"Not a valid ZIP file: {self._zip_path}")

        with zipfile.ZipFile(self._zip_path, "r") as zf:
            if MANIFEST_FILENAME not in zf.namelist():
                raise ValueError(f"ZIP does not contain {MANIFEST_FILENAME} — not an SCCS export archive")

            manifest_content = zf.read(MANIFEST_FILENAME).decode("utf-8")

        self._manifest = deserialize_manifest(manifest_content)
        return self._manifest

    def build_selections_from_parsed(
        self,
        parsed: dict[str, list[str]],
    ) -> list[tuple[str, ManifestItem]]:
        """Build selection list from parsed UI choices.

        Args:
            parsed: Dict of category_name -> list of selected item names.

        Returns:
            List of (category_name, ManifestItem) tuples.
        """
        if self._manifest is None:
            raise RuntimeError("Manifest not loaded — call load_manifest() first")

        selections: list[tuple[str, ManifestItem]] = []
        for cat_name, item_names in parsed.items():
            cat_data = self._manifest.categories.get(cat_name)
            if cat_data is None:
                continue
            for item in cat_data.items:
                if item.name in item_names:
                    selections.append((cat_name, item))
        return selections

    def build_selections_all(self) -> list[tuple[str, ManifestItem]]:
        """Build selection list for all items in manifest (--all mode)."""
        if self._manifest is None:
            raise RuntimeError("Manifest not loaded — call load_manifest() first")

        selections: list[tuple[str, ManifestItem]] = []
        for cat_name, cat_data in self._manifest.categories.items():
            for item in cat_data.items:
                selections.append((cat_name, item))
        return selections

    def apply(
        self,
        selections: list[tuple[str, ManifestItem]],
        *,
        dry_run: bool = False,
        overwrite: bool = False,
        backup: bool = True,
    ) -> ImportResult:
        """Extract and place selected items from ZIP.

        Args:
            selections: List of (category_name, ManifestItem) to import.
            dry_run: Preview only, don't write files.
            overwrite: Overwrite existing files without prompting.
            backup: Create backups before overwriting.

        Returns:
            ImportResult with counts and errors.
        """
        if self._manifest is None:
            raise RuntimeError("Manifest not loaded — call load_manifest() first")

        result = ImportResult(success=True, total_items=len(selections))

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Extract ZIP to staging area
            try:
                self._safe_extract(tmp_path)
            except ValueError as e:
                logger.error("Refused unsafe ZIP during extraction: %s", e)
                return ImportResult(success=False, errors=[str(e)])

            for cat_name, item in selections:
                cat_data = self._manifest.categories.get(cat_name)
                if cat_data is None:
                    result.errors.append(f"Category {cat_name} not found in manifest")
                    continue

                try:
                    target_base = self._resolve_target_base(cat_name, cat_data.local_path)
                except ValueError as e:
                    logger.error("Rejected category %s: %s", cat_name, e)
                    result.errors.append(str(e))
                    continue

                error = self._apply_item(
                    item=item,
                    target_base=target_base,
                    staging_dir=tmp_path,
                    dry_run=dry_run,
                    overwrite=overwrite,
                    backup=backup,
                    result=result,
                    cat_name=cat_name,
                )
                if error:
                    result.errors.append(error)

        result.success = len(result.errors) == 0
        return result

    def _resolve_target_base(self, cat_name: str, manifest_local_path: str) -> Path:
        """Resolve and validate the target base directory for a category.

        The manifest-supplied `local_path` is attacker-controlled (it's read
        from a ZIP the user obtained from somewhere). Without a config we
        accept it as-is (legacy mode), but with a config the category must
        exist locally and the manifest path must match the config's
        `local_path` for that category. This prevents a hostile ZIP from
        redirecting writes to arbitrary paths such as ``~/.ssh``.

        Args:
            cat_name: Category name from the manifest.
            manifest_local_path: local_path string from the manifest.

        Returns:
            Resolved, absolute target base path.

        Raises:
            ValueError: If the category is unknown or the path escapes the
                configured allowlist.
        """
        manifest_path = Path(manifest_local_path).expanduser().resolve()

        if self._config is None:
            return manifest_path

        category = self._config.sync_categories.get(cat_name)
        if category is None:
            raise ValueError(
                f"Category '{cat_name}' is not configured locally — refusing to "
                f"write to path '{manifest_local_path}' from untrusted manifest"
            )

        expected = Path(category.local_path).expanduser().resolve()
        if manifest_path != expected:
            raise ValueError(
                f"Manifest local_path for '{cat_name}' ({manifest_local_path}) "
                f"does not match local configuration ({category.local_path})"
            )

        return expected

    def _apply_item(
        self,
        *,
        item: ManifestItem,
        target_base: Path,
        staging_dir: Path,
        dry_run: bool,
        overwrite: bool,
        backup: bool,
        result: ImportResult,
        cat_name: str,
    ) -> str | None:
        """Apply a single item from staging to target.

        Returns:
            Error message string, or None on success.
        """
        # item.name comes from the manifest (attacker-controlled). Guard
        # against path-traversal (../) and absolute paths before building
        # the target path.
        if not _is_safe_relative_name(item.name):
            return f"Refused item with unsafe name: {item.name!r}"

        if item.item_type == "directory":
            source = staging_dir / item.zip_path.rstrip("/")
            target = target_base / item.name
        else:
            source = staging_dir / item.zip_path
            target = target_base / item.name

        # Defense-in-depth: the resolved target must stay underneath target_base.
        try:
            resolved_target = target.resolve()
            resolved_base = target_base.resolve()
            resolved_target.relative_to(resolved_base)
        except ValueError:
            return f"Refused item {item.name!r}: resolved path escapes target base"

        if not source.exists():
            return f"Item {item.name} not found in ZIP staging area"

        if dry_run:
            result.written += 1
            return None

        # Handle existing target
        if target.exists():
            if not overwrite:
                result.skipped += 1
                return None

            if backup:
                backup_path = create_backup(target, category=f"import-{cat_name}")
                if backup_path:
                    result.backed_up += 1

        # Ensure parent directory exists
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            if source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target, symlinks=False)
            else:
                safe_copy(source, target)

            result.written += 1
            return None
        except OSError as e:
            return f"Failed to write {item.name}: {e}"

    def _safe_extract(self, extract_path: Path) -> None:
        """Extract ZIP to staging directory with path traversal protection.

        Rejects symlink entries (CWE-61) before extraction to prevent
        subsequent copy operations from following attacker-crafted links
        outside the staging area, and rejects filenames that resolve
        outside the staging directory (CWE-22).

        Raises:
            ValueError: If a ZIP member would escape the extraction
                directory or contains a symlink entry.
        """
        safe_base = os.path.normpath(os.path.abspath(extract_path))

        with zipfile.ZipFile(self._zip_path, "r") as zf:
            for info in zf.infolist():
                # Reject symlinks: zipfile.extractall() recreates Unix
                # symlinks from external_attr without any target validation,
                # which trivially bypasses the path-traversal check below
                # (a symlink entry named "inside/link" pointing to "/tmp"
                # passes the name check but later copy operations follow
                # the link out of the staging area).
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise ValueError(f"ZIP contains symlink entry (not allowed): {info.filename}")

                member_path = os.path.normpath(os.path.abspath(os.path.join(extract_path, info.filename)))
                if not member_path.startswith(safe_base + os.sep) and member_path != safe_base:
                    raise ValueError(f"ZIP path traversal detected: {info.filename}")

            zf.extractall(extract_path)


def _is_safe_relative_name(name: str) -> bool:
    """Return True if ``name`` is a safe relative path component.

    Rejects absolute paths, Windows drive prefixes, and any ``..``
    traversal components. The name is allowed to contain nested
    sub-directories (e.g. ``foo/bar.md``) as long as nothing tries to
    escape the eventual base directory.
    """
    if not name or name in (".", ".."):
        return False

    candidate = Path(name)
    if candidate.is_absolute():
        return False

    # Path("foo").drive is "" on POSIX; it catches Windows forms like "C:foo".
    if candidate.drive:
        return False

    return all(part not in ("", "..") for part in candidate.parts)
