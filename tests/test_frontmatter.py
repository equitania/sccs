# Tests for the shared YAML-frontmatter parser.
#
# Two functions with deliberately DIFFERENT contracts live here:
#
#   parse_frontmatter     — broken YAML => the whole document (fences included)
#                           comes back as the body. Load-bearing for the
#                           parse/render PAIR in doctor/scope_patch.py.
#   parse_frontmatter_ex  — broken YAML => the block is stripped and an error
#                           explains why. Used by converters that emit their
#                           own frontmatter.
#
# The split exists because v2.58.4 found a real export writing two stacked
# frontmatter blocks, and fixing it naively would have made the GSD scope patch
# delete frontmatter from other people's prompt files.

from __future__ import annotations

from pathlib import Path

from sccs.convert.frontmatter import (
    parse_frontmatter,
    parse_frontmatter_ex,
    render_frontmatter,
)

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

# The exact shape that triggered the bug: `argument-hint` uses Claude Code's
# documented bracket syntax, which is not valid YAML (two flow sequences on one
# line). The `description` above it is real and was being reported as absent.
REAL_WORLD_BROKEN = """---
description: Enforce strict adherence to project rules and defined skills
argument-hint: [skill-name] [optional-additional-skills...]
tags: [rules, standards, skills, conventions]
---

# Strict Project Rules & Skills Enforcement

You must always apply all defined skills.
"""


class TestParseFrontmatterEx:
    def test_valid_block_parses(self):
        result = parse_frontmatter_ex("---\nname: x\ndescription: d\n---\nbody here\n")
        assert result.metadata == {"name": "x", "description": "d"}
        assert result.body.strip() == "body here"
        assert result.error is None

    def test_no_fence_is_not_an_error(self):
        result = parse_frontmatter_ex("just text, no fence")
        assert result.metadata == {}
        assert result.body == "just text, no fence"
        assert result.error is None

    def test_unterminated_block_is_not_an_error(self):
        content = "---\nname: x\nbody without closing fence\n"
        result = parse_frontmatter_ex(content)
        assert result.metadata == {}
        assert result.body == content
        assert result.error is None

    def test_empty_block(self):
        result = parse_frontmatter_ex("---\n---\nbody\n")
        assert result.metadata == {}
        assert result.body.strip() == "body"
        assert result.error is None

    def test_broken_yaml_strips_the_block_and_reports_why(self):
        result = parse_frontmatter_ex(REAL_WORLD_BROKEN)
        assert result.metadata == {}
        assert result.error is not None
        assert "invalid YAML in frontmatter" in result.error
        # The whole point: the fence must NOT survive into the body, or the
        # caller's own frontmatter ends up stacked on top of it.
        assert not result.body.lstrip().startswith("---")
        assert "Strict Project Rules" in result.body

    def test_error_names_the_offending_line_in_FILE_coordinates(self):
        result = parse_frontmatter_ex(REAL_WORLD_BROKEN)
        # `argument-hint` is line 3 of the file (line 2 of the YAML block).
        # Reporting the block-relative number would send the user one line off.
        assert "line 3" in result.error
        assert "column" in result.error

    def test_non_dict_block_is_left_alone(self):
        content = "---\n- a\n- b\n---\nbody\n"
        result = parse_frontmatter_ex(content)
        assert result.metadata == {}
        assert result.body == content
        assert result.error is None

    def test_markdown_horizontal_rule_is_never_stripped(self):
        # A document opening with a rule parses as YAML *comment* -> None, not
        # an error. Stripping it would silently delete the heading.
        content = "---\n# Real heading, not metadata\n---\n\nActual body.\n"
        result = parse_frontmatter_ex(content)
        assert result.metadata == {}
        assert result.body == content
        assert result.error is None
        assert "Real heading" in result.body


class TestParseFrontmatterContractUnchanged:
    """`parse_frontmatter` keeps its historical broken-YAML behaviour.

    doctor/scope_patch.py relies on it: it parses, prepends a directive and
    renders again. With empty metadata `render_frontmatter` returns the body
    unchanged — so a gsd-* prompt whose frontmatter does not parse still keeps
    that frontmatter. Stripping the block here would delete it.
    """

    def test_broken_yaml_returns_the_whole_document(self):
        meta, body = parse_frontmatter(REAL_WORLD_BROKEN)
        assert meta == {}
        assert body == REAL_WORLD_BROKEN

    def test_scope_patch_style_roundtrip_keeps_frontmatter(self):
        meta, body = parse_frontmatter(REAL_WORLD_BROKEN)
        patched = render_frontmatter(meta, f"DIRECTIVE\n\n{body}")
        assert "argument-hint: [skill-name]" in patched
        assert "description: Enforce strict adherence" in patched
        assert patched.startswith("DIRECTIVE")

    def test_valid_input_matches_ex(self):
        content = "---\nname: x\n---\nbody\n"
        meta, body = parse_frontmatter(content)
        result = parse_frontmatter_ex(content)
        assert (meta, body) == (result.metadata, result.body)


class TestConvertersRejectStackedFrontmatter:
    """End-to-end: a broken source must not yield a two-header document."""

    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_codex_command_wrap_emits_one_block(self, tmp_path):
        from sccs.integrations.codex import _render_command

        path = self._write(tmp_path, "s.md", REAL_WORLD_BROKEN)
        document, warnings = _render_command("s", path)

        assert document.count("\n---\n") == 1, f"stacked frontmatter:\n{document}"
        assert document.startswith("---\nname: s\n")
        assert "Strict Project Rules" in document
        assert any("invalid YAML in frontmatter" in w for w in warnings)
        # The misleading warning must be gone — the description exists.
        assert not any("has no 'description'" in w for w in warnings)

    def test_codex_agent_body_has_no_leftover_fence(self, tmp_path):
        from sccs.integrations.codex import _render_agent

        path = self._write(tmp_path, "broken.md", REAL_WORLD_BROKEN)
        document, warnings = _render_agent(path)

        parsed = tomllib.loads(document)
        assert not parsed["developer_instructions"].lstrip().startswith("---")
        assert "Strict Project Rules" in parsed["developer_instructions"]
        assert any("invalid YAML in frontmatter" in w for w in warnings)
        assert not any("has no 'description'" in w for w in warnings)

    def test_opencode_agent_emits_one_block(self, tmp_path):
        from sccs.integrations.opencode import _render_agent as oc_render_agent

        path = self._write(tmp_path, "broken.md", REAL_WORLD_BROKEN)
        document, warnings = oc_render_agent(path)

        assert document.count("\n---\n") == 1, f"stacked frontmatter:\n{document}"
        assert any("invalid YAML in frontmatter" in w for w in warnings)
        assert not any("has no 'description'" in w for w in warnings)

    def test_quoted_argument_hint_parses_normally(self, tmp_path):
        """The fix on the source side: quoting makes it valid YAML again."""
        from sccs.integrations.codex import _render_command

        fixed = REAL_WORLD_BROKEN.replace(
            "argument-hint: [skill-name] [optional-additional-skills...]",
            'argument-hint: "[skill-name] [optional-additional-skills...]"',
        )
        path = self._write(tmp_path, "s.md", fixed)
        document, warnings = _render_command("s", path)

        assert "description: Enforce strict adherence" in document
        assert not any("invalid YAML" in w for w in warnings)
        # argument-hint is dropped on purpose (Codex skills carry name/description).
        assert any("dropped" in w and "argument-hint" in w for w in warnings)
