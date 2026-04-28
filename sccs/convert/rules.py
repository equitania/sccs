# SCCS Fish -> PowerShell Conversion Rules
#
# Each rule operates on a single non-empty, non-comment fish line and either
# returns a PowerShell-equivalent or signals "not handled" so the caller can
# fall back to a passthrough comment.

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# Pattern that matches a fish alias declaration:
#   alias name=value
#   alias name='value with spaces'
#   alias name="value with $vars"
ALIAS_PATTERN = re.compile(
    r"""
    ^\s*alias\s+
    (?P<name>[A-Za-z_][\w\-+]*)\s*
    =\s*
    (?P<value>
        '(?P<sq>[^']*)'
      | "(?P<dq>[^"]*)"
      | (?P<bare>\S+)
    )
    \s*$
    """,
    re.VERBOSE,
)

# `set -gx VAR value` (with optional quoting and $vars in the value).
SET_GX_PATTERN = re.compile(
    r"""
    ^\s*set\s+(?:-gx|-x|--export)\s+
    (?P<name>[A-Za-z_]\w*)\s+
    (?P<value>
        '(?P<sq>[^']*)'
      | "(?P<dq>[^"]*)"
      | (?P<bare>\S+)
    )
    \s*$
    """,
    re.VERBOSE,
)

# `fish_add_path some/path`
FISH_ADD_PATH_PATTERN = re.compile(
    r"""
    ^\s*fish_add_path\s+
    (?P<value>
        '(?P<sq>[^']*)'
      | "(?P<dq>[^"]*)"
      | (?P<bare>\S+)
    )
    \s*$
    """,
    re.VERBOSE,
)

# `abbr -a name expansion` — Fish abbreviations.
ABBR_PATTERN = re.compile(
    r"""
    ^\s*abbr\s+(?:-a|--add)\s+
    (?P<name>[A-Za-z_][\w\-+]*)\s+
    (?P<value>.+?)
    \s*$
    """,
    re.VERBOSE,
)

# Fish variable references we want to keep as PowerShell built-ins (no $env:
# prefix). PowerShell exposes these directly. Everything else we treat as an
# env-var reference and rewrite `$FOO` -> `$env:FOO`.
_PS_BUILTIN_VARS: frozenset[str] = frozenset(
    {"HOME", "PWD", "PROFILE", "PSScriptRoot", "args", "_"}
)

# Pattern for `$VAR` or `${VAR}` references in shell strings.
_VAR_REF_PATTERN = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def _extract_value(match: re.Match[str]) -> str:
    """Pull the unquoted value out of one of the alternation groups."""
    if match.group("sq") is not None:
        return match.group("sq")
    if match.group("dq") is not None:
        return match.group("dq")
    return match.group("bare")


def _rewrite_vars(value: str) -> str:
    """
    Rewrite Fish-style variable references for PowerShell.

    Fish auto-resolves `$FOO` against env vars, so a value like `"$HOME/x"`
    works in Fish but in PowerShell `$HOME` is a built-in (fine) while
    `$GITBASE_PATH` would be an *unset local variable* unless we route it
    through `$env:`. We rewrite anything that's not a known PS built-in.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _PS_BUILTIN_VARS:
            return f"${name}"
        return f"$env:{name}"

    return _VAR_REF_PATTERN.sub(replace, value)


@dataclass
class ConversionResult:
    """Result of converting a single fish line."""

    powershell: str
    kind: str  # "alias", "function", "env", "path", "abbr", "comment", "skipped"


def convert_alias(line: str) -> ConversionResult | None:
    """
    Convert `alias name=value` to PowerShell.

    - Aliases without arguments use Set-Alias for native PS semantics.
    - Aliases with arguments use a function with `@args` splatting because
      PowerShell aliases cannot carry arguments.
    """
    match = ALIAS_PATTERN.match(line)
    if not match:
        return None

    name = match.group("name")
    value = _extract_value(match)
    rewritten = _rewrite_vars(value).strip()

    if not rewritten:
        return ConversionResult(
            powershell=f"# WARN: empty alias value for '{name}': {line.rstrip()}",
            kind="comment",
        )

    parts = rewritten.split()
    if len(parts) == 1:
        # Simple binary alias: cat=uu-cat -> Set-Alias
        ps = f"Set-Alias -Name {name} -Value {parts[0]} -Scope Global -Force"
        return ConversionResult(powershell=ps, kind="alias")

    # Alias carries arguments — wrap in a function with @args.
    cmd = parts[0]
    args = " ".join(parts[1:])
    ps = f"function {name} {{ {cmd} {args} @args }}"
    return ConversionResult(powershell=ps, kind="function")


def convert_set_gx(line: str) -> ConversionResult | None:
    """Convert `set -gx VAR value` to `$env:VAR = "value"`."""
    match = SET_GX_PATTERN.match(line)
    if not match:
        return None

    name = match.group("name")
    value = _extract_value(match)
    rewritten = _rewrite_vars(value)

    # Quote the value; escape any inner double quotes for safety.
    escaped = rewritten.replace('"', '`"')
    ps = f'$env:{name} = "{escaped}"'
    return ConversionResult(powershell=ps, kind="env")


def convert_fish_add_path(line: str) -> ConversionResult | None:
    """
    Convert `fish_add_path /some/dir` to a duplicate-aware PATH prepend
    using PowerShell's platform-correct path separator.
    """
    match = FISH_ADD_PATH_PATTERN.match(line)
    if not match:
        return None

    value = _extract_value(match)
    rewritten = _rewrite_vars(value).replace('"', '`"')

    ps = (
        f'if (-not ($env:PATH -split [IO.Path]::PathSeparator | '
        f'Where-Object {{ $_ -eq "{rewritten}" }})) '
        f'{{ $env:PATH = "{rewritten}" + [IO.Path]::PathSeparator + $env:PATH }}'
    )
    return ConversionResult(powershell=ps, kind="path")


def convert_abbr(line: str) -> ConversionResult | None:
    """
    Convert Fish abbreviations to a PowerShell function (closest semantic
    fit — PowerShell has no native abbreviations).
    """
    match = ABBR_PATTERN.match(line)
    if not match:
        return None

    name = match.group("name")
    expansion = _rewrite_vars(match.group("value").strip())
    parts = expansion.split()
    if len(parts) == 1:
        ps = f"Set-Alias -Name {name} -Value {parts[0]} -Scope Global -Force"
        return ConversionResult(powershell=ps, kind="alias")
    cmd, *rest = parts
    ps = f'function {name} {{ {cmd} {" ".join(rest)} @args }}'
    return ConversionResult(powershell=ps, kind="function")


# Ordered conversion pipeline; first rule that matches wins.
RULE_PIPELINE: tuple[Callable[[str], ConversionResult | None], ...] = (
    convert_alias,
    convert_set_gx,
    convert_fish_add_path,
    convert_abbr,
)


def convert_line(line: str) -> ConversionResult | None:
    """
    Apply the conversion pipeline to a single fish line.

    Returns None if no rule matched (caller should preserve the line as a
    fish-original comment).
    """
    for rule in RULE_PIPELINE:
        result = rule(line)
        if result is not None:
            return result
    return None
