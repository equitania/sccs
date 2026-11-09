"""Tests for sccs.supervisor.models: per-tool model lists and validation."""

from __future__ import annotations

import json

import pytest

from sccs.supervisor.models import ModelList, check_model, list_models


@pytest.mark.parametrize("bad", ["x; rm -rf ~", "$(id)", "a b", "`id`", "-m", "--help", "", "a|b", "a\nb", "opus\n"])
def test_pattern_rejects(bad):
    assert check_model("opencode", bad, ModelList("opencode", (bad,), True)).status == "rejected"


def test_gemini_template_rejects_non_gemini():
    ml = ModelList("agy", ("gemini-4-argon-high", "claude-opus-5-5-high"), True)
    assert check_model("agy", "claude-opus-5-5-high", ml).status == "rejected"
    assert check_model("agy", "gemini-4-argon-high", ml).status == "verified"


def test_absent_from_readable_list_is_rejected():
    ml = ModelList("opencode", ("openrouter/~moonshotai/kimi-latest",), True)
    assert check_model("opencode", "openrouter/other", ml).status == "rejected"


def test_unreadable_list_gives_unverified():
    ml = ModelList("opencode", (), False)
    c = check_model("opencode", "openrouter/~moonshotai/kimi-latest", ml)
    assert c.ok and c.status == "unverified"


def test_agy_list_from_fake_binary(fake_home, fake_bin):
    fake_bin("agy", stdout="gemini-4-argon-high\ngemini-3.8-flash-medium\n")
    assert list_models("agy", fake_home).models == ("gemini-4-argon-high", "gemini-3.8-flash-medium")


def test_codex_list_is_not_readable(fake_home, empty_path):
    assert list_models("codex", fake_home).readable is False


def test_codex_list_carries_config_model(fake_home, empty_path):
    (fake_home / ".codex").mkdir()
    (fake_home / ".codex" / "config.toml").write_text('model = "gpt-5.5"\n', encoding="utf-8")
    ml = list_models("codex", fake_home)
    assert ml.models == ("gpt-5.5",) and ml.readable is False


def test_claude_list_is_fixed(fake_home, empty_path):
    ml = list_models("claude", fake_home)
    assert ml.models == ("haiku", "sonnet", "opus", "fable") and ml.readable


def test_opencode_list_drops_blank_and_ansi_lines(fake_home, fake_bin):
    fake_bin("opencode", stdout="\x1b[0m\n\x1b[32manthropic/claude-x\x1b[0m\n\nopencode/big-pickle\n")
    ml = list_models("opencode", fake_home)
    assert ml.models == ("anthropic/claude-x", "opencode/big-pickle")
    assert ml.readable


def test_failing_binary_is_unreadable(fake_home, empty_path):
    ml = list_models("agy", fake_home)
    assert ml.models == () and ml.readable is False


def test_pi_models_from_json(fake_home, empty_path):
    d = fake_home / ".pi" / "agent"
    d.mkdir(parents=True)
    (d / "models.json").write_text(
        json.dumps({"providers": {"p": {"models": [{"id": "m1"}, {"id": "m2"}]}}}), encoding="utf-8"
    )
    ml = list_models("pi", fake_home)
    assert ml.models == ("m1", "m2") and ml.readable


def test_pi_unparseable_is_unreadable(fake_home, empty_path):
    d = fake_home / ".pi" / "agent"
    d.mkdir(parents=True)
    (d / "models.json").write_text("{nope", encoding="utf-8")
    assert list_models("pi", fake_home).readable is False


def test_codex_unreadable_list_is_unverified():
    c = check_model("codex", "gpt-5.5", ModelList("codex", (), False))
    assert c.ok and c.status == "unverified"


def test_trailing_newline_rejected_for_agy():
    ml = ModelList("agy", ("gemini-x\n",), True)
    assert check_model("agy", "gemini-x\n", ml).status == "rejected"


def test_agy_nonzero_exit_gives_unreadable_list(fake_home, fake_bin):
    fake_bin("agy", stdout="Error: not logged in", exit_code=1)
    ml = list_models("agy", fake_home)
    assert ml.readable is False and ml.models == ()


def test_parse_lines_deduplicates_preserving_order():
    from sccs.supervisor.models import _parse_lines

    assert _parse_lines("b\na\nb\n\na\nc\n") == ("b", "a", "c")


def test_model_warning_only_for_free_opencode_models():
    from sccs.supervisor.models import model_warning

    assert "unclear data policy" in model_warning("opencode", "opencode/big-free")
    assert model_warning("opencode", "openrouter/x") is None
    assert model_warning("agy", "opencode/x") is None
