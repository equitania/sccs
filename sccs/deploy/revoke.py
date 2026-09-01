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

# Why a sweep finding is on the list. Only NOT_OURS is not a failure.
SWEEP_PLANNED_SURVIVOR = "planned_survivor"
SWEEP_UNRECORDED = "unrecorded"
SWEEP_OURS = "ours"
SWEEP_CONTENT_MATCH = "content_match"
SWEEP_NOT_OURS = "not_ours"

SWEEP_REASON_LABELS = {
    SWEEP_PLANNED_SURVIVOR: "planned for removal and still here",
    SWEEP_UNRECORDED: "a name this bundle ships with no receipt entry — an install wrote without recording it",
    SWEEP_OURS: "the receipt records that SCCS wrote here",
    SWEEP_CONTENT_MATCH: "byte-identical to the artefact this bundle ships — our knowledge, whoever put it there",
    SWEEP_NOT_OURS: "recorded as never written by SCCS, and its content differs from ours",
}


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
class SweepFinding:
    """One artefact the verification sweep still found on the host."""

    path: str
    category: str
    name: str
    reason: str
    profile: str | None = None
    # False only for case 3: an entry that POSITIVELY records SCCS never
    # wrote there and whose content is not the artefact we ship.
    failure: bool = True


@dataclass
class RevokeResult:
    """Outcome of a revoke, including what the sweep found."""

    success: bool
    removed: int = 0
    errors: list[str] = field(default_factory=list)
    # Findings that fail the revoke — everything this tool cannot prove it
    # did not write.
    leftovers: list[str] = field(default_factory=list)
    # Case 3: reported so the operator sees the whole picture, but not a
    # failure. `claude_framework` ships CLAUDE.md and Claude Code creates
    # ~/.claude/CLAUDE.md on nearly every host, so treating this as a
    # failure would exit non-zero on essentially every customer machine —
    # an alarm that always fires is an alarm nobody reads.
    benign_leftovers: list[str] = field(default_factory=list)
    findings: list[SweepFinding] = field(default_factory=list)


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


def _classify(entry: ReceiptEntry | None, candidate: Path) -> tuple[str, bool]:
    """Decide whether one surviving artefact is a failure. Three-way rule.

    1. No receipt entry at all (`entry is None`) → failure. That is the
       signature of an install that wrote files without recording them, and
       there is nothing to re-derive the artefact from later.
    2. An entry that does NOT positively record "SCCS never wrote here",
       or whose on-disk content is byte-identical to what the bundle ships
       → failure. `written_by_sccs` is the record; `pre_existing` is an
       inference an older build got wrong on its own artefacts, so it is
       never consulted here. And content decides where ownership cannot:
       if their file IS our file, our knowledge is on that host.
    3. Recorded as never written by us AND holding different content →
       reported, clearly labelled, but not a failure. `claude_framework`
       ships CLAUDE.md and Claude Code writes ~/.claude/CLAUDE.md on nearly
       every host; failing there would fail on every customer machine.
    """
    if entry is None:
        return SWEEP_UNRECORDED, True
    if entry.written_by_sccs:
        return SWEEP_OURS, True
    if entry.shipped_hash and _current_hash(candidate, entry.item_type) == entry.shipped_hash:
        return SWEEP_CONTENT_MATCH, True
    return SWEEP_NOT_OURS, False


def sweep_findings(plan: RevokePlan) -> list[SweepFinding]:
    """Verify the host, not the bookkeeping. Returns what is still there.

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
    every name the profile shipped that is still on disk is reported, and
    `_classify` then decides which of them fail the revoke. Only two things
    are excluded outright, because for them "still present" is the intended
    outcome, not a leak:

    * categories in the record's `retain` (shell config stays by design), and
    * entries bucketed `shared`, still claimed by another installed profile.
    """
    findings: list[SweepFinding] = []
    seen: set[str] = set()

    def _note(path: Path, *, category: str, name: str, reason: str, profile: str | None, failure: bool) -> None:
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        findings.append(
            SweepFinding(path=key, category=category, name=name, reason=reason, profile=profile, failure=failure)
        )

    for item in plan.to_remove:
        target = Path(item.entry.target)
        if target.exists():
            _note(
                target,
                category=item.entry.category,
                name=item.entry.name,
                reason=SWEEP_PLANNED_SURVIVOR,
                profile=item.profile,
                failure=True,
            )

    shared_claims = {(i.entry.category, i.entry.name) for i in plan.shared}

    for record in plan.records:
        dirs = _category_dirs(record)
        by_key = {(e.category, e.name): e for e in record.entries}
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
                if not candidate.exists():
                    continue
                reason, failure = _classify(by_key.get((category, name)), candidate)
                _note(
                    candidate,
                    category=category,
                    name=name,
                    reason=reason,
                    profile=record.profile,
                    failure=failure,
                )

    return findings


def sweep(plan: RevokePlan) -> list[str]:
    """Every shipped name still on the host — failing or not.

    Kept as the human-facing view: the operator is shown everything the
    sweep saw. `execute_revoke` works from `sweep_findings` instead, because
    only that carries the failure verdict per finding.
    """
    return [f.path for f in sweep_findings(plan)]


def execute_revoke(
    plan: RevokePlan,
    receipt_manager: ReceiptManager,
    *,
    dry_run: bool = False,
) -> RevokeResult:
    """Carry out the plan, then verify it actually happened.

    A profile keeps its receipt record whenever the sweep finds anything
    attributable to it that this tool cannot prove it did not write — a
    removal error, a planned removal that survived, an unrecorded artefact,
    or a foreign target holding our content. Only case 3 of `_classify`
    (recorded as never written by us, different content) lets the record
    go. A profile that failed keeps its record so a retry can still find
    what it left behind; dropping it would report "nothing to revoke" on a
    host that is still full of our artefacts, which is the one failure the
    receipt's own `load()` docstring says this feature must not have.
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

    findings = sweep_findings(plan)
    failures = [f for f in findings if f.failure]
    benign = [f for f in findings if not f.failure]

    if failures:
        logger.error("Revoke left %d artefacts behind", len(failures))
    # Every failing finding costs its profile the receipt record, not just a
    # planned removal that survived. A second-pass finding is the one that
    # most needs the record kept: an `unrecorded` artefact has no entry to
    # re-derive its directory from, so dropping the record means the sweep
    # can never find it again — the next run would print "Nothing to revoke
    # on this host", exit 0, and leave it standing.
    for finding in failures:
        if finding.profile:
            failed_profiles.add(finding.profile)

    for profile in plan.profiles:
        if profile not in failed_profiles:
            receipt_manager.remove_install(profile)

    return RevokeResult(
        success=not errors and not failures,
        removed=removed,
        errors=errors,
        leftovers=[f.path for f in failures],
        benign_leftovers=[f.path for f in benign],
        findings=findings,
    )
