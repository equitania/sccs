# SCCS Capacity Probes
#
# One probe per provider. Every probe degrades to a ProviderCapacity with
# source="unavailable" plus an error string instead of raising: a supervisor
# asking "how much is left?" must always get an answer it can route on, even
# when one CLI is missing or misbehaving.
#
# Parsing is split from I/O on purpose — the `parse_*` functions are pure and
# carry the test coverage; the `probe_*` functions only locate bytes and hand
# them over.

from __future__ import annotations

from datetime import UTC, datetime

from sccs.capacity.schema import ProviderCapacity, QuotaScope, QuotaWindow
from sccs.doctor.runner import DoctorError, _run, which

# `agy -p "/usage"` is a real (if tiny) request. Cap it so a hung backend cannot
# stall an orchestration decision.
_AGY_TIMEOUT_SECONDS = 60


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    """Render a UTC timestamp as ISO-8601 with a literal Z (not '+00:00')."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _window_name(minutes: int | None) -> str:
    """Map a window length onto the label a human and a router both recognise."""
    if minutes is None:
        return "unknown"
    if minutes == 300:
        return "5h"
    if minutes == 10080:
        return "weekly"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}min"


def _reset_fields(resets_at: datetime | None, now: datetime) -> tuple[str | None, int | None, bool]:
    """Return (iso, minutes_until, expired) for a reset moment."""
    if resets_at is None:
        return None, None, False
    delta = (resets_at - now).total_seconds()
    return _iso(resets_at), int(delta // 60), delta <= 0


# --------------------------------------------------------------------------
# Antigravity
# --------------------------------------------------------------------------

# `/usage` labels its rows in prose; map them onto the shared window names.
_AGY_WINDOW_LABELS = {
    "weekly limit remaining": ("weekly", 10080),
    "five hour limit remaining": ("5h", 300),
}


def parse_antigravity_usage(text: str, *, now: datetime | None = None) -> list[QuotaScope]:
    """Parse the tab-separated table printed by ``agy -p "/usage"``.

    Each row is ``<model family>\\t<window label>\\t<remaining>%\\t<reset ISO>``.
    Rows that do not match are skipped rather than failing the whole probe —
    the CLI prepends progress chatter on some runs.
    """
    now = now or _utc_now()
    scopes: dict[str, QuotaScope] = {}
    for raw in text.splitlines():
        parts = [p.strip() for p in raw.split("\t")]
        if len(parts) < 4:
            continue
        family, label, remaining_raw, reset_raw = parts[0], parts[1], parts[2], parts[3]
        mapped = _AGY_WINDOW_LABELS.get(label.lower())
        if not family or mapped is None:
            continue
        window_name, window_minutes = mapped
        try:
            remaining = float(remaining_raw.rstrip("%"))
        except ValueError:
            continue
        try:
            reset_dt = datetime.fromisoformat(reset_raw.replace("Z", "+00:00"))
        except ValueError:
            reset_dt = None
        iso, minutes_until, expired = _reset_fields(reset_dt, now)
        scope = scopes.setdefault(family, QuotaScope(name=family))
        scope.windows.append(
            QuotaWindow(
                name=window_name,
                window_minutes=window_minutes,
                remaining_percent=remaining,
                used_percent=round(100.0 - remaining, 2),
                resets_at=iso,
                resets_in_minutes=minutes_until,
                expired=expired,
            )
        )
    return list(scopes.values())


def probe_antigravity(
    *,
    offline: bool = False,
    now: datetime | None = None,
    runner=None,
) -> ProviderCapacity:
    """Query Antigravity's live quota panel through print mode.

    ``agy`` exposes no ``usage`` subcommand, but slash commands are expanded in
    ``--print`` mode, so ``agy -p "/usage"`` yields the same table the
    interactive panel shows. That is a real request against the account, which
    is why ``offline`` skips it.
    """
    now = now or _utc_now()
    result = ProviderCapacity(provider="antigravity", installed=which("agy") is not None)

    if not result.installed:
        result.error = "agy binary not found on PATH"
        return result
    if offline:
        result.note = "live probe skipped (--offline); Antigravity has no local quota cache"
        return result

    run = runner or _run
    try:
        proc = run(
            ["agy", "-p", "/usage", "--print-timeout", "30s"],
            check=False,
            timeout=_AGY_TIMEOUT_SECONDS,
        )
    except DoctorError as err:
        result.error = str(err)
        return result

    scopes = parse_antigravity_usage(proc.stdout or "", now=now)
    if not scopes:
        result.error = "could not parse the /usage table"
        return result

    result.source = "live"
    result.observed_at = _iso(now)
    result.scopes = scopes
    return result


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------


def probe_claude(*, now: datetime | None = None) -> ProviderCapacity:
    """Report Claude Code without inventing numbers.

    Claude Code keeps no machine-readable quota cache on disk and exposes
    ``/usage`` only inside an interactive session, so the honest answer is
    "installed, quota unknown". Routing treats it as the fallback reserve
    rather than reading a figure that does not exist.
    """
    result = ProviderCapacity(provider="claude_code", installed=which("claude") is not None)
    if not result.installed:
        result.error = "claude binary not found on PATH"
        return result
    result.source = "assumed"
    result.observed_at = _iso(now or _utc_now())
    result.note = "No local quota cache; /usage is interactive only. Treated as the fallback reserve."
    return result
