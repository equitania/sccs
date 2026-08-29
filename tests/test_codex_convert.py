# Tests for the Claude -> Codex conversion rules and the minimal TOML emitter.

from __future__ import annotations

import json

import pytest

from sccs.convert.claude_to_codex import (
    DEFAULT_CODEX_MODEL_MAP,
    DEFAULT_CODEX_REASONING_EFFORT_MAP,
    convert_agent_frontmatter,
    map_model,
    tools_to_sandbox_mode,
    validate_reasoning_effort_map,
    wrap_command_as_skill,
)
from sccs.convert.toml_write import (
    render_codex_agent_toml,
    toml_basic_string,
    toml_multiline_string,
)
from sccs.integrations.codex import validate_model_map_against_cache

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


def _parse(document: str) -> dict:
    return tomllib.loads(document)


# --------------------------------------------------------------------------- #
# map_model
# --------------------------------------------------------------------------- #


class TestMapModel:
    def test_known_alias(self):
        model, effort, warnings = map_model("sonnet")
        assert model == DEFAULT_CODEX_MODEL_MAP["sonnet"]
        assert effort == DEFAULT_CODEX_REASONING_EFFORT_MAP["sonnet"]
        assert warnings == []

    def test_none_omits_both(self):
        assert map_model(None) == (None, None, [])

    def test_inherit_omits_both(self):
        assert map_model("inherit") == (None, None, [])
        assert map_model("  ") == (None, None, [])

    def test_case_insensitive(self):
        model, effort, _ = map_model("OPUS")
        assert model == DEFAULT_CODEX_MODEL_MAP["opus"]
        assert effort == "high"

    def test_unknown_passes_through_with_warning(self):
        model, effort, warnings = map_model("gpt-9-turbo")
        assert model == "gpt-9-turbo"
        assert effort is None
        assert len(warnings) == 1
        assert "unknown model" in warnings[0]

    def test_injected_maps_win(self):
        model, effort, warnings = map_model(
            "sonnet",
            model_map={"sonnet": "my-model"},
            reasoning_map={"sonnet": "xhigh"},
        )
        assert model == "my-model"
        assert effort == "xhigh"
        assert warnings == []

    def test_invalid_reasoning_effort_is_reported(self):
        assert validate_reasoning_effort_map({"sonnet": "turbo"}) == ["sonnet: invalid reasoning effort 'turbo'"]

    def test_model_map_rejects_slug_missing_from_available_cache(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text(json.dumps({"models": [{"slug": "gpt-current"}]}), encoding="utf-8")

        errors, warnings = validate_model_map_against_cache({"sonnet": "retired-model"}, cache)
        assert errors == ["sonnet: model 'retired-model' is not in Codex's local model cache"]
        assert warnings == []


# --------------------------------------------------------------------------- #
# tools_to_sandbox_mode
# --------------------------------------------------------------------------- #


class TestToolsToSandboxMode:
    def test_empty_is_noop(self):
        assert tools_to_sandbox_mode(None) == (None, [])
        assert tools_to_sandbox_mode("") == (None, [])

    def test_read_only_set_maps_to_read_only(self):
        mode, warnings = tools_to_sandbox_mode("Read, Grep, Glob, WebFetch")
        assert mode == "read-only"
        assert warnings == []

    def test_read_only_list_form(self):
        mode, _ = tools_to_sandbox_mode(["Read", "WebSearch"])
        assert mode == "read-only"

    def test_mutating_tools_dropped_with_single_warning(self):
        mode, warnings = tools_to_sandbox_mode("Read, Write, Edit, Bash")
        assert mode == "workspace-write"
        assert len(warnings) == 1
        assert "workspace-write" in warnings[0]


# --------------------------------------------------------------------------- #
# convert_agent_frontmatter
# --------------------------------------------------------------------------- #


class TestAgentConversion:
    def test_full_conversion(self):
        meta = {
            "name": "reviewer",
            "description": "Reviews Python code.",
            "model": "sonnet",
            "tools": "Read, Grep, Glob",
        }
        codex_meta, warnings = convert_agent_frontmatter(meta)
        assert codex_meta["description"] == "Reviews Python code."
        assert codex_meta["model"] == DEFAULT_CODEX_MODEL_MAP["sonnet"]
        assert codex_meta["model_reasoning_effort"] == "medium"
        assert codex_meta["sandbox_mode"] == "read-only"
        assert warnings == []

    def test_missing_description_warns(self):
        codex_meta, warnings = convert_agent_frontmatter({})
        assert "description" not in codex_meta
        assert any("description" in w for w in warnings)

    def test_inherit_model_omitted(self):
        codex_meta, _ = convert_agent_frontmatter({"description": "x", "model": "inherit"})
        assert "model" not in codex_meta
        assert "model_reasoning_effort" not in codex_meta

    def test_allowed_tools_key_variant(self):
        codex_meta, _ = convert_agent_frontmatter({"description": "x", "allowed-tools": "Read"})
        assert codex_meta["sandbox_mode"] == "read-only"


# --------------------------------------------------------------------------- #
# wrap_command_as_skill
# --------------------------------------------------------------------------- #


class TestCommandWrapping:
    def test_description_passthrough(self):
        meta, body, warnings = wrap_command_as_skill("finalize", {"description": "Quality gate"}, "Do it.")
        assert meta == {"name": "finalize", "description": "Quality gate"}
        assert body == "Do it."
        assert warnings == []

    def test_missing_description_placeholder(self):
        meta, _, warnings = wrap_command_as_skill("foo", {}, "body")
        assert meta["description"] == "Claude Code command 'foo'"
        assert any("placeholder" in w for w in warnings)

    def test_dropped_fields_collected_once(self):
        _, _, warnings = wrap_command_as_skill(
            "foo",
            {"description": "d", "model": "opus", "allowed-tools": "Bash", "argument-hint": "[x]"},
            "body",
        )
        dropped = [w for w in warnings if w.startswith("dropped")]
        assert len(dropped) == 1
        assert "model" in dropped[0] and "argument-hint" in dropped[0]

    def test_placeholder_warning(self):
        _, _, warnings = wrap_command_as_skill("foo", {"description": "d"}, "Use $ARGUMENTS and $1 here.")
        assert any("$ARGUMENTS" in w for w in warnings)

    def test_dollar_amount_is_not_a_placeholder(self):
        _, _, warnings = wrap_command_as_skill("foo", {"description": "d"}, "Costs $10 or $ARGUMENTSXYZ.")
        assert warnings == []


# --------------------------------------------------------------------------- #
# TOML emitter (round-trip verified through a real parser)
# --------------------------------------------------------------------------- #


class TestTomlBasicString:
    @pytest.mark.parametrize(
        "value",
        [
            "plain",
            'quote " inside',
            "back\\slash",
            "tab\tand\nnewline",
            "unicode äöü „quotes“",
            "control \x07 char",
        ],
    )
    def test_round_trip(self, value):
        parsed = _parse(f"v = {toml_basic_string(value)}")
        assert parsed["v"] == value


class TestTomlMultilineString:
    @pytest.mark.parametrize(
        "body",
        [
            "# Heading\n\nPlain body with `code` and **bold**.",
            "contains ''' a literal-delimiter run",
            'quotes """ and \\ backslashes',
            "ends with a quote'",
            "ends with two quotes''",
            "unicode ✓ äöü",
            "windows\r\nline endings",
            "```bash\necho 'hi'\n```",
        ],
    )
    def test_round_trip_normalised(self, body):
        parsed = _parse(f"v = {toml_multiline_string(body)}")
        # The emitter normalises the value to end with exactly one newline.
        assert parsed["v"] == body.rstrip("\n") + "\n"

    def test_empty_body(self):
        parsed = _parse(f"v = {toml_multiline_string('')}")
        assert parsed["v"] == ""


class TestRenderCodexAgentToml:
    def test_minimal_document(self):
        doc = render_codex_agent_toml("reviewer", "Reviews code.", "Be thorough.")
        parsed = _parse(doc)
        assert parsed["name"] == "reviewer"
        assert parsed["description"] == "Reviews code."
        assert parsed["developer_instructions"] == "Be thorough.\n"
        assert "model" not in parsed
        assert "sandbox_mode" not in parsed

    def test_full_document(self):
        doc = render_codex_agent_toml(
            "reviewer",
            'Reviews "critical" code.',
            "# Role\n\nYou review diffs.\n",
            model="gpt-5.6-terra",
            model_reasoning_effort="high",
            sandbox_mode="read-only",
        )
        parsed = _parse(doc)
        assert parsed["model"] == "gpt-5.6-terra"
        assert parsed["model_reasoning_effort"] == "high"
        assert parsed["sandbox_mode"] == "read-only"
        assert parsed["description"] == 'Reviews "critical" code.'
        assert parsed["developer_instructions"] == "# Role\n\nYou review diffs.\n"

    def test_field_order_identity_first(self):
        doc = render_codex_agent_toml("a", "b", "c", model="m")
        lines = doc.splitlines()
        assert lines[0].startswith("name = ")
        assert lines[1].startswith("description = ")
        assert lines[-1].endswith("'''") or lines[-1].endswith('"""')


class TestBundledModelMapPolicy:
    """Guards the owner's mapping policy (v2.58.3).

    The v2.53.0 map shipped `gpt-5.1-codex` / `gpt-5.1-codex-mini` and went
    stale unnoticed — Codex retired that family, so every exported agent
    carried a dead model id. These tests do not pin a specific slug (that
    would need updating on every OpenAI release anyway); they pin the two
    properties that made the old map wrong.
    """

    def test_every_alias_is_mapped(self):
        assert set(DEFAULT_CODEX_MODEL_MAP) == {"opus", "sonnet", "haiku"}
        assert set(DEFAULT_CODEX_REASONING_EFFORT_MAP) == {"opus", "sonnet", "haiku"}

    def test_all_aliases_share_one_model_family(self):
        # Policy: a Claude tier is a depth signal, and Codex expresses depth
        # through model_reasoning_effort — so the tiers must not drift onto
        # different model generations (never map haiku onto an older mini).
        families = {value.rsplit("-", 1)[0] for value in DEFAULT_CODEX_MODEL_MAP.values()}
        assert len(families) == 1, f"aliases straddle model families: {DEFAULT_CODEX_MODEL_MAP}"

    def test_retired_model_family_is_gone(self):
        assert not any(v.startswith("gpt-5.1-codex") for v in DEFAULT_CODEX_MODEL_MAP.values())

    def test_effort_ordering_matches_tier_depth(self):
        efforts = DEFAULT_CODEX_REASONING_EFFORT_MAP
        order = ["low", "medium", "high", "xhigh", "max"]
        assert order.index(efforts["haiku"]) < order.index(efforts["sonnet"])
        assert order.index(efforts["sonnet"]) <= order.index(efforts["opus"])
