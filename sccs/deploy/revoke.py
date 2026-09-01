# `sccs deploy revoke` — take our knowledge back off a foreign host.
#
# Reads only the receipt, so it works where there is no SCCS config. Ends
# with a verification sweep: a removal that reports success while a skill
# directory survived is the worst possible outcome of this feature, because
# the report is what the decision to stop looking is based on.

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sccs.deploy.receipt import InstallRecord, ReceiptEntry, ReceiptManager
from sccs.deploy.traces import TraceTarget, enumerate_traces, remove_traces
from sccs.doctor._paths import is_home_path
from sccs.utils.hashing import directory_hash, file_hash
from sccs.utils.logging import get_logger

logger = get_logger("sccs.deploy")

BUCKET_REMOVE = "remove"
BUCKET_RETAIN = "retain"
BUCKET_UNTOUCHED = "untouched"
BUCKET_GONE = "gone"
BUCKET_SHARED = "shared"


@dataclass
class RevokeItem:
    """One receipt entry with its verdict."""

    entry: ReceiptEntry
    bucket: str
    modified: bool = False
    # Which install record this entry came from. Used to attribute a
    # removal error or a leftover back to its profile, so only the
    # profiles that actually finished cleanly lose their receipt record.
    profile: str | None = None


@dataclass
class RevokePlan:
    """What a revoke would do, before it does it."""

    profiles: list[str] = field(default_factory=list)
    items: list[RevokeItem] = field(default_factory=list)
    traces: list[TraceTarget] = field(default_factory=list)
    purge_traces: bool = True
    # The install records being revoked. The verification sweep works from
    # these — their `sweep_globs` — rather than from the per-entry buckets,
    # because the whole point of the sweep is to not trust that bookkeeping.
    records: list[InstallRecord] = field(default_factory=list)
    # True when ~/.config/sccs/ was the host user's own before we arrived, so
    # the trace purge leaves it alone and takes only the receipt.
    keep_state_dir: bool = False

    def _bucket(self, bucket: str) -> list[RevokeItem]:
        return [i for i in self.items if i.bucket == bucket]

    @property
    def to_remove(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_REMOVE)

    @property
    def retained(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_RETAIN)

    @property
    def untouched(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_UNTOUCHED)

    @property
    def already_gone(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_GONE)

    @property
    def shared(self) -> list[RevokeItem]:
        return self._bucket(BUCKET_SHARED)

    @property
    def modified(self) -> list[RevokeItem]:
        return [i for i in self.items if i.modified]


@dataclass
class RevokeResult:
    """Outcome of a revoke, including what the sweep found."""

    success: bool
    removed: int = 0
    errors: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)


def _current_hash(path: Path, item_type: str) -> str | None:
    if not path.exists():
        return None
    return directory_hash(path) if item_type == "directory" else file_hash(path)


def build_revoke_plan(
    receipt_manager: ReceiptManager,
    *,
    profile: str | None = None,
    keep_traces: bool = False,
    home: Path | None = None,
) -> RevokePlan:
    """Sort the receipt into buckets and decide the trace policy.

    Args:
        profile: Revoke only this profile. Default: every installed one.
        keep_traces: Leave transcripts, plans, todos and history in place.
        home: Root for trace enumeration. Defaults to the real home.

    Raises:
        ValueError: If the receipt cannot be read, or if `profile` names a
            profile that is not installed. A typo must not be answered with
            "nothing to revoke" and exit 0 — that reads as a clean host.
    """
    receipt = receipt_manager.load()
    records = [r for r in receipt.installs if profile is None or r.profile == profile]
    remaining = [r for r in receipt.installs if r not in records]

    if profile is not None and not records:
        installed = ", ".join(sorted(r.profile for r in receipt.installs))
        raise ValueError(f"No install record for profile '{profile}' on this host. Installed: {installed or 'nothing'}")

    # (category, name) pairs still claimed by an install that is NOT being
    # revoked. Two profiles can ship the same skill (e.g. "odoo-common"
    # under both "odoo-server" and "fastreport") — revoking one must not
    # pull the artefact out from under the other.
    remaining_claims = {(e.category, e.name) for r in remaining for e in r.entries}

    plan = RevokePlan(profiles=[r.profile for r in records], records=list(records))

    for record in records:
        for entry in record.entries:
            target = Path(entry.target)
            if entry.pre_existing:
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_UNTOUCHED, profile=record.profile))
                continue
            if entry.category in record.retain:
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_RETAIN, profile=record.profile))
                continue
            if not target.exists():
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_GONE, profile=record.profile))
                continue
            if (entry.category, entry.name) in remaining_claims:
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_SHARED, profile=record.profile))
                continue

            # A modified artefact is still removed — it still carries our
            # knowledge. The flag exists so the decision is visible rather
            # than inherited.
            now = _current_hash(target, entry.item_type)
            modified = bool(entry.content_hash) and now != entry.content_hash
            plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_REMOVE, modified=modified, profile=record.profile))

    # Traces belong to no single profile: purge them only when the last
    # install goes. Otherwise removing one of two profiles would delete
    # transcripts the other is still producing.
    plan.purge_traces = bool(records) and not remaining and not keep_traces

    # ~/.config/sccs/ is only ours to purge when we created it. `sccs` stays
    # installed as a public tool, so a host user who runs it themselves keeps
    # their config.yaml, sync state and backups; only the receipt goes.
    plan.keep_state_dir = any(r.state_dir_pre_existing for r in records)

    if plan.purge_traces:
        plan.traces = [t for t in enumerate_traces(home, include_sccs_state=not plan.keep_state_dir) if t.exists]

    return plan


def _category_dirs(record: InstallRecord) -> dict[str, Path]:
    """Where each category's artefacts live, derived from the record itself.

    The customer host has no config.yaml of ours, so the only description of
    the layout that travelled with the deployment is the recorded absolute
    target of each entry. All entries of one category share a parent.
    """
    dirs: dict[str, Path] = {}
    for entry in record.entries:
        dirs.setdefault(entry.category, Path(entry.target).parent)
    return dirs


def sweep(plan: RevokePlan) -> list[str]:
    """Verify the host, not the bookkeeping. Returns paths still present.

    Two passes, and the second is the one the spec asks for:

    1. Re-stat every planned removal.
    2. Re-scan the known locations against each revoked record's
       `sweep_globs` — the list of names the bundle actually shipped —
       independently of how the per-entry buckets turned out.

    Pass 2 exists precisely because pass 1 can only find what the
    bookkeeping already admits to. An entry wrongly marked `pre_existing`,
    or an artefact written before a crash left no receipt entry at all, is
    invisible to pass 1 and is exactly what a "sweep clean" report must not
    cover up. So this pass deliberately does NOT filter on `pre_existing`:
    a name the profile shipped that is still on disk gets reported, and the
    operator decides. Only two things are excluded, because for them
    "still present" is the intended outcome, not a leak:

    * categories in the record's `retain` (shell config stays by design), and
    * entries bucketed `shared`, still claimed by another installed profile.
    """
    leftovers: list[str] = []
    seen: set[str] = set()

    def _note(path: Path) -> None:
        key = str(path)
        if key not in seen:
            seen.add(key)
            leftovers.append(key)

    for item in plan.to_remove:
        target = Path(item.entry.target)
        if target.exists():
            _note(target)

    shared_claims = {(i.entry.category, i.entry.name) for i in plan.shared}

    for record in plan.records:
        dirs = _category_dirs(record)
        for category, names in record.sweep_globs.items():
            if category in record.retain:
                continue
            base = dirs.get(category)
            if base is None:
                # No entry of that category was ever recorded, so the record
                # does not say where it would live. Nothing to re-scan.
                continue
            for name in names:
                if (category, name) in shared_claims:
                    continue
                candidate = base / name
                if candidate.exists():
                    _note(candidate)

    return leftovers


def execute_revoke(
    plan: RevokePlan,
    receipt_manager: ReceiptManager,
    *,
    dry_run: bool = False,
) -> RevokeResult:
    """Carry out the plan, then verify it actually happened.

    The receipt record for a profile is dropped only once every one of
    that profile's own entries is confirmed gone (no removal error, and no
    leftover surviving the final sweep). A profile that failed keeps its
    record, so a retry can still find what it left behind — dropping it
    unconditionally would report "nothing to remove" on a host that is
    still full of our artefacts, which is the one failure the receipt's
    own `load()` docstring says this feature must not have.
    """
    if dry_run:
        return RevokeResult(success=True, removed=len(plan.to_remove))

    errors: list[str] = []
    removed = 0
    failed_profiles: set[str] = set()

    for item in plan.to_remove:
        target = Path(item.entry.target)
        # The receipt is ours and written 0600, but it is the one place a
        # corrupted or hand-edited receipt could point a recursive delete
        # outside the customer's home. No legitimate entry can land here —
        # Task 5's install guard already refuses such categories — so this
        # only ever fires against a broken receipt.
        if not is_home_path(str(target)):
            errors.append(f"{target}: outside home — refusing to remove")
            if item.profile:
                failed_profiles.add(item.profile)
            continue
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed += 1
            logger.info("Removed %s (%s)", target, item.entry.category)
        except OSError as e:
            errors.append(f"{target}: {e}")
            if item.profile:
                failed_profiles.add(item.profile)

    if plan.purge_traces:
        errors.extend(remove_traces(plan.traces))

    leftovers = sweep(plan)
    if leftovers:
        logger.error("Revoke left %d artefacts behind", len(leftovers))
        leftover_paths = set(leftovers)
        # Only a PLANNED removal that survived costs its profile the receipt
        # record — a retry needs that pointer. A finding from the sweep's
        # second pass does not: it was found without the per-entry
        # bookkeeping and would be found again, and keeping the record on
        # every such finding would make a host where the customer's own copy
        # of a shipped skill name lives permanently un-revokable.
        for item in plan.to_remove:
            if item.profile and str(Path(item.entry.target)) in leftover_paths:
                failed_profiles.add(item.profile)

    for profile in plan.profiles:
        if profile not in failed_profiles:
            receipt_manager.remove_install(profile)

    return RevokeResult(
        success=not errors and not leftovers,
        removed=removed,
        errors=errors,
        leftovers=leftovers,
    )
