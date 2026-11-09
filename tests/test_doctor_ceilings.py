# Regression tests for the 2.72.2 doctor trust ceilings: config-sourced
# npx invocations, bundled-skill targets, marketplace and skill-package sources.

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from sccs.doctor.defaults import DEFAULT_CLAUDE_PLUGINS, DEFAULT_NPX_TOOLS
from sccs.doctor.runner import DoctorError
from sccs.doctor.schema import BundledSkillSpec, NpxToolSpec, PluginSpec


class TestNpxInvocationHead:
    @pytest.mark.parametrize("head", ["bash", "sh", "curl", "python3"])
    def test_non_npm_head_is_rejected(self, head: str) -> None:
        with pytest.raises(ValidationError, match="npx' or 'npm"):
            NpxToolSpec(name="x", invocation=[head, "-c", "echo hi"])

    @pytest.mark.parametrize("head", ["npx", "npm"])
    def test_npm_heads_are_accepted(self, head: str) -> None:
        assert NpxToolSpec(name="x", invocation=[head, "-y", "pkg"]).invocation[0] == head

    def test_every_default_passes(self) -> None:
        assert all(t.invocation[0] in ("npx", "npm") for t in DEFAULT_NPX_TOOLS)


class TestNpxConfirm:
    def _status(self, spec: NpxToolSpec):
        from sccs.doctor.detectors import NpxToolStatus

        return NpxToolStatus(spec=spec, available=False, binary_path=None)

    def test_bundled_default_runs_unattended(self) -> None:
        from sccs.doctor.installer import _npx_install_actions

        default = next(t for t in DEFAULT_NPX_TOOLS if not t.optional)
        [first, *_] = _npx_install_actions([self._status(default)])
        assert first.auto_confirm is True

    def test_config_invocation_asks(self) -> None:
        from sccs.doctor.installer import _npx_install_actions, _npx_update_actions

        spec = NpxToolSpec(name="my-tool", invocation=["npx", "-y", "some-package"])
        assert _npx_install_actions([self._status(spec)])[0].auto_confirm is False
        assert _npx_update_actions([self._status(spec)])[0].auto_confirm is False

    def test_changed_invocation_of_a_default_asks(self) -> None:
        from sccs.doctor.installer import _is_bundled_npx_tool

        default = DEFAULT_NPX_TOOLS[0]
        changed = default.model_copy(update={"invocation": ["npx", "-y", "other-package"]})
        assert _is_bundled_npx_tool(default) is True
        assert _is_bundled_npx_tool(changed) is False


class TestBundledSkillTarget:
    @pytest.mark.parametrize(
        "target",
        ["~/Documents", "~/.claude", "~/.claude/skills", "~/.claude/skills/a/b", "/tmp/x", "~/.claude/skills/.."],
    )
    def test_target_outside_one_skill_folder_is_rejected(self, target: str) -> None:
        with pytest.raises(ValidationError, match="~/.claude/skills/<name>"):
            BundledSkillSpec(package_subpath="p/skills/s", target=target)

    @pytest.mark.parametrize("subpath", ["../../..", "p/../../x", "/etc", "~/x", "C:/x"])
    def test_subpath_leaving_npm_root_is_rejected(self, subpath: str) -> None:
        with pytest.raises(ValidationError, match="package_subpath"):
            BundledSkillSpec(package_subpath=subpath, target="~/.claude/skills/s")

    def _sync(self, tmp_path: Path, monkeypatch, *, prepare_target) -> Path:
        from sccs.doctor.installer import _sync_bundled_skill

        monkeypatch.setenv("HOME", str(tmp_path))
        npm_root = tmp_path / "npm"
        (npm_root / "p" / "skills" / "s").mkdir(parents=True)
        (npm_root / "p" / "skills" / "s" / "SKILL.md").write_text("new\n", encoding="utf-8")
        target = tmp_path / ".claude" / "skills" / "s"
        prepare_target(target)
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=f"{npm_root}\n", stderr="")
        with patch("sccs.doctor.installer._run", return_value=proc):
            _sync_bundled_skill(BundledSkillSpec(package_subpath="p/skills/s", target="~/.claude/skills/s"))
        return target

    def test_folder_without_skill_md_is_never_deleted(self, tmp_path: Path, monkeypatch) -> None:
        def prepare(target: Path) -> None:
            target.mkdir(parents=True)
            (target / "notes.txt").write_text("mine\n", encoding="utf-8")

        with pytest.raises(DoctorError, match="no SKILL.md"):
            self._sync(tmp_path, monkeypatch, prepare_target=prepare)
        assert (tmp_path / ".claude" / "skills" / "s" / "notes.txt").exists()

    def test_symlinked_target_is_refused(self, tmp_path: Path, monkeypatch) -> None:
        elsewhere = tmp_path / "Documents"

        def prepare(target: Path) -> None:
            elsewhere.mkdir()
            (elsewhere / "SKILL.md").write_text("decoy\n", encoding="utf-8")
            target.parent.mkdir(parents=True)
            target.symlink_to(elsewhere)

        with pytest.raises(DoctorError, match="not a folder under"):
            self._sync(tmp_path, monkeypatch, prepare_target=prepare)
        assert (elsewhere / "SKILL.md").read_text(encoding="utf-8") == "decoy\n"

    def test_skill_folder_is_replaced(self, tmp_path: Path, monkeypatch) -> None:
        def prepare(target: Path) -> None:
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old\n", encoding="utf-8")

        target = self._sync(tmp_path, monkeypatch, prepare_target=prepare)
        assert (target / "SKILL.md").read_text(encoding="utf-8") == "new\n"


class TestSourceConfirm:
    def test_marketplace_source(self) -> None:
        from sccs.doctor.installer import _is_bundled_marketplace_source

        bundled = next(p.marketplace_source for p in DEFAULT_CLAUDE_PLUGINS if p.marketplace_source)
        assert _is_bundled_marketplace_source(bundled) is True
        assert _is_bundled_marketplace_source("someone/else") is False
        assert _is_bundled_marketplace_source(None) is False

    def test_config_plugin_marketplace_add_asks(self) -> None:
        from sccs.doctor.detectors import PluginStatus
        from sccs.doctor.installer import _plugin_install_actions

        spec = PluginSpec(name="codex", marketplace="openai-codex", marketplace_source="openai/codex-plugin-cc")
        actions = _plugin_install_actions([PluginStatus(spec=spec, installed=False, update_available=None)])
        [add] = [a for a in actions if "register marketplace" in a.label]
        assert add.auto_confirm is False

    def test_skill_package_source(self) -> None:
        from sccs.doctor.skill_packages import BUILTIN_SKILL_PACKAGES, _is_builtin

        builtin = BUILTIN_SKILL_PACKAGES["hyperframes"]
        assert _is_builtin(builtin) is True
        assert _is_builtin(builtin.model_copy(update={"source": "evil/fork"})) is False


class TestVersionProbeArgs:
    """`version_args` run unattended on every `doctor check` (2.72.3).

    The probe is `[detect_command or name, *version_args]`; config.yaml travels
    through the sync repo, so `python3 -c …` there was code execution on every
    host without a prompt.
    """

    @pytest.mark.parametrize(
        "args",
        [["-c", "import os"], ["-e", "1"], ["--version", "-c", "x"], ["--eval=1"], ["exec", "rm"]],
    )
    def test_npx_non_version_args_are_rejected(self, args: list[str]) -> None:
        with pytest.raises(ValidationError, match="version_args"):
            NpxToolSpec(name="x", invocation=["npx", "pkg"], detect_command="python3", version_args=args)

    @pytest.mark.parametrize("args", [["-c", "import os"], ["--version", "-e", "1"]])
    def test_cli_non_version_args_are_rejected(self, args: list[str]) -> None:
        from sccs.doctor.schema import CliToolSpec

        with pytest.raises(ValidationError, match="version_args"):
            CliToolSpec(name="x", detect_command="python3", version_args=args)

    @pytest.mark.parametrize("args", [["--version"], ["-V"], ["-v"], ["version"]])
    def test_version_flags_are_accepted(self, args: list[str]) -> None:
        from sccs.doctor.schema import CliToolSpec

        assert NpxToolSpec(name="x", invocation=["npx", "pkg"], version_args=args).version_args == args
        assert CliToolSpec(name="x", detect_command="x", version_args=args).version_args == args

    def test_every_default_passes(self) -> None:
        from sccs.doctor.defaults import BUILTIN_CLI_TOOLS
        from sccs.doctor.schema import CliToolSpec

        for tool in DEFAULT_NPX_TOOLS:
            NpxToolSpec.model_validate(tool.model_dump())
        for tool in BUILTIN_CLI_TOOLS.values():
            CliToolSpec.model_validate(tool.model_dump())

    @pytest.mark.parametrize("value", ["-rf", "a b", "x;y", "$(id)"])
    def test_npx_detect_command_is_validated(self, value: str) -> None:
        with pytest.raises(ValidationError, match="detect_command"):
            NpxToolSpec(name="x", invocation=["npx", "pkg"], detect_command=value)
