# SCCS Capacity Report
#
# Assembles the per-provider probes into one report and derives the routing
# hints a CAO supervisor acts on. The derivation lives here rather than in a
# prompt so it is testable and identical on every host — a supervisor that has
# to re-derive "is Codex tight?" from raw percentages gets it wrong differently
# every session.

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sccs.capacity.probes import (
    _iso,
    _utc_now,
    probe_antigravity,
    probe_claude,
    probe_codex,
)
from sccs.capacity.schema import (
    LOW_REMAINING_PERCENT,
    CapacityReport,
    ProviderCapacity,
    QuotaScope,
    RoutingAdvice,
)

# Codex snapshots come from its session records. Older than one 5h window and
# the 5h figure describes a window that has since rolled over.
_CODEX_STALE_AFTER_MINUTES = 300

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
        seen = seen.replace(tzinfo=timezone.utc)
    return int((now - seen).total_seconds() // 60)


def derive_routing(
    providers: list[ProviderCapacity],
    *,
    now: datetime | None = None,
) -> RoutingAdvice:
    """Turn observed quota into the three decisions a supervisor actually makes."""
    now = now or _utc_now()
    codex = _find(providers, "codex")
    antigravity = _find(providers, "antigravity")

    codex_status = _status(_provider_remaining(codex))
    gemini = _gemini_scope(antigravity)
    gemini_status = _status(_scope_remaining(gemini)) if gemini else UNKNOWN

    codex_usable = _usable(codex, codex_status)
    gemini_usable = _usable(antigravity, gemini_status) and gemini is not None

    # Image work is free inside both plans; the billed API is the last resort.
    if codex_usable:
        image_generation = "codex"
    elif gemini_usable:
        image_generation = "antigravity"
    else:
        image_generation = "paid-api"

    # Antigravity earns the reviewer slot because a Google model is behind it.
    # When Gemini is exhausted the answer is Codex — NOT Antigravity running a
    # Claude model, which would make Anthropic review its own work.
    if gemini_usable:
        independent_reviewer = "antigravity"
    elif codex_usable:
        independent_reviewer = "codex"
    else:
        independent_reviewer = "none"

    codex_weekly = _window(codex, "", "weekly")
    gemini_weekly = _window(antigravity, "gemini", "weekly")
    weekly_tight = any(
        w is not None and w.effective_remaining is not None and w.effective_remaining < LOW_REMAINING_PERCENT
        for w in (codex_weekly, gemini_weekly)
    ) or any(p.exhausted for p in providers)

    constraints: list[str] = []

    for provider in providers:
        if provider.exhausted:
            constraints.append(
                f"{provider.provider} plan quota is SPENT - it will refuse work until the "
                "window resets. Route elsewhere; do not retry."
            )

    codex_5h = _window(codex, "", "5h")
    if codex_5h and codex_5h.effective_remaining is not None and codex_5h.effective_remaining < LOW_REMAINING_PERCENT:
        constraints.append(
            f"Codex 5h window at {codex_5h.effective_remaining:.0f}% remaining"
            f"{_reset_hint(codex_5h.resets_in_minutes)} - send only short, tightly scoped tasks."
        )
    if (
        codex_weekly
        and codex_weekly.effective_remaining is not None
        and codex_weekly.effective_remaining < LOW_REMAINING_PERCENT
    ):
        constraints.append(
            f"Codex weekly window at {codex_weekly.effective_remaining:.0f}% remaining"
            f"{_reset_hint(codex_weekly.resets_in_minutes)} - do not start parallel Codex workers."
        )
    if gemini and gemini_status == TIGHT:
        constraints.append(
            "Gemini quota is tight - fall back to Codex for independent review. "
            "Do NOT switch Antigravity to a Claude model: that turns cross-review into self-review."
        )
    if codex and codex.source == "session-cache":
        age = _stale_minutes(codex.observed_at, now)
        if age is not None and age > _CODEX_STALE_AFTER_MINUTES:
            constraints.append(
                f"Codex figures are {age // 60}h old (read from its last session record); "
                "run Codex once to refresh before relying on the 5h window."
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


def _reset_hint(minutes: int | None) -> str:
    if minutes is None or minutes <= 0:
        return ""
    if minutes < 60:
        return f" (resets in {minutes}min)"
    return f" (resets in {minutes // 60}h)"


def build_report(
    *,
    offline: bool = False,
    home: Path | None = None,
    now: datetime | None = None,
    runner=None,
) -> CapacityReport:
    """Probe every provider and derive routing advice."""
    now = now or _utc_now()
    providers = [
        probe_claude(now=now),
        probe_codex(home=home, now=now),
        probe_antigravity(offline=offline, now=now, runner=runner),
    ]
    return CapacityReport(
        generated_at=_iso(now),
        providers=providers,
        routing=derive_routing(providers, now=now),
    )
