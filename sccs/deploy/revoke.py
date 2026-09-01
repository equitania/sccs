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

from sccs.deploy.receipt import ReceiptEntry, ReceiptManager
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
    """
    receipt = receipt_manager.load()
    records = [r for r in receipt.installs if profile is None or r.profile == profile]
    remaining = [r for r in receipt.installs if r not in records]

    # (category, name) pairs still claimed by an install that is NOT being
    # revoked. Two profiles can ship the same skill (e.g. "odoo-common"
    # under both "odoo-server" and "fastreport") — revoking one must not
    # pull the artefact out from under the other.
    remaining_claims = {(e.category, e.name) for r in remaining for e in r.entries}

    plan = RevokePlan(profiles=[r.profile for r in records])

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
    if plan.purge_traces:
        plan.traces = [t for t in enumerate_traces(home) if t.exists]

    return plan


def sweep(plan: RevokePlan) -> list[str]:
    """Re-check every planned removal. Returns paths that are still there."""
    leftovers: list[str] = []
    for item in plan.to_remove:
        target = Path(item.entry.target)
        if target.exists():
            leftovers.append(str(target))
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
