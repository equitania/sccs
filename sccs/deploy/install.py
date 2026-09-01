# `sccs deploy install` — run the existing Importer, then write the receipt.
#
# On a customer host there is no config.yaml of ours, so the Importer runs
# in legacy mode (config=None) and accepts the manifest's local_path. That
# path is attacker-controlled, so we add the guard the legacy branch lacks:
# every target base must live under HOME.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sccs import __version__
from sccs.config.schema import SccsConfig
from sccs.deploy.receipt import InstallRecord, ReceiptEntry, ReceiptManager
from sccs.doctor._paths import is_home_path
from sccs.transfer.importer import Importer
from sccs.transfer.manifest import ManifestItem
from sccs.utils.hashing import directory_hash, file_hash
from sccs.utils.logging import get_logger

logger = get_logger("sccs.deploy")


@dataclass
class InstallOutcome:
    """Result of installing one deployment bundle."""

    success: bool
    profile: str = ""
    installed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    record: InstallRecord | None = None


def _target_path(base: Path, item: ManifestItem) -> Path:
    return base / item.name


def _hash_target(path: Path, item_type: str) -> str | None:
    if not path.exists():
        return None
    if item_type == "directory":
        return directory_hash(path)
    return file_hash(path)


def install_bundle(
    zip_path: Path,
    *,
    config: SccsConfig | None,
    receipt_manager: ReceiptManager,
    dry_run: bool = False,
    overwrite: bool = True,
) -> InstallOutcome:
    """Install a deployment bundle and record what was written.

    Args:
        zip_path: The bundle produced by `sccs deploy export`.
        config: Local SCCS config, or None on a host that has none.
        receipt_manager: Where the receipt is written.
        dry_run: Preview only — nothing is written, no receipt.
        overwrite: Replace existing targets. True by default: a deployment
            that silently skips half its payload is worse than one that
            refreshes it, and `pre_existing` records what was displaced.
    """
    importer = Importer(zip_path, config=config)

    try:
        manifest = importer.load_manifest()
    except (ValueError, OSError) as e:
        return InstallOutcome(success=False, errors=[f"Cannot read bundle: {e}"])

    if manifest.deployment is None:
        return InstallOutcome(
            success=False,
            errors=[
                "Archive has no deployment section — it was made by `sccs export`, "
                "not `sccs deploy export`. Use `sccs import` for it."
            ],
        )

    section = manifest.deployment

    # Home guard. With a config the Importer already pins every target to
    # the configured local_path; without one it accepts the manifest's word,
    # and the manifest came out of a file. Nothing we ship belongs outside HOME.
    for cat_name, cat_data in manifest.categories.items():
        if not is_home_path(cat_data.local_path):
            return InstallOutcome(
                success=False,
                profile=section.profile,
                errors=[
                    f"Category '{cat_name}' targets '{cat_data.local_path}', which is "
                    f"outside the home directory — refusing to install"
                ],
            )

    selections = importer.build_selections_all()

    # Record pre-existing state BEFORE the import writes anything.
    pre_existing: dict[tuple[str, str], bool] = {}
    bases: dict[str, Path] = {}
    for cat_name, item in selections:
        cat_data = manifest.categories[cat_name]
        base = Path(cat_data.local_path).expanduser()
        bases[cat_name] = base
        pre_existing[(cat_name, item.name)] = _target_path(base, item).exists()

    result = importer.apply(selections, dry_run=dry_run, overwrite=overwrite, backup=not dry_run)

    if dry_run:
        return InstallOutcome(
            success=result.success,
            profile=section.profile,
            installed=len(selections),
            errors=list(result.errors),
        )

    entries: list[ReceiptEntry] = []
    for cat_name, item in selections:
        target = _target_path(bases[cat_name], item)
        if not target.exists():
            continue
        entries.append(
            ReceiptEntry(
                category=cat_name,
                name=item.name,
                target=str(target),
                item_type=item.item_type,
                content_hash=_hash_target(target, item.item_type),
                pre_existing=pre_existing[(cat_name, item.name)],
            )
        )

    record = InstallRecord(
        profile=section.profile,
        installed_at=datetime.now(timezone.utc).isoformat(),
        sccs_version=__version__,
        retain=list(section.retain),
        sweep_globs={k: list(v) for k, v in section.sweep_globs.items()},
        entries=entries,
    )
    receipt_manager.record_install(record)
    logger.info("Installed profile %s: %d artefacts", section.profile, len(entries))

    return InstallOutcome(
        success=result.success,
        profile=section.profile,
        installed=len(entries),
        skipped=len(selections) - len(entries),
        errors=list(result.errors),
        record=record,
    )
