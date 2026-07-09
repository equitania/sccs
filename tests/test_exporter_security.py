# Tests for symlink-rejection in the ZIP exporter
# A planted symlink (e.g. SKILL.md -> ~/.ssh/id_ed25519) must never be
# dereferenced into an export archive — that would turn a shared export
# ZIP into cross-machine secret exfiltration.

import os
import sys
import zipfile

import pytest

from sccs.config.schema import ItemType, SccsConfig
from sccs.sync.item import SyncItem
from sccs.transfer.exporter import Exporter, ExportSelection
from sccs.transfer.manifest import MANIFEST_FILENAME

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Symlink semantics differ on Windows and require elevated privileges",
)

SECRET_MARKER = b"TOP-SECRET-DO-NOT-EXPORT"


def _assert_zip_free_of_secret(zip_path):
    """No entry in the archive may carry the symlink target's contents."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            assert SECRET_MARKER not in zf.read(name), f"secret leaked into ZIP entry {name}"


class TestScanExcludesSymlinkItems:
    """scan_available_items() drops symlink items before UI/manifest."""

    def test_symlinked_file_item_excluded(self, sample_config, mock_claude_dir, temp_dir):
        secret = temp_dir / "secret.txt"
        secret.write_bytes(SECRET_MARKER)
        os.symlink(secret, mock_claude_dir / "commands" / "evil.md")

        config = SccsConfig.model_validate(sample_config)
        scanned = Exporter(config).scan_available_items()

        names = [i.name for i in scanned.get("claude_commands", [])]
        assert "evil.md" not in names

    def test_symlinked_directory_item_excluded(self, sample_config, mock_claude_dir, temp_dir):
        real_dir = temp_dir / "evil-skill"
        real_dir.mkdir()
        (real_dir / "SKILL.md").write_bytes(SECRET_MARKER)
        os.symlink(real_dir, mock_claude_dir / "skills" / "evil-skill")

        config = SccsConfig.model_validate(sample_config)
        scanned = Exporter(config).scan_available_items()

        names = [i.name for i in scanned.get("claude_skills", [])]
        assert "evil-skill" not in names

    def test_regular_items_still_scanned(self, sample_config, mock_claude_dir, temp_dir):
        os.symlink(temp_dir / "nowhere", mock_claude_dir / "skills" / "dangling")

        config = SccsConfig.model_validate(sample_config)
        scanned = Exporter(config).scan_available_items()

        names = [i.name for i in scanned.get("claude_skills", [])]
        assert "test-skill" in names


class TestExportSkipsSymlinks:
    """The ZIP writer itself refuses symlinks (defence-in-depth)."""

    def test_symlinked_file_inside_directory_item(self, sample_config, mock_claude_dir, temp_dir):
        secret = temp_dir / "secret.txt"
        secret.write_bytes(SECRET_MARKER)
        skill_dir = mock_claude_dir / "skills" / "test-skill"
        os.symlink(secret, skill_dir / "leak.md")

        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)
        selections = exporter.build_selections_all(exporter.scan_available_items())
        output = temp_dir / "symlink-file.zip"

        result = exporter.export_to_zip(selections, output, sample_config)

        assert result.success is True
        with zipfile.ZipFile(output, "r") as zf:
            assert not any("leak.md" in n for n in zf.namelist())
        _assert_zip_free_of_secret(output)

    def test_symlinked_subdirectory_inside_directory_item(self, sample_config, mock_claude_dir, temp_dir):
        secret_dir = temp_dir / "secrets"
        secret_dir.mkdir()
        (secret_dir / "credentials").write_bytes(SECRET_MARKER)
        skill_dir = mock_claude_dir / "skills" / "test-skill"
        os.symlink(secret_dir, skill_dir / "references")

        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)
        selections = exporter.build_selections_all(exporter.scan_available_items())
        output = temp_dir / "symlink-dir.zip"

        result = exporter.export_to_zip(selections, output, sample_config)

        assert result.success is True
        with zipfile.ZipFile(output, "r") as zf:
            assert not any("references" in n for n in zf.namelist())
        _assert_zip_free_of_secret(output)

    def test_symlink_item_injected_past_scan_is_skipped(self, sample_config, mock_claude_dir, temp_dir):
        """Even a hand-built selection (bypassing the scan filter) must not
        dereference a symlink item into the archive."""
        secret = temp_dir / "secret.txt"
        secret.write_bytes(SECRET_MARKER)
        link = mock_claude_dir / "commands" / "evil.md"
        os.symlink(secret, link)
        real = mock_claude_dir / "commands" / "good.md"
        real.write_text("# fine\n", encoding="utf-8")

        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)
        evil_item = SyncItem(name="evil.md", category="claude_commands", item_type=ItemType.FILE)
        evil_item.local_path = link
        good_item = SyncItem(name="good.md", category="claude_commands", item_type=ItemType.FILE)
        good_item.local_path = real
        selection = ExportSelection(
            category_name="claude_commands",
            category=config.sync_categories["claude_commands"],
            items=[evil_item, good_item],
        )
        output = temp_dir / "injected.zip"

        result = exporter.export_to_zip([selection], output, sample_config)

        assert result.success is True
        assert result.total_items == 1  # only good.md counted
        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            assert "claude_commands/good.md" in names
            assert "claude_commands/evil.md" not in names
            assert MANIFEST_FILENAME in names
        _assert_zip_free_of_secret(output)
