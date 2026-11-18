# SCCS Capacity Report
#
# Assembles the per-provider probes into one report and derives the routing
# hints a supervising agent acts on. The derivation lives here rather than in a
# prompt so it is testable and identical on every host — a supervisor that has
# to re-derive "is Gemini tight?" from raw percentages gets it wrong differently
# every session.

from __future__ import annotations

from datetime import UTC, datetime

from sccs.capacity.probes import (
    _iso,
    _utc_now,
    probe_antigravity,
    probe_claude,
)
from sccs.capacity.schema import (
    LOW_REMAINING_PERCENT,
    CapacityReport,
    ProviderCapacity,
    QuotaScope,
    RoutingAdvice,
)

FREE = "free"
TIGHT = "tight"
UNKNOWN = "unknown"


def _scope_remaining(scope: QuotaScope) -> float | None:
    """Smallest effective remaining share across a scope's windows."""
    values = [w.effective_remaining for w in scope.windows if w.effective_remaining is not None]
    return min(values) if values else None


def _provider_remaining(provider: ProviderCapacity | None) -> float | None:
    if provider is None:
        return None
    values = [v for v in (_scope_remaining(s) for s in provider.scopes) if v is not None]
    return min(values) if values else None


def _status(remaining: float | None) -> str:
    """Classify a remaining share.

    UNKNOWN is deliberately distinct from TIGHT: missing data is not evidence of
    exhaustion, and treating it as such would push paid work onto the billed API
    for no reason.
    """
    if remaining is None:
        return UNKNOWN
    return TIGHT if remaining < LOW_REMAINING_PERCENT else FREE


def _find(providers: list[ProviderCapacity], name: str) -> ProviderCapacity | None:
    return next((p for p in providers if p.provider == name), None)


def _gemini_scope(provider: ProviderCapacity | None) -> QuotaScope | None:
    """Antigravity bills Gemini separately from the Claude/GPT models it resells."""
    if provider is None:
        return None
    return next((s for s in provider.scopes if "gemini" in s.name.lower()), None)


def _window(provider: ProviderCapacity | None, scope_name_part: str, window_name: str):
    if provider is None:
        return None
    for scope in provider.scopes:
        if scope_name_part and scope_name_part not in scope.name.lower():
            continue
        for window in scope.windows:
            if window.name == window_name:
                return window
    return None


def _usable(provider: ProviderCapacity | None, status: str) -> bool:
    """A provider is routable when it is installed, not tight, and not exhausted.

    ``exhausted`` is checked separately from ``status`` because an exhausted
    provider reports no windows at all — its status reads UNKNOWN, which this
    module otherwise treats as routable on purpose.
    """
    return bool(provider and provider.installed and status != TIGHT and not provider.exhausted)


def _stale_minutes(observed_at: str | None, now: datetime) -> int | None:
    if not observed_at:
        return None
    try:
        seen = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return int((now - seen).total_seconds() // 60)


def derive_routing(
    providers: list[ProviderCapacity],
    *,
    now: datetime | None = None,
) -> RoutingAdvice:
    """Turn observed quota into the three decisions a supervisor actually makes."""
    now = now or _utc_now()
    antigravity = _find(providers, "antigravity")

    gemini = _gemini_scope(antigravity)
    gemini_status = _status(_scope_remaining(gemini)) if gemini else UNKNOWN

    gemini_usable = _usable(antigravity, gemini_status) and gemini is not None

    # Image work is free inside the Antigravity plan; the billed API is the last resort.
    image_generation = "antigravity" if gemini_usable else "paid-api"

    # Antigravity earns the reviewer slot because a Google model is behind it.
    # When Gemini is exhausted there is no independent reviewer - NOT Antigravity
    # running a Claude model, which would make Anthropic review its own work.
    independent_reviewer = "antigravity" if gemini_usable else "none"

    gemini_weekly = _window(antigravity, "gemini", "weekly")
    weekly_tight = (
        gemini_weekly is not None
        and gemini_weekly.effective_remaining is not None
        and gemini_weekly.effective_remaining < LOW_REMAINING_PERCENT
    ) or any(p.exhausted for p in providers)

    constraints: list[str] = []

    for provider in providers:
        if provider.exhausted:
            constraints.append(
                f"{provider.provider} plan quota is SPENT - it will refuse work until the "
                "window resets. Route elsewhere; do not retry."
            )

    if gemini and gemini_status == TIGHT:
        constraints.append(
            "Gemini quota is tight - no independent reviewer is available. "
            "Do NOT switch Antigravity to a Claude model: that turns cross-review into self-review."
        )
    claude = _find(providers, "claude_code")
    if claude and claude.installed:
        constraints.append("Claude Code quota is not machine-readable; treated as the fallback reserve.")
    if image_generation == "paid-api":
        constraints.append("No free image quota left - image work would hit the billed API.")

    return RoutingAdvice(
        image_generation=image_generation,
        independent_reviewer=independent_reviewer,
        parallel_workers_ok=not weekly_tight,
        constraints=constraints,
    )


def build_report(
    *,
    offline: bool = False,
    now: datetime | None = None,
    runner=None,
) -> CapacityReport:
    """Probe every provider and derive routing advice."""
    now = now or _utc_now()
    providers = [
        probe_claude(now=now),
        probe_antigravity(offline=offline, now=now, runner=runner),
    ]
    return CapacityReport(
        generated_at=_iso(now),
        providers=providers,
        routing=derive_routing(providers, now=now),
    )
