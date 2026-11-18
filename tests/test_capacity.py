# SCCS Capacity Probe Tests
#
# Every probe is exercised through injected fakes rather than the real CLIs:
# CI runs on Linux where agy/claude do not exist, and a test that depends
# on a locally installed agent passes on the author's Mac and nowhere else.

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sccs.capacity.probes import (
    parse_antigravity_usage,
    probe_antigravity,
    probe_claude,
)
from sccs.capacity.report import build_report, derive_routing
from sccs.capacity.schema import ProviderCapacity, QuotaScope, QuotaWindow
from sccs.doctor.runner import DoctorError

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


# Shape captured from `agy -p "/usage"`.
AGY_OUTPUT = (
    "Gemini Models\tWeekly Limit Remaining\t99%\t2026-09-06T08:01:34Z\n"
    "Gemini Models\tFive Hour Limit Remaining\t99%\t2026-08-30T13:01:34Z\n"
    "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-09-06T08:53:24Z\n"
    "Claude and GPT models\tFive Hour Limit Remaining\t100%\t2026-08-30T13:53:24Z\n"
)


class FakeRunner:
    """Stand-in for doctor.runner._run with a recorded argv."""

    def __init__(self, stdout: str = "", raises: Exception | None = None) -> None:
        self.stdout = stdout
        self.raises = raises
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *, check=True, capture=True, timeout=60):
        self.calls.append(list(cmd))
        if self.raises is not None:
            raise self.raises
        return type("Proc", (), {"stdout": self.stdout, "stderr": "", "returncode": 0})()


class TestAntigravityParsing:
    def test_splits_scopes_per_model_family(self) -> None:
        scopes = parse_antigravity_usage(AGY_OUTPUT, now=NOW)

        names = sorted(s.name for s in scopes)
        assert names == ["Claude and GPT models", "Gemini Models"]

    def test_reads_remaining_and_derives_used(self) -> None:
        scopes = parse_antigravity_usage(AGY_OUTPUT, now=NOW)
        gemini = next(s for s in scopes if s.name == "Gemini Models")

        weekly = next(w for w in gemini.windows if w.name == "weekly")
        assert weekly.remaining_percent == 99.0
        assert weekly.used_percent == 1.0
        assert weekly.resets_at == "2026-09-06T08:01:34Z"

    def test_progress_chatter_is_ignored(self) -> None:
        noisy = "Fetching quota...\nsome unrelated line\n" + AGY_OUTPUT

        assert len(parse_antigravity_usage(noisy, now=NOW)) == 2

    def test_unparsable_output_yields_no_scopes(self) -> None:
        assert parse_antigravity_usage("error: not logged in", now=NOW) == []


class TestAntigravityProbe:
    def test_live_probe_uses_print_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/agy")
        runner = FakeRunner(stdout=AGY_OUTPUT)

        result = probe_antigravity(now=NOW, runner=runner)

        assert result.source == "live"
        assert runner.calls == [["agy", "-p", "/usage", "--print-timeout", "30s"]]
        assert len(result.scopes) == 2

    def test_offline_skips_the_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/agy")
        runner = FakeRunner(stdout=AGY_OUTPUT)

        result = probe_antigravity(offline=True, now=NOW, runner=runner)

        assert runner.calls == []
        assert result.source == "unavailable"
        assert "offline" in (result.note or "")

    def test_runner_failure_degrades_to_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/agy")
        runner = FakeRunner(raises=DoctorError("Command timed out: agy"))

        result = probe_antigravity(now=NOW, runner=runner)

        assert result.source == "unavailable"
        assert "timed out" in (result.error or "")


class TestClaudeProbe:
    def test_reports_assumed_without_inventing_numbers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/claude")

        result = probe_claude(now=NOW)

        assert result.source == "assumed"
        assert result.scopes == []
        assert "fallback reserve" in (result.note or "")


def _provider(name: str, scopes: list[QuotaScope], *, installed: bool = True, source: str = "live") -> ProviderCapacity:
    return ProviderCapacity(provider=name, installed=installed, source=source, scopes=scopes)


def _scope(name: str, **windows: float) -> QuotaScope:
    return QuotaScope(
        name=name,
        windows=[QuotaWindow(name=k, remaining_percent=v, used_percent=100.0 - v) for k, v in windows.items()],
    )


class TestRouting:
    def test_uses_antigravity_for_images_when_free(self) -> None:
        providers = [_provider("antigravity", [_scope("Gemini Models", weekly=99.0)])]

        assert derive_routing(providers, now=NOW).image_generation == "antigravity"

    def test_tight_gemini_falls_back_to_paid_api_without_a_reviewer(self) -> None:
        providers = [
            _provider(
                "antigravity",
                [_scope("Gemini Models", weekly=2.0), _scope("Claude and GPT models", weekly=100.0)],
            ),
        ]

        advice = derive_routing(providers, now=NOW)

        # Antigravity's Claude pool being full must NOT make it the reviewer:
        # Anthropic reviewing Anthropic is self-review, which is the whole point
        # of having a third provider.
        assert advice.image_generation == "paid-api"
        assert advice.independent_reviewer == "none"
        assert any("billed API" in c for c in advice.constraints)
        assert any("self-review" in c for c in advice.constraints)

    def test_unknown_quota_is_not_treated_as_exhausted(self) -> None:
        # Installed but no readable numbers: routing must still use it rather
        # than pushing work onto the billed API for lack of data.
        providers = [_provider("antigravity", [_scope("Gemini Models")], source="unavailable")]

        assert derive_routing(providers, now=NOW).image_generation == "antigravity"

    def test_tight_weekly_window_blocks_parallel_workers(self) -> None:
        providers = [_provider("antigravity", [_scope("Gemini Models", weekly=4.0)])]

        assert derive_routing(providers, now=NOW).parallel_workers_ok is False

    def test_healthy_quota_allows_parallel_workers(self) -> None:
        providers = [_provider("antigravity", [_scope("Gemini Models", weekly=99.0)])]

        assert derive_routing(providers, now=NOW).parallel_workers_ok is True

    def test_no_provider_leaves_reviewer_unassigned(self) -> None:
        advice = derive_routing([], now=NOW)

        assert advice.independent_reviewer == "none"


class TestBuildReport:
    def test_offline_report_covers_both_providers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: None)

        report = build_report(offline=True, now=NOW)

        assert [p.provider for p in report.providers] == ["claude_code", "antigravity"]
        assert report.generated_at == "2026-08-30T12:00:00Z"
        assert report.routing is not None


class TestCapacityCli:
    def test_json_output_is_single_line_and_parsable(self) -> None:
        from click.testing import CliRunner

        from sccs.cli import cli

        result = CliRunner().invoke(cli, ["capacity", "--offline", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output.strip())
        assert "providers" in payload
        assert "routing" in payload
        assert payload["routing"]["image_generation"] in {"antigravity", "paid-api"}


class TestExhaustedRouting:
    def _exhausted(self) -> ProviderCapacity:
        return ProviderCapacity(provider="antigravity", installed=True, source="live", scopes=[], exhausted=True)

    def test_exhausted_provider_never_wins_a_routing_slot(self) -> None:
        # The regression: an exhausted provider can report no windows, so its
        # status reads UNKNOWN, which routing deliberately treats as usable.
        # Without the explicit exhausted check it was recommended while
        # rate-limited for hours.
        advice = derive_routing([self._exhausted()], now=NOW)

        assert advice.image_generation == "paid-api"
        assert advice.independent_reviewer == "none"

    def test_names_the_exhausted_provider_in_constraints(self) -> None:
        advice = derive_routing([self._exhausted()], now=NOW)

        assert any("antigravity" in c and "SPENT" in c for c in advice.constraints)

    def test_exhaustion_blocks_parallel_workers(self) -> None:
        assert derive_routing([self._exhausted()], now=NOW).parallel_workers_ok is False
