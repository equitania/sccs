# SCCS Capacity Schema
#
# Plain dataclasses (not Pydantic): this data is *observed*, never validated
# user input, and sccs.output.json_emit.to_jsonable serializes dataclass fields
# directly. Timestamps are stored as ISO-8601 strings rather than datetime
# objects so the JSON payload is stable and needs no custom encoder — a
# supervisor consuming `sccs capacity --json` gets the same shape on every host.

from __future__ import annotations

from dataclasses import dataclass, field

# A window whose remaining share drops below this is treated as "tight": no
# long-running or parallel work should be routed to that provider.
LOW_REMAINING_PERCENT = 20.0


@dataclass
class QuotaWindow:
    """One rolling quota window of one provider scope.

    Providers disagree on which half of the fraction they report — Codex emits
    ``used_percent``, Antigravity emits remaining — so both fields are carried
    and whichever is missing is derived. ``expired`` means ``resets_at`` already
    passed, i.e. the window rolled over since the value was observed and the
    real remaining share is 100%.
    """

    name: str  # "5h" | "weekly" | fallback "<n>min"
    window_minutes: int | None = None
    remaining_percent: float | None = None
    used_percent: float | None = None
    resets_at: str | None = None  # ISO-8601, UTC
    resets_in_minutes: int | None = None
    expired: bool = False

    @property
    def effective_remaining(self) -> float | None:
        """Remaining share a router should act on (an expired window is free)."""
        if self.expired:
            return 100.0
        return self.remaining_percent


@dataclass
class QuotaScope:
    """A group of windows sharing one limit pool.

    Codex has a single pool. Antigravity bills Gemini models and the Claude/GPT
    models it resells against *separate* pools, which is why scopes are a list
    and not a flat field — routing must be able to see that Gemini is exhausted
    while the Claude pool is untouched.
    """

    name: str
    windows: list[QuotaWindow] = field(default_factory=list)


@dataclass
class ProviderCapacity:
    """What is known about one provider's remaining plan quota.

    ``source`` is deliberately part of the payload: a caller must be able to
    tell a live reading from a cached one from an outright assumption before
    it routes real work.

      live           -- queried from the provider just now
      session-cache  -- read from the provider's own on-disk session record;
                        only as fresh as the user's last session with it
      assumed        -- not machine-readable at all; no numbers are invented
      unavailable    -- binary missing, probe skipped, or the probe failed
    """

    provider: str
    installed: bool = False
    source: str = "unavailable"
    observed_at: str | None = None
    scopes: list[QuotaScope] = field(default_factory=list)
    # Affirmative evidence that the plan quota is spent — NOT the same as having
    # no data. Codex reports exhaustion by replacing its two windows with null
    # and switching limit_id, so an empty scope can mean either "nothing known"
    # or "nothing left"; conflating them once made this tool recommend a
    # provider that was rate-limited for another three hours.
    exhausted: bool = False
    note: str | None = None
    error: str | None = None


@dataclass
class RoutingAdvice:
    """Capacity-derived hints a supervisor can act on without re-deriving them."""

    image_generation: str  # "codex" | "antigravity" | "paid-api"
    independent_reviewer: str  # "antigravity" | "codex" | "none"
    parallel_workers_ok: bool
    constraints: list[str] = field(default_factory=list)


@dataclass
class CapacityReport:
    generated_at: str
    providers: list[ProviderCapacity] = field(default_factory=list)
    routing: RoutingAdvice | None = None
