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

import json
from datetime import datetime, timezone
from pathlib import Path

from sccs.capacity.schema import ProviderCapacity, QuotaScope, QuotaWindow
from sccs.doctor.runner import DoctorError, _run, which

# Codex writes one rollout file per session; the newest one carries the most
# recent rate_limits snapshot. We scan a handful in case the newest session was
# too short to receive one.
_MAX_ROLLOUTS_SCANNED = 5

# `agy -p "/usage"` is a real (if tiny) request. Cap it so a hung backend cannot
# stall an orchestration decision.
_AGY_TIMEOUT_SECONDS = 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    """Render a UTC timestamp as ISO-8601 with a literal Z (not '+00:00')."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
# Codex
# --------------------------------------------------------------------------


def _find_rate_limits(obj: object) -> dict | None:
    """Depth-first search for a ``rate_limits`` mapping anywhere in a rollout event.

    Codex has moved this payload between nesting levels across releases, so the
    key is located structurally rather than at a hardcoded path.
    """
    if isinstance(obj, dict):
        candidate = obj.get("rate_limits")
        if isinstance(candidate, dict):
            return candidate
        for value in obj.values():
            found = _find_rate_limits(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_rate_limits(value)
            if found is not None:
                return found
    return None


def parse_codex_rate_limits(payload: dict, *, now: datetime | None = None) -> QuotaScope:
    """Convert a Codex ``rate_limits`` mapping into a QuotaScope.

    Codex names its windows ``primary`` (rolling 5h) and ``secondary`` (weekly)
    and reports ``used_percent``; remaining is derived so both providers expose
    the same field to a caller.
    """
    now = now or _utc_now()
    scope = QuotaScope(name=str(payload.get("limit_id") or "codex"))
    for key in ("primary", "secondary"):
        entry = payload.get(key)
        if not isinstance(entry, dict):
            continue
        minutes = entry.get("window_minutes")
        minutes = int(minutes) if isinstance(minutes, (int, float)) else None
        used = entry.get("used_percent")
        used = float(used) if isinstance(used, (int, float)) else None
        raw_reset = entry.get("resets_at")
        reset_dt = (
            datetime.fromtimestamp(float(raw_reset), tz=timezone.utc) if isinstance(raw_reset, (int, float)) else None
        )
        iso, minutes_until, expired = _reset_fields(reset_dt, now)
        scope.windows.append(
            QuotaWindow(
                name=_window_name(minutes),
                window_minutes=minutes,
                remaining_percent=None if used is None else round(100.0 - used, 2),
                used_percent=used,
                resets_at=iso,
                resets_in_minutes=minutes_until,
                expired=expired,
            )
        )
    return scope


def is_codex_exhausted(payload: dict) -> bool:
    """True when a Codex ``rate_limits`` payload reports a spent plan quota.

    Observed shape once the limit is hit (30.08.2026)::

        {"limit_id": "premium", "primary": null, "secondary": null,
         "credits": {"has_credits": false, "unlimited": false, "balance": "0"}}

    Both windows go null and the credit balance is empty — at the same moment
    the Codex TUI prints "You've hit your usage limit ... try again at 3:00 PM".
    Null windows alone are NOT enough: a payload can lack them for other
    reasons, and calling that exhaustion would send work to a healthy provider's
    fallback for no reason. The empty credit balance is the corroborating half.
    """
    if any(isinstance(payload.get(key), dict) for key in ("primary", "secondary")):
        return False
    credits = payload.get("credits")
    if not isinstance(credits, dict):
        return False
    if credits.get("unlimited") is True or credits.get("has_credits") is True:
        return False
    balance = str(credits.get("balance", "")).strip()
    return balance in {"", "0", "0.0", "0.00"}


def _newest_rollouts(sessions_dir: Path, limit: int = _MAX_ROLLOUTS_SCANNED) -> list[Path]:
    if not sessions_dir.is_dir():
        return []
    files = [p for p in sessions_dir.rglob("*.jsonl") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def _last_rate_limits_in(path: Path) -> tuple[dict, str | None] | None:
    """Return the last ``rate_limits`` payload in a rollout file, plus its timestamp.

    Reads line by line and keeps only the newest match, so a multi-megabyte
    session file never lands in memory whole.
    """
    newest: tuple[dict, str | None] | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"rate_limits"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                found = _find_rate_limits(event)
                if found is not None:
                    stamp = event.get("timestamp") if isinstance(event, dict) else None
                    newest = (found, stamp if isinstance(stamp, str) else None)
    except OSError:
        return None
    return newest


def probe_codex(
    *,
    home: Path | None = None,
    now: datetime | None = None,
) -> ProviderCapacity:
    """Read Codex plan quota from its own session records.

    Costs nothing and needs no network, but is only as fresh as the user's last
    Codex session — hence source="session-cache" and an explicit observed_at.
    """
    now = now or _utc_now()
    home = home or Path.home()
    result = ProviderCapacity(provider="codex", installed=which("codex") is not None)

    sessions_dir = home / ".codex" / "sessions"
    for rollout in _newest_rollouts(sessions_dir):
        found = _last_rate_limits_in(rollout)
        if found is None:
            continue
        payload, stamp = found
        result.source = "session-cache"
        result.observed_at = stamp or _iso(datetime.fromtimestamp(rollout.stat().st_mtime, tz=timezone.utc))
        result.scopes = [parse_codex_rate_limits(payload, now=now)]
        result.exhausted = is_codex_exhausted(payload)
        if result.exhausted:
            result.note = (
                "Plan quota spent: Codex reports both windows as null with an empty credit "
                "balance. It will refuse work until the window resets."
            )
        else:
            result.note = "Read from the newest Codex session record; run Codex once to refresh."
        return result

    if not result.installed:
        result.error = "codex binary not found on PATH"
    elif not sessions_dir.is_dir():
        result.error = f"no Codex session directory at {sessions_dir}"
    else:
        result.error = "no rate_limits snapshot in the recent Codex sessions"
    return result


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
