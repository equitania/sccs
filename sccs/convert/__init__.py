# SCCS Conversion Subpackage
# Convert shell configurations between formats (e.g. Fish -> PowerShell) and
# Claude Code artefacts to the OpenCode formats.

from sccs.convert.claude_to_opencode import (
    DEFAULT_OPENCODE_MODEL_MAP,
    MODEL_MAP,
    TIER_KEYWORDS,
    convert_agent_frontmatter,
    convert_command_frontmatter,
    convert_mcp_server,
    map_model,
    match_models,
    tools_to_permission,
)
from sccs.convert.fish_to_pwsh import ConversionReport, FishToPwshConverter
from sccs.convert.fish_to_zsh import FishToZshConverter, ZshConversionReport
from sccs.convert.frontmatter import parse_frontmatter, render_frontmatter

__all__ = [
    "DEFAULT_OPENCODE_MODEL_MAP",
    "MODEL_MAP",
    "TIER_KEYWORDS",
    "ConversionReport",
    "FishToPwshConverter",
    "FishToZshConverter",
    "ZshConversionReport",
    "convert_agent_frontmatter",
    "convert_command_frontmatter",
    "convert_mcp_server",
    "map_model",
    "match_models",
    "parse_frontmatter",
    "render_frontmatter",
    "tools_to_permission",
]
