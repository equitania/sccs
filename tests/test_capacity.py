# SCCS Capacity Probe Tests
#
# Every probe is exercised through injected fakes rather than the real CLIs:
# CI runs on Linux where codex/agy/claude do not exist, and a test that depends
# on a locally installed agent passes on the author's Mac and nowhere else.

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sccs.capacity.probes import (
    _find_rate_limits,
    is_codex_exhausted,
    parse_antigravity_usage,
    parse_codex_rate_limits,
    probe_antigravity,
    probe_claude,
    probe_codex,
)
from sccs.capacity.report import build_report, derive_routing
from sccs.capacity.schema import ProviderCapacity, QuotaScope, QuotaWindow
from sccs.doctor.runner import DoctorError

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


# Shape captured from a real ~/.codex/sessions rollout file.
CODEX_PAYLOAD = {
    "limit_id": "codex",
    "limit_name": None,
    "primary": {"used_percent": 8.0, "window_minutes": 300, "resets_at": _epoch(NOW + timedelta(hours=3))},
    "secondary": {"used_percent": 1.0, "window_minutes": 10080, "resets_at": _epoch(NOW + timedelta(days=6))},
}

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


class TestCodexParsing:
    def test_derives_remaining_and_window_names(self) -> None:
        scope = parse_codex_rate_limits(CODEX_PAYLOAD, now=NOW)

        assert scope.name == "codex"
        names = [w.name for w in scope.windows]
        assert names == ["5h", "weekly"]
        five_hour = scope.windows[0]
        # Codex reports used; remaining must be derived so both providers agree.
        assert five_hour.used_percent == 8.0
        assert five_hour.remaining_percent == 92.0
        assert five_hour.expired is False
        assert five_hour.resets_in_minutes == pytest.approx(180, abs=1)

    def test_past_reset_marks_window_expired_and_free(self) -> None:
        payload = {
            "limit_id": "codex",
            "primary": {"used_percent": 95.0, "window_minutes": 300, "resets_at": _epoch(NOW - timedelta(hours=1))},
        }

        window = parse_codex_rate_limits(payload, now=NOW).windows[0]

        # The window rolled over since the snapshot: 95% used is historical.
        assert window.expired is True
        assert window.effective_remaining == 100.0

    def test_missing_window_is_skipped_not_faked(self) -> None:
        scope = parse_codex_rate_limits({"limit_id": "codex"}, now=NOW)

        assert scope.windows == []

    def test_finds_rate_limits_at_any_nesting_depth(self) -> None:
        event = {"type": "event", "payload": {"info": {"rate_limits": CODEX_PAYLOAD}}}

        assert _find_rate_limits(event) == CODEX_PAYLOAD

    def test_returns_none_when_absent(self) -> None:
        assert _find_rate_limits({"payload": {"items": [1, 2, {"other": True}]}}) is None


class TestCodexProbe:
    def _write_rollout(self, home: Path, payload: dict, timestamp: str = "2026-08-30T11:00:00Z") -> Path:
        target = home / ".codex" / "sessions" / "2026" / "08" / "30"
        target.mkdir(parents=True)
        rollout = target / "rollout-2026-08-30T11-00-00-abc.jsonl"
        rollout.write_text(
            json.dumps({"timestamp": "2026-08-30T10:00:00Z", "payload": {"noise": True}})
            + "\n"
            + json.dumps({"timestamp": timestamp, "payload": {"info": {"rate_limits": payload}}})
            + "\n",
            encoding="utf-8",
        )
        return rollout

    def test_reads_newest_snapshot(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/codex")
        self._write_rollout(tmp_path, CODEX_PAYLOAD)

        result = probe_codex(home=tmp_path, now=NOW)

        assert result.installed is True
        assert result.source == "session-cache"
        assert result.observed_at == "2026-08-30T11:00:00Z"
        assert result.scopes[0].windows[0].remaining_percent == 92.0

    def test_uses_last_snapshot_in_file_not_first(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/codex")
        target = tmp_path / ".codex" / "sessions"
        target.mkdir(parents=True)
        early = dict(CODEX_PAYLOAD, primary={"used_percent": 5.0, "window_minutes": 300, "resets_at": _epoch(NOW)})
        late = dict(
            CODEX_PAYLOAD,
            primary={"used_percent": 42.0, "window_minutes": 300, "resets_at": _epoch(NOW + timedelta(hours=2))},
        )
        (target / "r.jsonl").write_text(
            json.dumps({"timestamp": "2026-08-30T09:00:00Z", "rate_limits": early})
            + "\n"
            + json.dumps({"timestamp": "2026-08-30T11:30:00Z", "rate_limits": late})
            + "\n",
            encoding="utf-8",
        )

        result = probe_codex(home=tmp_path, now=NOW)

        assert result.scopes[0].windows[0].used_percent == 42.0

    def test_missing_sessions_dir_reports_error_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/codex")

        result = probe_codex(home=tmp_path, now=NOW)

        assert result.source == "unavailable"
        assert result.scopes == []
        assert "session directory" in (result.error or "")

    def test_not_installed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: None)

        result = probe_codex(home=tmp_path, now=NOW)

        assert result.installed is False
        assert "not found" in (result.error or "")

    def test_corrupt_line_is_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/codex")
        target = tmp_path / ".codex" / "sessions"
        target.mkdir(parents=True)
        (target / "r.jsonl").write_text(
            '{"rate_limits": TRUNCATED\n' + json.dumps({"rate_limits": CODEX_PAYLOAD}) + "\n",
            encoding="utf-8",
        )

        result = probe_codex(home=tmp_path, now=NOW)

        assert result.source == "session-cache"


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
    def test_prefers_codex_for_images_when_free(self) -> None:
        providers = [
            _provider("codex", [_scope("codex", **{"5h": 90.0, "weekly": 95.0})]),
            _provider("antigravity", [_scope("Gemini Models", weekly=99.0)]),
        ]

        assert derive_routing(providers, now=NOW).image_generation == "codex"

    def test_falls_back_to_antigravity_then_paid_api(self) -> None:
        tight_codex = _provider("codex", [_scope("codex", **{"5h": 2.0, "weekly": 3.0})])
        free_gemini = _provider("antigravity", [_scope("Gemini Models", weekly=80.0)])
        assert derive_routing([tight_codex, free_gemini], now=NOW).image_generation == "antigravity"

        tight_gemini = _provider("antigravity", [_scope("Gemini Models", weekly=1.0)])
        advice = derive_routing([tight_codex, tight_gemini], now=NOW)
        assert advice.image_generation == "paid-api"
        assert any("billed API" in c for c in advice.constraints)

    def test_tight_gemini_routes_review_to_codex_not_a_claude_model(self) -> None:
        providers = [
            _provider("codex", [_scope("codex", **{"5h": 70.0, "weekly": 70.0})]),
            _provider(
                "antigravity",
                [_scope("Gemini Models", weekly=2.0), _scope("Claude and GPT models", weekly=100.0)],
            ),
        ]

        advice = derive_routing(providers, now=NOW)

        # Antigravity's Claude pool being full must NOT make it the reviewer:
        # Anthropic reviewing Anthropic is self-review, which is the whole point
        # of having a third provider.
        assert advice.independent_reviewer == "codex"
        assert any("self-review" in c for c in advice.constraints)

    def test_unknown_quota_is_not_treated_as_exhausted(self) -> None:
        # Installed but no readable numbers: routing must still use it rather
        # than pushing work onto the billed API for lack of data.
        providers = [_provider("codex", [], source="unavailable")]

        assert derive_routing(providers, now=NOW).image_generation == "codex"

    def test_tight_weekly_window_blocks_parallel_workers(self) -> None:
        providers = [_provider("codex", [_scope("codex", **{"5h": 90.0, "weekly": 4.0})])]

        advice = derive_routing(providers, now=NOW)

        assert advice.parallel_workers_ok is False
        assert any("parallel Codex workers" in c for c in advice.constraints)

    def test_healthy_quota_allows_parallel_workers(self) -> None:
        providers = [
            _provider("codex", [_scope("codex", **{"5h": 90.0, "weekly": 95.0})]),
            _provider("antigravity", [_scope("Gemini Models", weekly=99.0)]),
        ]

        assert derive_routing(providers, now=NOW).parallel_workers_ok is True

    def test_stale_codex_snapshot_is_flagged(self) -> None:
        provider = ProviderCapacity(
            provider="codex",
            installed=True,
            source="session-cache",
            observed_at="2026-08-28T12:00:00Z",
            scopes=[_scope("codex", **{"5h": 90.0})],
        )

        advice = derive_routing([provider], now=NOW)

        assert any("old" in c and "refresh" in c for c in advice.constraints)

    def test_no_provider_leaves_reviewer_unassigned(self) -> None:
        advice = derive_routing([], now=NOW)

        assert advice.independent_reviewer == "none"


class TestBuildReport:
    def test_offline_report_covers_all_three_providers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: None)

        report = build_report(offline=True, home=tmp_path, now=NOW)

        assert [p.provider for p in report.providers] == ["claude_code", "codex", "antigravity"]
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
        assert payload["routing"]["image_generation"] in {"codex", "antigravity", "paid-api"}


# Captured from ~/.codex/sessions on 30.08.2026, at the moment the Codex TUI
# printed "You've hit your usage limit ... try again at 3:00 PM". Both windows
# go null and the credit balance empties; limit_id flips from "codex".
CODEX_EXHAUSTED_PAYLOAD = {
    "limit_id": "premium",
    "limit_name": None,
    "primary": None,
    "secondary": None,
    "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
    "individual_limit": None,
    "spend_control_reached": None,
    "plan_type": None,
    "rate_limit_reached_type": None,
}


class TestCodexExhaustion:
    def test_detects_the_spent_quota_shape(self) -> None:
        assert is_codex_exhausted(CODEX_EXHAUSTED_PAYLOAD) is True

    def test_healthy_payload_is_not_exhausted(self) -> None:
        assert is_codex_exhausted(CODEX_PAYLOAD) is False

    def test_null_windows_alone_are_not_enough(self) -> None:
        # Without the corroborating empty credit balance this must stay
        # "unknown": treating every windowless payload as exhaustion would
        # divert work away from a healthy provider.
        assert is_codex_exhausted({"limit_id": "premium", "primary": None, "secondary": None}) is False

    def test_available_credits_override_null_windows(self) -> None:
        payload = dict(CODEX_EXHAUSTED_PAYLOAD, credits={"has_credits": True, "balance": "12.50"})
        assert is_codex_exhausted(payload) is False

    def test_unlimited_credits_are_never_exhausted(self) -> None:
        payload = dict(CODEX_EXHAUSTED_PAYLOAD, credits={"unlimited": True, "balance": "0"})
        assert is_codex_exhausted(payload) is False

    def test_probe_marks_provider_exhausted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sccs.capacity.probes.which", lambda _b: "/usr/bin/codex")
        target = tmp_path / ".codex" / "sessions"
        target.mkdir(parents=True)
        (target / "r.jsonl").write_text(json.dumps({"rate_limits": CODEX_EXHAUSTED_PAYLOAD}) + "\n", encoding="utf-8")

        result = probe_codex(home=tmp_path, now=NOW)

        assert result.exhausted is True
        assert result.scopes[0].windows == []
        assert "spent" in (result.note or "").lower()


class TestExhaustedRouting:
    def _exhausted_codex(self) -> ProviderCapacity:
        return ProviderCapacity(provider="codex", installed=True, source="session-cache", scopes=[], exhausted=True)

    def test_exhausted_provider_never_wins_a_routing_slot(self) -> None:
        # The regression: an exhausted Codex reports no windows, so its status
        # reads UNKNOWN, which routing deliberately treats as usable. Without
        # the explicit exhausted check it was recommended for image work while
        # rate-limited for another three hours.
        advice = derive_routing([self._exhausted_codex()], now=NOW)

        assert advice.image_generation == "paid-api"
        assert advice.independent_reviewer == "none"

    def test_falls_back_to_antigravity_for_images(self) -> None:
        providers = [self._exhausted_codex(), _provider("antigravity", [_scope("Gemini Models", weekly=90.0)])]

        advice = derive_routing(providers, now=NOW)

        assert advice.image_generation == "antigravity"
        assert advice.independent_reviewer == "antigravity"

    def test_names_the_exhausted_provider_in_constraints(self) -> None:
        advice = derive_routing([self._exhausted_codex()], now=NOW)

        assert any("codex" in c and "SPENT" in c for c in advice.constraints)

    def test_exhaustion_blocks_parallel_workers(self) -> None:
        providers = [self._exhausted_codex(), _provider("antigravity", [_scope("Gemini Models", weekly=99.0)])]

        assert derive_routing(providers, now=NOW).parallel_workers_ok is False
