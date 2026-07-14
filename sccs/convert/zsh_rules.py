# SCCS Fish -> Zsh Conversion Rules
#
# Line-level rules for the fish->zsh converter. Fish's simple declarations
# (aliases, exports, PATH manipulation, abbreviations) map almost 1:1 onto
# zsh, so — unlike the PowerShell rules — no `$env:` rewriting is needed.
# Only fish-specific variable idioms ($argv, $status, (count $argv)) and
# fish's `(cmd)` command substitution are rewritten.
#
# The regex patterns are shared with the PowerShell rules (rules.py); only
# the emitted right-hand sides differ.

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from sccs.convert.rules import (
    ABBR_PATTERN,
    ALIAS_PATTERN,
    SET_GX_PATTERN,
)

# Fish also supports the space-separated alias form `alias name 'value'`
# (no `=`). The shared ALIAS_PATTERN only covers the `=` form.
ALIAS_SPACE_PATTERN = re.compile(
    r"""
    ^\s*alias\s+
    (?P<name>[A-Za-z_][\w\-+]*)\s+
    (?P<value>
        '(?P<sq>[^']*)'
      | "(?P<dq>[^"]*)"
      | (?P<bare>\S.*?)
    )
    \s*$
    """,
    re.VERBOSE,
)

# `$argv[N]` -> `$N` (positional parameters). Only literal indices are safe;
# ranges like `$argv[2..]` have no direct zsh equivalent and are left alone
# (the block translator flags them as untranslated).
_ARGV_INDEX_PATTERN = re.compile(r"\$argv\[(\d+)\]")

# Bare `$argv` (not followed by `[`) -> `"$@"`, absorbing surrounding quotes.
_ARGV_BARE_PATTERN = re.compile(r'"\$argv"|\$argv\b(?!\[)')

# `(count $argv)` -> `$#`.
_COUNT_ARGV_PATTERN = re.compile(r"\(\s*count\s+\$argv\s*\)")

# `$status` -> `$?`.
_STATUS_PATTERN = re.compile(r"\$status\b")

# Fish command substitution `(cmd ...)` -> `$(cmd ...)`. Conservative: only
# an opening paren that is not already part of `$(` and is followed by
# something command-like. Closing parens are left untouched (they are valid
# in both syntaxes).
_CMD_SUB_PATTERN = re.compile(r"(?<![\w$])\((?=[A-Za-z_./~])")


def rewrite_fish_tokens(value: str) -> str:
    """
    Rewrite fish-specific variable/substitution idioms into zsh equivalents.

    Order matters: `(count $argv)` must be handled before the generic
    command-substitution rewrite, and `$argv[N]` before bare `$argv`.
    """
    value = _COUNT_ARGV_PATTERN.sub("$#", value)
    value = _ARGV_INDEX_PATTERN.sub(lambda m: f"${m.group(1)}", value)
    value = _ARGV_BARE_PATTERN.sub('"$@"', value)
    value = _STATUS_PATTERN.sub("$?", value)
    value = _CMD_SUB_PATTERN.sub("$(", value)
    return value


def _extract_value(match: re.Match[str]) -> str:
    """Pull the unquoted value out of one of the alternation groups."""
    if match.group("sq") is not None:
        return match.group("sq")
    if match.group("dq") is not None:
        return match.group("dq")
    # Fish expands `~` only in unquoted tokens; the zsh output ends up inside
    # double quotes where `~` stays literal — substitute $HOME explicitly.
    bare: str = match.group("bare")
    if bare.startswith("~/"):
        return "$HOME/" + bare[2:]
    if bare == "~":
        return "$HOME"
    return bare


def _sq(value: str) -> str:
    """Wrap a value in single quotes, escaping embedded single quotes."""
    return "'" + value.replace("'", "'\\''") + "'"


@dataclass
class ZshConversionResult:
    """Result of converting a single fish line to zsh."""

    zsh: str
    kind: str  # "alias", "env", "path", "comment"


def convert_alias(line: str) -> ZshConversionResult | None:
    """
    Convert `alias name=value` to a zsh alias.

    Zsh aliases carry arguments natively, so — unlike PowerShell — no
    function wrapping is needed for multi-word values.
    """
    match = ALIAS_PATTERN.match(line) or ALIAS_SPACE_PATTERN.match(line)
    if not match:
        return None

    name = match.group("name")
    value = rewrite_fish_tokens(_extract_value(match)).strip()

    if not value:
        return ZshConversionResult(
            zsh=f"# WARN: empty alias value for '{name}': {line.rstrip()}",
            kind="comment",
        )

    return ZshConversionResult(zsh=f"alias {name}={_sq(value)}", kind="alias")


def convert_set_gx(line: str) -> ZshConversionResult | None:
    """Convert `set -gx VAR value` to `export VAR="value"`."""
    match = SET_GX_PATTERN.match(line)
    if not match:
        return None

    name = match.group("name")
    value = rewrite_fish_tokens(_extract_value(match))
    escaped = value.replace('"', '\\"')
    return ZshConversionResult(zsh=f'export {name}="{escaped}"', kind="env")


# fish_add_path accepts flags (--path, -g, -m, ...) and MULTIPLE directories;
# the shared single-value pattern doesn't cover that, so zsh gets its own.
_FISH_ADD_PATH_LINE = re.compile(r"^\s*fish_add_path\s+(?P<rest>.+?)\s*$")


def _path_guard(directory: str) -> str:
    return f'[[ ":$PATH:" != *":{directory}:"* ]] && export PATH="{directory}:$PATH"'


def convert_fish_add_path(line: str) -> ZshConversionResult | None:
    """
    Convert `fish_add_path [flags] DIR...` to duplicate-aware PATH prepends.

    Flags (--path, -g/--global, -m/--move, ...) only steer WHERE fish stores
    the entry — irrelevant for the generated zsh, so they are dropped.
    """
    match = _FISH_ADD_PATH_LINE.match(line)
    if not match:
        return None

    guards: list[str] = []
    for token in match.group("rest").split():
        if token.startswith("-"):
            continue
        value = token.strip("'\"")
        if value.startswith("~/"):
            value = "$HOME/" + value[2:]
        elif value == "~":
            value = "$HOME"
        value = rewrite_fish_tokens(value).replace('"', '\\"')
        guards.append(_path_guard(value))

    if not guards:
        return ZshConversionResult(zsh=f"# WARN: no path in: {line.strip()}", kind="comment")
    return ZshConversionResult(zsh="\n".join(guards), kind="path")


def convert_abbr(line: str) -> ZshConversionResult | None:
    """Convert fish abbreviations to plain zsh aliases (closest fit)."""
    match = ABBR_PATTERN.match(line)
    if not match:
        return None

    name = match.group("name")
    expansion = rewrite_fish_tokens(match.group("value").strip())
    # Strip one level of quoting — the abbr value regex captures greedily.
    if len(expansion) >= 2 and expansion[0] == expansion[-1] and expansion[0] in "'\"":
        expansion = expansion[1:-1]
    return ZshConversionResult(zsh=f"alias {name}={_sq(expansion)}", kind="alias")


# Ordered conversion pipeline; first rule that matches wins.
ZSH_RULE_PIPELINE: tuple[Callable[[str], ZshConversionResult | None], ...] = (
    convert_alias,
    convert_set_gx,
    convert_fish_add_path,
    convert_abbr,
)


def convert_line_zsh(line: str) -> ZshConversionResult | None:
    """
    Apply the zsh conversion pipeline to a single fish line.

    Returns None if no rule matched (the block translator then attempts a
    statement-level translation before falling back to a comment).
    """
    for rule in ZSH_RULE_PIPELINE:
        result = rule(line)
        if result is not None:
            return result
    return None
