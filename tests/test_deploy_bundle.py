"""Bundle building: manifest deployment section and cleanup command."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import yaml

from sccs.config.schema import SccsConfig
from sccs.deploy.bundle import CLEANUP_COMMAND_NAME, build_bundle, build_cleanup_command
from sccs.deploy.resolve import resolve_profile
from sccs.deploy.schema import DeploymentProfile
from sccs.transfer.manifest import MANIFEST_FILENAME, deserialize_manifest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    skills = tmp_path / ".claude" / "skills"
    (skills / "odoo-common").mkdir(parents=True)
    (skills / "odoo-common" / "SKILL.md").write_text(
        "---\nname: odoo-common\ndescription: t\n---\n\nBody.\n", encoding="utf-8"
    )
    commands = tmp_path / ".claude" / "commands"
    commands.mkdir(parents=True)
    (commands / "s.md").write_text("# s\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(home):
    return SccsConfig.model_validate(
        {
            "repository": {"path": str(home / "repo")},
            "sync_categories": {
                "claude_skills": {
                    "enabled": True,
                    "local_path": "~/.claude/skills",
                    "repo_path": ".claude/skills",
                    "item_type": "directory",
                    "item_marker": "SKILL.md",
                    "include": ["*"],
                },
                "claude_commands": {
                    "enabled": True,
                    "local_path": "~/.claude/commands",
                    "repo_path": ".claude/commands",
                    "item_type": "file",
                    "item_pattern": "*.md",
                    "include": ["*.md"],
                },
            },
        }
    )


@pytest.fixture
def profile():
    return DeploymentProfile(
        description="test profile",
        target_platform="linux",
        include={"claude_skills": ["odoo-common"], "claude_commands": ["s.md"]},
        retain=["claude_commands"],
    )


def test_bundle_carries_deployment_section(config, profile, tmp_path):
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    result = build_bundle(config, resolved, out, {})
    assert result.success

    with zipfile.ZipFile(out) as zf:
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))

    assert manifest.deployment is not None
    assert manifest.deployment.profile == "t"
    assert manifest.deployment.target_platform == "linux"
    assert manifest.deployment.retain == ["claude_commands"]
    assert manifest.deployment.sweep_globs["claude_skills"] == ["odoo-common"]


def test_bundle_contains_cleanup_command(config, profile, tmp_path):
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    build_bundle(config, resolved, out, {})

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert f"claude_commands/{CLEANUP_COMMAND_NAME}" in names


def test_cleanup_command_is_a_manifest_item(config, profile, tmp_path):
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    build_bundle(config, resolved, out, {})

    with zipfile.ZipFile(out) as zf:
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))
    item_names = {i.name for i in manifest.categories["claude_commands"].items}
    assert CLEANUP_COMMAND_NAME in item_names


def test_cleanup_command_is_in_sweep_globs(config, profile, tmp_path):
    """`deploy revoke`'s verification sweep re-scans sweep_globs, not the

    manifest items — see `sccs.deploy.revoke.sweep`, second pass. The cleanup
    command must therefore be added to sweep_globs["claude_commands"]
    explicitly, since _deployment_section() builds sweep_globs from
    resolved.selections before the cleanup item is spliced in. Without that,
    the sweep would never look for the one file the bundle generates itself.
    """
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    build_bundle(config, resolved, out, {})

    with zipfile.ZipFile(out) as zf:
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))
    assert manifest.deployment is not None
    assert CLEANUP_COMMAND_NAME in manifest.deployment.sweep_globs["claude_commands"]


def test_shell_only_bundle_has_no_cleanup_command(config, tmp_path):
    """A profile that ships no skills has nothing to clean up."""
    shell_only = DeploymentProfile(
        description="shell",
        target_platform="linux",
        include={"claude_commands": ["s.md"]},
        retain=["claude_commands"],
    )
    resolved = resolve_profile(config, "shell", {"shell": shell_only})
    out = tmp_path / "bundle.zip"
    build_bundle(config, resolved, out, {})

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))
    assert f"claude_commands/{CLEANUP_COMMAND_NAME}" not in names
    assert manifest.deployment is not None
    assert CLEANUP_COMMAND_NAME not in manifest.deployment.sweep_globs.get("claude_commands", [])


def test_cleanup_command_names_the_profile_and_the_commands():
    text = build_cleanup_command("odoo-server")
    assert "odoo-server" in text
    assert "sccs deploy status" in text
    assert "sccs deploy revoke" in text
    assert "rm -rf" not in text


def test_manifest_without_deployment_section_still_parses():
    """Bundles from `sccs export` (v2.64.0 and older) stay readable."""
    legacy = yaml.dump(
        {
            "sccs_version": "2.64.0",
            "created_at": "2026-08-01T00:00:00+00:00",
            "created_on": "macos",
            "categories": {},
        }
    )
    manifest = deserialize_manifest(legacy)
    assert manifest.deployment is None


def test_bundle_local_paths_are_home_relative(config, profile, tmp_path):
    """A bundle exists to travel to a host with a different home directory.

    SyncCategory expands `~` eagerly, so without a fix the manifest would
    carry THIS host's absolute paths — dead, or quietly wrong, on any other
    machine. Every category's local_path must come back out as `~/...`.
    """
    resolved = resolve_profile(config, "t", {"t": profile})
    out = tmp_path / "bundle.zip"
    assert build_bundle(config, resolved, out, {}).success

    with zipfile.ZipFile(out) as zf:
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))

    assert manifest.categories
    for cat_name, cat_data in manifest.categories.items():
        assert cat_data.local_path.startswith("~/"), (
            f"{cat_name} local_path {cat_data.local_path!r} is not home-relative"
        )


def test_bundle_local_paths_survive_conflicting_raw_config(config, profile, tmp_path):
    """The portable form wins even when raw_config disagrees.

    Covers both the case that exposed the bug (raw_config == {}, so the
    manifest falls back to the eagerly-expanded absolute path) and a
    raw_config that explicitly carries a stale absolute local_path for the
    same category — the bundle must overwrite it, not defer to it.
    """
    resolved = resolve_profile(config, "t", {"t": profile})

    empty_out = tmp_path / "empty.zip"
    assert build_bundle(config, resolved, empty_out, {}).success
    with zipfile.ZipFile(empty_out) as zf:
        empty_manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))
    assert empty_manifest.categories["claude_skills"].local_path == "~/.claude/skills"

    conflicting_raw = {
        "sync_categories": {
            "claude_skills": {"local_path": "/some/other/machines/absolute/path"},
        }
    }
    conflict_out = tmp_path / "conflict.zip"
    assert build_bundle(config, resolved, conflict_out, conflicting_raw).success
    with zipfile.ZipFile(conflict_out) as zf:
        conflict_manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))
    assert conflict_manifest.categories["claude_skills"].local_path == "~/.claude/skills"


# --- Final review, MINOR 1: the manifest must stamp the EFFECTIVE platform ---


def test_platform_override_reaches_the_manifest(config, profile, tmp_path):
    """`deploy export --platform macos` used to stamp the profile's own value.

    `_deployment_section` read `resolved.profile.target_platform`, which the
    override never touched — the ZIP contents followed the override while the
    manifest said something else, and the install host has no way to tell.
    """
    resolved = resolve_profile(config, "t", {"t": profile}, target_platform="macos")
    assert resolved.profile.target_platform == "linux"
    assert resolved.target_platform == "macos"

    out = tmp_path / "override.zip"
    assert build_bundle(config, resolved, out, {}).success

    with zipfile.ZipFile(out) as zf:
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))
    assert manifest.deployment is not None
    assert manifest.deployment.target_platform == "macos"


def test_without_an_override_the_profile_platform_is_used(config, profile, tmp_path):
    resolved = resolve_profile(config, "t", {"t": profile})
    assert resolved.target_platform == "linux"

    out = tmp_path / "no-override.zip"
    assert build_bundle(config, resolved, out, {}).success

    with zipfile.ZipFile(out) as zf:
        manifest = deserialize_manifest(zf.read(MANIFEST_FILENAME).decode("utf-8"))
    assert manifest.deployment.target_platform == "linux"
