# Tests for SCCS Claude -> OpenCode conversion logic
# Frontmatter parsing/rendering + agent/command/MCP frontmatter transforms

from sccs.convert.claude_to_opencode import (
    MODEL_MAP,
    convert_agent_frontmatter,
    convert_command_frontmatter,
    convert_mcp_server,
    map_model,
    tools_to_permission,
)
from sccs.convert.frontmatter import parse_frontmatter, render_frontmatter

# --- Frontmatter parser ---


class TestFrontmatterParser:
    def test_basic_parse(self) -> None:
        meta, body = parse_frontmatter("---\nname: x\ndescription: d\n---\nbody here\n")
        assert meta == {"name": "x", "description": "d"}
        assert body.strip() == "body here"

    def test_no_frontmatter(self) -> None:
        meta, body = parse_frontmatter("just text, no fence")
        assert meta == {}
        assert body == "just text, no fence"

    def test_unterminated_block_is_body(self) -> None:
        content = "---\nname: x\nbody never closes"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_empty_block(self) -> None:
        meta, body = parse_frontmatter("---\n---\nbody\n")
        assert meta == {}
        assert body.strip() == "body"

    def test_broken_yaml_returns_body(self) -> None:
        content = "---\n: : : not yaml\n---\nbody\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_non_dict_block_returns_body(self) -> None:
        content = "---\n- a\n- b\n---\nbody\n"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_roundtrip(self) -> None:
        meta = {"description": "d", "mode": "subagent"}
        body = "the prompt body"
        rendered = render_frontmatter(meta, body)
        re_meta, re_body = parse_frontmatter(rendered)
        assert re_meta == meta
        assert re_body.strip() == body

    def test_render_empty_meta_is_body_only(self) -> None:
        assert render_frontmatter({}, "body") == "body"

    def test_render_ends_with_single_newline(self) -> None:
        out = render_frontmatter({"description": "d"}, "body")
        assert out.endswith("\n")
        assert not out.endswith("\n\n")


# --- Model mapping ---


class TestMapModel:
    def test_known_alias(self) -> None:
        mapped, warns = map_model("sonnet")
        assert mapped == MODEL_MAP["sonnet"]
        assert warns == []

    def test_none(self) -> None:
        assert map_model(None) == (None, [])

    def test_inherit_omits_model(self) -> None:
        assert map_model("inherit") == (None, [])

    def test_already_qualified_passthrough(self) -> None:
        mapped, warns = map_model("anthropic/claude-sonnet-4-5")
        assert mapped == "anthropic/claude-sonnet-4-5"
        assert warns == []

    def test_unknown_passthrough_with_warning(self) -> None:
        mapped, warns = map_model("gpt-9000")
        assert mapped == "gpt-9000"
        assert len(warns) == 1


# --- allowed-tools -> permission ---


class TestToolsToPermission:
    def test_none(self) -> None:
        assert tools_to_permission(None) == (None, [])

    def test_comma_separated_real_frontmatter(self) -> None:
        # Regression: real CC frontmatter is comma-separated. A whitespace-only
        # split left a trailing comma on every token and matched nothing.
        perm, warns = tools_to_permission("Read, Write, Edit, Glob, Grep, WebFetch")
        assert perm == {
            "*": "deny",
            "read": "allow",
            "edit": "allow",  # Write + Edit both fold into `edit`
            "glob": "allow",
            "grep": "allow",
            "webfetch": "allow",
        }
        assert warns == []

    def test_write_and_edit_fold_into_edit(self) -> None:
        perm, _ = tools_to_permission("Read, Write, Edit")
        assert perm == {"*": "deny", "read": "allow", "edit": "allow"}

    def test_space_separated_still_works(self) -> None:
        perm, _ = tools_to_permission("Read Bash")
        assert perm == {"*": "deny", "read": "allow", "bash": "allow"}

    def test_list_tools(self) -> None:
        perm, _ = tools_to_permission(["Read", "Write"])
        assert perm == {"*": "deny", "read": "allow", "edit": "allow"}

    def test_extended_tool_keys(self) -> None:
        perm, warns = tools_to_permission("WebSearch, Skill, Agent, AskUserQuestion")
        assert perm == {
            "*": "deny",
            "websearch": "allow",
            "skill": "allow",
            "task": "allow",  # Agent -> task
            "question": "allow",  # AskUserQuestion -> question
        }
        assert warns == []

    def test_catch_all_deny_makes_it_faithful(self) -> None:
        # A read-only allowlist becomes a read-only agent in OpenCode.
        perm, warns = tools_to_permission("Read, Grep, Glob")
        assert perm["*"] == "deny"
        assert "write" not in perm and "edit" not in perm
        assert not any("allowlist" in w for w in warns)  # no longer lossy

    def test_bash_scoped(self) -> None:
        perm, _ = tools_to_permission("Bash(git:*)")
        assert perm == {"*": "deny", "bash": {"git *": "allow"}}

    def test_bash_bare(self) -> None:
        perm, _ = tools_to_permission("Bash")
        assert perm == {"*": "deny", "bash": "allow"}

    def test_mcp_tool_maps_to_wildcard(self) -> None:
        perm, warns = tools_to_permission("mcp__context7__*")
        assert perm == {"*": "deny", "context7_*": "allow"}
        assert warns == []

    def test_mcp_specific_tool(self) -> None:
        perm, _ = tools_to_permission("mcp__context7__resolve-lib")
        assert perm == {"*": "deny", "context7_resolve-lib": "allow"}

    def test_unknown_tool_single_summary_warning(self) -> None:
        perm, warns = tools_to_permission("Frobnicate")
        assert perm is None
        assert len(warns) == 1
        assert "Frobnicate" in warns[0]

    def test_unknown_tools_collapsed_into_one_warning(self) -> None:
        perm, warns = tools_to_permission("Read, Frobnicate, Wibble")
        assert perm == {"*": "deny", "read": "allow"}
        assert len(warns) == 1
        assert "Frobnicate" in warns[0] and "Wibble" in warns[0]


# --- Agent frontmatter ---


class TestAgentConversion:
    def test_drops_name_maps_model(self) -> None:
        oc, _ = convert_agent_frontmatter({"name": "x", "description": "d", "model": "sonnet"})
        assert "name" not in oc
        assert oc["description"] == "d"
        assert oc["mode"] == "subagent"
        assert oc["model"] == MODEL_MAP["sonnet"]

    def test_missing_description_warns(self) -> None:
        oc, warns = convert_agent_frontmatter({"name": "x"})
        assert "description" not in oc
        assert any("description" in w for w in warns)

    def test_inherit_model_omitted(self) -> None:
        oc, _ = convert_agent_frontmatter({"description": "d", "model": "inherit"})
        assert "model" not in oc

    def test_allowed_tools_become_permission(self) -> None:
        oc, _ = convert_agent_frontmatter({"description": "d", "allowed-tools": "Read, Edit"})
        assert oc["permission"] == {"*": "deny", "read": "allow", "edit": "allow"}

    def test_tools_field_fallback_comma_separated(self) -> None:
        # The `tools:` field (real CC agents use this, comma-separated).
        oc, _ = convert_agent_frontmatter({"description": "d", "tools": "Read, Bash, Grep, Glob"})
        assert oc["permission"] == {
            "*": "deny",
            "read": "allow",
            "bash": "allow",
            "grep": "allow",
            "glob": "allow",
        }

    def test_temperature_passthrough(self) -> None:
        oc, _ = convert_agent_frontmatter({"description": "d", "temperature": 0.2})
        assert oc["temperature"] == 0.2


# --- Command frontmatter ---


class TestCommandConversion:
    def test_keeps_description_maps_model(self) -> None:
        oc, _ = convert_command_frontmatter({"description": "d", "model": "opus"})
        assert oc["description"] == "d"
        assert oc["model"] == MODEL_MAP["opus"]

    def test_tags_dropped_silently(self) -> None:
        # tags is cosmetic metadata — no warning.
        oc, warns = convert_command_frontmatter({"description": "d", "tags": ["a"]})
        assert "tags" not in oc
        assert warns == []

    def test_allowed_tools_dropped_with_one_soft_note(self) -> None:
        oc, warns = convert_command_frontmatter({"description": "d", "allowed-tools": "Read"})
        assert "allowed-tools" not in oc
        assert len(warns) == 1
        assert "inherit tool access" in warns[0]

    def test_passes_through_agent_and_subtask(self) -> None:
        # `agent` and `subtask` are native OpenCode command fields — kept verbatim.
        oc, warns = convert_command_frontmatter(
            {"description": "d", "agent": "reviewer", "subtask": True, "model": "opus"}
        )
        assert oc["agent"] == "reviewer"
        assert oc["subtask"] is True
        assert oc["model"] == MODEL_MAP["opus"]
        assert warns == []

    def test_omits_agent_and_subtask_when_absent(self) -> None:
        oc, _ = convert_command_frontmatter({"description": "d"})
        assert "agent" not in oc
        assert "subtask" not in oc


# --- MCP server ---


class TestMcpConversion:
    def test_local_command_args_merge(self) -> None:
        oc, warns = convert_mcp_server({"command": "npx", "args": ["-y", "foo"], "env": {"K": "V"}})
        assert oc["type"] == "local"
        assert oc["command"] == ["npx", "-y", "foo"]
        assert oc["environment"] == {"K": "V"}
        assert oc["enabled"] is True
        assert warns == []

    def test_command_as_list(self) -> None:
        oc, _ = convert_mcp_server({"command": ["uvx", "bar"]})
        assert oc["command"] == ["uvx", "bar"]

    def test_remote_server(self) -> None:
        oc, _ = convert_mcp_server({"type": "sse", "url": "https://x/mcp"})
        assert oc == {"type": "remote", "url": "https://x/mcp", "enabled": True}

    def test_missing_command_warns(self) -> None:
        oc, warns = convert_mcp_server({})
        assert oc["command"] == []
        assert any("no 'command'" in w for w in warns)

    def test_cwd_passthrough(self) -> None:
        oc, _ = convert_mcp_server({"command": "x", "cwd": "/tmp"})
        assert oc["cwd"] == "/tmp"
