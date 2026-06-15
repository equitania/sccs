# Tests for the dynamic OpenCode model resolution:
# match_models, map_model injection, list_opencode_models, resolve_model_map,
# OpenCodeConfig.effective_model_map, loader passthrough + save.

from pathlib import Path
from unittest.mock import patch

import yaml

from sccs.config.loader import _merge_with_defaults, save_opencode_model_map
from sccs.config.schema import OpenCodeConfig, SccsConfig
from sccs.convert.claude_to_opencode import (
    DEFAULT_OPENCODE_MODEL_MAP,
    map_model,
    match_models,
)

AVAIL = [
    "anthropic/claude-sonnet-4-5",
    "anthropic/claude-sonnet-4-0",
    "anthropic/claude-opus-4-1",
    "opencode/big-pickle",
    "github-copilot/claude-sonnet-4",
]


class TestMatchModels:
    def test_family_match_anthropic_first(self) -> None:
        result, _ = match_models(["sonnet"], AVAIL, preferred_providers=["anthropic"])
        assert result["sonnet"] == "anthropic/claude-sonnet-4-5"

    def test_ambiguity_warns(self) -> None:
        _, warns = match_models(["sonnet"], AVAIL, preferred_providers=["anthropic"])
        assert any("matched" in w for w in warns)

    def test_no_match_omitted(self) -> None:
        result, _ = match_models(["haiku"], AVAIL, preferred_providers=["anthropic"])
        assert "haiku" not in result

    def test_empty_available(self) -> None:
        result, warns = match_models(["sonnet"], [], preferred_providers=["anthropic"])
        assert result == {}
        assert warns == []

    def test_preferred_provider_order(self) -> None:
        # prefer github-copilot -> picks its sonnet over anthropic's
        result, _ = match_models(["sonnet"], AVAIL, preferred_providers=["github-copilot"])
        assert result["sonnet"] == "github-copilot/claude-sonnet-4"

    def test_non_tier_token_skipped(self) -> None:
        result, _ = match_models(["weird-model"], AVAIL, preferred_providers=["anthropic"])
        assert result == {}


class TestMapModelInjection:
    def test_injected_map_wins(self) -> None:
        mapped, _ = map_model("sonnet", {"sonnet": "anthropic/custom"})
        assert mapped == "anthropic/custom"

    def test_default_map_used_when_none(self) -> None:
        mapped, _ = map_model("sonnet")
        assert mapped == DEFAULT_OPENCODE_MODEL_MAP["sonnet"]

    def test_qualified_passthrough_ignores_map(self) -> None:
        mapped, warns = map_model("anthropic/foo", {"sonnet": "x"})
        assert mapped == "anthropic/foo"
        assert warns == []

    def test_unknown_in_injected_map_warns(self) -> None:
        mapped, warns = map_model("zzz", {"sonnet": "x"})
        assert mapped == "zzz"
        assert len(warns) == 1


class TestListOpencodeModels:
    def test_parse(self) -> None:
        raw = "anthropic/claude-sonnet-4-5\nopencode/big-pickle\n"
        with patch("sccs.integrations.opencode.run_opencode_models", return_value=raw):
            from sccs.integrations.opencode import list_opencode_models

            assert list_opencode_models() == ["anthropic/claude-sonnet-4-5", "opencode/big-pickle"]

    def test_ignores_noise_and_dedups(self) -> None:
        raw = "\nheader line without slash\nanthropic/x\nanthropic/x\n  anthropic/y extra-col\n"
        with patch("sccs.integrations.opencode.run_opencode_models", return_value=raw):
            from sccs.integrations.opencode import list_opencode_models

            assert list_opencode_models() == ["anthropic/x", "anthropic/y"]

    def test_empty(self) -> None:
        with patch("sccs.integrations.opencode.run_opencode_models", return_value=""):
            from sccs.integrations.opencode import list_opencode_models

            assert list_opencode_models() == []


class TestResolveModelMap:
    def test_discovery_fills_in(self) -> None:
        from sccs.integrations.opencode import resolve_model_map

        with patch(
            "sccs.integrations.opencode.list_opencode_models",
            return_value=["anthropic/claude-sonnet-4-9"],
        ):
            result = resolve_model_map(None, discover=True)
        # discovered sonnet overrides the static default
        assert result["sonnet"] == "anthropic/claude-sonnet-4-9"
        # untouched aliases keep the static default
        assert result["opus"] == DEFAULT_OPENCODE_MODEL_MAP["opus"]

    def test_offline_falls_back_to_static(self) -> None:
        from sccs.integrations.opencode import resolve_model_map

        with patch("sccs.integrations.opencode.list_opencode_models", return_value=[]):
            result = resolve_model_map(None, discover=True)
        assert result == DEFAULT_OPENCODE_MODEL_MAP

    def test_config_explicit_wins_over_discovery(self) -> None:
        from sccs.integrations.opencode import resolve_model_map

        config = SccsConfig.model_validate(
            {
                "repository": {"path": "~/x"},
                "opencode": {"model_map": {"sonnet": "anthropic/pinned"}},
            }
        )
        with patch(
            "sccs.integrations.opencode.list_opencode_models",
            return_value=["anthropic/claude-sonnet-4-9"],
        ):
            result = resolve_model_map(config, discover=True)
        assert result["sonnet"] == "anthropic/pinned"

    def test_discover_false_skips_subprocess(self) -> None:
        from sccs.integrations.opencode import resolve_model_map

        with patch("sccs.integrations.opencode.list_opencode_models") as mock_list:
            result = resolve_model_map(None, discover=False)
        mock_list.assert_not_called()
        assert result == DEFAULT_OPENCODE_MODEL_MAP


class TestOpenCodeConfig:
    def test_default_effective_map(self) -> None:
        cfg = OpenCodeConfig()
        assert cfg.effective_model_map == DEFAULT_OPENCODE_MODEL_MAP

    def test_extra_merges_on_top(self) -> None:
        cfg = OpenCodeConfig(extra_model_map={"sonnet": "anthropic/override"})
        assert cfg.effective_model_map["sonnet"] == "anthropic/override"

    def test_full_override(self) -> None:
        cfg = OpenCodeConfig(model_map={"only": "p/m"})
        assert cfg.effective_model_map == {"only": "p/m"}

    def test_preferred_providers_default(self) -> None:
        assert OpenCodeConfig().preferred_providers == ["anthropic"]


class TestLoaderPassthrough:
    def test_opencode_block_survives_merge(self) -> None:
        data = {"repository": {"path": "~/x"}, "opencode": {"model_map": {"sonnet": "p/m"}}}
        merged = _merge_with_defaults(data)
        assert merged["opencode"] == {"model_map": {"sonnet": "p/m"}}

    def test_save_opencode_model_map(self, tmp_path: Path, monkeypatch) -> None:
        # Isolate the backup dir (Path.home()/.config/sccs/backups) from real home.
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"repository": {"path": str(tmp_path / "repo")}}),
            encoding="utf-8",
        )
        cfg = save_opencode_model_map({"sonnet": "anthropic/x"}, config_path=config_file)
        assert cfg.opencode.model_map == {"sonnet": "anthropic/x"}
        # written to disk under opencode.model_map
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert raw["opencode"]["model_map"] == {"sonnet": "anthropic/x"}

    def test_save_preserves_other_opencode_keys(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "repository": {"path": str(tmp_path / "repo")},
                    "opencode": {"preferred_providers": ["github-copilot"]},
                }
            ),
            encoding="utf-8",
        )
        save_opencode_model_map({"sonnet": "anthropic/x"}, config_path=config_file)
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert raw["opencode"]["preferred_providers"] == ["github-copilot"]
        assert raw["opencode"]["model_map"] == {"sonnet": "anthropic/x"}
