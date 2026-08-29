# Tests for CodexConfig and the loader passthrough of the codex/pi blocks.

from __future__ import annotations

import pytest

from sccs.config.loader import _merge_with_defaults
from sccs.config.schema import CodexConfig, SccsConfig
from sccs.convert.claude_to_codex import (
    DEFAULT_CODEX_MODEL_MAP,
    DEFAULT_CODEX_REASONING_EFFORT_MAP,
)


class TestCodexConfig:
    def test_defaults(self):
        config = CodexConfig()
        assert config.base_dir is None
        assert config.skills_dir is None
        assert config.exclude == []
        assert config.effective_model_map == DEFAULT_CODEX_MODEL_MAP
        assert config.effective_reasoning_effort_map == DEFAULT_CODEX_REASONING_EFFORT_MAP

    def test_model_map_full_override(self):
        config = CodexConfig(model_map={"sonnet": "my-model"})
        assert config.effective_model_map == {"sonnet": "my-model"}

    def test_extra_model_map_is_additive(self):
        config = CodexConfig(extra_model_map={"sonnet": "my-model"})
        effective = config.effective_model_map
        assert effective["sonnet"] == "my-model"
        assert effective["haiku"] == DEFAULT_CODEX_MODEL_MAP["haiku"]

    def test_reasoning_effort_override(self):
        config = CodexConfig(reasoning_effort_map={"sonnet": "xhigh"})
        assert config.effective_reasoning_effort_map == {"sonnet": "xhigh"}

    def test_invalid_reasoning_effort_is_rejected_by_config(self):
        with pytest.raises(ValueError, match="invalid reasoning effort"):
            CodexConfig(reasoning_effort_map={"sonnet": "turbo"})

    def test_sccs_config_default_factory(self):
        config = SccsConfig.model_validate({"repository": {"path": "/tmp/repo"}})
        assert isinstance(config.codex, CodexConfig)
        assert config.codex.base_dir is None


class TestLoaderPassthrough:
    def test_codex_block_passes_through(self):
        merged = _merge_with_defaults({"codex": {"base_dir": "~/custom-codex", "exclude": ["foo-*"]}})
        assert merged["codex"] == {"base_dir": "~/custom-codex", "exclude": ["foo-*"]}

        merged["repository"] = {"path": "/tmp/repo"}
        config = SccsConfig.model_validate(merged)
        assert config.codex.base_dir == "~/custom-codex"
        assert config.codex.exclude == ["foo-*"]

    def test_pi_block_passes_through(self):
        # Regression: the `pi` passthrough branch was missing until v2.53.0 —
        # user pi.base_dir/pi.exclude overrides were silently dropped.
        merged = _merge_with_defaults({"pi": {"base_dir": "~/custom-pi", "exclude": ["bar-*"]}})
        assert merged["pi"] == {"base_dir": "~/custom-pi", "exclude": ["bar-*"]}

        merged["repository"] = {"path": "/tmp/repo"}
        config = SccsConfig.model_validate(merged)
        assert config.pi.base_dir == "~/custom-pi"
        assert config.pi.exclude == ["bar-*"]

    def test_absent_blocks_fall_back_to_defaults(self):
        merged = _merge_with_defaults({})
        assert "codex" not in merged
        assert "pi" not in merged
