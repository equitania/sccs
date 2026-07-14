# SCCS Fish -> Zsh Block Translator
#
# Best-effort, line-based translation of fish control-flow and statements
# into zsh. Used for functions/*.fish (real function bodies) AND conf.d
# files (inline `if ... end` blocks), unlike the PowerShell converter which
# only stubs them.
#
# This is deliberately a pragmatic line-oriented state machine, not a fish
# parser. Lines that cannot be confidently translated are preserved as
# `# fish-untranslated:` comments; if a file accumulates too many of them
# (or its block structure does not balance) the caller falls back to a
# fully commented stub so we NEVER emit syntactically broken zsh.

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

from sccs.convert.zsh_rules import ZshConversionResult, convert_line_zsh, rewrite_fish_tokens

# Fish builtins/idioms with no safe automatic zsh mapping. Statement-level
# prefixes checked against the stripped line.
UNTRANSLATABLE_PREFIXES: tuple[str, ...] = (
    "string ",
    "math ",
    "argparse ",
    "set -U",
    "set --universal",
    "commandline",
    "bind ",
    "funced",
    "funcsave",
    "emit ",
    "block ",
    "fish_config",
    "read ",
    "complete ",  # fish completion builtin — zsh uses compdef/fpath instead
    "functions --copy",
)

# Sourcing a *.fish file from zsh would parse fish syntax — always wrong.
# (Platform *.macos.fish sources are also correctly dropped here: their
# content is converted separately into a uname-guarded conf.d file.)
_SOURCE_FISH_PATTERN = re.compile(r"\bsource\b[^|;]*\.fish\b")

# `<tool> init|hook|completion fish | source` — the canonical fish hook line
# of zoxide/starship/direnv & friends. Maps 1:1 onto the zsh equivalent.
_INIT_PIPE_SOURCE_PATTERN = re.compile(
    r"^(?P<cmd>[\w./-]+)\s+(?P<verb>init|hook|completion)\s+fish(?P<rest>[^|]*?)\s*\|\s*source\s*$"
)

# `A; and B; or C` — fish statement chains on one line.
_CHAIN_SPLIT_PATTERN = re.compile(r";\s*(and|or)\s+")

# Substrings that mark a line as untranslatable wherever they appear.
UNTRANSLATABLE_SUBSTRINGS: tuple[str, ...] = (
    "psub",
    "$argv[",  # only non-numeric indices/ranges survive rewrite_fish_tokens
)

# Function-header flags that turn the whole file into a stub — fish event
# handlers have no zsh equivalent worth guessing at.
_EVENT_FLAGS: tuple[str, ...] = (
    "--on-event",
    "--on-variable",
    "--on-signal",
    "--on-process-exit",
    "--on-job-exit",
    "-e",
    "-v",
    "-s",
)

# Fraction of untranslated body lines above which a file should be stubbed.
STUB_THRESHOLD = 0.3

_SET_PATTERN = re.compile(
    r"^set\s+(?P<flags>(?:-\S+\s+)*)(?P<name>[A-Za-z_]\w*)(?:\s+(?P<rest>.*))?$",
)

_FOR_PATTERN = re.compile(r"^for\s+(?P<var>[A-Za-z_]\w*)\s+in\s+(?P<rest>.+)$")

# `if cond; ...; end` one-liners — out of scope for the line-based machine.
_ONELINER_BLOCK = re.compile(r"^(?:if|for|while|switch|function|begin)\b.*;\s*end\b")


@dataclass
class _Frame:
    kind: str  # "function" | "if" | "for" | "while" | "switch" | "begin"
    case_open: bool = False
    indent: str = ""


@dataclass
class BlockTranslation:
    """Result of translating a sequence of fish lines to zsh."""

    lines: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(
        default_factory=lambda: {
            "alias": 0,
            "env": 0,
            "path": 0,
            "translated": 0,
            "passthrough": 0,
            "untranslated": 0,
        }
    )
    body_lines: int = 0  # non-blank, non-comment source lines
    balanced: bool = True
    event_handler: bool = False
    uses_argparse: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def should_stub(self) -> bool:
        """True when the translation is too lossy to ship as live zsh."""
        if self.event_handler or not self.balanced:
            return True
        # A function built around fish's argparse is semantically dead without
        # it (every `$_flag_*` reference stays unset) — stub it honestly.
        if self.uses_argparse:
            return True
        if self.body_lines == 0:
            return False
        return (self.stats["untranslated"] / self.body_lines) > STUB_THRESHOLD


def _split_tokens(text: str) -> list[str]:
    """Tokenize preserving quotes; fall back to whitespace split."""
    try:
        return shlex.split(text, posix=False)
    except ValueError:
        return text.split()


def _is_untranslatable(stripped: str) -> bool:
    if any(stripped.startswith(prefix) for prefix in UNTRANSLATABLE_PREFIXES):
        return True
    if _SOURCE_FISH_PATTERN.search(stripped):
        return True
    rewritten = rewrite_fish_tokens(stripped)
    return any(marker in rewritten for marker in UNTRANSLATABLE_SUBSTRINGS)


def translate_expr(text: str) -> str | None:
    """
    Translate a fish condition/statement expression into zsh.

    Returns None when the expression has no confident zsh equivalent.
    """
    stripped = text.strip()

    # `A; and B; or C` chains: translate each segment, join with && / ||.
    if _CHAIN_SPLIT_PATTERN.search(stripped):
        parts = _CHAIN_SPLIT_PATTERN.split(stripped)
        translated = translate_expr(parts[0])
        if translated is None:
            return None
        for keyword, segment in zip(parts[1::2], parts[2::2], strict=True):
            translated_segment = translate_expr(segment)
            if translated_segment is None:
                return None
            joiner = "&&" if keyword == "and" else "||"
            translated = f"{translated} {joiner} {translated_segment}"
        return translated

    if stripped.startswith("not "):
        inner = translate_expr(stripped[4:])
        return None if inner is None else f"! {inner}"

    # `zoxide init fish | source` -> `eval "$(zoxide init zsh)"` (same for
    # starship init / direnv hook / ... — the canonical shell-hook idiom).
    match = _INIT_PIPE_SOURCE_PATTERN.match(stripped)
    if match:
        rest = match.group("rest").rstrip()
        return f'eval "$({match.group("cmd")} {match.group("verb")} zsh{rest})"'

    if _is_untranslatable(stripped):
        return None

    # `command -q X` / `command -sq X` / `command --query X` -> command -v
    match = re.match(r"^command\s+(?:-s?q|-qs|--query|--search\s+--query)\s+(?P<cmd>\S+)\s*$", stripped)
    if match:
        return f"command -v {match.group('cmd')} >/dev/null 2>&1"

    # `type -q X` -> command -v
    match = re.match(r"^type\s+-q\s+(?P<cmd>\S+)\s*$", stripped)
    if match:
        return f"command -v {match.group('cmd')} >/dev/null 2>&1"

    # `functions -q name` -> typeset -f
    match = re.match(r"^functions\s+-q\s+(?P<fn>\S+)\s*$", stripped)
    if match:
        return f"typeset -f {match.group('fn')} >/dev/null 2>&1"

    # `set -q VAR` -> [[ -v VAR ]]
    match = re.match(r"^set\s+(?:-q|--query)\s+(?P<var>[A-Za-z_]\w*)\s*$", stripped)
    if match:
        return f"[[ -v {match.group('var')} ]]"

    # `status is-interactive` / `status --is-interactive` -> [[ -o interactive ]]
    match = re.match(r"^status\s+(?:--)?is-(?P<mode>interactive|login)\s*$", stripped)
    if match:
        return f"[[ -o {match.group('mode')} ]]"

    return rewrite_fish_tokens(stripped)


def _translate_set(stripped: str, *, in_function: bool) -> tuple[str | None, str]:
    """
    Translate a `set` statement. Returns (zsh_or_None, kind).

    kind is "env" for exports, "translated" otherwise.
    """
    match = _SET_PATTERN.match(stripped)
    if not match:
        return None, "untranslated"

    flags = match.group("flags") or ""
    name = match.group("name")
    rest = (match.group("rest") or "").strip()

    # Long options must NOT decay into short-flag characters (`--export`
    # contains an `e` but is not `--erase`).
    short_flags: set[str] = set()
    long_flags: set[str] = set()
    for part in flags.split():
        if part.startswith("--"):
            long_flags.add(part)
        elif part.startswith("-"):
            short_flags.update(part[1:])

    if "--erase" in long_flags or "e" in short_flags:
        return f"unset {name}", "translated"
    if "--query" in long_flags or "q" in short_flags:
        return f"[[ -v {name} ]]", "translated"
    if "--universal" in long_flags or "U" in short_flags:
        return None, "untranslated"
    if {"--append", "--prepend"} & long_flags or {"a", "p", "P"} & short_flags:
        return None, "untranslated"

    value = rewrite_fish_tokens(rest)
    tokens = _split_tokens(value)
    if len(tokens) > 1:
        assignment = f"{name}=({value})"
    elif tokens:
        assignment = f"{name}={tokens[0]}"
    else:
        assignment = f"{name}="

    exported = "--export" in long_flags or "x" in short_flags
    local = "--local" in long_flags or "l" in short_flags
    global_ = "--global" in long_flags or "g" in short_flags

    if exported:
        return f"export {assignment}", "env"
    if local and in_function:
        return f"local {assignment}", "translated"
    if global_ and in_function:
        return f"typeset -g {assignment}", "translated"
    if in_function and not global_:
        # fish default scope inside a function is function-local.
        return f"local {assignment}", "translated"
    return assignment, "translated"


def _parse_function_header(stripped: str) -> tuple[str | None, str | None, list[str], bool]:
    """
    Parse a `function name [flags]` header.

    Returns (name, description, argument_names, is_event_handler).
    """
    tokens = _split_tokens(stripped)
    if len(tokens) < 2:
        return None, None, [], False

    name = tokens[1]
    description: str | None = None
    argument_names: list[str] = []
    is_event = False

    i = 2
    while i < len(tokens):
        token = tokens[i]
        if token in _EVENT_FLAGS or token.startswith("--on-"):
            is_event = True
            i += 2
        elif token in ("-d", "--description"):
            if i + 1 < len(tokens):
                description = tokens[i + 1].strip("'\"")
            i += 2
        elif token.startswith("--description="):
            description = token.split("=", 1)[1].strip("'\"")
            i += 1
        elif token in ("-a", "--argument-names"):
            i += 1
            while i < len(tokens) and not tokens[i].startswith("-"):
                argument_names.append(tokens[i])
                i += 1
        elif token in ("-w", "--wraps") or token.startswith("--wraps="):
            # Completion hint — no zsh mapping needed.
            i += 2 if token in ("-w", "--wraps") else 1
        else:
            i += 1

    return name, description, argument_names, is_event


_END_TOKEN: dict[str, str] = {
    "function": "}",
    "if": "fi",
    "for": "done",
    "while": "done",
    "switch": "esac",
    "begin": "}",
}


def translate_block(fish_lines: list[str]) -> BlockTranslation:  # noqa: C901
    """
    Translate fish source lines into zsh, best-effort.

    The caller decides via `result.should_stub` whether the translation is
    good enough to ship or whether the file should be emitted as a stub.
    """
    result = BlockTranslation()
    stack: list[_Frame] = []

    def emit(line: str) -> None:
        result.lines.append(line)

    def untranslated(indent: str, stripped: str) -> None:
        emit(f"{indent}# fish-untranslated: {stripped}")
        result.stats["untranslated"] += 1

    for raw_line in fish_lines:
        stripped = raw_line.strip()
        indent = raw_line[: len(raw_line) - len(raw_line.lstrip())]

        if not stripped:
            emit("")
            continue
        if stripped.startswith("#"):
            emit(raw_line)
            result.stats["passthrough"] += 1
            continue

        result.body_lines += 1
        in_function = any(frame.kind == "function" for frame in stack)

        if stripped.startswith("argparse"):
            result.uses_argparse = True

        # One-liner blocks (`if x; y; end`) are out of scope.
        if _ONELINER_BLOCK.match(stripped):
            untranslated(indent, stripped)
            continue

        # ---- block structure -------------------------------------------------
        if stripped.startswith("function ") or stripped == "function":
            name, description, argument_names, is_event = _parse_function_header(stripped)
            if is_event:
                result.event_handler = True
            if name is None:
                untranslated(indent, stripped)
                result.balanced = False
                continue
            stack.append(_Frame(kind="function", indent=indent))
            if description:
                emit(f"{indent}# {description}")
            # Quote the function name: zsh expands aliases at PARSE time, so an
            # unquoted `hg() {` breaks when conf.d already defined `alias hg=…`
            # ("defining function based on alias"). Quoting suppresses alias
            # expansion; the definition itself is unchanged.
            emit(f"{indent}'{name}'() {{")
            for position, arg_name in enumerate(argument_names, start=1):
                emit(f'{indent}  local {arg_name}="${{{position}}}"')
            result.stats["translated"] += 1
            continue

        if stripped == "end":
            if not stack:
                result.balanced = False
                untranslated(indent, stripped)
                continue
            frame = stack.pop()
            if frame.kind == "switch" and frame.case_open:
                emit(f"{frame.indent}    ;;")
            emit(f"{frame.indent}{_END_TOKEN[frame.kind]}")
            result.stats["translated"] += 1
            continue

        if stripped.startswith("else if "):
            condition = translate_expr(stripped[len("else if ") :])
            if condition is None:
                emit(f"{indent}elif false; then  # fish-untranslated: {stripped}")
                result.stats["untranslated"] += 1
            else:
                emit(f"{indent}elif {condition}; then")
                result.stats["translated"] += 1
            continue

        if stripped == "else":
            emit(f"{indent}else")
            result.stats["translated"] += 1
            continue

        if stripped.startswith("if "):
            stack.append(_Frame(kind="if", indent=indent))
            condition = translate_expr(stripped[3:])
            if condition is None:
                emit(f"{indent}if false; then  # fish-untranslated: {stripped}")
                result.stats["untranslated"] += 1
            else:
                emit(f"{indent}if {condition}; then")
                result.stats["translated"] += 1
            continue

        if stripped.startswith("while "):
            stack.append(_Frame(kind="while", indent=indent))
            condition = translate_expr(stripped[6:])
            if condition is None:
                emit(f"{indent}while false; do  # fish-untranslated: {stripped}")
                result.stats["untranslated"] += 1
            else:
                emit(f"{indent}while {condition}; do")
                result.stats["translated"] += 1
            continue

        if stripped.startswith("for "):
            match = _FOR_PATTERN.match(stripped)
            stack.append(_Frame(kind="for", indent=indent))
            if match is None:
                emit(f"{indent}for _ in; do  # fish-untranslated: {stripped}")
                result.stats["untranslated"] += 1
            else:
                iterable = rewrite_fish_tokens(match.group("rest"))
                emit(f"{indent}for {match.group('var')} in {iterable}; do")
                result.stats["translated"] += 1
            continue

        if stripped.startswith("switch "):
            stack.append(_Frame(kind="switch", indent=indent))
            subject = rewrite_fish_tokens(stripped[7:].strip())
            emit(f"{indent}case {subject} in")
            result.stats["translated"] += 1
            continue

        if stripped.startswith("case ") and stack and stack[-1].kind == "switch":
            frame = stack[-1]
            if frame.case_open:
                emit(f"{frame.indent}    ;;")
            patterns = [token.strip("'\"") for token in _split_tokens(stripped[5:])]
            emit(f"{frame.indent}  {'|'.join(patterns) or '*'})")
            frame.case_open = True
            result.stats["translated"] += 1
            continue

        if stripped == "begin":
            stack.append(_Frame(kind="begin", indent=indent))
            emit(f"{indent}{{")
            result.stats["translated"] += 1
            continue

        # ---- `and` / `or` continuation lines ---------------------------------
        if stripped.startswith(("and ", "or ")):
            keyword, rest = stripped.split(" ", 1)
            translated = translate_expr(rest)
            if translated is None:
                untranslated(indent, stripped)
                continue
            check = "-eq" if keyword == "and" else "-ne"
            emit(f"{indent}[ $? {check} 0 ] && {translated}")
            result.stats["translated"] += 1
            continue

        # ---- simple declarations (alias / set -gx / fish_add_path / abbr) ----
        rule_result: ZshConversionResult | None = convert_line_zsh(stripped)
        if rule_result is not None:
            emit(f"{indent}{rule_result.zsh}")
            if rule_result.kind in result.stats:
                result.stats[rule_result.kind] += 1
            else:
                result.stats["translated"] += 1
            continue

        # ---- general `set` statements ----------------------------------------
        if stripped.startswith("set "):
            translated_set, kind = _translate_set(stripped, in_function=in_function)
            if translated_set is None:
                untranslated(indent, stripped)
            else:
                emit(f"{indent}{translated_set}")
                result.stats[kind if kind in result.stats else "translated"] += 1
            continue

        # ---- generic statement -------------------------------------------------
        translated_stmt = translate_expr(stripped)
        if translated_stmt is None:
            untranslated(indent, stripped)
            continue
        emit(f"{indent}{translated_stmt}")
        result.stats["translated"] += 1

    if stack:
        result.balanced = False
        result.warnings.append(f"Unbalanced block structure ({len(stack)} unclosed block(s))")

    return result
