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
from sccs.utils.hashing import directory_hash, file_hash
from sccs.utils.logging import get_logger

logger = get_logger("sccs.deploy")

BUCKET_REMOVE = "remove"
BUCKET_RETAIN = "retain"
BUCKET_UNTOUCHED = "untouched"
BUCKET_GONE = "gone"


@dataclass
class RevokeItem:
    """One receipt entry with its verdict."""

    entry: ReceiptEntry
    bucket: str
    modified: bool = False


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

    plan = RevokePlan(profiles=[r.profile for r in records])

    for record in records:
        for entry in record.entries:
            target = Path(entry.target)
            if entry.pre_existing:
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_UNTOUCHED))
                continue
            if entry.category in record.retain:
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_RETAIN))
                continue
            if not target.exists():
                plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_GONE))
                continue

            # A modified artefact is still removed — it still carries our
            # knowledge. The flag exists so the decision is visible rather
            # than inherited.
            now = _current_hash(target, entry.item_type)
            modified = bool(entry.content_hash) and now != entry.content_hash
            plan.items.append(RevokeItem(entry=entry, bucket=BUCKET_REMOVE, modified=modified))

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
    """Carry out the plan, then verify it actually happened."""
    if dry_run:
        return RevokeResult(success=True, removed=len(plan.to_remove))

    errors: list[str] = []
    removed = 0

    for item in plan.to_remove:
        target = Path(item.entry.target)
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed += 1
            logger.info("Removed %s (%s)", target, item.entry.category)
        except OSError as e:
            errors.append(f"{target}: {e}")

    if plan.purge_traces:
        errors.extend(remove_traces(plan.traces))

    for profile in plan.profiles:
        receipt_manager.remove_install(profile)

    leftovers = sweep(plan)
    if leftovers:
        logger.error("Revoke left %d artefacts behind", len(leftovers))

    return RevokeResult(
        success=not errors and not leftovers,
        removed=removed,
        errors=errors,
        leftovers=leftovers,
    )
