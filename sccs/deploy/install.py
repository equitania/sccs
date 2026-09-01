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
from sccs.deploy.receipt import DeployReceipt, InstallRecord, ReceiptEntry, ReceiptManager
from sccs.doctor._paths import is_home_path
from sccs.transfer.importer import Importer
from sccs.transfer.manifest import ManifestCategory, ManifestItem, resolves_to_parent
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
    # "category/name" for every target that already existed and was NOT
    # written by SCCS. Nothing of ours landed there; the operator has to see
    # that, or they will assume the bundle is complete on that host.
    skipped_foreign: list[str] = field(default_factory=list)


def _target_path(base: Path, item: ManifestItem) -> Path:
    return base / item.name


def _category_base(cat_data: ManifestCategory) -> Path:
    """Where a category's items land on this host.

    Mirrors the export-side convention in `scan_items_for_category`: a
    single-file category carries the FILE itself as `local_path`
    (`starship_config` -> `~/.config/starship.toml`), so its items sit in the
    file's parent directory, not underneath the file.
    """
    base = Path(cat_data.local_path).expanduser()
    if resolves_to_parent(cat_data, base):
        return base.parent
    return base


def _hash_target(path: Path, item_type: str) -> str | None:
    if not path.exists():
        return None
    if item_type == "directory":
        return directory_hash(path)
    return file_hash(path)


def _sticky_pre_existing(receipt: DeployReceipt) -> dict[str, bool]:
    """Every TARGET PATH any install record already accounts for.

    `pre_existing` answers "did this target exist before SCCS ever wrote
    there" — a fact from the FIRST install, not from the current one. Asking
    `target.exists()` again on a reinstall answers "did the previous install
    put something there", which is True for everything we wrote and would
    turn the whole receipt into a list of artefacts revoke must not touch.

    Records of other profiles count too: two profiles can ship the same
    skill, and whichever installed first is the one that saw the host
    untouched.

    The key is the resolved absolute target, NOT `(category, name)`. A
    category's `local_path` is not fixed for all time — a maintainer edits
    the config, or a second export machine has a different layout — and the
    same `(category, name)` then resolves to a DIFFERENT directory. Keyed on
    the pair, the claim from the old path answers "ours" for a path no
    install has ever touched, and the fresh `target.exists()` check that
    would have caught the customer's file there never runs at all.
    """
    claimed: dict[str, bool] = {}
    for record in receipt.installs:
        for entry in record.entries:
            # An earlier "this was already here" wins: once a target has been
            # seen as foreign, no later install may promote it to ours.
            claimed[entry.target] = claimed.get(entry.target, False) or entry.pre_existing
    return claimed


def install_bundle(
    zip_path: Path,
    *,
    config: SccsConfig | None,
    receipt_manager: ReceiptManager,
    dry_run: bool = False,
    overwrite: bool = True,
) -> InstallOutcome:
    """Install a deployment bundle and record what was written.

    Ownership rule, the same line the Codex export draws between a target
    SCCS wrote and one holding somebody's hand edits:

    * A target SCCS itself installed (a receipt entry exists for it and says
      it is ours) is refreshed, so a deployment never ships stale artefacts.
    * A target that exists but SCCS did not write is never displaced: it is
      recorded `pre_existing=True`, skipped, and reported in
      `InstallOutcome.skipped_foreign`.

    Args:
        zip_path: The bundle produced by `sccs deploy export`.
        config: Local SCCS config, or None on a host that has none.
        receipt_manager: Where the receipt is written.
        dry_run: Preview only — nothing is written, no receipt.
        overwrite: Refresh targets SCCS previously installed. Never applies
            to foreign targets — those are skipped regardless.
    """
    importer = Importer(zip_path, config=config)

    try:
        manifest = importer.load_manifest()
    except (ValueError, OSError) as e:
        return InstallOutcome(success=False, errors=[f"Cannot read bundle: {e}"])

    # Read the receipt BEFORE anything is written. A corrupt receipt found
    # after the copy leaves files on the host with no record of them, which
    # makes `deploy status` say "nothing installed" and `revoke` say "nothing
    # to revoke" — the exact failure this feature must not have.
    try:
        receipt = receipt_manager.load()
    except ValueError as e:
        return InstallOutcome(success=False, errors=[str(e)])

    # Does ~/.config/sccs/ belong to the host user? Sticky, like pre_existing:
    # once an install has seen the directory there, later installs must not
    # decide it is ours just because we have been writing the receipt into it.
    if receipt.installs:
        state_dir_pre_existing = any(r.state_dir_pre_existing for r in receipt.installs)
    else:
        state_dir_pre_existing = receipt_manager.path.parent.exists()

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

    # Decide ownership BEFORE the import writes anything.
    claimed = _sticky_pre_existing(receipt)
    pre_existing: dict[tuple[str, str], bool] = {}
    bases: dict[str, Path] = {}
    to_import: list[tuple[str, ManifestItem]] = []
    skipped_foreign: list[str] = []

    for cat_name, item in selections:
        cat_data = manifest.categories[cat_name]
        base = _category_base(cat_data)
        bases[cat_name] = base
        key = (cat_name, item.name)
        target = _target_path(base, item)
        # A path no record accounts for gets the only honest answer there is:
        # whatever is on disk right now.
        is_foreign = claimed[str(target)] if str(target) in claimed else target.exists()
        pre_existing[key] = is_foreign
        if is_foreign:
            skipped_foreign.append(f"{cat_name}/{item.name}")
        else:
            to_import.append((cat_name, item))

    # backup=False on purpose. Nothing foreign is ever written over, so the
    # only thing a backup could hold is a previous copy of OUR artefact — and
    # ~/.config/sccs/backups/ on a customer host is one more place our
    # knowledge would sit after `revoke` (which keeps that directory when the
    # host user runs sccs themselves). Nothing to preserve, something to leak.
    result = importer.apply(to_import, dry_run=dry_run, overwrite=overwrite, backup=False)

    if dry_run:
        return InstallOutcome(
            success=result.success,
            profile=section.profile,
            installed=len(to_import),
            skipped=len(skipped_foreign),
            errors=list(result.errors),
            skipped_foreign=skipped_foreign,
        )

    # For every target we refused to write: what the bundle WOULD have put
    # there. "The customer already had a file here" and "the customer's file
    # IS our file" are different facts, and only this hash separates them at
    # revoke time. Hashed from the staging area, so nothing is written.
    skipped_selections = [(c, i) for c, i in selections if pre_existing[(c, i.name)]]
    shipped_hashes = importer.staged_hashes(skipped_selections)

    entries: list[ReceiptEntry] = []
    for cat_name, item in selections:
        target = _target_path(bases[cat_name], item)
        if not target.exists():
            continue
        is_foreign = pre_existing[(cat_name, item.name)]
        entries.append(
            ReceiptEntry(
                category=cat_name,
                name=item.name,
                target=str(target),
                item_type=item.item_type,
                content_hash=_hash_target(target, item.item_type),
                pre_existing=is_foreign,
                # Recorded, not inferred: the one thing revoke may trust
                # when it decides that a leftover is not ours.
                written_by_sccs=not is_foreign,
                shipped_hash=shipped_hashes.get((cat_name, item.name)) if is_foreign else None,
            )
        )

    record = InstallRecord(
        profile=section.profile,
        installed_at=datetime.now(timezone.utc).isoformat(),
        sccs_version=__version__,
        retain=list(section.retain),
        sweep_globs={k: list(v) for k, v in section.sweep_globs.items()},
        entries=entries,
        state_dir_pre_existing=state_dir_pre_existing,
    )
    receipt_manager.record_install(record)
    logger.info(
        "Installed profile %s: %d artefacts, %d foreign targets skipped",
        section.profile,
        len(entries),
        len(skipped_foreign),
    )

    installed = sum(1 for e in entries if not e.pre_existing)
    return InstallOutcome(
        success=result.success,
        profile=section.profile,
        installed=installed,
        skipped=len(selections) - installed,
        errors=list(result.errors),
        record=record,
        skipped_foreign=skipped_foreign,
    )
