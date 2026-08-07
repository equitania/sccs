# Tests for the Fish -> Zsh converter (rules, block translator, directory
# conversion, CLI wiring, and zsh syntax validity of the generated output).

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sccs.cli import cli
from sccs.convert.fish_to_zsh import DEFAULT_ZSH_SKIP_PATTERNS, FishToZshConverter
from sccs.convert.zsh_block import translate_block, translate_expr
from sccs.convert.zsh_rules import (
    convert_abbr,
    convert_alias,
    convert_fish_add_path,
    convert_line_zsh,
    convert_set_gx,
    rewrite_fish_tokens,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# -------------------------------------------------------------- line rules


class TestZshAliasRule:
    def test_simple_alias(self):
        result = convert_alias("alias gs='git status'")
        assert result is not None
        assert result.zsh == "alias gs='git status'"
        assert result.kind == "alias"

    def test_space_form_alias(self):
        result = convert_alias("alias ll 'ls -la'")
        assert result is not None
        assert result.zsh == "alias ll='ls -la'"

    def test_space_form_bare_alias(self):
        result = convert_alias("alias gp git push")
        assert result is not None
        assert result.zsh == "alias gp='git push'"

    def test_alias_with_embedded_single_quote(self):
        result = convert_alias('alias say="echo it\'s")'.rstrip(")"))
        assert result is not None
        assert "'\\''" in result.zsh

    def test_empty_alias_warns(self):
        result = convert_alias("alias empty=''")
        assert result is not None
        assert result.kind == "comment"
        assert "WARN" in result.zsh

    def test_non_alias_returns_none(self):
        assert convert_alias("set -gx FOO bar") is None


class TestZshSetGx:
    def test_simple_export(self):
        result = convert_set_gx("set -gx EDITOR nvim")
        assert result is not None
        assert result.zsh == 'export EDITOR="nvim"'
        assert result.kind == "env"

    def test_quoted_value(self):
        # Single-quoted in fish means literal, so it stays literal in zsh.
        result = convert_set_gx("set -gx GREETING 'hello world'")
        assert result is not None
        assert result.zsh == "export GREETING='hello world'"

    def test_variable_reference_kept(self):
        result = convert_set_gx('set -gx GOPATH "$HOME/go"')
        assert result is not None
        assert result.zsh == 'export GOPATH="$HOME/go"'

    def test_bare_tilde_expands_to_home(self):
        result = convert_set_gx("set -gx CARGO_HOME ~/.cargo")
        assert result is not None
        assert result.zsh == 'export CARGO_HOME="$HOME/.cargo"'


class TestZshLiteralValueSafety:
    """A fish value that is inert must not become live zsh code.

    Fish single quotes suppress every expansion, and fish has no backtick
    command substitution at all — so text that merely *looks* like code is
    plain data at the source. Emitting it into a zsh double-quoted string
    used to execute it on the next shell start.
    """

    def test_single_quoted_command_substitution_stays_literal(self):
        result = convert_set_gx("set -gx B 'text (whoami) literal'")
        assert result is not None
        assert result.zsh == "export B='text (whoami) literal'"
        assert "$(whoami)" not in result.zsh

    def test_single_quoted_dollar_stays_literal(self):
        result = convert_set_gx("set -gx A 'literal $HOME stays'")
        assert result is not None
        assert result.zsh == "export A='literal $HOME stays'"

    def test_single_quoted_backtick_stays_literal(self):
        result = convert_set_gx("set -gx C 'back`id`tick'")
        assert result is not None
        assert result.zsh == "export C='back`id`tick'"

    def test_double_quoted_backtick_is_escaped(self):
        # Fish double quotes expand $var but never backticks.
        result = convert_set_gx('set -gx C "has `id` inside"')
        assert result is not None
        assert result.zsh == 'export C="has \\`id\\` inside"'

    def test_bare_backtick_is_escaped(self):
        result = convert_set_gx("set -gx C pre`id`post")
        assert result is not None
        assert result.zsh == 'export C="pre\\`id\\`post"'

    def test_intended_command_substitution_survives(self):
        # An UNQUOTED `(cmd)` is real fish command substitution — it must
        # still become `$(cmd)`. The fix must not break this feature.
        result = convert_set_gx("set -gx D (date)")
        assert result is not None
        assert result.zsh == 'export D="$(date)"'

    def test_intended_variable_expansion_survives(self):
        result = convert_set_gx('set -gx E "expand $HOME here"')
        assert result is not None
        assert result.zsh == 'export E="expand $HOME here"'

    def test_add_path_backtick_is_escaped(self):
        result = convert_fish_add_path("fish_add_path /opt/`id`/bin")
        assert result is not None
        assert "\\`id\\`" in result.zsh
        assert "/opt/`id`/bin" not in result.zsh

    def test_add_path_home_substitution_survives(self):
        result = convert_fish_add_path("fish_add_path ~/bin")
        assert result is not None
        assert '"$HOME/bin:$PATH"' in result.zsh


class TestZshAliasRuleUnchanged:
    def test_alias_was_already_single_quoted(self):
        """Regression guard: aliases were never vulnerable — keep it that way."""
        from sccs.convert.zsh_rules import convert_alias

        result = convert_alias("alias danger 'echo `id`'")
        assert result is not None
        assert result.zsh == "alias danger='echo `id`'"


class TestZshAddPath:
    def test_add_path_dedup_guard(self):
        result = convert_fish_add_path("fish_add_path /opt/homebrew/bin")
        assert result is not None
        assert result.kind == "path"
        assert result.zsh == ('[[ ":$PATH:" != *":/opt/homebrew/bin:"* ]] && export PATH="/opt/homebrew/bin:$PATH"')

    def test_tilde_path_expands_to_home(self):
        result = convert_fish_add_path("fish_add_path ~/.local/bin")
        assert result is not None
        assert "$HOME/.local/bin" in result.zsh
        assert "~" not in result.zsh

    def test_flags_are_dropped(self):
        result = convert_fish_add_path("fish_add_path --path /usr/local/bin")
        assert result is not None
        assert result.kind == "path"
        assert '":/usr/local/bin:"' in result.zsh
        assert "--path" not in result.zsh

    def test_multiple_paths_one_guard_each(self):
        result = convert_fish_add_path("fish_add_path -g $HOME/bin /opt/bin")
        assert result is not None
        lines = result.zsh.splitlines()
        assert len(lines) == 2
        assert "$HOME/bin" in lines[0]
        assert "/opt/bin" in lines[1]


class TestZshAbbr:
    def test_abbr_becomes_alias(self):
        result = convert_abbr("abbr -a gco git checkout")
        assert result is not None
        assert result.zsh == "alias gco='git checkout'"

    def test_quoted_abbr(self):
        result = convert_abbr("abbr --add gst 'git status'")
        assert result is not None
        assert result.zsh == "alias gst='git status'"


class TestFishTokenRewrites:
    def test_argv_bare(self):
        assert rewrite_fish_tokens("echo $argv") == 'echo "$@"'

    def test_argv_quoted(self):
        assert rewrite_fish_tokens('echo "$argv"') == 'echo "$@"'

    def test_argv_index(self):
        assert rewrite_fish_tokens("echo $argv[1] $argv[2]") == "echo $1 $2"

    def test_count_argv(self):
        assert rewrite_fish_tokens("test (count $argv) -eq 0") == "test $# -eq 0"

    def test_status(self):
        assert rewrite_fish_tokens("return $status") == "return $?"

    def test_command_substitution(self):
        assert rewrite_fish_tokens("set x (git branch)") == "set x $(git branch)"

    def test_existing_dollar_paren_untouched(self):
        assert rewrite_fish_tokens("echo $(date)") == "echo $(date)"

    def test_pipeline_dispatch(self):
        assert convert_line_zsh("alias x='y'") is not None
        assert convert_line_zsh("echo hello") is None


# ---------------------------------------------------------- expr translation


class TestTranslateExpr:
    def test_command_q(self):
        assert translate_expr("command -q git") == "command -v git >/dev/null 2>&1"

    def test_command_sq(self):
        assert translate_expr("command -sq eza") == "command -v eza >/dev/null 2>&1"

    def test_type_q(self):
        assert translate_expr("type -q nvim") == "command -v nvim >/dev/null 2>&1"

    def test_functions_q(self):
        assert translate_expr("functions -q mkcd") == "typeset -f mkcd >/dev/null 2>&1"

    def test_set_q(self):
        assert translate_expr("set -q TMUX") == "[[ -v TMUX ]]"

    def test_status_is_interactive(self):
        assert translate_expr("status is-interactive") == "[[ -o interactive ]]"

    def test_not_prefix(self):
        assert translate_expr("not command -q git") == "! command -v git >/dev/null 2>&1"

    def test_test_passthrough(self):
        assert translate_expr("test -f ~/.zshrc") == "test -f ~/.zshrc"

    def test_string_builtin_untranslatable(self):
        assert translate_expr("string match -r 'x' $foo") is None

    def test_init_pipe_source_idiom(self):
        assert translate_expr("zoxide init fish | source") == 'eval "$(zoxide init zsh)"'
        assert translate_expr("starship init fish | source") == 'eval "$(starship init zsh)"'
        assert translate_expr("direnv hook fish | source") == 'eval "$(direnv hook zsh)"'

    def test_init_pipe_source_with_args(self):
        assert translate_expr("zoxide init fish --cmd j | source") == 'eval "$(zoxide init zsh --cmd j)"'

    def test_and_or_chain(self):
        assert translate_expr("test -f x; and echo yes; or echo no") == "test -f x && echo yes || echo no"

    def test_chain_with_untranslatable_segment_fails_whole_line(self):
        assert translate_expr("test -f x; and string match 'y' $z") is None

    def test_chain_with_fish_builtin_segments(self):
        assert (
            translate_expr("functions -q foo; or command -q bar")
            == "typeset -f foo >/dev/null 2>&1 || command -v bar >/dev/null 2>&1"
        )


# ------------------------------------------------------------ block translator


class TestBlockTranslator:
    def test_simple_function(self):
        result = translate_block(
            [
                'function mkcd -d "make dir and cd" -a target',
                "    mkdir -p $target",
                "    cd $target",
                "end",
            ]
        )
        assert not result.should_stub
        text = "\n".join(result.lines)
        # Name is quoted so a same-named alias can't break the definition
        # (zsh expands aliases at parse time).
        assert "'mkcd'() {" in text
        assert 'local target="${1}"' in text
        assert "# make dir and cd" in text
        assert text.rstrip().endswith("}")

    def test_argv_in_function_body(self):
        result = translate_block(["function greet", "    echo hello $argv[1]", "    echo $argv", "end"])
        text = "\n".join(result.lines)
        assert "echo hello $1" in text
        assert 'echo "$@"' in text

    def test_if_else_block(self):
        result = translate_block(
            [
                "if command -q eza",
                "    alias ls='eza'",
                "else if command -q lsd",
                "    alias ls='lsd'",
                "else",
                "    alias ls='ls -G'",
                "end",
            ]
        )
        assert not result.should_stub
        text = "\n".join(result.lines)
        assert "if command -v eza >/dev/null 2>&1; then" in text
        assert "elif command -v lsd >/dev/null 2>&1; then" in text
        assert "else" in text
        assert text.rstrip().endswith("fi")

    def test_for_loop(self):
        result = translate_block(["for f in *.txt", "    echo $f", "end"])
        text = "\n".join(result.lines)
        assert "for f in *.txt; do" in text
        assert text.rstrip().endswith("done")

    def test_while_loop(self):
        result = translate_block(["while test -f lock", "    sleep 1", "end"])
        text = "\n".join(result.lines)
        assert "while test -f lock; do" in text
        assert text.rstrip().endswith("done")

    def test_switch_case(self):
        result = translate_block(
            [
                "switch (uname)",
                "case Darwin",
                "    echo mac",
                "case Linux FreeBSD",
                "    echo nix",
                "case '*'",
                "    echo other",
                "end",
            ]
        )
        assert not result.should_stub
        text = "\n".join(result.lines)
        assert "case $(uname) in" in text
        assert "Darwin)" in text
        assert "Linux|FreeBSD)" in text
        assert "*)" in text
        assert text.count(";;") == 3
        assert text.rstrip().endswith("esac")

    def test_begin_end(self):
        result = translate_block(["begin", "    echo grouped", "end"])
        text = "\n".join(result.lines)
        assert text.splitlines()[0] == "{"
        assert text.rstrip().endswith("}")

    def test_set_local_in_function(self):
        result = translate_block(["function f", "    set -l name value", "end"])
        assert "local name=value" in "\n".join(result.lines)

    def test_set_default_scope_in_function_is_local(self):
        result = translate_block(["function f", "    set name value", "end"])
        assert "local name=value" in "\n".join(result.lines)

    def test_set_global_in_function(self):
        result = translate_block(["function f", "    set -g counter 0", "end"])
        assert "typeset -g counter=0" in "\n".join(result.lines)

    def test_set_erase(self):
        result = translate_block(["set -e TEMP_VAR"])
        assert "unset TEMP_VAR" in "\n".join(result.lines)

    def test_set_list_becomes_array(self):
        result = translate_block(["function f", "    set -l parts a b c", "end"])
        assert "local parts=(a b c)" in "\n".join(result.lines)

    def test_set_toplevel_is_plain_assignment(self):
        result = translate_block(["set -l tmp /tmp/x"])
        assert "tmp=/tmp/x" in "\n".join(result.lines)
        assert "local" not in "\n".join(result.lines)

    def test_and_or_continuation(self):
        result = translate_block(["mkdir -p /tmp/x", "and cd /tmp/x", "or echo failed"])
        text = "\n".join(result.lines)
        assert "[ $? -eq 0 ] && cd /tmp/x" in text
        assert "[ $? -ne 0 ] && echo failed" in text

    def test_untranslatable_line_is_commented(self):
        result = translate_block(
            [
                "function f",
                "    echo ok",
                "    echo also ok",
                "    echo three",
                "    string match -r 'x' $f",
                "end",
            ]
        )
        text = "\n".join(result.lines)
        assert "# fish-untranslated: string match" in text
        assert not result.should_stub  # 1/6 lines is below threshold

    def test_mostly_untranslatable_recommends_stub(self):
        result = translate_block(
            [
                "function f",
                "    string match -r 'x' $argv",
                "    math 1+2",
                "end",
            ]
        )
        assert result.should_stub

    def test_event_handler_recommends_stub(self):
        result = translate_block(["function on_exit --on-event fish_exit", "    echo bye", "end"])
        assert result.event_handler
        assert result.should_stub

    def test_argparse_recommends_stub(self):
        """A function built around fish's argparse is semantically dead
        without it — must be stubbed even if the ratio is below threshold."""
        result = translate_block(
            [
                "function f",
                "    argparse 'h/help' -- $argv",
                "    or return 1",
                "    echo one",
                "    echo two",
                "    echo three",
                "    echo four",
                "end",
            ]
        )
        assert result.uses_argparse
        assert result.should_stub

    def test_complete_builtin_untranslated(self):
        result = translate_block(["complete -c mytool -f -a '(mytool --list)'"])
        assert "# fish-untranslated: complete" in result.lines[0]

    def test_source_fish_file_untranslated(self):
        result = translate_block(['test -f "$HOME/.local/bin/env.fish" && source "$HOME/.local/bin/env.fish"'])
        assert result.lines[0].startswith("# fish-untranslated:")

    def test_unbalanced_end_recommends_stub(self):
        result = translate_block(["end"])
        assert not result.balanced
        assert result.should_stub

    def test_unclosed_block_recommends_stub(self):
        result = translate_block(["if test -f x", "    echo y"])
        assert not result.balanced
        assert result.should_stub
        assert result.warnings

    def test_untranslatable_condition_stays_valid_zsh(self):
        result = translate_block(["if string match -q 'x' $y", "    echo hit", "end"])
        text = "\n".join(result.lines)
        assert "if false; then  # fish-untranslated:" in text
        assert text.rstrip().endswith("fi")

    def test_oneliner_block_untranslated(self):
        result = translate_block(["if test -f x; echo y; end"])
        assert "# fish-untranslated:" in result.lines[0]
        assert result.balanced

    def test_comments_and_blanks_preserved(self):
        result = translate_block(["# a comment", "", "alias x='y'"])
        assert result.lines[0] == "# a comment"
        assert result.lines[1] == ""


# --------------------------------------------------------- directory conversion


@pytest.fixture
def fish_tree(tmp_path: Path) -> Path:
    """Synthetic fish config tree covering the interesting conversion cases."""
    fish = tmp_path / "fish"
    confd = fish / "conf.d"
    functions = fish / "functions"
    confd.mkdir(parents=True)
    functions.mkdir()

    (confd / "00-env.fish").write_text(
        'set -gx EDITOR nvim\nset -gx GOPATH "$HOME/go"\nfish_add_path ~/.local/bin\n',
        encoding="utf-8",
    )
    (confd / "31-aliases-git.fish").write_text(
        "alias gs='git status'\nalias gp='git push'\nabbr -a gco git checkout\n",
        encoding="utf-8",
    )
    (confd / "20-listing.fish").write_text(
        "if command -q eza\n    alias ll='eza -lah'\nelse\n    alias ll='ls -alhF'\nend\n",
        encoding="utf-8",
    )
    (confd / "30-aliases.macos.fish").write_text(
        "alias brewup='brew update && brew upgrade'\n",
        encoding="utf-8",
    )
    (confd / "40-paths.linux.fish").write_text(
        "fish_add_path /usr/local/go/bin\n",
        encoding="utf-8",
    )
    (confd / "99-secrets.fish").write_text(
        "set -gx SECRET_TOKEN abc123\n",
        encoding="utf-8",
    )
    (confd / "50-work.local.fish").write_text(
        "alias vpn='connect-vpn'\n",
        encoding="utf-8",
    )

    (functions / "mkcd.fish").write_text(
        'function mkcd -d "Create directory and cd into it"\n    mkdir -p $argv[1]\n    cd $argv[1]\nend\n',
        encoding="utf-8",
    )
    (functions / "fishy.fish").write_text(
        "function fishy\n    string match -r 'x' $argv\n    math 1+2\nend\n",
        encoding="utf-8",
    )
    return fish


class TestZshConverterDirectory:
    def test_layout(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish_tree, dst).convert_directory()

        assert (dst / "zshrc").exists()
        assert (dst / "conf.d" / "00-env.zsh").exists()
        assert (dst / "conf.d" / "31-aliases-git.zsh").exists()
        assert (dst / "conf.d" / "20-listing.zsh").exists()
        assert (dst / "functions" / "mkcd.zsh").exists()
        assert (dst / "README.md").exists()
        assert report.files_processed > 0

    def test_env_conversion(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish_tree, dst).convert_directory()
        content = (dst / "conf.d" / "00-env.zsh").read_text(encoding="utf-8")
        assert 'export EDITOR="nvim"' in content
        assert 'export GOPATH="$HOME/go"' in content
        assert 'export PATH="$HOME/.local/bin:$PATH"' in content
        assert report.env_vars_converted == 2
        assert report.path_lines_converted == 2  # 00-env + linux platform file

    def test_if_block_translated_not_commented(self, fish_tree: Path, tmp_path: Path) -> None:
        """Unlike fish-to-pwsh, inline if-blocks become real zsh."""
        dst = tmp_path / "zsh"
        FishToZshConverter(fish_tree, dst).convert_directory()
        content = (dst / "conf.d" / "20-listing.zsh").read_text(encoding="utf-8")
        assert "if command -v eza >/dev/null 2>&1; then" in content
        assert "alias ll='eza -lah'" in content
        assert "fi" in content
        assert "# fish-original" not in content

    def test_macos_file_gets_uname_guard(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        FishToZshConverter(fish_tree, dst).convert_directory()
        target = dst / "conf.d" / "30-aliases.macos.zsh"
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert 'if [[ "$(uname)" == "Darwin" ]]; then' in content
        assert "alias brewup=" in content
        assert content.rstrip().endswith("fi")

    def test_linux_file_gets_uname_guard(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        FishToZshConverter(fish_tree, dst).convert_directory()
        content = (dst / "conf.d" / "40-paths.linux.zsh").read_text(encoding="utf-8")
        assert 'if [[ "$(uname)" == "Linux" ]]; then' in content

    def test_secrets_and_local_files_skipped(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish_tree, dst).convert_directory()
        assert not (dst / "conf.d" / "99-secrets.zsh").exists()
        assert not (dst / "conf.d" / "50-work.local.zsh").exists()
        skipped_names = {p.name for p in report.skipped_files}
        assert "99-secrets.fish" in skipped_names
        assert "50-work.local.fish" in skipped_names

    def test_platform_files_not_in_default_skip(self) -> None:
        assert "*.macos.fish" not in DEFAULT_ZSH_SKIP_PATTERNS
        assert "*.linux.fish" not in DEFAULT_ZSH_SKIP_PATTERNS

    def test_function_translated(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish_tree, dst).convert_directory()
        content = (dst / "functions" / "mkcd.zsh").read_text(encoding="utf-8")
        assert "'mkcd'() {" in content
        assert "mkdir -p $1" in content
        assert report.functions_translated == 1

    def test_fishy_function_stubbed(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish_tree, dst).convert_directory()
        content = (dst / "functions" / "fishy.zsh").read_text(encoding="utf-8")
        assert "Auto-generated stub" in content
        assert "# function fishy" in content
        assert report.functions_stubbed == 1
        assert any("fishy" in warning for warning in report.warnings)

    def test_dry_run_writes_nothing(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish_tree, dst).convert_directory(dry_run=True)
        assert not dst.exists()
        assert report.written_files

    def test_existing_file_backed_up_0600(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        confd = dst / "conf.d"
        confd.mkdir(parents=True)
        target = confd / "00-env.zsh"
        target.write_text("# hand edit\n", encoding="utf-8")

        FishToZshConverter(fish_tree, dst).convert_directory()

        backup = confd / "00-env.zsh.bak"
        assert backup.exists()
        assert "# hand edit" in backup.read_text(encoding="utf-8")
        assert backup.stat().st_mode & 0o077 == 0, "backup must be 0600-private"

    def test_existing_readme_not_clobbered(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        dst.mkdir()
        readme = dst / "README.md"
        readme.write_text("# Custom hand-written README\n", encoding="utf-8")

        FishToZshConverter(fish_tree, dst).convert_directory()

        assert "Custom hand-written README" in readme.read_text(encoding="utf-8")

    def test_missing_source_returns_warning(self, tmp_path: Path) -> None:
        report = FishToZshConverter(tmp_path / "nope", tmp_path / "out").convert_directory()
        assert report.warnings
        assert "not found" in report.warnings[0]

    def test_zshrc_sources_confd_and_functions(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        FishToZshConverter(fish_tree, dst).convert_directory()
        content = (dst / "zshrc").read_text(encoding="utf-8")
        assert "conf.d" in content
        assert "functions" in content
        assert "source ~/.config/zsh/zshrc" in content  # activation hint
        assert "grep -qxF" in content  # idempotent copy-paste one-liner (v2.52.1)

    def test_readme_contains_activation_one_liner(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        FishToZshConverter(fish_tree, dst).convert_directory()
        readme = (dst / "README.md").read_text(encoding="utf-8")
        assert "grep -qxF 'source ~/.config/zsh/zshrc'" in readme
        assert ">> ~/.zshrc" in readme


class TestZshConveniences:
    def test_conveniences_emitted_by_default(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish_tree, dst).convert_directory()
        target = dst / "conf.d" / "95-conveniences.zsh"
        assert target.exists()
        assert report.conveniences_emitted is True
        content = target.read_text(encoding="utf-8")
        assert "alias ..='cd ..'" in content
        assert "mkcd()" in content

    def test_no_conveniences_skips_file(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish_tree, dst, include_conveniences=False).convert_directory()
        assert not (dst / "conf.d" / "95-conveniences.zsh").exists()
        assert report.conveniences_emitted is False

    def test_conveniences_load_last(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        FishToZshConverter(fish_tree, dst).convert_directory()
        names = sorted(p.name for p in (dst / "conf.d").glob("*.zsh"))
        assert names[-1] == "95-conveniences.zsh"


# ----------------------------------------------------------------- CLI wiring


class TestFishToZshCli:
    def test_dry_run(self, fish_tree: Path, tmp_path: Path) -> None:
        cfg = MagicMock()
        cfg.repository.path = str(tmp_path / "repo")
        with patch("sccs.cli.load_config", return_value=cfg):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "convert",
                    "fish-to-zsh",
                    "--dry-run",
                    "--src",
                    str(fish_tree),
                    "--dst",
                    str(tmp_path / "out"),
                ],
            )
        assert result.exit_code == 0, result.output
        cleaned = _ANSI_RE.sub("", result.output)
        assert "Conversion summary" in cleaned
        assert "Would write" in cleaned

    def test_default_dst_is_repo_zsh(self, fish_tree: Path, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        cfg = MagicMock()
        cfg.repository.path = str(repo)
        with (
            patch("sccs.cli.load_config", return_value=cfg),
            patch("sccs.cli.get_current_platform", return_value="macos"),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["convert", "fish-to-zsh", "--dry-run", "--src", str(fish_tree)],
            )
        assert result.exit_code == 0, result.output
        cleaned = "".join(_ANSI_RE.sub("", result.output).split())
        assert "".join(str(repo / ".config" / "zsh").split()) in cleaned

    def test_refuses_non_empty_dst_without_force(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "out"
        dst.mkdir()
        (dst / "keep.zsh").write_text("# keep\n", encoding="utf-8")
        cfg = MagicMock()
        cfg.repository.path = str(tmp_path / "repo")
        with patch("sccs.cli.load_config", return_value=cfg):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["convert", "fish-to-zsh", "--src", str(fish_tree), "--dst", str(dst)],
            )
        assert result.exit_code == 1
        assert "not empty" in _ANSI_RE.sub("", result.output)

    def test_activation_hint_printed(self, fish_tree: Path, tmp_path: Path) -> None:
        cfg = MagicMock()
        cfg.repository.path = str(tmp_path / "repo")
        with patch("sccs.cli.load_config", return_value=cfg):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "convert",
                    "fish-to-zsh",
                    "--src",
                    str(fish_tree),
                    "--dst",
                    str(tmp_path / "out"),
                ],
            )
        assert result.exit_code == 0, result.output
        cleaned = _ANSI_RE.sub("", result.output)
        assert "source ~/.config/zsh/zshrc" in cleaned
        assert "grep -qxF" in cleaned  # idempotent copy-paste one-liner (v2.52.1)
        assert "zsh_config" in cleaned

    def test_no_conveniences_flag(self, fish_tree: Path, tmp_path: Path) -> None:
        cfg = MagicMock()
        cfg.repository.path = str(tmp_path / "repo")
        with patch("sccs.cli.load_config", return_value=cfg):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "convert",
                    "fish-to-zsh",
                    "--dry-run",
                    "--no-conveniences",
                    "--src",
                    str(fish_tree),
                    "--dst",
                    str(tmp_path / "out"),
                ],
            )
        assert result.exit_code == 0, result.output
        assert "skipped (--no-conveniences)" in _ANSI_RE.sub("", result.output)

    def test_windows_default_src_uses_repo(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        fish = repo / ".config" / "fish" / "conf.d"
        fish.mkdir(parents=True)
        (fish / "10-aliases.fish").write_text("alias ll='ls -la'\n", encoding="utf-8")
        cfg = MagicMock()
        cfg.repository.path = str(repo)
        with (
            patch("sccs.cli.load_config", return_value=cfg),
            patch("sccs.cli.get_current_platform", return_value="windows"),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["convert", "fish-to-zsh", "--dry-run", "--dst", str(tmp_path / "out")],
            )
        assert result.exit_code == 0, result.output
        cleaned = "".join(_ANSI_RE.sub("", result.output).split())
        assert "".join(str(repo / ".config" / "fish").split()) in cleaned


# ------------------------------------------------------------ zsh syntax gate


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
class TestZshSyntaxValidity:
    """Every generated file must pass `zsh -n` — the converter's hard promise
    is to never emit syntactically broken zsh."""

    def test_generated_files_pass_zsh_n(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "zsh"
        FishToZshConverter(fish_tree, dst).convert_directory()

        generated = [dst / "zshrc", *sorted(dst.rglob("*.zsh"))]
        assert generated
        for path in generated:
            proc = subprocess.run(
                ["zsh", "-n", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"zsh -n failed for {path.name}:\n{proc.stderr}"

    def test_multiline_command_substitution_falls_back_to_stub(self, tmp_path: Path) -> None:
        """Fish multi-line command substitutions defeat the line-based
        translator (unbalanced parens) — the `zsh -n` gate must catch the
        broken output and fall back to a commented stub."""
        fish = tmp_path / "fish"
        functions = fish / "functions"
        functions.mkdir(parents=True)
        (functions / "multi.fish").write_text(
            "function multi\n"
            "    set -l response (env FOO=bar \\\n"
            "        COMP_CWORD=(commandline -t) mytool 2>/dev/null)\n"
            "    echo $response\n"
            "end\n",
            encoding="utf-8",
        )

        dst = tmp_path / "zsh"
        report = FishToZshConverter(fish, dst).convert_directory()

        content = (dst / "functions" / "multi.zsh").read_text(encoding="utf-8")
        assert "Auto-generated stub" in content
        assert report.functions_stubbed == 1
        assert any("zsh -n" in warning or "untranslatable" in warning for warning in report.warnings)
        proc = subprocess.run(
            ["zsh", "-n", str(dst / "functions" / "multi.zsh")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
