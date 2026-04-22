# SCCS Importer Security Tests
# Regression tests for the 2.17.1 security fixes:
#   H1 — Arbitrary File Write via manipulated manifest local_path / item.name
#   H2 — Symlink entries in ZIP bypassing path-traversal protection

from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

import pytest

from sccs.config.schema import SccsConfig
from sccs.transfer.importer import Importer, _is_safe_relative_name
from sccs.transfer.manifest import (
    MANIFEST_FILENAME,
    ExportManifest,
    ManifestCategory,
    ManifestItem,
    serialize_manifest,
)


def _write_zip(
    zip_path: Path,
    manifest: ExportManifest,
    items: dict[str, str] | None = None,
) -> None:
    """Create a ZIP with a manifest and optional additional entries."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_FILENAME, serialize_manifest(manifest))
        if items:
            for arc_name, content in items.items():
                zf.writestr(arc_name, content)


# ── Helper: _is_safe_relative_name ─────────────────────────────


class TestIsSafeRelativeName:
    """Unit tests for the path-validation helper."""

    @pytest.mark.parametrize(
        "name",
        ["skill.md", "sub/skill.md", "a/b/c/d.md", "file_with.dots.md"],
    )
    def test_safe_names_accepted(self, name: str) -> None:
        assert _is_safe_relative_name(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "",
            ".",
            "..",
            "../escape",
            "foo/../bar",
            "/etc/passwd",
            "/absolute/path",
        ],
    )
    def test_unsafe_names_rejected(self, name: str) -> None:
        assert _is_safe_relative_name(name) is False


# ── H1: Arbitrary File Write ───────────────────────────────────


class TestManifestLocalPathAllowlist:
    """H1 — manifest-supplied local_path must match the local config."""

    def test_unknown_category_rejected(self, temp_dir: Path, temp_home: Path) -> None:
        """ZIP containing a category that doesn't exist locally is refused."""
        config = _make_config(temp_home)

        manifest = ExportManifest(
            sccs_version="2.17.0",
            created_at="2026-04-22T00:00:00Z",
            created_on="macos",
            categories={
                "evil_category": ManifestCategory(
                    description="Unknown",
                    item_type="file",
                    local_path=str(temp_home / ".ssh"),
                    items=[
                        ManifestItem(
                            name="authorized_keys",
                            zip_path="evil_category/authorized_keys",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "unknown-category.zip"
        _write_zip(
            zip_path,
            manifest,
            {"evil_category/authorized_keys": "ssh-rsa ATTACKER"},
        )

        importer = Importer(zip_path, config=config)
        importer.load_manifest()
        result = importer.apply(importer.build_selections_all(), overwrite=True)

        assert result.success is False
        assert any("not configured locally" in err for err in result.errors)
        assert not (temp_home / ".ssh" / "authorized_keys").exists()

    def test_path_mismatch_rejected(self, temp_dir: Path, temp_home: Path) -> None:
        """ZIP re-targets a known category to a different directory — refused."""
        config = _make_config(temp_home)

        manifest = ExportManifest(
            sccs_version="2.17.0",
            created_at="2026-04-22T00:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Commands but redirected",
                    item_type="file",
                    local_path=str(temp_home / "redirected"),  # not the configured path
                    items=[
                        ManifestItem(
                            name="hijack.md",
                            zip_path="claude_commands/hijack.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "redirected.zip"
        _write_zip(
            zip_path,
            manifest,
            {"claude_commands/hijack.md": "hijacked"},
        )

        importer = Importer(zip_path, config=config)
        importer.load_manifest()
        result = importer.apply(importer.build_selections_all(), overwrite=True)

        assert result.success is False
        assert any("does not match local configuration" in err for err in result.errors)
        assert not (temp_home / "redirected").exists()

    def test_matching_path_accepted(self, temp_dir: Path, temp_home: Path) -> None:
        """A manifest that matches the local config is accepted."""
        config = _make_config(temp_home)
        target_dir = temp_home / ".claude" / "commands"
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest = ExportManifest(
            sccs_version="2.17.0",
            created_at="2026-04-22T00:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Commands",
                    item_type="file",
                    local_path=str(target_dir),
                    items=[
                        ManifestItem(
                            name="legit.md",
                            zip_path="claude_commands/legit.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "legit.zip"
        _write_zip(
            zip_path,
            manifest,
            {"claude_commands/legit.md": "# Legit\n"},
        )

        importer = Importer(zip_path, config=config)
        importer.load_manifest()
        result = importer.apply(importer.build_selections_all(), overwrite=True)

        assert result.success is True
        assert (target_dir / "legit.md").exists()


class TestItemNameTraversal:
    """H1 — item.name is attacker-controlled and must not escape target_base."""

    def test_item_name_with_parent_ref_rejected(self, temp_dir: Path, temp_home: Path) -> None:
        """`item.name` containing `..` escapes the target base — refused."""
        config = _make_config(temp_home)
        target_dir = temp_home / ".claude" / "commands"
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest = ExportManifest(
            sccs_version="2.17.0",
            created_at="2026-04-22T00:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Commands",
                    item_type="file",
                    local_path=str(target_dir),
                    items=[
                        ManifestItem(
                            name="../escaped.md",
                            zip_path="claude_commands/escaped.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "item-escape.zip"
        _write_zip(
            zip_path,
            manifest,
            {"claude_commands/escaped.md": "escaped content"},
        )

        importer = Importer(zip_path, config=config)
        importer.load_manifest()
        result = importer.apply(importer.build_selections_all(), overwrite=True)

        assert result.success is False
        assert any("unsafe name" in err for err in result.errors)
        assert not (temp_home / ".claude" / "escaped.md").exists()

    def test_absolute_item_name_rejected(self, temp_dir: Path, temp_home: Path) -> None:
        """`item.name` that is an absolute path is refused."""
        config = _make_config(temp_home)
        target_dir = temp_home / ".claude" / "commands"
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest = ExportManifest(
            sccs_version="2.17.0",
            created_at="2026-04-22T00:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Commands",
                    item_type="file",
                    local_path=str(target_dir),
                    items=[
                        ManifestItem(
                            name=str(temp_home / "pwned.md"),
                            zip_path="claude_commands/pwned.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "absolute-name.zip"
        _write_zip(
            zip_path,
            manifest,
            {"claude_commands/pwned.md": "pwned"},
        )

        importer = Importer(zip_path, config=config)
        importer.load_manifest()
        result = importer.apply(importer.build_selections_all(), overwrite=True)

        assert result.success is False
        assert not (temp_home / "pwned.md").exists()


# ── H2: Symlink rejection ──────────────────────────────────────


class TestZipSymlinkRejection:
    """H2 — symlink entries in ZIP must be rejected before extraction."""

    def test_symlink_entry_rejected(self, temp_dir: Path, temp_home: Path) -> None:
        """A ZIP containing a Unix symlink entry is refused."""
        config = _make_config(temp_home)
        target_dir = temp_home / ".claude" / "commands"
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest = ExportManifest(
            sccs_version="2.17.0",
            created_at="2026-04-22T00:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Commands",
                    item_type="file",
                    local_path=str(target_dir),
                    items=[
                        ManifestItem(
                            name="payload.md",
                            zip_path="claude_commands/payload.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "symlink.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_FILENAME, serialize_manifest(manifest))

            # Craft a symlink entry inside the archive. The Unix symlink bit
            # lives in the top half of external_attr.
            link_info = zipfile.ZipInfo("claude_commands/payload.md")
            link_mode = stat.S_IFLNK | 0o777
            link_info.external_attr = link_mode << 16
            link_info.create_system = 3  # Unix
            zf.writestr(link_info, "/tmp/elsewhere")

        importer = Importer(zip_path, config=config)
        importer.load_manifest()
        result = importer.apply(importer.build_selections_all(), overwrite=True)

        assert result.success is False
        assert any("symlink" in err.lower() for err in result.errors)
        # Nothing should have been written to the target directory
        assert list(target_dir.iterdir()) == []


# ── Legacy behaviour preserved ─────────────────────────────────


class TestLegacyModeWithoutConfig:
    """Importer(zip_path) — no config — keeps working for existing tests."""

    def test_no_config_still_rejects_zip_traversal(self, temp_dir: Path) -> None:
        """_safe_extract still rejects `../` entries even without a config."""
        manifest = ExportManifest(
            sccs_version="2.17.0",
            created_at="2026-04-22T00:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Commands",
                    item_type="file",
                    local_path="~/.claude/commands",
                    items=[
                        ManifestItem(
                            name="evil.md",
                            zip_path="../../../etc/passwd",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "legacy-traversal.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(MANIFEST_FILENAME, serialize_manifest(manifest))
            zf.writestr("../../../etc/passwd", "root:x:0:0")

        importer = Importer(zip_path)  # no config
        importer.load_manifest()
        result = importer.apply(importer.build_selections_all(), overwrite=True)

        assert result.success is False


# ── Helpers ────────────────────────────────────────────────────


def _make_config(home: Path) -> SccsConfig:
    """Build a minimal SccsConfig with a claude_commands category rooted in ``home``."""
    return SccsConfig.model_validate(
        {
            "repository": {"path": str(home / "repo")},
            "sync_categories": {
                "claude_commands": {
                    "enabled": True,
                    "description": "Test commands",
                    "local_path": str(home / ".claude" / "commands"),
                    "repo_path": ".claude/commands",
                    "sync_mode": "bidirectional",
                    "item_type": "file",
                    "item_pattern": "*.md",
                },
            },
        }
    )


@pytest.fixture(autouse=True)
def _restore_umask():
    """Keep file creation permissions predictable across tests."""
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)
