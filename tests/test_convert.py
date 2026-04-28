# SCCS Fish -> PowerShell Conversion Tests

from __future__ import annotations

from pathlib import Path

import pytest

from sccs.convert import ConversionReport, FishToPwshConverter
from sccs.convert.rules import (
    convert_abbr,
    convert_alias,
    convert_fish_add_path,
    convert_line,
    convert_set_gx,
)

# ---------------------------------------------------------------------- rules


class TestAliasConversion:
    def test_simple_alias_emits_set_alias(self) -> None:
        result = convert_alias("alias cat='uu-cat'")
        assert result is not None
        assert result.kind == "alias"
        assert result.powershell == "Set-Alias -Name cat -Value uu-cat -Scope Global -Force"

    def test_bare_alias_value_works(self) -> None:
        result = convert_alias("alias lg=lazygit")
        assert result is not None
        assert result.kind == "alias"
        assert "Set-Alias -Name lg -Value lazygit" in result.powershell

    def test_alias_with_args_becomes_function(self) -> None:
        result = convert_alias("alias gst='git status'")
        assert result is not None
        assert result.kind == "function"
        assert result.powershell == "function gst { git status @args }"

    def test_alias_with_many_args(self) -> None:
        result = convert_alias("alias glog='git log --oneline --decorate --graph'")
        assert result is not None
        assert result.kind == "function"
        assert "git log --oneline --decorate --graph @args" in result.powershell

    def test_alias_with_double_quotes(self) -> None:
        result = convert_alias('alias gcm="git commit -m"')
        assert result is not None
        assert result.kind == "function"
        assert "git commit -m @args" in result.powershell

    def test_alias_with_dashes_and_underscores(self) -> None:
        result = convert_alias("alias docker-platform='docker inspect'")
        assert result is not None
        assert result.kind == "function"
        assert result.powershell.startswith("function docker-platform")

    def test_non_alias_returns_none(self) -> None:
        assert convert_alias("set -gx FOO bar") is None
        assert convert_alias("# comment") is None
        assert convert_alias("") is None


class TestSetGxConversion:
    def test_set_gx_with_quoted_value(self) -> None:
        result = convert_set_gx('set -gx GITBASE_PATH "$HOME/gitbase"')
        assert result is not None
        assert result.kind == "env"
        # $HOME is rewritten to PowerShell's $HOME (same name).
        assert result.powershell == '$env:GITBASE_PATH = "$HOME/gitbase"'

    def test_set_gx_bare_value(self) -> None:
        result = convert_set_gx("set -gx FOO 42")
        assert result is not None
        assert result.kind == "env"
        assert result.powershell == '$env:FOO = "42"'

    def test_set_gx_short_flag(self) -> None:
        # `set -x` (no -g) is also accepted.
        result = convert_set_gx("set -x BAR baz")
        assert result is not None
        assert result.kind == "env"

    def test_local_set_is_not_matched(self) -> None:
        # No -g/-x — local fish variable, ignored by converter.
        assert convert_set_gx("set -l TEMP foo") is None

    def test_set_gx_rewrites_user_var_references(self) -> None:
        # $GITBASE_PATH is not a PS built-in; must be routed via $env:.
        result = convert_set_gx('set -gx ODOO_NATIVE_BASE "$GITBASE_PATH"')
        assert result is not None
        assert result.powershell == '$env:ODOO_NATIVE_BASE = "$env:GITBASE_PATH"'

    def test_set_gx_keeps_home_as_builtin(self) -> None:
        # $HOME is a PowerShell built-in — leave it untouched.
        result = convert_set_gx('set -gx X "$HOME/foo"')
        assert result is not None
        assert result.powershell == '$env:X = "$HOME/foo"'


class TestFishAddPath:
    def test_add_path_emits_dedupe_check(self) -> None:
        result = convert_fish_add_path("fish_add_path /opt/homebrew/bin")
        assert result is not None
        assert result.kind == "path"
        assert "PathSeparator" in result.powershell
        assert "/opt/homebrew/bin" in result.powershell


class TestAbbrConversion:
    def test_simple_abbr(self) -> None:
        result = convert_abbr("abbr -a oda odoodev-activate")
        assert result is not None
        assert result.kind == "alias"
        assert "Set-Alias -Name oda -Value odoodev-activate" in result.powershell


class TestPipeline:
    def test_pipeline_dispatches_to_alias(self) -> None:
        result = convert_line("alias gst='git status'")
        assert result is not None
        assert result.kind == "function"

    def test_pipeline_dispatches_to_env(self) -> None:
        result = convert_line('set -gx FOO "bar"')
        assert result is not None
        assert result.kind == "env"

    def test_pipeline_returns_none_for_unknown(self) -> None:
        assert convert_line("if test -d /tmp") is None
        assert convert_line("string match -q '*.fish' $file") is None


# --------------------------------------------------------------------- driver


@pytest.fixture
def fish_tree(tmp_path: Path) -> Path:
    """Build a small fish config tree for converter tests."""
    src = tmp_path / "fish"
    confd = src / "conf.d"
    fns = src / "functions"
    confd.mkdir(parents=True)
    fns.mkdir(parents=True)

    (confd / "00-env.fish").write_text(
        "# Env vars\n"
        'set -gx GITBASE_PATH "$HOME/gitbase"\n'
        "set -gx FOO bar\n",
        encoding="utf-8",
    )

    (confd / "31-aliases-git.fish").write_text(
        "# Git aliases\n"
        "alias g='git'\n"
        "alias gst='git status'\n"
        "alias gcm='git commit -m'\n",
        encoding="utf-8",
    )

    # Should be skipped due to *.macos.fish pattern.
    (confd / "30-aliases-system.macos.fish").write_text(
        "alias brewup='brew update && brew upgrade'\n",
        encoding="utf-8",
    )

    # Should be skipped because the filename matches secret patterns.
    (confd / "99-secrets.fish").write_text(
        'set -gx SUPER_SECRET_TOKEN "should-never-leak"\n',
        encoding="utf-8",
    )

    (fns / "mkcd.fish").write_text(
        'function mkcd --description "Create dir and cd"\n'
        "    mkdir -p $argv[1] && cd $argv[1]\n"
        "end\n",
        encoding="utf-8",
    )

    return src


class TestConverterDirectory:
    def test_writes_profile_entry(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "powershell"
        converter = FishToPwshConverter(fish_tree, dst)
        report = converter.convert_directory()
        profile = dst / "Microsoft.PowerShell_profile.ps1"
        assert profile.exists()
        assert "PSScriptRoot" in profile.read_text(encoding="utf-8")
        assert isinstance(report, ConversionReport)

    def test_converts_confd_files(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "powershell"
        converter = FishToPwshConverter(fish_tree, dst)
        report = converter.convert_directory()

        env_file = dst / "conf.d" / "00-env.ps1"
        git_file = dst / "conf.d" / "31-aliases-git.ps1"
        assert env_file.exists()
        assert git_file.exists()

        env_content = env_file.read_text(encoding="utf-8")
        assert '$env:GITBASE_PATH = "$HOME/gitbase"' in env_content
        assert '$env:FOO = "bar"' in env_content

        git_content = git_file.read_text(encoding="utf-8")
        assert "Set-Alias -Name g -Value git" in git_content
        assert "function gst { git status @args }" in git_content
        assert "function gcm { git commit -m @args }" in git_content

        assert report.aliases_converted >= 1
        assert report.functions_wrapped >= 2
        assert report.env_vars_converted == 2

    def test_skips_macos_fish_files(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "powershell"
        converter = FishToPwshConverter(fish_tree, dst)
        report = converter.convert_directory()

        assert not (dst / "conf.d" / "30-aliases-system.macos.ps1").exists()
        # 30-aliases-system.macos.fish + 99-secrets.fish both skipped.
        assert report.files_skipped == 2
        assert any("macos" in str(p) for p in report.skipped_files)

    def test_skips_secret_files(self, fish_tree: Path, tmp_path: Path) -> None:
        """Files matching secret patterns must never be converted."""
        dst = tmp_path / "powershell"
        converter = FishToPwshConverter(fish_tree, dst)
        report = converter.convert_directory()

        # No converted output for the secrets file should exist.
        assert not (dst / "conf.d" / "99-secrets.ps1").exists()
        assert any("secret" in str(p) for p in report.skipped_files)

        # And no leftover content from the secret should appear in any output.
        if dst.exists():
            for ps_file in dst.rglob("*.ps1"):
                content = ps_file.read_text(encoding="utf-8")
                assert "should-never-leak" not in content
                assert "SUPER_SECRET_TOKEN" not in content

    def test_function_files_become_stubs(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "powershell"
        converter = FishToPwshConverter(fish_tree, dst)
        report = converter.convert_directory()

        stub = dst / "functions" / "mkcd.ps1"
        assert stub.exists()
        body = stub.read_text(encoding="utf-8")
        # Stub preserves Fish source as comments.
        assert "# function mkcd" in body
        assert "fish-original" not in body  # only used in conf.d, not function stubs
        assert "Auto-generated stub" in body
        assert report.functions_stubbed == 1

    def test_dry_run_writes_nothing(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "powershell"
        converter = FishToPwshConverter(fish_tree, dst)
        report = converter.convert_directory(dry_run=True)
        assert not dst.exists()
        # Report still tracks what would have been written.
        assert report.files_processed > 0

    def test_existing_file_is_backed_up(
        self, fish_tree: Path, tmp_path: Path
    ) -> None:
        dst = tmp_path / "powershell"
        target = dst / "conf.d" / "00-env.ps1"
        target.parent.mkdir(parents=True)
        target.write_text("# old hand-written content\n", encoding="utf-8")

        converter = FishToPwshConverter(fish_tree, dst)
        converter.convert_directory()

        backup = target.with_suffix(target.suffix + ".bak")
        assert backup.exists()
        assert "old hand-written content" in backup.read_text(encoding="utf-8")

    def test_readme_template_emitted(self, fish_tree: Path, tmp_path: Path) -> None:
        dst = tmp_path / "powershell"
        converter = FishToPwshConverter(fish_tree, dst)
        converter.convert_directory()
        readme = dst / "README.md"
        assert readme.exists()
        assert "PowerShell Profile" in readme.read_text(encoding="utf-8")

    def test_existing_readme_not_clobbered(
        self, fish_tree: Path, tmp_path: Path
    ) -> None:
        dst = tmp_path / "powershell"
        dst.mkdir()
        readme = dst / "README.md"
        readme.write_text("# Custom hand-written README\n", encoding="utf-8")

        converter = FishToPwshConverter(fish_tree, dst)
        converter.convert_directory()

        assert "Custom hand-written README" in readme.read_text(encoding="utf-8")

    def test_missing_source_returns_warning(self, tmp_path: Path) -> None:
        src = tmp_path / "nope"
        dst = tmp_path / "out"
        converter = FishToPwshConverter(src, dst)
        report = converter.convert_directory()
        assert report.warnings
        assert "not found" in report.warnings[0]
